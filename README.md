# WoW: Forever Addon-Manager (Linux)

Ein inoffizieller Addon-Manager für **WoW: Forever** (Interface 16xxx) unter Linux. Er funktioniert mit Installationen unter Steam/Proton, Lutris, Wine, Bottles oder Heroic, durchsucht deinen `AddOns`-Ordner, erkennt deine Addons, zeigt verfügbare Updates an und installiert sie mit automatischem Backup.

![Hauptfenster](docs/screenshots/main.png)

## Funktionen

- **CurseForge-Erkennung per Fingerprint**: Installierte Addons werden anhand ihrer Dateien erkannt, ganz ohne manuelle Zuordnung.
- **Nur Forever-Dateien**: Es wird gezielt der Forever-Build eines Releases geladen und die `.toc` auf Interface 16xxx geprüft.
- **GitHub als Ausweichquelle** für Addons, die als GitHub-Release veröffentlicht werden.
- **Direkt-Download auch für gesperrte Addons**: Bieten Autoren ihr Addon nicht über die CurseForge-API an (z. B. DBM, Auctionator), lädt der Manager dieselbe Datei automatisch über den Download-Link der CurseForge-Website bzw. das CurseForge-CDN, ganz ohne Browser. Abschaltbar unter ☰ → Einstellungen.
- **Tray und Autostart**: Optional startet der Manager mit dem System und läuft minimiert in der Menüleiste. Er prüft beim Start und stündlich (einstellbar) auf Updates und meldet sich nur, wenn es neue gibt („3 Updates verfügbar“). Rechtsklick auf das Symbol: Addons aktualisieren, Jetzt prüfen, App öffnen, Einstellungen, Protokoll, Beenden. Auf Wunsch installiert er Updates selbst, aber nur, solange WoW nicht läuft.
- **Updates im Blick**: Nach jeder Prüfung sind alle veralteten Addons angehakt, ein Klick auf „N aktualisieren“ genügt. Der Changelog der neuen Version erscheint als Tooltip und per Rechtsklick. Einzelne Addons lassen sich per Rechtsklick „ignorieren“, sie werden dann nie vorgemerkt und nicht mitgezählt.
- **Selbst-Update**: Der Manager prüft GitHub-Releases auf neue Versionen. Die Release-Datei ersetzt sich auf Wunsch selbst (nach SHA256-Prüfung gegen `SHA256SUMS`, die vorige Version bleibt als `.old` liegen), optional auch automatisch.
- **Browser als letzter Ausweichweg**: Klappt auch der Direkt-Download nicht, öffnet sich die exakte Dateiseite (oder eine auf die Forever-Spielversion vorgefilterte Dateiliste) und der Manager wartet auf die neue Zip-Datei. Sind mehrere Addons markiert, werden die Browser-Downloads nacheinander abgearbeitet (jederzeit überspringen oder abbrechen), am Ende gibt es eine Übersicht.
- **Download-Ordner aus dem Browser**: Der Manager liest die Download-Einstellung deines Standardbrowsers (Chrome/Chromium-Familie, Firefox-Familie inkl. Flatpak/Snap) und überwacht zusätzlich die Ordner der übrigen erkannten Browser sowie den XDG-Download-Ordner. Ein eigener Ordner lässt sich unter ☰ → Einstellungen festlegen. Aus den Browser-Profilen werden nur die Download-Einstellungen gelesen, sonst nichts.
- **Klassischer Look**: dunkles Fantasy-Theme mit Goldakzenten und selbst gezeichneten Ornamenten, abschaltbar unter ☰ → Einstellungen („Klassisches Theme“; aus = Systemtheme).
- **Neue Addons installieren**: über die durchblätterbare Liste aller Forever-Addons (sortierbar nach Downloads, Beliebtheit, Aktualität oder Name, mit Logo, Beschreibung und Screenshots im Tooltip), die Suche, eine CurseForge-Projekt-ID, `gh:owner/repo`, eine GitHub-URL, einen direkten Zip-Link oder eine lokale Zip-Datei.
- **Backups und Wiederherstellen**: Ersetzte Ordner werden zuerst in einen Backup-Satz verschoben (die letzten 5 bleiben erhalten). `WTF`/SavedVariables werden nie angefasst.
- **Deinstallieren**: Entfernt ein Addon-Paket, indem seine Ordner in einen Backup-Satz verschoben werden (über „Backups“ wiederherstellbar). Abhängigkeiten anderer Addons werden vorher angezeigt. Deine Einstellungen (`WTF`/SavedVariables) bleiben erhalten.
- **Kompatibilitätsprüfung** vor jeder Installation, mit Warnung bei Paketen, die WoW: Forever nicht laden wird. Läuft WoW scheinbar gerade, erscheint ein Hinweis (die Erkennung ist eine Heuristik und kann danebenliegen).

![Neues Addon installieren](docs/screenshots/new-addon.png)

## Download (einfachster Weg)

1. Lade `wow-forever-addon-manager-x86_64-linux` aus dem [neuesten Release](https://github.com/m3rtl/wow-forever-addon-manager-linux/releases/latest) herunter (prüfbar mit `SHA256SUMS`).
2. Ausführbar machen und starten:
   ```sh
   chmod +x wow-forever-addon-manager-x86_64-linux
   ./wow-forever-addon-manager-x86_64-linux
   ```
3. Optional: Menü ☰ → „Startmenü-Eintrag anlegen“ fügt den Manager deinem Anwendungsmenü hinzu (alternativ mit `--install-desktop-entry` starten).

Die Datei wird auf Ubuntu 22.04 gebaut (benötigt glibc 2.35 oder neuer) und bringt Python und GTK selbst mit. Auf anderen oder älteren Distributionen läuft sie eventuell nicht; dann die Quellcode-Version nutzen (für die GUI `python3-gi` und GTK 3, der Kommandozeilenmodus kommt ohne aus).

## Aus dem Quellcode starten

Voraussetzungen: Python 3.10 oder neuer. Für die GUI zusätzlich `python3-gi` und GTK 3 (`gir1.2-gtk-3.0`). Der Kommandozeilenmodus braucht nur die Standardbibliothek.

```sh
./start.sh                 # GUI (ohne Display / PyGObject automatisch Kommandozeile)
./start.sh --cli           # interaktive Kommandozeile
./start.sh --check         # nur die Tabelle ausgeben
./start.sh --check --addons-dir PFAD
./start.sh --tray          # minimiert im Tray starten (so startet auch der Autostart-Eintrag)
```

Den Autostart schaltest du unter ☰ → Einstellungen → „Beim Systemstart im Tray starten“ ein (legt `~/.config/autostart/wow-forever-addon-manager.desktop` an). Das Tray-Symbol braucht einen StatusNotifier-Host: KDE, Xfce, Cinnamon, MATE und Budgie haben einen, unter GNOME die Erweiterung „AppIndicator and KStatusNotifierItem Support“ (bei Ubuntu und Zorin vorinstalliert). Ohne Tray schließt das Fenster ganz normal.

Die Einzeldatei selbst bauen: `./build.sh` (Ergebnis in `dist/`).

## CurseForge-API-Key

Kostenlos unter <https://console.curseforge.com>. Eintragen unter ☰ → Einstellungen oder über die Umgebungsvariable `CF_API_KEY` (hat Vorrang). Ohne Key lassen sich nur GitHub-basierte und manuell zugeordnete Pakete prüfen.
Manche Keys dürfen die Suche nicht nutzen; dann helfen die Liste „Beliebt“, eine Projekt-ID oder die Suche im Browser.

## Wo Daten gespeichert werden

- Aus dem Quellcode gestartet: neben dem Programm (`config.json`, `backups/`, `cache/`).
- Release-Datei: in den XDG-Ordnern (`~/.config`, `~/.local/share`, `~/.cache`, jeweils unter `wow-forever-addon-manager`).
- `WOW_FA_HOME=<Ordner>` überschreibt beides.

## Datenschutz

Dein API-Key wird nur lokal in `config.json` gespeichert (Rechte 0600) und ist nie Teil dieses Repositorys. Das Programm spricht nur mit der CurseForge-API, der CurseForge-Website (Download-Link), dem CurseForge-CDN, GitHub (auch für die eigene Update-Prüfung) und den Download-Servern der Pakete, die du installierst. Keine Telemetrie.

## Kompatibilitätsregeln

Das Client-Interface wird aus deiner Installation gelesen (derzeit 16001). Für jeden Addon-Ordner zählt die erste vorhandene TOC-Datei aus `<Name>_Forever.toc`, `<Name>-Forever.toc`, `<Name>.toc`. Installiert werden nur kompatible Ordner (oder solche, die bereits installiert sind); alle anderen werden übersprungen und aufgelistet.

## Schrift und Grafiken

Die Titelschrift ist [Cinzel](https://github.com/NDISCOVER/Cinzel) unter der SIL Open Font License 1.1 (`assets/fonts/cinzel/OFL.txt`). Sie wird zur Laufzeit nur für dieses Programm registriert; ohne sie wird eine Ersatz-Serifenschrift verwendet. Alle Ornamente sind eigene Zeichnungen; es werden keine Logos, Grafiken oder Schriften von Blizzard verwendet.

## Haftungsausschluss

Inoffizielles Community-Werkzeug. Nicht verbunden mit oder unterstützt von Blizzard Entertainment oder CurseForge/Overwolf. Alle Marken gehören ihren jeweiligen Inhabern. Nutzung auf eigene Gefahr; es werden Backups angelegt, eigene Sicherungen schaden trotzdem nicht.

## Lizenz

[MIT](LICENSE), Copyright (c) 2026 m3rtl.
