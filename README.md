# WoW: Forever Addon-Manager (Linux)

Inoffizieller Addon-Manager für **WoW: Forever** (Interface 16xxx) unter Linux (Steam/Proton, Lutris, Wine, Bottles, Heroic). Er erkennt die Addons im `AddOns`-Ordner, zeigt Updates an und installiert sie mit Backup, auf Wunsch still im Hintergrund aus dem Tray.

![Hauptfenster](docs/screenshots/main.png)

## Funktionen

**Updates**
- Erkennung installierter Addons per CurseForge-Fingerprint, GitHub-Releases als Ausweichquelle; nur Forever-Builds (`.toc` mit Interface 16xxx).
- Veraltete Addons sind angehakt, „N aktualisieren“ spielt sie ein; Changelog als Tooltip.
- Updates pro Addon ignorieren, eine bestimmte Version installieren und festhalten oder auslassen.
- Kanal pro Addon (Release, Beta, Alpha), erkennbar an β/α in der Liste.
- Fehlende Pflicht-Abhängigkeiten werden angezeigt und mitinstalliert (Auto-Update: nur CurseForge).
- Nicht erkannte Ordner per Rechtsklick „Zuordnen …“ (Vorschläge aus TOC und Suche).

**Downloads**
- Wege: CurseForge-API, Website-Link, CDN (auch für gesperrte Addons wie DBM), mit Fortschritt und Wiederholung.
- Zuletzt der Browser: Der Manager wartet im Download-Ordner auf die Zip-Datei.

**Neue Addons**
- Alle Forever-Addons durchblättern, sortieren, filtern.
- Außerdem: CurseForge-Projekt-ID, `gh:owner/repo`, GitHub-URL, Zip-Link oder lokale Zip-Datei („Direkt“).
- Addon-Liste exportieren/importieren (☰): JSON oder Kurztext `WFA1 cf:18808 cf:4646@beta gh:owner/repo`.

![Neues Addon installieren](docs/screenshots/new-addon.png)

**Sicherheit**
- Ersetzte oder deinstallierte Ordner landen im Backup (letzte 5), wiederherstellbar über ☰ → Backups.
- SavedVariables-Schnappschuss vor jedem Update (letzte 5, abschaltbar), Wiederherstellen nur bei beendetem WoW.
- ☰ → „Verlauf …“: „Zurücksetzen“ und „Einstellungen zurücksetzen“ je Addon.
- Kompatibilitätsprüfung vor jeder Installation, Hinweis wenn WoW zu laufen scheint.
- Beim Ersetzen von Addon-Ordnern bleibt `WTF` unverändert; geschrieben wird dort nur beim ausdrücklichen Wiederherstellen.

## Download

1. [Neuestes Release](https://github.com/m3rtl/wow-forever-addon-manager-linux/releases/latest): `wow-forever-addon-manager-x86_64-linux` laden (Prüfsumme: `SHA256SUMS`).
2. `chmod +x wow-forever-addon-manager-x86_64-linux`
3. `./wow-forever-addon-manager-x86_64-linux` (gebaut auf Ubuntu 22.04, glibc 2.35+; sonst Quellcode nutzen)

## Bedienung

| Was | Wo |
| --- | --- |
| Auf Updates prüfen | Refresh-Symbol oben links, <kbd>F5</kbd>, <kbd>Strg</kbd>+<kbd>R</kbd> |
| Markierte aktualisieren | „N aktualisieren“ unten links |
| Changelog, Ignorieren, Seite/Ordner öffnen, Browser-Download, Deinstallieren | Rechtsklick auf eine Zeile (oder Menütaste) |
| Andere Version, Festhalten/Auslassen aufheben, Kanal, Zuordnen, Verlauf | Rechtsklick auf eine Zeile |
| Protokoll, Backups, Verlauf, Addon-Liste exportieren/importieren, Einstellungen, Programm-Updates, Beenden | ☰-Menü oben rechts |

Kommandozeile: `./start.sh --cli` (Menütasten u. a. `v` Version/Kanal, `h` Verlauf, `w` Backups inkl. SavedVariables), `--export PFAD|-` und `--import PFAD|TEXT`.

## Tray und Autostart

Unter ☰ → Einstellungen, „Hintergrund“: Start im Tray beim Systemstart, Prüfintervall, Auto-Update (nur wenn WoW nicht läuft; Standard aus). Unter GNOME braucht der Tray die Erweiterung „AppIndicator and KStatusNotifierItem Support“.

## Programm-Updates

Prüfung über GitHub-Releases (höchstens alle 12 h). Die Release-Datei ersetzt sich nach SHA256-Prüfung selbst (alte als `.old`), die Quellcode-Version zeigt nur einen Hinweis. Abschaltbar unter ☰ → Einstellungen.

## Aus dem Quellcode starten

Python 3.10+, für die GUI `python3-gi` und `gir1.2-gtk-3.0`.

```sh
./start.sh                 # GUI (ohne Display automatisch Kommandozeile)
./start.sh --tray          # minimiert im Tray
./start.sh --check         # nur die Tabelle ausgeben
./build.sh                 # Einzeldatei bauen (dist/)
```

## CurseForge-API-Key

Kostenlos unter <https://console.curseforge.com>; eintragen unter ☰ → Einstellungen oder per `CF_API_KEY` (hat Vorrang). Ohne Key gehen nur GitHub und manuell zugeordnete Pakete.

## Wo Daten gespeichert werden

- Aus dem Quellcode gestartet: neben dem Programm (`config.json`, `backups/`, `sv_backups/`, `history.jsonl`, `cache/`).
- Release-Datei: in den XDG-Ordnern (`~/.config`, `~/.local/share`, `~/.cache`, jeweils unter `wow-forever-addon-manager`).
- `WOW_FA_HOME=<Ordner>` überschreibt beides.

## Datenschutz

Dein API-Key liegt nur lokal in `config.json` (Rechte 0600). Das Programm spricht nur mit CurseForge, GitHub und den Servern der Pakete, die du installierst; keine Telemetrie. Aus Browser-Profilen liest es nur den eingestellten Download-Ordner. Direkt-Download und Selbst-Update lassen sich unter ☰ → Einstellungen abschalten.

## Kompatibilitätsregeln

Das Client-Interface kommt aus `.build.info` (1.60.1 → 16001), sonst gilt die häufigste Nummer der Addons. Je Ordner zählt die erste TOC aus `<Name>_Forever.toc`, `<Name>-Forever.toc`, `<Name>.toc`. Nur kompatible oder bereits installierte Ordner werden installiert.

## Schrift und Grafiken

Titelschrift: [Cinzel](https://github.com/NDISCOVER/Cinzel), SIL Open Font License 1.1 (`assets/fonts/cinzel/OFL.txt`). Die Ornamente sind eigene Zeichnungen; es werden keine Logos, Grafiken oder Schriften von Blizzard verwendet. Das klassische Theme lässt sich unter ☰ → Einstellungen abschalten.

## Haftungsausschluss

Inoffizielles Community-Werkzeug. Nicht verbunden mit oder unterstützt von Blizzard Entertainment oder CurseForge/Overwolf. Alle Marken gehören ihren jeweiligen Inhabern. Nutzung auf eigene Gefahr; es werden Backups angelegt, eigene Sicherungen schaden trotzdem nicht.

## Lizenz

[MIT](LICENSE), Copyright (c) 2026 m3rtl.
