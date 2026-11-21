"""
Kleiner lokaler Server fuer die Spielschnitt-App.

Liefert die Oberflaeche (ui/), den Zustand des Spielordners, spielt Videos ab
und startet die Arbeitsschritte aus spielschnitt.py in einem Hintergrund-Thread.
Lauscht nur auf 127.0.0.1.
"""
import json, os, queue, re, shutil, subprocess, sys, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(APP)
sys.path.insert(0, TOOL)
import spielschnitt as ss  # noqa: E402

VERSION = "2.0.0"
UI = os.path.join(APP, "ui")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
         ".mp4": "video/mp4", ".ico": "image/x-icon"}

STATE = {"folder": None, "last_ping": time.time()}
JOB = {"kind": None, "running": False, "log": [], "label": "", "i": 0, "n": 1, "frac": 0.0,
       "error": None, "result": None, "started": 0.0, "ended": 0.0}
LOCK = threading.Lock()


# ---------------------------------------------------------------- Spielordner
def load_last_folder():
    p = ss.LAST_FILE
    if os.path.exists(p):
        d = open(p, encoding="utf-8").read().strip()
        if os.path.isdir(d):
            try:
                STATE["folder"] = ss.use_folder(d)
            except ss.Fehler:
                pass


def set_folder(d):
    d = ss.check_folder(d)
    stop_prep()
    STATE["folder"] = ss.use_folder(d)
    PREP.update(folder=None, done=False, error=None, label="", frac=0.0, i=0, n=0)


def find_file(folder, names):
    """Erste Datei (Gross/Klein egal) aus names in folder bzw. folder/_arbeit."""
    want = {n.lower() for n in names}
    for sub in ("", ss.WORK):
        d = os.path.join(folder, sub)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower() in want:
                    return os.path.join(sub, f) if sub else f
    return None


def folder_state():
    d = STATE["folder"]
    if not d or not os.path.isdir(d):
        return None
    files = os.listdir(d)
    vids = []
    for v in ss.originals(d):
        name = os.path.splitext(v)[0].upper()
        sicht = os.path.join(ss.WORK, f"sicht_{name}.mp4")
        mk = find_file(d, [f"marker_{name}.txt"])
        info = None
        if mk:
            try:
                m = ss.parse_marker(os.path.join(d, mk))
                info = {"wechsel": len(m["events"]), "hl": len(m["hl"])}
            except Exception:
                info = {"wechsel": 0, "hl": 0}
        prev = next((f for f in files if re.fullmatch(rf"vorschau_v\d+_{re.escape(name)}\.mp4", f, re.I)), None)
        vids.append({"file": v, "name": name, "size": os.path.getsize(os.path.join(d, v)),
                     "sicht": sicht.replace("\\", "/") if os.path.exists(os.path.join(d, sicht)) else None,
                     "marker": info, "vorschau": prev,
                     "vorschau_t": int(os.path.getmtime(os.path.join(d, prev))) if prev else 0})
    results = sorted(f for f in files if f.lower().endswith(("_einsatzzeit.mp4", "_highlights.mp4"))
                     and ".tmp." not in f.lower())
    return {"path": d, "name": os.path.basename(d), "videos": vids, "results": results,
            "korrekturen": os.path.exists(os.path.join(d, "korrekturen.txt")),
            "bild_gesetzt": os.path.exists(os.path.join(d, ss.BILD_FILE))}


def load_fixes():
    p = os.path.join(STATE["folder"], ss.FIX_FILE)
    return ss.parse_fixes(ss.read_text(p)) if os.path.exists(p) else []


def schnitt(name):
    """Schnittdaten der letzten Vorschau + Korrekturen fuer ein Video."""
    p = os.path.join(STATE["folder"], ss.WORK, f"schnitt_{name}.json")
    data = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    fp = os.path.join(STATE["folder"], ss.FIX_FILE)
    stale = bool(data) and os.path.exists(fp) and os.path.getmtime(fp) > os.path.getmtime(p)
    return {"schnitt": data, "fixes": [f for f in load_fixes() if f["name"] == name],
            "bild": ss.load_bild(STATE["folder"]), "stale": stale}


def save_fixes(name, items):
    """Korrekturen eines Videos ersetzen, die der anderen Videos bleiben."""
    clean = []
    for it in items:
        try:
            what, a, b = it["what"], float(it["a"]), float(it["b"])
            pos = min(1.0, max(0.0, float(it.get("pos", 0.5))))
        except (KeyError, TypeError, ValueError):
            continue
        if what in ss.FIX_KINDS and b - a >= 0.5:
            clean.append({"name": name, "what": what, "a": max(0.0, a), "b": b, "pos": pos})
    fixes = [f for f in load_fixes() if f["name"] != name] + clean
    p = os.path.join(STATE["folder"], ss.FIX_FILE)
    if fixes:
        with open(p, "w", encoding="utf-8") as f:
            f.write(ss.format_fixes(fixes))
    elif os.path.exists(p):
        os.remove(p)


def inside_folder(rel):
    """Relativen Pfad sicher im Spielordner aufloesen (kein Ausbrechen nach oben)."""
    d = STATE["folder"]
    if not d or not rel:
        return None
    p = os.path.abspath(os.path.join(d, rel))
    if os.path.commonpath([p, os.path.abspath(d)]) != os.path.abspath(d) or not os.path.isfile(p):
        return None
    return p


# Der Starter (Spielschnitt.pyw) zeigt Dialoge im Hauptthread und holt sie hier ab.
DIALOGS = queue.Queue()
UI_LOOP = {"active": False}


def show_folder_dialog(initdir):
    """Im Hauptthread aufrufen (tkinter)."""
    import tkinter
    from tkinter import filedialog
    r = tkinter.Tk()
    r.withdraw()
    r.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(title="Spielordner auswaehlen", initialdir=initdir or None) or ""
    finally:
        r.destroy()


def serve_dialogs(timeout):
    """Vom Starter in seiner Warteschleife aufgerufen."""
    try:
        initdir, done, out = DIALOGS.get(timeout=timeout)
    except queue.Empty:
        return
    try:
        out.append(show_folder_dialog(initdir))
    except Exception:
        out.append("")
    done.set()


def pick_folder_dialog():
    """Ordnerauswahl: ueber den Hauptthread des Starters, sonst in eigenem Prozess (Entwicklung)."""
    if UI_LOOP["active"]:
        done, out = threading.Event(), []
        DIALOGS.put((STATE["folder"] or "", done, out))
        done.wait()
        return out[0] if out else ""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        exe = alt if os.path.exists(alt) else exe
    code = ("import sys,tkinter\nfrom tkinter import filedialog as f\n"
            "r=tkinter.Tk();r.withdraw();r.attributes('-topmost',True)\n"
            "p=f.askdirectory(title='Spielordner auswaehlen',initialdir=sys.argv[1] or None)\n"
            "sys.stdout.write(p or '');r.destroy()")
    init = STATE["folder"] or ""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([exe, "-c", code, init], capture_output=True, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout.decode("utf-8", "replace").strip()


# ---------------------------------------------------------------- Arbeitsschritte
def _log(line):
    with LOCK:
        for part in str(line).splitlines() or [""]:
            JOB["log"].append(part)
        del JOB["log"][:-400]


def _step(i, n, label):
    with LOCK:
        JOB.update(i=i, n=max(1, n), label=label, frac=0.0)


def _frac(f):
    JOB["frac"] = f


ss.HOOKS.update(say=_log, step=_step, frac=_frac)


# ---------------------------------------------------------------- Vorbereitung im Hintergrund
# Startet, sobald ein Spielordner gewaehlt ist: Sichtkopien (nur wenn der Browser die Originale
# nicht abspielen kann) und Bewegungsmessung aller Videos. So ist am Ende kaum noch Wartezeit.
PREP = {"running": False, "folder": None, "need_sicht": None, "label": "", "i": 0, "n": 0, "frac": 0.0,
        "error": None, "done": False}
PREP_CANCEL = threading.Event()
PREP_THREAD = {"t": None}


def _prep_items(folder):
    """Naechste Aufgabe: zuerst fehlende Sichtkopien (falls noetig), dann Bewegungsmessungen."""
    P = {"work": ss.WORK, "bild": ss.load_bild(folder)}
    vids = ss.originals(folder)
    todo = []
    if PREP["need_sicht"]:
        todo += [("sicht", v) for v in vids
                 if not os.path.exists(os.path.join(folder, ss.sicht_path(P, os.path.splitext(v)[0].upper())))]
    todo += [("motion", v) for v in vids
             if not os.path.exists(os.path.join(folder, ss.motion_cache(P, os.path.splitext(v)[0].upper(), P["bild"])))]
    return P, todo


def _prep_worker(folder):
    def step(i, n, label):
        PREP.update(label=label, frac=0.0)

    ss.set_thread_context({"say": None, "step": step, "frac": lambda f: PREP.update(frac=f)}, PREP_CANCEL)
    try:
        os.makedirs(os.path.join(folder, ss.WORK), exist_ok=True)
        done = 0
        while not PREP_CANCEL.is_set():
            P, todo = _prep_items(folder)
            if not todo:
                PREP["done"] = True
                break
            kind, v = todo[0]
            PREP.update(i=done, n=done + len(todo), frac=0.0,
                        label=("Sichtkopie " if kind == "sicht" else "Bewegung messen ") + os.path.splitext(v)[0].upper())
            if kind == "sicht":
                ss.make_sicht(P, v)
            else:
                ss.motion_full(P, v, P["bild"])
            done += 1
    except ss.Abgebrochen:
        pass
    except Exception as e:
        PREP["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    finally:
        PREP["running"] = False


def start_prep(need_sicht=None):
    """Vorbereitung (neu) anstossen. Laeuft sie schon, nimmt sie neue Aufgaben von selbst mit."""
    if need_sicht is not None:
        PREP["need_sicht"] = bool(need_sicht)
    d = STATE["folder"]
    if not d or (JOB["running"] and JOB["kind"] == "videos"):
        return
    PREP.update(done=False, error=None)
    if PREP["running"]:
        return
    PREP_CANCEL.clear()
    PREP.update(running=True, folder=d)
    t = threading.Thread(target=_prep_worker, args=(d,), daemon=True)
    PREP_THREAD["t"] = t
    t.start()


def stop_prep():
    if PREP["running"]:
        PREP_CANCEL.set()
        t = PREP_THREAD["t"]
        if t:
            t.join(15)


def worker(kind, folder):
    try:
        ss._probe.clear()
        ss.need_tools()
        ss.use_folder(folder)
        if kind == "sichtkopien":
            ss.cmd_sichtkopien(folder)
        elif kind == "vorschau":
            ss.cmd_vorschau(ss.load_plan(folder))
        else:
            ss.cmd_videos(ss.load_plan(folder))
        JOB["result"] = "ok"
    except ss.Abgebrochen:
        JOB["result"] = "abgebrochen"
    except ss.Fehler as e:
        JOB["result"], JOB["error"] = "fehler", str(e)
        _log("FEHLER: " + str(e))
    except Exception as e:  # unerwartet: ganze Meldung ins Protokoll
        JOB["result"], JOB["error"] = "fehler", f"{type(e).__name__}: {e}"
        _log(traceback.format_exc())
    finally:
        JOB["running"], JOB["ended"] = False, time.time()


def start_job(kind):
    if kind not in ("sichtkopien", "vorschau", "videos"):
        return "Unbekannter Schritt."
    if JOB["running"]:
        return "Es laeuft schon etwas."
    if not STATE["folder"]:
        return "Bitte zuerst einen Spielordner auswaehlen."
    if kind == "videos":
        stop_prep()
    ss.CANCEL.clear()
    JOB.update(kind=kind, running=True, log=[], label="Geht gleich los ...", i=0, n=1, frac=0.0,
               error=None, result=None, started=time.time(), ended=0.0)
    threading.Thread(target=worker, args=(kind, STATE["folder"]), daemon=True).start()
    return None


def cancel_job():
    if JOB["running"]:
        ss.CANCEL.set()


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def _file(self, path, ctype=None):
        ctype = ctype or TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        size = os.path.getsize(path)
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass

    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "forbidden"}, 403)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        STATE["last_ping"] = time.time()
        if u.path == "/api/state":
            with LOCK:
                job = dict(JOB, log=JOB["log"][-60:])
            return self._json({"version": VERSION, "folder": folder_state(), "job": job, "prep": dict(PREP),
                               "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))})
        if u.path == "/api/log":
            with LOCK:
                return self._json({"log": JOB["log"]})
        if u.path == "/api/marker":
            name = (q.get("name") or [""])[0]
            if not re.fullmatch(r"[\w\-]+", name) or not STATE["folder"]:
                return self._json({"error": "Ungueltiger Name"}, 400)
            mk = find_file(STATE["folder"], [f"marker_{name}.txt"])
            text = ss.read_text(os.path.join(STATE["folder"], mk)) if mk else None
            return self._json({"text": text})
        if u.path == "/api/frame":
            name = (q.get("name") or [""])[0].upper()
            src = next((v for v in ss.originals(STATE["folder"]) if os.path.splitext(v)[0].upper() == name),
                       None) if STATE["folder"] else None
            if not src:
                return self._json({"error": "nicht gefunden"}, 404)
            try:
                t = float((q.get("t") or ["0"])[0])
                jpg = ss.frame_jpeg(os.path.join(STATE["folder"], src), t, 1280)
            except (ValueError, ss.Fehler):
                return self._json({"error": "Standbild nicht moeglich"}, 500)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpg)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(jpg)
            return
        if u.path == "/api/bild":
            if not STATE["folder"]:
                return self._json({"error": "Kein Ordner"}, 400)
            vids = []
            for v in ss.originals(STATE["folder"]):
                try:
                    dur, w, h = ss.probe(os.path.join(STATE["folder"], v))
                except ss.Fehler:
                    continue
                vids.append({"name": os.path.splitext(v)[0].upper(), "dur": dur, "w": w, "h": h})
            return self._json({"bild": ss.load_bild(STATE["folder"]), "standard": ss.BILD_DEFAULT,
                               "gesetzt": os.path.exists(os.path.join(STATE["folder"], ss.BILD_FILE)),
                               "videos": vids})
        if u.path == "/api/schnitt":
            name = (q.get("name") or [""])[0]
            if not re.fullmatch(r"[\w\-]+", name) or not STATE["folder"]:
                return self._json({"error": "Ungueltiger Name"}, 400)
            return self._json(schnitt(name.upper()))
        if u.path == "/media":
            p = inside_folder((q.get("p") or [""])[0])
            if not p:
                return self._json({"error": "nicht gefunden"}, 404)
            return self._file(p)
        rel = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        p = os.path.abspath(os.path.join(UI, rel))
        if os.path.commonpath([p, UI]) == UI and os.path.isfile(p):
            return self._file(p)
        self._json({"error": "nicht gefunden"}, 404)

    def do_POST(self):
        if not self._host_ok() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._json({"error": "forbidden"}, 403)
        u = urlparse(self.path)
        b = self._body()
        try:
            if u.path == "/api/choose":
                if JOB["running"]:
                    return self._json({"error": "Waehrend etwas laeuft, kann der Ordner nicht gewechselt werden."})
                d = pick_folder_dialog()
                if d:
                    set_folder(d)
                return self._json({"ok": True, "chosen": bool(d)})
            if u.path == "/api/run":
                err = start_job(b.get("kind"))
                return self._json({"error": err} if err else {"ok": True})
            if u.path == "/api/cancel":
                cancel_job()
                return self._json({"ok": True})
            if u.path == "/api/marker":
                name, text = b.get("name", ""), b.get("text", "")
                if not re.fullmatch(r"[\w\-]+", name) or not STATE["folder"] or not isinstance(text, str):
                    return self._json({"error": "Ungueltig"}, 400)
                mk = find_file(STATE["folder"], [f"marker_{name}.txt"]) or f"marker_{name}.txt"
                with open(os.path.join(STATE["folder"], mk), "w", encoding="utf-8", newline="") as f:
                    f.write(text)
                return self._json({"ok": True})
            if u.path == "/api/korrekturen":
                name = str(b.get("name", "")).upper()
                if not re.fullmatch(r"[\w\-]+", name) or not STATE["folder"] or not isinstance(b.get("fixes"), list):
                    return self._json({"error": "Ungueltig"}, 400)
                if JOB["running"]:
                    return self._json({"error": "Bitte warten, bis der Computer fertig ist."})
                save_fixes(name, b["fixes"])
                return self._json({"ok": True, **schnitt(name)})
            if u.path == "/api/bild":
                if not STATE["folder"] or not isinstance(b.get("bild"), dict):
                    return self._json({"error": "Ungueltig"}, 400)
                if JOB["running"]:
                    return self._json({"error": "Bitte warten, bis der Computer fertig ist."})
                bild = ss.save_bild(b["bild"], STATE["folder"])
                start_prep()                       # Bewegung fuer den neuen Ausschnitt messen
                return self._json({"ok": True, "bild": bild})
            if u.path == "/api/prepare":
                start_prep(b.get("need_sicht"))
                return self._json({"ok": True})
            if u.path == "/api/open":
                d = STATE["folder"]
                if not d:
                    return self._json({"error": "Kein Ordner"}, 400)
                p = d if not b.get("p") else inside_folder(b["p"])
                if not p:
                    return self._json({"error": "nicht gefunden"}, 404)
                os.startfile(p)
                return self._json({"ok": True})
        except ss.Fehler as e:
            return self._json({"error": str(e)})
        self._json({"error": "nicht gefunden"}, 404)


def make_server(port):
    load_last_folder()
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
