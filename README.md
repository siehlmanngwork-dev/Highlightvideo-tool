# 🏀 Spielschnitt

**Aus langen GoPro-Aufnahmen eines Basketballspiels automatisch zwei fertige Videos machen:**

- **Einsatzzeit**: die ganze Spielzeit eines Spielers, ohne Pausen, Auszeiten und Bankzeiten
- **Highlights**: nur die markierten tollen Szenen, mit weichen Überblendungen

Die Kamera folgt dabei automatisch dem Spiel: Aus dem Weitwinkelbild wird ein 16:9-Ausschnitt geschnitten, der dem Geschehen folgt. Die Fischaugen-Verzerrung wird korrigiert, das Ergebnis ist ein Video in 1920×1080.

Die App ist bewusst einfach gehalten und funktioniert auch für Kinder: ein Fenster, fünf Schritte, große Knöpfe.

---

## ⬇️ Download

**[SpielschnittSetup.exe herunterladen](https://github.com/siehlmanngwork-dev/Highlightvideo-tool/releases/latest/download/SpielschnittSetup.exe)**
(oder unter [Releases](https://github.com/siehlmanngwork-dev/Highlightvideo-tool/releases) die neueste Version wählen)

Webseite: **https://siehlmanngwork-dev.github.io/Highlightvideo-tool/**

**Voraussetzungen:** Windows 10 oder 11 (64 Bit) und Microsoft Edge (ist bei Windows dabei).
Sonst wird nichts gebraucht: Python und ffmpeg stecken schon im Setup.

### Installation

1. `SpielschnittSetup.exe` herunterladen und doppelklicken.
2. Erscheint **„Der Computer wurde durch Windows geschützt“**, auf **Weitere Informationen → Trotzdem ausführen** klicken.
   (Das kommt, weil das Setup nicht digital signiert ist.)
3. Den Schritten folgen. Administratorrechte sind nicht nötig, installiert wird nur für deinen Benutzer.
4. Danach **Spielschnitt** über das Startmenü oder das Desktop-Symbol starten.

Deinstallieren geht über *Einstellungen → Apps → Spielschnitt*.

---

## So funktioniert's

Vorbereitung: Lege für jedes Spiel einen eigenen Ordner an und kopiere **nur die Videos dieses Spiels** hinein.
Die Reihenfolge der Dateinamen ist die Reihenfolge im fertigen Video (`GX010535` vor `GX010536` …).
Der Ordnername wird zum Namen der fertigen Videos.

| Schritt | Was passiert | Dauer |
|---|---|---|
| **1 · Spiel wählen** | Spielordner auswählen. Die App zeigt alle Videos und was schon erledigt ist. | – |
| **2 · Sichtkopien** | Kleine Kopien der Videos, damit man flüssig markieren kann. | ca. 5–15 Min pro Video |
| **3 · Markieren** | Video ansehen und markieren, wann der Spieler aufs Feld geht, runtergeht und was ein Highlight ist. Wird automatisch gespeichert. | so lange wie du schaust |
| **4 · Vorschau** *(freiwillig)* | Kleine Vorschau der Einsatzzeit ansehen und bei Bedarf korrigieren (siehe unten). | ein paar Minuten |
| **5 · Videos erstellen** | Fertige Videos in voller Qualität. Danach wird aufgeräumt. | ca. 30–60 Min pro Video |

Am Ende liegen im Spielordner nur noch:

```
GX010535.MP4, GX010536.MP4, …          ← Originale (werden nie verändert)
<Ordnername>_Einsatzzeit.mp4
<Ordnername>_Highlights.mp4
```

### Tasten beim Markieren

| Taste | Bedeutung |
|---|---|
| `E` | 🟢 **Rein**: Spieler kommt aufs Feld |
| `A` | 🔴 **Raus**: Spieler geht runter |
| `H` | ⭐ **Highlight** |
| `Z` | nächstgelegene Markierung löschen |
| `Leertaste` | Abspielen / Pause |
| `←` / `→` | 5 Sekunden zurück / vor |
| `J` / `L` | 1 Sekunde zurück / vor |
| `,` / `.` | ein Bild zurück / vor |

Tipps:
- Ist der Spieler schon am Anfang des Videos auf dem Feld, braucht es kein **Rein**. Bleibt er bis zum Ende drin, braucht es kein **Raus**.
- Pausen, Auszeiten und Freiwürfe musst du **nicht** markieren, die schneidet die App selbst heraus.
- Rechts lässt sich einstellen, wie viele Sekunden vor und nach einem Highlight mit ins Video kommen.

### Korrigieren in der Vorschau

Unter der Vorschau zeigt eine Leiste, was die App entschieden hat:
🟩 **grün** = kommt ins Video, ▨ **grau gestreift** = rausgeschnitten, ⬛ **dunkel** = Bank.

1. Eine Stelle auswählen: entweder **Start hier** und **Ende hier** drücken oder ein graues Stück anklicken.
   Graue Stücke kann man sich direkt ansehen.
2. Festlegen, was damit passieren soll:
   - **✂ Rausschneiden**: kommt nicht ins Video
   - **✚ Wieder rein**: eine rausgeschnittene Stelle zurückholen
   - **🎥 Kamera fest**: kein automatischer Schwenk, mit dem Regler wählen, wohin die Kamera schaut
   - **🔭 Ganzes Feld**: das ganze Bild ohne Ausschnitt und ohne Schwenk
3. **🔄 Vorschau neu machen**, um das Ergebnis zu sehen.

Die Korrekturen gelten auch für die fertigen Videos in Schritt 5.

---

## Fragen & Probleme

- **„Hoppla, da ist etwas schiefgegangen“**: Unter *Details (für Erwachsene)* steht die genaue Meldung.
  Das ausführliche Protokoll liegt in `<Spielordner>\_arbeit\log.txt`.
- **Abgebrochen oder PC ausgegangen?** Einfach den Schritt nochmal starten. Fertige Teile werden übersprungen.
- **Ein Video fehlt im Ergebnis?** Nur markierte Videos kommen ins fertige Video. Schritt 5 zeigt eine Warnung, welche fehlen.
- **App startet nicht?** Fehlerprotokoll: `%LOCALAPPDATA%\Spielschnitt\app.log`
- **Datenschutz:** Alles läuft auf deinem PC. Es wird nichts hochgeladen, die App benutzt kein Internet.

---

## Für Entwickler

### Aufbau

```
Spielschnitt.pyw        Starter: lokaler Server + App-Fenster (Edge/Chrome im App-Modus)
spielschnitt.py         Videologik (nur Python-Standardbibliothek + ffmpeg/ffprobe)
app/server.py           lokaler HTTP-Server (127.0.0.1), API, Hintergrund-Jobs
app/ui/                 Oberfläche (HTML/CSS/JS, ohne Frameworks)
app/spielschnitt.ico    App-Symbol
build/                  Build-Skripte für SpielschnittSetup.exe
docs/                   Download-Webseite (GitHub Pages)
```

Die Oberfläche läuft als Webseite in einem Edge-Fenster im App-Modus. Der Server lauscht nur auf `127.0.0.1`.
Die Arbeitsschritte laufen in einem Hintergrund-Thread und sind über den Stopp-Knopf abbrechbar.

### Aus dem Quellcode starten

Voraussetzungen: Python ≥ 3.10 und `ffmpeg`/`ffprobe` im `PATH` (z. B. `winget install Gyan.FFmpeg`).

```bash
pythonw Spielschnitt.pyw
```

Die Videologik geht auch ohne Oberfläche über die Kommandozeile:

```bash
python spielschnitt.py sichtkopien "D:\Spiele\2026-11-22 Darmstadt"
python spielschnitt.py vorschau    "D:\Spiele\2026-11-22 Darmstadt"
python spielschnitt.py videos      "D:\Spiele\2026-11-22 Darmstadt"
```

### Setup bauen

```bash
python -m pip install pyinstaller
winget install JRSoftware.InnoSetup
powershell -ExecutionPolicy Bypass -File build\build.ps1 -Version 1.0.0
```

Ergebnis: `build\out\SpielschnittSetup.exe`. Das Skript packt die App mit PyInstaller, legt `ffmpeg.exe` und `ffprobe.exe` aus dem `PATH` dazu und baut mit Inno Setup das Installationsprogramm.

> Die Setup-Datei ist größer als 100 MB und gehört **nicht** ins Repository. Lade sie stattdessen als Datei zu einem
> [GitHub Release](https://docs.github.com/de/repositories/releasing-projects-on-github/managing-releases-in-a-repository) hoch.

### Dateien im Spielordner

| Datei | Inhalt |
|---|---|
| `marker_<Video>.txt` | Markierungen aus Schritt 3 (`REIN`/`RAUS`/`HL` + Zeit) |
| `korrekturen.txt` | Korrekturen aus Schritt 4, siehe unten |
| `Vorschau_V1_<Video>.mp4`, `Schnittliste_…txt` | Vorschau und Schnittübersicht |
| `_arbeit\` | Sichtkopien, Bewegungsanalyse, Zwischenteile, `log.txt` |

`korrekturen.txt` (Zeiten im Originalvideo, spätere Zeilen gewinnen):

```
GX010540 schneiden: 17:15.0-17:31.0
GX010540 behalten: 13:53.0-14:03.0
GX010540 kamera 0.400: 05:10.0-05:25.0     (0 = ganz links, 1 = ganz rechts)
GX010540 weit: 22:00.0-22:12.0
```

Wichtige Einstellungen stehen oben in `spielschnitt.py`, zum Beispiel Linsenkorrektur (`LENS`), Bildausschnitt (`CROP_W`, `CROP_Y`), Kamerageschwindigkeit (`CAM_SPEED`) und Pausenerkennung (`STOP_REL`, `STOP_MIN`).

---

## Lizenz

Spielschnitt steht unter der **GNU General Public License v3.0**, siehe [LICENSE](LICENSE).

### Drittanbieter

- **FFmpeg** (im Setup enthalten): GPLv3, Build von [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), Quellcode unter [ffmpeg.org](https://ffmpeg.org/download.html).
  Spielschnitt ruft ffmpeg nur als eigenständiges Programm auf.
- **Python** (über PyInstaller eingebettet): [Python Software Foundation License](https://docs.python.org/3/license.html)
