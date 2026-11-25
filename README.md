# WoW: Forever Addon-Manager (Linux)

Ein inoffizieller Addon-Manager für **WoW: Forever** (Interface 16xxx) unter Linux. Er funktioniert mit Installationen unter Steam/Proton, Lutris, Wine, Bottles oder Heroic, erkennt die Addons in deinem `AddOns`-Ordner, zeigt verfügbare Updates an und installiert sie mit automatischem Backup, auf Wunsch auch still im Hintergrund aus der Menüleiste heraus.

![Hauptfenster](docs/screenshots/main.png)

## Funktionen

### Updates

- **Erkennung per CurseForge-Fingerprint**: Installierte Addons werden anhand ihrer Dateien erkannt, ganz ohne manuelle Zuordnung. GitHub-Releases dienen als Ausweichquelle.
- **Ein Klick genügt**: Nach jeder Prüfung sind alle veralteten Addons angehakt, „N aktualisieren“ spielt sie ein. Geprüft wird beim Start und jederzeit über das Refresh-Symbol oben links (<kbd>F5</kbd> oder <kbd>Strg</kbd>+<kbd>R</kbd>).
- **Changelog vorab**: Der Changelog der neuen Version erscheint als Tooltip über der Zeile und per Rechtsklick → „Changelog …“.
- **Addons ignorieren**: Per Rechtsklick → „Updates ignorieren“ wird ein Addon nie mehr vorgemerkt und nicht mitgezählt, etwa wenn du bewusst bei einer älteren Version bleibst.
- **Nur Forever-Dateien**: Geladen wird gezielt der Forever-Build eines Releases, die `.toc` wird auf Interface 16xxx geprüft.

### Downloads ohne Umweg

- **Direkt-Download auch für gesperrte Addons**: Manche Autoren geben ihr Addon nicht für die CurseForge-API frei (z. B. DBM, Auctionator). Dann lädt der Manager dieselbe Datei automatisch über den Download-Link der CurseForge-Website bzw. das CurseForge-CDN, ganz ohne Browser. Abschaltbar unter ☰ → Einstellungen.
- **Browser als letzter Ausweg**: Klappt auch das nicht, öffnet sich die exakte Dateiseite (oder eine auf die Forever-Spielversion vorgefilterte Dateiliste), und der Manager wartet auf die heruntergeladene Zip-Datei. Mehrere Addons werden nacheinander abgearbeitet (jederzeit überspringen oder abbrechen), am Ende gibt es eine Übersicht.
- **Download-Ordner aus dem Browser**: Überwacht wird der Download-Ordner deines Standardbrowsers (Chrome/Chromium-Familie, Firefox-Familie inkl. Flatpak/Snap), dazu die Ordner der übrigen erkannten Browser und der XDG-Download-Ordner. Ein eigener Ordner lässt sich unter ☰ → Einstellungen festlegen. Aus den Browser-Profilen werden nur die Download-Einstellungen gelesen, sonst nichts.

### Im Hintergrund

- **Tray und Autostart**: Optional startet der Manager mit dem System und läuft minimiert in der Menüleiste. Er prüft beim Start und stündlich (einstellbar) und meldet sich nur, wenn es neue Updates gibt („3 Updates verfügbar“), sonst bleibt er still.
- **Tray-Menü** (Rechtsklick auf das Symbol): „N Addons aktualisieren“, „Jetzt prüfen“, „App öffnen“, „Einstellungen …“, „Protokoll …“, „Beenden“. Ein Linksklick zeigt oder versteckt das Fenster.
- **Auto-Update (optional)**: Der Manager installiert Updates selbst, aber nur, solange WoW nicht läuft. Läuft das Spiel, wartet er und versucht es alle 5 Minuten erneut.
- **Selbst-Update**: Neue Versionen des Managers werden über die GitHub-Releases gemeldet. Die Release-Datei ersetzt sich auf Wunsch selbst, optional auch automatisch.

### Neue Addons

- **Alle Forever-Addons durchblättern**: sortierbar nach Downloads, Beliebtheit, Aktualität oder Name, mit Filterfeld und Seiten. Der Tooltip zeigt Logo, Beschreibung, Kategorien und Screenshots.
- **Weitere Wege**: CurseForge-Projekt-ID, `gh:owner/repo`, GitHub-URL, direkter Zip-Link oder lokale Zip-Datei (Reiter „Direkt“).

![Neues Addon installieren](docs/screenshots/new-addon.png)

### Sicherheit

- **Backups und Wiederherstellen**: Ersetzte Ordner werden zuerst in einen Backup-Satz verschoben (die letzten 5 bleiben erhalten). `WTF`/SavedVariables werden nie angefasst.
- **Deinstallieren**: Die Ordner eines Addon-Pakets wandern in einen Backup-Satz (über ☰ → „Backups“ wiederherstellbar). Abhängigkeiten anderer Addons werden vorher angezeigt.
- **Kompatibilitätsprüfung** vor jeder Installation, mit Warnung bei Paketen, die WoW: Forever nicht laden wird. Läuft WoW scheinbar gerade, erscheint ein Hinweis (die Erkennung ist eine Heuristik und kann danebenliegen).

## Download (einfachster Weg)

1. Lade `wow-forever-addon-manager-x86_64-linux` aus dem [neuesten Release](https://github.com/m3rtl/wow-forever-addon-manager-linux/releases/latest) herunter (prüfbar mit `sha256sum -c SHA256SUMS`).
2. Ausführbar machen und starten:
   ```sh
   chmod +x wow-forever-addon-manager-x86_64-linux
   ./wow-forever-addon-manager-x86_64-linux
   ```
3. Optional: ☰ → „Startmenü-Eintrag anlegen“ fügt den Manager deinem Anwendungsmenü hinzu (alternativ mit `--install-desktop-entry` starten).

Die Datei wird auf Ubuntu 22.04 gebaut (benötigt glibc 2.35 oder neuer) und bringt Python und GTK selbst mit. Auf anderen oder älteren Distributionen läuft sie eventuell nicht; dann die Quellcode-Version nutzen.

## Bedienung

| Was | Wo |
| --- | --- |
| Auf Updates prüfen | Refresh-Symbol oben links, <kbd>F5</kbd>, <kbd>Strg</kbd>+<kbd>R</kbd> |
| Markierte aktualisieren | „N aktualisieren“ unten links |
| Changelog, Ignorieren, Seite/Ordner öffnen, Browser-Download, Deinstallieren | Rechtsklick auf eine Zeile (oder Menütaste) |
| Protokoll, Backups, Einstellungen, Programm-Updates, Beenden | ☰-Menü oben rechts |

## Tray, Autostart und Updates im Hintergrund

Einschalten unter ☰ → Einstellungen, Bereich „Hintergrund“:

- **Beim Systemstart im Tray starten** legt `~/.config/autostart/wow-forever-addon-manager.desktop` an (startet mit `--tray`).
- **Fenster schließen minimiert in den Tray** (Standard: an). Beenden dann über das Tray-Menü oder ☰ → „Beenden“.
- **Prüfintervall** in Minuten (Standard: 60).
- **Updates automatisch installieren (nur wenn WoW nicht läuft)** (Standard: aus).

Warum nicht während WoW läuft? Das Spiel liest Addons beim Einloggen und bei `/reload`. Wird genau dann ein Ordner ausgetauscht oder haben sich Abhängigkeiten zwischen Addons geändert, lädt WoW einen halbfertigen Stand. Deshalb wartet das Auto-Update, bis das Spiel beendet ist.

Das Tray-Symbol braucht einen StatusNotifier-Host: KDE, Xfce, Cinnamon, MATE und Budgie haben einen, unter GNOME die Erweiterung „AppIndicator and KStatusNotifierItem Support“ (bei Ubuntu und Zorin vorinstalliert). Ohne Tray schließt das Fenster ganz normal. Ein zweiter Start des Programms holt das laufende Fenster nach vorn.

## Programm-Updates

Der Manager prüft die GitHub-Releases beim Start und im Tray-Betrieb höchstens alle 12 Stunden. Gibt es eine neue Version, erscheint ein Hinweis im Fenster bzw. eine Benachrichtigung aus dem Tray, mit „Aktualisieren“, „Details“ oder „Überspringen“.

- **Release-Datei**: ersetzt sich selbst, aber nur nach erfolgreicher SHA256-Prüfung gegen `SHA256SUMS`. Die vorige Version bleibt als `<datei>.old` daneben liegen. Mit „Programm-Updates automatisch installieren“ geschieht das ohne Nachfrage.
- **Quellcode-Version**: Es gibt nur einen Hinweis mit Link zur Release-Seite.

Beides lässt sich unter ☰ → Einstellungen abschalten.

## Aus dem Quellcode starten

Voraussetzungen: Python 3.10 oder neuer. Für die GUI zusätzlich `python3-gi` und GTK 3 (`gir1.2-gtk-3.0`). Der Kommandozeilenmodus braucht nur die Standardbibliothek. Für Tray und Benachrichtigungen sind keine weiteren Pakete nötig (sie laufen direkt über D-Bus).

```sh
./start.sh                 # GUI (ohne Display / PyGObject automatisch Kommandozeile)
./start.sh --tray          # minimiert im Tray starten (so startet auch der Autostart-Eintrag)
./start.sh --cli           # interaktive Kommandozeile
./start.sh --check         # nur die Tabelle ausgeben
./start.sh --check --addons-dir PFAD
```

Die Einzeldatei selbst bauen: `./build.sh` (Ergebnis in `dist/`).

## CurseForge-API-Key

Kostenlos unter <https://console.curseforge.com>. Eintragen unter ☰ → Einstellungen oder über die Umgebungsvariable `CF_API_KEY` (hat Vorrang). Ohne Key lassen sich nur GitHub-basierte und manuell zugeordnete Pakete prüfen.
Manche Keys dürfen die Suche nicht nutzen; dann zeigt „Neues Addon“ die Liste der vorgestellten Addons, und es helfen eine Projekt-ID oder die Suche im Browser.

## Wo Daten gespeichert werden

- Aus dem Quellcode gestartet: neben dem Programm (`config.json`, `backups/`, `cache/`).
- Release-Datei: in den XDG-Ordnern (`~/.config`, `~/.local/share`, `~/.cache`, jeweils unter `wow-forever-addon-manager`).
- `WOW_FA_HOME=<Ordner>` überschreibt beides.

## Datenschutz

Dein API-Key wird nur lokal in `config.json` gespeichert (Rechte 0600) und ist nie Teil dieses Repositorys. Das Programm spricht nur mit der CurseForge-API, der CurseForge-Website (Download-Link), dem CurseForge-CDN (Downloads, Logos, Screenshots), GitHub (Addons und die eigene Update-Prüfung) und den Download-Servern der Pakete, die du installierst. Keine Telemetrie.

## Kompatibilitätsregeln

Das Client-Interface wird aus deiner Installation gelesen (derzeit 16001). Für jeden Addon-Ordner zählt die erste vorhandene TOC-Datei aus `<Name>_Forever.toc`, `<Name>-Forever.toc`, `<Name>.toc`. Installiert werden nur kompatible Ordner (oder solche, die bereits installiert sind); alle anderen werden übersprungen und aufgelistet.

## Schrift und Grafiken

Die Titelschrift ist [Cinzel](https://github.com/NDISCOVER/Cinzel) unter der SIL Open Font License 1.1 (`assets/fonts/cinzel/OFL.txt`). Sie wird zur Laufzeit nur für dieses Programm registriert; ohne sie wird eine Ersatz-Serifenschrift verwendet. Alle Ornamente sind eigene Zeichnungen; es werden keine Logos, Grafiken oder Schriften von Blizzard verwendet. Das klassische Theme lässt sich unter ☰ → Einstellungen abschalten (dann gilt das Systemtheme).

## Haftungsausschluss

Inoffizielles Community-Werkzeug. Nicht verbunden mit oder unterstützt von Blizzard Entertainment oder CurseForge/Overwolf. Alle Marken gehören ihren jeweiligen Inhabern. Nutzung auf eigene Gefahr; es werden Backups angelegt, eigene Sicherungen schaden trotzdem nicht.

## Lizenz

[MIT](LICENSE), Copyright (c) 2026 m3rtl.
