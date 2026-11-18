"""
Spielschnitt - Desktop-App starten (Doppelklick, kein Konsolenfenster).

Startet den lokalen Server aus app/server.py und oeffnet die Oberflaeche
als eigenes App-Fenster (Microsoft Edge oder Chrome im App-Modus).
Wird das Fenster geschlossen, beendet sich auch die App.
"""
import os, socket, subprocess, sys, threading, time, traceback, webbrowser

TOOL = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.environ.get("LOCALAPPDATA") or TOOL, "Spielschnitt")
PORT = 47615
os.makedirs(DATA, exist_ok=True)

# pythonw hat keine Konsole: Fehler in eine Logdatei schreiben
if sys.stderr is None or sys.stdout is None:
    sys.stdout = sys.stderr = open(os.path.join(DATA, "app.log"), "a", encoding="utf-8", buffering=1)

sys.path.insert(0, TOOL)

# Installierte App: mitgeliefertes ffmpeg (Ordner "ffmpeg" neben der .exe) zuerst verwenden
if getattr(sys, "frozen", False):
    for d in (os.path.join(os.path.dirname(sys.executable), "ffmpeg"),
              os.path.join(getattr(sys, "_MEIPASS", ""), "ffmpeg")):
        if os.path.exists(os.path.join(d, "ffmpeg.exe")):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            break


def port_in_use(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_browser():
    pf = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for base in filter(None, pf):
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            p = os.path.join(base, rel)
            if os.path.exists(p):
                return p
    return None


def open_window(url):
    """App-Fenster oeffnen. Liefert den Prozess, wenn er bis zum Schliessen des Fensters laeuft."""
    br = find_browser()
    if not br:
        webbrowser.open(url)
        return None
    return subprocess.Popen([br, f"--app={url}", f"--user-data-dir={os.path.join(DATA, 'fenster')}",
                             "--no-first-run", "--no-default-browser-check", "--window-size=1360,900",
                             "--autoplay-policy=no-user-gesture-required"])


def message(text):
    try:
        import tkinter
        from tkinter import messagebox
        r = tkinter.Tk()
        r.withdraw()
        messagebox.showerror("Spielschnitt", text)
        r.destroy()
    except Exception:
        pass


def main():
    url = f"http://127.0.0.1:{PORT}/"
    if port_in_use(PORT):                 # App laeuft schon: nur ein weiteres Fenster zeigen
        open_window(url)
        return
    from app import server
    srv = server.make_server(PORT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    server.UI_LOOP["active"] = True        # Ordner-Dialoge laufen hier im Hauptthread
    t0 = time.time()
    proc = open_window(url)
    if proc is not None:
        while proc.poll() is None:
            server.serve_dialogs(0.3)
    if proc is None or time.time() - t0 < 5:
        # Fenster gehoert zu einem schon laufenden Browser: am Lebenszeichen der Seite erkennen,
        # wann sie geschlossen wurde (nie waehrend ein Arbeitsschritt laeuft).
        while server.JOB["running"] or time.time() - server.STATE["last_ping"] < 120:
            server.serve_dialogs(0.5)
    server.cancel_job()
    for _ in range(50):                   # ffmpeg sauber beenden lassen
        if not server.JOB["running"]:
            break
        time.sleep(0.1)
    srv.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        message("Die App konnte nicht starten.\n\n" + traceback.format_exc()[-800:])
