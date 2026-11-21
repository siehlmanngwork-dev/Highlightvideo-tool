#!/usr/bin/env python3
"""
spielschnitt.py - Einsatzzeit- und Highlight-Videos aus GoPro-Basketballaufnahmen.

Normalerweise ueber die Desktop-App (Spielschnitt.pyw). Kommandozeile:
    python spielschnitt.py sichtkopien [Spielordner]   kleine Sichtkopien (nur noetig, wenn der
                                                       Browser die Originale nicht abspielen kann)
    python spielschnitt.py vorschau    [Spielordner]   Vorschau der Einsatzzeit (optional)
    python spielschnitt.py videos      [Spielordner]   Einsatzzeit- und Highlight-Video

Ohne Ordnerangabe erscheint ein Auswahldialog. Bearbeitet werden NUR die Videos
in diesem Spielordner. Ein-/Auswechslungen und Highlights kommen aus den
Marker-Dateien (marker_<Video>.txt), den Bildausschnitt aus bildausschnitt.json und
Korrekturen aus korrekturen.txt - alle drei schreibt die App in den Spielordner.
Am Ende enthaelt der Spielordner nur die Originale, <Ordner>_Einsatzzeit.mp4
und <Ordner>_Highlights.mp4. Braucht nur Python (Standardbibliothek) und ffmpeg/ffprobe im PATH.
Originalvideos werden nie veraendert.
"""
import hashlib, json, math, os, re, shutil, subprocess, sys, threading, time

# ---------------------------------------------------------------- Einstellungen
LENS = "lenscorrection=k1=-0.15:k2=-0.02:i=bilinear"   # GoPro-Fischauge
CROP_W = 0.5625          # Ausschnittbreite relativ zur Bildbreite (16:9-Fenster)
CROP_Y = 0.0972          # obere Kante des Ausschnitts relativ zur Bildhoehe
ANA_FPS = 10             # Analyse-Bildrate
COLS = 64                # Spalten der Bewegungsmessung
CAM_SIGMA = 0.8          # Glaettung Kamerabahn in Sekunden
CAM_SPEED = 0.27         # max. Kamerageschwindigkeit (Bildbreiten pro Sekunde)
STOP_REL = 0.55          # Unterbrechung: Bewegung < 55 % des Medians ...
STOP_MIN = 4             # ... fuer mindestens 4 Sekunden
MIN_SEG = 3              # kuerzere Spielabschnitte werden verworfen
FADE = 0.5               # Ueberblendung zwischen Highlights
OUT_FPS = "30000/1001"
VIDEO_EXT = (".mp4",)

TOOL = os.path.dirname(os.path.abspath(__file__))
# Einstellungen (letzter Ordner): neben dem Skript, in der installierten App unter %LOCALAPPDATA%
if getattr(sys, "frozen", False):
    SETTINGS = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Spielschnitt")
    os.makedirs(SETTINGS, exist_ok=True)
else:
    SETTINGS = TOOL
LAST_FILE = os.path.join(SETTINGS, "letzter_ordner.txt")
WORK = "_arbeit"          # Zwischendateien im Spielordner, wird am Ende geloescht


# ---------------------------------------------------------------- Hilfen
class Fehler(Exception):
    """Abbruch mit verstaendlicher Meldung (Kommandozeile und App)."""


class Abgebrochen(Fehler):
    """Vom Benutzer abgebrochen (nur App)."""


# Haken fuer die Desktop-App (app/server.py). Auf der Kommandozeile bleiben sie leer.
HOOKS = {"say": None, "step": None, "frac": None}
CANCEL = threading.Event()
# Ein Hintergrund-Thread (Vorbereitung) kann eigene Haken und ein eigenes Abbruch-Signal setzen.
_TLS = threading.local()


def _hook(name):
    return (getattr(_TLS, "hooks", None) or HOOKS).get(name)


def _cancel():
    return getattr(_TLS, "cancel", None) or CANCEL


def set_thread_context(hooks, cancel):
    _TLS.hooks, _TLS.cancel = hooks, cancel


def say(*a):
    print(*a, flush=True)
    if _hook("say"):
        _hook("say")(" ".join(str(x) for x in a))


def step(i, n, label):
    """Fortschritt: Schritt i (0-basiert) von n, z.B. Teil 3 von 12."""
    if _hook("step"):
        _hook("step")(i, n, label)


def die(msg):
    raise Fehler(msg)


def need_tools():
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            die(f"{t} wurde nicht gefunden. Bitte ffmpeg installieren und in den PATH aufnehmen.")


_TIME_RE = re.compile(rb"time=(\d+):(\d+):([\d.]+)")


def _exec(cmd, total, data=False):
    """Prozess starten; abbrechbar ueber CANCEL; meldet Fortschritt, wenn total (Sekunden) bekannt.
    data=True: stdout liefert Nutzdaten, der Fortschritt kommt dann aus der Statuszeile auf stderr."""
    cancel, frac = _cancel(), _hook("frac")
    if cancel.is_set():
        raise Abgebrochen("Abgebrochen.")
    stats = bool(total and cmd[0] == "ffmpeg" and data)
    if stats:
        cmd = [cmd[0], "-stats", "-stats_period", "1"] + cmd[1:]
    elif total and cmd[0] == "ffmpeg":
        cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + cmd[1:]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    out, err = [], []

    def read_err():
        if not stats:
            err.append(p.stderr.read())
            return
        while True:
            chunk = p.stderr.read1(4096) if hasattr(p.stderr, "read1") else p.stderr.read(4096)
            if not chunk:
                break
            err.append(chunk)
            m = None
            for m in _TIME_RE.finditer(chunk):
                pass
            if m and frac:
                frac(min(1.0, (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) / total))

    def read_out():
        if total and cmd[0] == "ffmpeg" and not stats:
            for line in p.stdout:
                if line.startswith(b"out_time_us=") and frac:
                    try:
                        frac(min(1.0, int(line[12:]) / 1e6 / total))
                    except ValueError:
                        pass
        else:
            out.append(p.stdout.read())

    th = [threading.Thread(target=read_out, daemon=True),
          threading.Thread(target=read_err, daemon=True)]
    for t in th:
        t.start()
    while p.poll() is None:
        if cancel.wait(0.3):
            p.kill()
            p.wait()
            raise Abgebrochen("Abgebrochen.")
    for t in th:
        t.join()
    return p.returncode, b"".join(out), b"".join(err)


def run(cmd, log=None, total=None, data=False):
    """ffmpeg/ffprobe ausfuehren; Fehlerausgabe in Logdatei.
    Scheitert die Grafikkarten-Dekodierung, wird automatisch ohne sie wiederholt."""
    code, out, err = _exec(cmd, total, data)
    if code != 0 and "-hwaccel" in cmd:
        i = cmd.index("-hwaccel")
        cmd = cmd[:i] + cmd[i + 2:]
        code, out, err = _exec(cmd, total, data)
    if log:
        with open(log, "ab") as f:
            f.write(b"\n>>> " + " ".join(cmd).encode("utf-8", "replace") + b"\n" + err[-4000:])
    if code != 0:
        die("ffmpeg ist fehlgeschlagen:\n" + err.decode("utf-8", "replace")[-1500:])
    return out


def tsec(s):
    """'MM:SS', 'HH:MM:SS', 'MM:SS.s' -> Sekunden."""
    v = 0.0
    for x in s.strip().replace(",", ".").split(":"):
        v = v * 60 + float(x)
    return v


def hms(t):
    t = max(0.0, t)
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


_probe = {}


def probe(path):
    if path not in _probe:
        out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=width,height:format=duration", "-of", "json", path])
        j = json.loads(out)
        s = j["streams"][0]
        _probe[path] = (float(j["format"]["duration"]), int(s["width"]), int(s["height"]))
    return _probe[path]


def font():
    for f in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(f):
            return f.replace("\\", "/").replace(":", "\\:")
    return None


def gauss(vals, sigma):
    if sigma <= 0 or len(vals) < 3:
        return list(vals)
    r = int(3 * sigma)
    k = [math.exp(-0.5 * (i / sigma) ** 2) for i in range(-r, r + 1)]
    ks = sum(k)
    n = len(vals)
    return [sum(w * vals[min(n - 1, max(0, i + j - r))] for j, w in enumerate(k)) / ks for i in range(n)]


def read_text(p):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return open(p, encoding=enc).read()
        except UnicodeDecodeError:
            pass
    return open(p, encoding="latin-1").read()


# ---------------------------------------------------------------- Spielordner
def choose_folder():
    """Spielordner: Kommandozeile, sonst Auswahldialog, sonst Eingabe."""
    last_file = LAST_FILE
    last = open(last_file, encoding="utf-8").read().strip() if os.path.exists(last_file) else ""
    if len(sys.argv) > 2 and sys.argv[2].strip():
        d = sys.argv[2].strip().strip('"')
    else:
        d = ""
        try:
            import tkinter
            from tkinter import filedialog
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            d = filedialog.askdirectory(title="Spielordner waehlen (mit den Videos dieses Spiels)",
                                        initialdir=last if os.path.isdir(last) else None)
            root.destroy()
        except Exception:
            d = input(f"Pfad zum Spielordner{' [' + last + ']' if last else ''}: ").strip().strip('"') or last
    return use_folder(d)


def check_folder(d):
    """Gueltigen Spielordner als absoluten Pfad liefern, sonst Fehler."""
    if not d or not os.path.isdir(d):
        die("Kein gueltiger Spielordner gewaehlt.")
    d = os.path.abspath(d)
    if os.path.normcase(d) == os.path.normcase(TOOL):
        die("Bitte nicht den Tool-Ordner waehlen, sondern einen eigenen Ordner pro Spiel.")
    return d


def use_folder(d):
    """Spielordner merken und hineinwechseln (alle Befehle arbeiten relativ dazu)."""
    d = check_folder(d)
    open(LAST_FILE, "w", encoding="utf-8").write(d)
    os.chdir(d)
    say(f"Spielordner: {d}")
    return d


def is_result(f):
    """Vom Tool erzeugte Videos (keine Originale)."""
    fl = f.lower()
    return fl.startswith("vorschau_") or fl.endswith("_einsatzzeit.mp4") or fl.endswith("_highlights.mp4") \
        or ".tmp." in fl


def originals(folder="."):
    """Videos im Spielordner (ohne erzeugte Ergebnisse), sortiert = Reihenfolge der Viertel."""
    return sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))
                  and f.lower().endswith(VIDEO_EXT) and not is_result(f))


def load_plan(folder):
    vids = originals()
    if not vids:
        die("Keine Videodateien (.MP4) im Spielordner gefunden.")
    base = re.sub(r"[^\w\-]+", "_", os.path.basename(folder)).strip("_") or "Spiel"
    os.makedirs(WORK, exist_ok=True)
    P = {"base": base, "out": ".", "work": WORK, "fixes": [], "quarters": [], "bild": load_bild()}
    if os.path.exists(FIX_FILE):
        P["fixes"] = parse_fixes(read_text(FIX_FILE))
    missing = []
    for idx, src in enumerate(vids):
        name = os.path.splitext(src)[0].upper()
        q = {"q": f"V{idx + 1}", "name": name, "src": src, "hl": [], "pre": 8.0, "post": 3.0}
        mk = find_marker(P, name)
        if not mk:
            missing.append(src)
            continue
        q.update(parse_marker(mk))
        q["marker"] = mk
        P["quarters"].append(q)
    if missing:
        say("Ohne Marker-Datei (werden NICHT bearbeitet): " + ", ".join(missing))
    if not P["quarters"]:
        die("Keine Marker-Dateien gefunden. Bitte mit Marker.html markieren und die Datei "
            "marker_<Video>.txt in den Spielordner speichern.")
    return P


# ---------------------------------------------------------------- Korrekturen
# korrekturen.txt im Spielordner (wird auch von der App geschrieben), z.B.:
#   GX010540 schneiden: 17:15-17:31          Stelle zusaetzlich rausschneiden
#   GX010540 behalten: 13:53-14:03           herausgeschnittene Stelle wieder rein
#   GX010540 kamera 0.40: 13:53-14:03        Kamera fest (0 = ganz links, 1 = ganz rechts)
#   GX010540 weit: 13:53-14:03               ganzes Bild ohne Ausschnitt/Kameraschwenk
# Zeiten = Zeit im Originalvideo. Spaetere Zeilen gewinnen bei Ueberschneidung.
FIX_FILE = "korrekturen.txt"
FIX_KINDS = ("schneiden", "behalten", "kamera", "weit")
_FIX_RE = re.compile(r"^\s*(\w+?)(?:\.mp4)?\s+(schneiden|behalten|kamera|weit)\s*([\d.]*)\s*:\s*(.+)$", re.I)


def parse_fixes(text):
    fixes = []
    for line in text.splitlines():
        m = _FIX_RE.match(line.split("(")[0].split("#")[0])
        if not m:
            continue
        try:
            pos = min(1.0, max(0.0, float(m.group(3)))) if m.group(3) else 0.5
        except ValueError:
            pos = 0.5
        for part in m.group(4).split(","):
            a, _, b = part.strip().partition("-")
            if a.strip() and b.strip():
                try:
                    ta, tb = tsec(a), tsec(b)
                except ValueError:
                    continue
                if tb > ta:
                    fixes.append({"name": m.group(1).upper(), "what": m.group(2).lower(), "a": ta, "b": tb, "pos": pos})
    return fixes


def format_fixes(fixes):
    lines = ["# Korrekturen fuer das Spielschnitt-Tool (Zeit im Originalvideo)",
             "# schneiden = raus, behalten = wieder rein, kamera <0-1> = Kamera fest, weit = ganzes Bild"]
    for f in fixes:
        what = f["what"] + (f" {f['pos']:.3f}" if f["what"] == "kamera" else "")
        lines.append(f"{f['name']} {what}: {hms(f['a'])}-{hms(f['b'])}")
    return "\n".join(lines) + "\n"


def fixes_for(P, q, *kinds):
    return [f for f in P["fixes"] if f["name"] == q["name"] and f["what"] in kinds]


def is_weit(q, a, b):
    mid = (a + b) / 2
    return any(w[0] <= mid < w[1] for w in q.get("weit", []))


# ---------------------------------------------------------------- Bildausschnitt pro Spiel
# bildausschnitt.json im Spielordner (wird von der App geschrieben). Alle Werte relativ zum
# entzerrten Originalbild: crop_w = Breite des 16:9-Fensters, crop_y = obere Kante,
# x_min/x_max = Bereich, in dem sich das Fenster (die "Kamera") bewegen darf.
BILD_FILE = "bildausschnitt.json"
BILD_DEFAULT = {"crop_w": CROP_W, "crop_y": CROP_Y, "x_min": 0.0, "x_max": 1.0}


def clean_bild(b, aspect=16 / 9):
    """Werte begrenzen: Fenster passt ins Bild, Bewegungsbereich mindestens so breit wie das Fenster."""
    out = dict(BILD_DEFAULT)
    for k in out:
        try:
            out[k] = float(b.get(k, out[k]))
        except (TypeError, ValueError, AttributeError):
            pass
    cw = min(1.0, max(0.25, out["crop_w"]))
    chf = min(1.0, cw * aspect * 9 / 16)                 # Fensterhoehe relativ zur Bildhoehe
    cy = min(1.0 - chf, max(0.0, out["crop_y"]))
    x0, x1 = sorted((min(1.0, max(0.0, out["x_min"])), min(1.0, max(0.0, out["x_max"]))))
    if x1 - x0 < cw:                                     # Bereich zu schmal: um seine Mitte auf Fensterbreite
        m = min(1.0 - cw / 2, max(cw / 2, (x0 + x1) / 2))
        x0, x1 = m - cw / 2, m + cw / 2
    return {"crop_w": round(cw, 4), "crop_y": round(cy, 4), "x_min": round(x0, 4), "x_max": round(x1, 4)}


def load_bild(folder="."):
    p = os.path.join(folder, BILD_FILE)
    if os.path.exists(p):
        try:
            return clean_bild(json.load(open(p, encoding="utf-8")))
        except (ValueError, OSError):
            pass
    return dict(BILD_DEFAULT)


def save_bild(b, folder="."):
    b = clean_bild(b)
    with open(os.path.join(folder, BILD_FILE), "w", encoding="utf-8") as f:
        json.dump(b, f)
    return b


def bild_key(b):
    """Teil des Cache-/Render-Schluessels; leer bei Standardwerten (alte Ergebnisse bleiben gueltig)."""
    return [] if b == BILD_DEFAULT else [b]


def window(P, W, H):
    """Kamerafenster in Pixeln: Breite, Hoehe, obere Kante, kleinste und groesste linke Kante."""
    b = P.get("bild") or BILD_DEFAULT
    cw = int(W * b["crop_w"]) // 2 * 2
    ch = min(H, int(cw * 9 / 16)) // 2 * 2
    cy = max(0, min(H - ch, int(H * b["crop_y"]))) // 2 * 2
    lo, hi = b["x_min"] * W, b["x_max"] * W - cw
    if hi < lo:
        lo = hi = (lo + hi) / 2
    return cw, ch, cy, max(0, int(lo)), max(0, min(W - cw, int(hi)))


def find_marker(P, name):
    want = f"marker_{name}.txt".lower()
    for d in (".", P["work"]):
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower() == want:
                    return os.path.join(d, f)
    return None


def parse_marker(path):
    pre, post, ev, hl = 8.0, 3.0, [], []
    for line in read_text(path).splitlines():
        line = line.strip()
        m = re.match(r"#\s*Clip:\s*([\d.]+)\s*s davor,\s*([\d.]+)\s*s danach", line)
        if m:
            pre, post = float(m.group(1)), float(m.group(2))
            continue
        m = re.match(r"^(REIN|RAUS|HL)\s+(\d+:\d+:[\d.]+|\d+:[\d.]+)", line, re.I)
        if m:
            t = tsec(m.group(2))
            typ = m.group(1).upper()
            (hl if typ == "HL" else ev).append(t if typ == "HL" else (t, typ))
    return {"events": sorted(ev), "hl": sorted(hl), "pre": pre, "post": post}


def resolve_stints(q):
    dur, w, h = probe(q["src"])
    q["dur"], q["w"], q["h"] = dur, w, h
    res = []
    if "events" in q:
        ev = q["events"]
        on = bool(ev) and ev[0][1] == "RAUS"          # erstes Ereignis RAUS -> war schon drin
        start = 0.0
        for t, typ in ev:
            if typ == "REIN" and not on:
                on, start = True, t
            elif typ == "RAUS" and on:
                on = False
                res.append((start, t))
        if on:
            res.append((start, dur))
        if not ev and q["hl"]:
            res.append((0.0, dur))                   # nur Highlights markiert -> ganze Datei
    q["abs"] = [(round(max(0.0, s), 2), round(min(dur, e), 2)) for s, e in res if min(dur, e) - s > 1]


# ---------------------------------------------------------------- Sichtkopien + Analyse
def sicht_path(P, name):
    return os.path.join(P["work"], f"sicht_{name}.mp4")


_LOCKS, _LOCKS_LOCK = {}, threading.Lock()


def _lock(key):
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(key, threading.Lock())


def make_sicht(P, src):
    name = os.path.splitext(src)[0].upper()
    with _lock("sicht_" + name):
        _make_sicht(P, src, name)


def _make_sicht(P, src, name):
    out = sicht_path(P, name)
    if os.path.exists(out):
        say(f"  {name}: Sichtkopie vorhanden.")
        return
    say(f"  {name}: Sichtkopie wird erstellt ...")
    tmp = out + ".tmp.mp4"
    run(["ffmpeg", "-hide_banner", "-y", "-hwaccel", "auto", "-i", src, "-map", "0:v:0", "-map", "0:a:0?",
         "-vf", "scale=960:540", "-c:v", "libx264", "-preset", "veryfast", "-b:v", "1500k",
         "-maxrate", "1500k", "-bufsize", "3000k", "-g", "30", "-c:a", "aac", "-b:a", "96k",
         "-movflags", "+faststart", tmp], os.path.join(P["work"], "log.txt"), total=probe(src)[0])
    os.replace(tmp, out)


def motion_cache(P, name, bild):
    k = hashlib.md5(json.dumps(bild, sort_keys=True).encode()).hexdigest()[:8]
    return os.path.join(P["work"], f"bewegung_{name}_{k}.json")


def motion_full(P, src, bild=None):
    """Bewegung je Analysebild fuer das ganze Video: [Energie, Schwerpunkt 0..1 der Bildbreite].
    Nutzt die Sichtkopie, falls vorhanden, sonst das Original. Wird zwischengespeichert."""
    name = os.path.splitext(src)[0].upper()
    bild = bild or P.get("bild") or BILD_DEFAULT
    cache = motion_cache(P, name, bild)
    with _lock("motion_" + name):
        if os.path.exists(cache):
            return json.load(open(cache))
        sicht = sicht_path(P, name)
        if os.path.exists(sicht):
            inp, hw, pre = sicht, [], ""
        else:                                            # Original: frueh verkleinern, spart viel Zeit
            inp, hw, pre = src, ["-hwaccel", "auto"], "scale=960:-2,"
        chf = min(1.0, bild["crop_w"] * 16 / 9 * 9 / 16)
        y0 = min(0.98, bild["crop_y"] + 0.25 * chf)
        hh = max(0.02, min(1.0 - y0, 0.66 * chf))
        x0, xw = bild["x_min"], max(0.05, bild["x_max"] - bild["x_min"])
        vf = (f"fps={ANA_FPS},{pre}{LENS},crop=iw*{xw:.4f}:ih*{hh:.4f}:iw*{x0:.4f}:ih*{y0:.4f},format=gray,"
              f"tblend=all_mode=difference,lutyuv=y=if(gt(val\\,12)\\,val\\,0),scale={COLS}:1:flags=area")
        say(f"  {name}: Bewegung wird gemessen ...")
        raw = run(["ffmpeg", "-v", "error", *hw, "-i", inp, "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                  os.path.join(P["work"], "log.txt"), total=probe(src)[0], data=True)
        res = []
        for i in range(0, len(raw) - COLS + 1, COLS):
            c = raw[i:i + COLS]
            tot = sum(c)
            if tot < 3:
                res.append([tot, None])
                continue
            acc, cx = 0, 0.5
            for j, v in enumerate(c):
                acc += v
                if acc >= tot / 2:
                    cx = (j + 0.5) / COLS
                    break
            res.append([tot, round(x0 + cx * xw, 4)])     # zurueck auf die ganze Bildbreite
        tmp = cache + ".tmp"
        json.dump(res, open(tmp, "w"))
        os.replace(tmp, cache)
        return res


def frame_jpeg(src, t, width=1280):
    """Ein entzerrtes Standbild (JPEG) aus dem Original, z.B. fuer den Bildausschnitt-Editor."""
    return run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", src, "-frames:v", "1",
                "-vf", f"scale={width * 2}:-2,{LENS},scale={width}:-2", "-q:v", "4",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-"])


def motion(P, q, s, e):
    """Bewegung je Analysebild im Abschnitt s..e (aus der Messung des ganzen Videos)."""
    full = motion_full(P, q["src"])
    return full[int(round(s * ANA_FPS)):int(round(e * ANA_FPS))]


def analyse(P, q):
    """Spielabschnitte ohne Unterbrechungen [a, b, s0] und Kamerabahn je Einsatz."""
    data = {s: motion(P, q, s, e) for s, e in q["abs"]}
    per, allsec = {}, []
    for s, e in q["abs"]:
        m = data[s]
        per[s] = [sum(x[0] for x in m[i:i + ANA_FPS]) / ANA_FPS for i in range(0, len(m), ANA_FPS)]
        allsec += per[s]
    med = sorted(allsec)[len(allsec) // 2] or 1.0
    segs = []
    for s, e in q["abs"]:
        low = [v < STOP_REL * med for v in gauss(per[s], 1.0)]
        n = len(low)
        keep = [not x for x in low]
        i = 0
        while i < n:                                   # kurze Ruhephasen behalten
            j = i
            while j < n and low[j] == low[i]:
                j += 1
            if low[i] and j - i < STOP_MIN:
                keep[i:j] = [True] * (j - i)
            i = j
        for f in fixes_for(P, q, "schneiden", "behalten"):   # Korrekturen aus korrekturen.txt
            for k in range(n):
                if f["a"] <= s + k < f["b"]:
                    keep[k] = f["what"] == "behalten"
        i = 0
        while i < n:
            j = i
            while j < n and keep[j] == keep[i]:
                j += 1
            if keep[i]:
                a, b = s + i, min(e, s + j)
                if b - a >= MIN_SEG:
                    segs.append([round(a, 2), round(b, 2), s])
            i = j
    # Abschnitte an Grenzen von "weit"-Korrekturen teilen (dort anderer Bildausschnitt)
    q["weit"] = sorted((f["a"], f["b"]) for f in fixes_for(P, q, "weit"))
    if q["weit"]:
        split = []
        for a, b, s0 in segs:
            pts = [a] + sorted({x for w in q["weit"] for x in w if a < x < b}) + [b]
            split += [[round(pts[k], 2), round(pts[k + 1], 2), s0] for k in range(len(pts) - 1)
                      if pts[k + 1] - pts[k] >= 0.5]
        segs = split
    camfix = fixes_for(P, q, "kamera")
    cams = {}
    for s, e in q["abs"]:
        cx = [x[1] for x in data[s]]
        last = next((v for v in cx if v is not None), 0.5)
        for i, v in enumerate(cx):
            cx[i] = last = (last if v is None else v)
        for f in camfix:                               # Kamera fest (wird weich angefahren)
            for i in range(len(cx)):
                if f["a"] <= s + i / ANA_FPS < f["b"]:
                    cx[i] = f["pos"]
        sm = gauss(cx, CAM_SIGMA * ANA_FPS)
        lim = CAM_SPEED / ANA_FPS
        out = [sm[0]]
        for v in sm[1:]:
            out.append(out[-1] + max(-lim, min(lim, v - out[-1])))
        cams[s] = out
    return segs, cams


# ---------------------------------------------------------------- Rendern
def cam_file(P, q, seg, cams, W, cw, tag, lo=0, hi=None):
    """sendcmd-Datei: eine Kameraposition pro Bild."""
    a, b, s0 = seg
    path = cams.get(s0) or [0.5]
    fps = 30000 / 1001
    xs = []
    for f in range(int((b - a) * fps) + 2):
        p = ((a - s0) + f / fps) * ANA_FPS
        i, u = int(math.floor(p)), p - math.floor(p)
        v0 = path[min(len(path) - 1, max(0, i))]
        v1 = path[min(len(path) - 1, max(0, i + 1))]
        xs.append(v0 + (v1 - v0) * u)
    xs = gauss(xs, 5)
    hi = W - cw if hi is None else hi
    fn = os.path.join(P["work"], f"kamera_{q['q']}_{tag}_{int(a * 10)}.txt")
    with open(fn, "w") as f:
        for k, c in enumerate(xs):
            f.write(f"{k / fps:.4f} crop x {max(lo, min(hi, round(c * W - cw / 2)))};\n")
    return fn.replace("\\", "/")


def render(P, q, segs, cams, mode, label=True):
    """mode 'vorschau' (Sichtkopie -> 480p) oder 'end'/'hl' (Original -> 1080p)."""
    fnt = font() if label else None
    parts = []
    for i, seg in enumerate(segs):
        a, b, s0 = seg
        out = os.path.join(P["work"], f"{q['q']}_{mode}_{i:03d}.mp4")
        if mode == "vorschau":                         # klein: aus der Sichtkopie, sonst aus dem Original
            sicht = sicht_path(P, q["name"])
            W, H = 1920, int(1920 * q["h"] / q["w"]) // 2 * 2
            if os.path.exists(sicht):
                src, pre, hw = sicht, f"{LENS},scale={W}:{H}", []
            else:
                src, pre, hw = q["src"], f"scale={W}:{H},{LENS}", ["-hwaccel", "auto"]
            post = "scale=854:480"
            if fnt:
                post += (f",drawtext=fontfile='{fnt}':text='{q['q']} {q['name']} %{{pts\\:hms\\:{a}}}':"
                         "x=8:y=8:fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.6")
            enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-c:a", "aac", "-b:a", "96k"]
        else:
            W, H, src = q["w"], q["h"], q["src"]
            pre, post, hw = LENS, "scale=1920:1080:flags=lanczos", ["-hwaccel", "auto"]
            enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "256k", "-ar", "48000"]
        cw, ch, cy, lo, hi = window(P, W, H)           # Bildausschnitt dieses Spiels
        if is_weit(q, a, b):                           # ganzes Bild, kein Kameraschwenk
            cw = W // 2 * 2
            ch = min(H, int(cw * 9 / 16)) // 2 * 2
            cy = max(0, min(H - ch, cy)) // 2 * 2
            lo = hi = 0
        cf = cam_file(P, q, seg, cams, W, cw, mode, lo, hi)
        vf = f"{pre},sendcmd=f='{cf}',crop={cw}:{ch}:0:{cy},{post}"
        say(f"  {q['q']} {'Highlight' if mode == 'hl' else 'Teil'} {i + 1}/{len(segs)}  ({hms(a)}-{hms(b)})")
        what = {"vorschau": "Vorschau", "end": "Einsatzzeit", "hl": "Highlights"}[mode]
        step(i, len(segs), f"{what} {q['name']}")
        run(["ffmpeg", "-hide_banner", "-y", *hw, "-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", src,
             "-map", "0:v:0", "-map", "0:a:0", "-vf", vf, "-r", OUT_FPS, *enc, out],
            os.path.join(P["work"], "log.txt"), total=b - a)
        parts.append(out)
    return parts


def concat(P, parts, out, delete=True):
    lst = os.path.join(P["work"], "liste.txt")
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
    tmp = out + ".tmp.mp4"
    run(["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
         "-movflags", "+faststart", tmp], os.path.join(P["work"], "log.txt"))
    os.replace(tmp, out)
    if delete:
        for p in parts:
            try:
                os.remove(p)
            except OSError:
                pass


def xfade_join(P, clips, out):
    if len(clips) == 1:
        shutil.copyfile(clips[0], out)
        return
    durs = [probe(c)[0] for c in clips]
    args = ["ffmpeg", "-hide_banner", "-y"]
    for c in clips:
        args += ["-i", c]
    parts, off, vp, ap = [], 0.0, "[0:v]", "[0:a]"
    for k in range(1, len(clips)):
        off += durs[k - 1] - FADE
        vo, ao = ("[v]", "[a]") if k == len(clips) - 1 else (f"[v{k}]", f"[a{k}]")
        parts.append(f"{vp}[{k}:v]xfade=transition=fade:duration={FADE}:offset={off:.3f}{vo}")
        parts.append(f"{ap}[{k}:a]acrossfade=d={FADE}{ao}")
        vp, ap = vo, ao
    run(args + ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
                "-movflags", "+faststart", out], os.path.join(P["work"], "log.txt"),
        total=max(1.0, sum(durs) - FADE * (len(clips) - 1)))


def hl_segments(q):
    """Highlight-Intervalle im Original (ueberlappende zusammengefasst) mit zugehoerigem Einsatz."""
    iv = []
    for t in q["hl"]:
        a, b = max(0.0, t - q["pre"]), min(q["dur"], t + q["post"])
        if iv and a <= iv[-1][1] + FADE:
            iv[-1][1] = max(iv[-1][1], b)
        else:
            iv.append([a, b])
    segs = []
    for a, b in iv:
        mid = (a + b) / 2
        s0 = next((s for s, e in q["abs"] if s - 2 <= mid <= e + 2), None)
        segs.append([round(a, 2), round(b, 2), s0 if s0 is not None else -1])
    return segs


def h(*x):
    return hashlib.md5(json.dumps(x).encode()).hexdigest()[:10]


def up_to_date(path, key):
    m = path + ".plan"
    return os.path.exists(path) and os.path.exists(m) and open(m).read() == key


def mark_done(path, key):
    open(path + ".plan", "w").write(key)


def write_report(P, q, segs):
    fn = os.path.join(P["out"], f"Schnittliste_{q['q']}_{q['name']}.txt")
    with open(fn, "w", encoding="utf-8") as f:
        f.write(f"{q['q']} - {q['src']}\n\nEinsaetze laut Marker:\n")
        for s, e in q["abs"]:
            f.write(f"  {hms(s)} - {hms(e)}\n")
        f.write("\nBehaltene Spielabschnitte (Zeit im Originalvideo):\n")
        for a, b, _ in segs:
            f.write(f"  {hms(a)} - {hms(b)}\n")
        f.write(f"Laenge: {hms(sum(b - a for a, b, _ in segs))}\n\nHerausgeschnittene Unterbrechungen:\n")
        for s, e in q["abs"]:
            t = s
            for a, b in sorted((a, b) for a, b, s0 in segs if s0 == s):
                if a - t >= 1:
                    f.write(f"  {hms(t)} - {hms(a)}\n")
                t = b
            if e - t >= 1:
                f.write(f"  {hms(t)} - {hms(e)}\n")
        f.write(f"\nHighlights: {len(q['hl'])}\n")


def prepare(P):
    for i, q in enumerate(P["quarters"]):
        step(i, len(P["quarters"]), f"Spiel {q['name']} wird angeschaut")
        resolve_stints(q)
        if not q["abs"]:
            say(f"{q['q']} ({q['src']}): keine Einsatzzeit markiert, uebersprungen.")
            q["segs"] = []
            continue
        segs, cams = analyse(P, q)
        q["segs"], q["cams"] = segs, cams
        # Kamera-Korrekturen veraendern das Bild, aber nicht die Schnitte -> eigener Teil im Schluessel
        ck = [[f["what"], f["a"], f["b"], f["pos"]] for f in fixes_for(P, q, "kamera", "weit")]
        q["camkey"] = ([ck] if ck else []) + bild_key(P["bild"])
        write_report(P, q, segs)
        with open(os.path.join(P["work"], f"schnitt_{q['name']}.json"), "w", encoding="utf-8") as f:
            json.dump({"q": q["q"], "name": q["name"], "dur": q["dur"], "abs": q["abs"],
                       "segs": [[a, b] for a, b, _ in segs], "hl": q["hl"]}, f)


# ---------------------------------------------------------------- Befehle
def cmd_sichtkopien(folder):
    os.makedirs(WORK, exist_ok=True)
    vids = originals()
    if not vids:
        die("Keine Videodateien (.MP4) im Spielordner gefunden.")
    P = {"work": WORK}
    for i, v in enumerate(vids):
        say(f"[{i + 1}/{len(vids)}]")
        step(i, len(vids), f"Sichtkopie {os.path.splitext(v)[0].upper()}")
        make_sicht(P, v)
    say(f"\nSichtkopien liegen in: {os.path.join(folder, WORK)}")
    say("Jetzt Marker.html oeffnen, die Sichtkopien markieren und marker_<Video>.txt")
    say("in den Spielordner speichern.")


def cmd_vorschau(P):
    prepare(P)
    for q in P["quarters"]:
        if not q["segs"]:
            continue
        out = f"Vorschau_{q['q']}_{q['name']}.mp4"
        key = h(q["segs"], q["abs"], *q["camkey"])
        if up_to_date(out, key):
            say(f"{q['q']}: Vorschau ist aktuell.")
            continue
        say(f"\n=== {q['q']} {q['name']} Vorschau ===")
        concat(P, render(P, q, q["segs"], q["cams"], "vorschau"), out)
        mark_done(out, key)
        say(f"  Fertig: {out}")


def cmd_videos(P):
    prepare(P)
    ends, hls = [], []
    for q in P["quarters"]:
        if not q["segs"]:
            continue
        out = os.path.join(WORK, f"Einsatzzeit_{q['q']}_{q['name']}.mp4")
        key = h(q["segs"], q["abs"], q["src"], *q["camkey"])
        if up_to_date(out, key):
            say(f"{q['q']}: Einsatzzeit schon erstellt.")
        else:
            say(f"\n=== {q['q']} {q['name']}: Einsatzzeit ({len(q['segs'])} Teile) ===")
            concat(P, render(P, q, q["segs"], q["cams"], "end"), out)
            mark_done(out, key)
        ends.append(out)
        if not q["hl"]:
            continue
        hout = os.path.join(WORK, f"Highlights_{q['q']}_{q['name']}.mp4")
        hsegs = hl_segments(q)
        key = h(hsegs, q["src"], *q["camkey"])
        if up_to_date(hout, key):
            say(f"{q['q']}: Highlights schon erstellt.")
        else:
            say(f"\n=== {q['q']} {q['name']}: Highlights ({len(hsegs)} Szenen) ===")
            clips = render(P, q, hsegs, q["cams"], "hl")
            say("  Ueberblendungen ...")
            step(0, 1, f"Highlights {q['name']} ueberblenden")
            xfade_join(P, clips, hout)
            for c in clips:
                os.remove(c)
            mark_done(hout, key)
        hls.append(hout)
    results = []
    if ends:
        fin = f"{P['base']}_Einsatzzeit.mp4"
        say("\nEinsatzzeit-Video zusammenfuegen ...")
        step(0, 1, "Einsatzzeit zusammenfuegen")
        if len(ends) == 1:
            shutil.copyfile(ends[0], fin)
        else:
            concat(P, ends, fin, delete=False)
        results.append(fin)
    if hls:
        fin = f"{P['base']}_Highlights.mp4"
        say("Highlight-Video zusammenfuegen ...")
        step(0, 1, "Highlights zusammenfuegen")
        xfade_join(P, hls, fin)
        results.append(fin)
    # Aufraeumen: nur Originale + Ergebnisse bleiben
    shutil.rmtree(WORK, ignore_errors=True)
    for f in os.listdir("."):
        fl = f.lower()
        if (fl.startswith("marker_") and fl.endswith(".txt")) or fl in ("korrekturen.txt", BILD_FILE) \
                or (fl.startswith("vorschau_") and (fl.endswith(".mp4") or fl.endswith(".plan"))) \
                or (fl.startswith("schnittliste_") and fl.endswith(".txt")):
            try:
                os.remove(f)
            except OSError:
                pass
    say("\nErgebnis im Spielordner:")
    for r in results:
        say("  " + r)


def main():
    cmds = {"sichtkopien": None, "vorschau": cmd_vorschau, "videos": cmd_videos}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        say(__doc__)
        sys.exit(1)
    try:
        need_tools()
        folder = choose_folder()
        t0 = time.time()
        if sys.argv[1] == "sichtkopien":
            cmd_sichtkopien(folder)
        else:
            cmds[sys.argv[1]](load_plan(folder))
    except Fehler as e:
        say("\nFEHLER: " + str(e))
        sys.exit(1)
    d = int(time.time() - t0)
    say(f"\nFERTIG nach {d // 60} Min {d % 60} s.")


if __name__ == "__main__":
    main()
