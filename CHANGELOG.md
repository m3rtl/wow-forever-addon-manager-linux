# Changelog

Alle nennenswerten Änderungen am WoW: Forever Addon-Manager. Die Abschnitte dienen zugleich als Text der GitHub-Releases.

## 0.5.3 – 2026-11-28

### Behoben

- Installieren und Aktualisieren schlug seit 0.5.0 mit „Unerwarteter Fehler: App.apply_plans() missing 2 required positional arguments“ ab. Betroffen waren Updates und Neuinstallationen aus dem Programmfenster sowie die automatischen Updates im Hintergrund. Die Updates vor dem Spielstart über die Kommandozeile (`--update`) liefen weiter.

## 0.5.2 – 2026-11-27

### Neu

- **Addons vorübergehend deaktivieren**: Rechtsklick auf ein Addon → „Deaktivieren (alle Charaktere)“, zurück mit „Wieder aktivieren“. Das Addon wird in der AddOns.txt aller vorhandenen Charaktere ausgeschaltet; die bisherigen Dateien werden vorher gesichert. Die Liste zeigt „⏸ deaktiviert“, die Summenzeile zählt mit. Bei laufendem WoW wird nichts geschrieben, weil WoW die Änderung beim Beenden überschreiben würde.
- **Neuigkeiten**: ☰ → „Neuigkeiten …“ zeigt den Changelog des Managers.

### Behoben

- Nach dem Einschalten von „Erweiterte Funktionen anzeigen“ klappte ☰ → „Erweitert“ ein leeres Untermenü aus.

## 0.5.1 – 2026-11-27

### Geändert

- **Einstellungen in Kategorien**: Der Dialog hat links eine Seitenleiste mit den Reitern „Allgemein“ (Sprache, Darstellung, Erweiterte Funktionen, Programm-Updates), „Installationen“ (WoW-Installationen, Download-Ordner), „Addons“ (CurseForge-API-Key, Downloads, Hinweise), „Sicherungen“ (SavedVariables, automatische Gesamtstände) und „Hintergrund“ (Tray, Update-Prüfung, Updates vor dem Spielstart). Kurze Erklärungen stehen direkt unter den Optionen.
- Der CurseForge-Key lässt sich über das Augen-Symbol im Feld sichtbar machen; „Gespeicherten Key löschen“ sperrt das Eingabefeld.
- „Programm-Updates automatisch installieren“ ist nur wählbar, wenn die Suche nach Programm-Updates eingeschaltet ist.
- Die Kopfzeile zeigt keinen Programmtitel und keinen Pfad mehr. Der Pfad der aktiven Installation steht im Tooltip des Installations-Umschalters.

## 0.5.0 – 2026-11-27

### Neu

- **Updates vor dem Spielstart**: `--update` aktualisiert veraltete Addons ohne Rückfragen (nicht bei laufendem WoW; Exit-Code 0 ok, 1 Fehler, 2 übersprungen), `--quiet` zeigt nur Zusammenfassung und Fehler, `--run CMD` startet danach das Spiel und impliziert `--update`. Der Lauf ist zeitlich begrenzt, damit er den Spielstart nicht aufhält. Der Dialog unter ☰ → Einstellungen → „Hintergrund“ → „Updates vor dem Spielstart …“ zeigt fertige Zeilen zum Kopieren und speichert ein Startskript („Startskript speichern …“):
  - **Steam**, Startoptionen: `<Programm> --update --quiet --run %command%`
  - **Lutris**: „Pre-launch script“ auf das Startskript setzen und „Wait for pre-launch script completion“ einschalten. **Heroic**: Skript vor dem Start im Reiter Erweitert.
  - **Flatpak**: `flatpak run io.github.m3rtl.WowForeverAddonManager --update --quiet ; %command%`, ohne `--run`.
- **Automatische Gesamtstände**: vor einem Update ab 5 Addons und bei neuer WoW-Version (☰ → Einstellungen → „Automatische Gesamtstände“, Standard an). Es bleiben die letzten 2 automatischen Stände, eigene werden nie verdrängt. Nach einem Client-Update weist ein Hinweis darauf hin.
- **Fehleranalyse** (☰ → Erweitert → „Fehleranalyse …“, `--errors [ADDON]`): wertet !BugGrabber aus, gruppiert nach Addon und zeigt Fehler seit dem letzten Update. „Zurücksetzen …“ stellt das Backup des Updates her.
- **Addon-Sets** (Dialog „Addons je Charakter und Sets …“, `--sets`, `--set NAME`, `--char NAME-REALM`): Zusammenstellungen speichern und auf einen oder alle Charaktere anwenden; Abhängigkeiten werden mit eingeschaltet.
- **Hinweise**: „⚠ verwaist“ (CurseForge-Projekt inaktiv, aufgegeben oder gelöscht, GitHub-Repo archiviert), „◷ lange kein Update“ (seit 180 Tagen keine neue Forever-Datei und TOC älter als der Client; Einstellung „Hinweis „lange kein Update“ nach“, 0 = aus) und Konflikte (geteilte oder doppelte Ordner, „⚠“ am Namen) mit Tooltip und Zählung in der Summenzeile. Doppelte Ordner lassen sich unter „Aufräumen …“ entfernen.
- **Mehrere Installationen**: Umschalter in der Kopfzeile (ab zwei Installationen), Verwaltung unter ☰ → Einstellungen → „Installationen“ („Hinzufügen …“, „Umbenennen …“, „Entfernen“, „Aktivieren“). Kommandozeile: `--installations`, `--use NAME|PFAD`, Taste `i` im Menü.

### Geändert

- „Gesamtstände …“ steht jetzt im ☰-Hauptmenü statt unter „Erweitert“, weil automatische Stände für alle entstehen. Der Dialog hat die Spalte „Art“ (manuell/automatisch).
- Der Menüeintrag „Addons je Charakter“ heißt jetzt „Addons je Charakter und Sets …“.
- „AddOns-Ordner“ in den Einstellungen ist jetzt der Abschnitt „Installationen“ (statt „Ändern …“ jetzt „Hinzufügen …“).
- Backups, SavedVariables-Sätze, Gesamtstände und Papierkorb merken sich die Installation; alte Sätze gehören zur bisherigen Installation. Die Listen zeigen nur Sätze der aktiven Installation.
- CurseForge-Projektstatus und GitHub-Archivstatus werden höchstens einmal am Tag abgefragt.

### Behoben

- Die Erkennung „WoW läuft“ schließt jetzt den eigenen Prozess und dessen Eltern aus. Bei Startoptionen, deren Kommandozeile `Wow.exe` enthält (`--update --run …/Wow.exe`), galt WoW sonst fälschlich als gestartet.

## 0.4.0 – 2026-11-27

### Neu

- **Englische Oberfläche**: Die Sprache richtet sich nach der Systemsprache (Deutsch bei deutscher Locale, sonst Englisch). Unter ☰ → Einstellungen → „Sprache“ lässt sie sich fest einstellen; das wirkt nach einem Neustart. `WFA_LANG=de|en` überschreibt beides.
- **Erweiterte Funktionen** (☰ → Einstellungen → „Erweiterte Funktionen anzeigen“, Standard aus). Danach gibt es unter ☰ das Untermenü „Erweitert“:
  - **Addons je Charakter**: Addons pro Charakter oder für alle Charaktere an- und ausschalten, ohne sie zu deinstallieren (`AddOns.txt` in `WTF`). Vor dem Schreiben wird die alte Datei gesichert.
  - **Aufräumen**: zeigt die Speicherbelegung und findet Einstellungen deinstallierter Addons, verschachtelte Ordner (`AddOns/Foo/Foo/`) und Ordner ohne TOC. Aufgeräumtes landet im Papierkorb (letzte 5 Sätze) und lässt sich zurücklegen.
  - **Gesamtstände**: sichert alle Addons samt `WTF/Account` als einen Satz (letzte 3) und stellt ihn mit einem Klick wieder her, z. B. vor einem großen Client-Patch. Vor dem Wiederherstellen wird der aktuelle Stand automatisch gesichert.
  - Alles, was in `AddOns` oder `WTF` schreibt, geht nur bei beendetem WoW.
- Kommandozeile: `--snapshot [BEZEICHNUNG]`, `--snapshots`, `--restore-snapshot ID`, `--cleanup` (nur auflisten) und `--cleanup --apply`.
- **AUR-Paket** `wow-forever-addon-manager`: nutzt Python und GTK des Systems, damit entfällt die glibc-2.35-Vorgabe der Release-Datei. Startmenü-Eintrag und Icon bringt das Paket mit; Programm-Updates kommen über die Paketverwaltung.
- **Flatpak** (`io.github.m3rtl.WowForeverAddonManager`, GNOME-Runtime 51), als Bundle am Release. Zugriff nur auf die üblichen Wine/Proton-Orte (Steam, Lutris, Bottles, Heroic, Wine, umu, Faugus, `~/Games`); andere Orte über das Datei-Portal (Ordner „World of Warcraft“ wählen) oder `flatpak override`. Nicht freigegebene Steam-Bibliotheken nennt der Auswahldialog samt Befehl.
- Release-Datei, AUR-Paket und Flatpak nutzen dieselben Einstellungen, Backups und denselben Verlauf; ein Wechsel übernimmt alles.
- Als Ordner lässt sich jetzt auch „World of Warcraft“ wählen; der Manager nimmt dann `_forever_/Interface/AddOns`.

### Geändert

- Unter der Haube: `wfa_core.py` ist in thematische Module aufgeteilt (`wfa_base`, `wfa_paths`, `wfa_http`, `wfa_toc`, `wfa_sources`, `wfa_files`, `wfa_manager` und weitere); `wfa_core` bleibt als Sammelmodul erhalten. Neu sind eine Testsuite (`python3 -m unittest discover -s tests`) und ein CI-Workflow, der sie bei jedem Push ausführt.
- Datei- und Ordnerwahl laufen über `Gtk.FileChooserNative` (im Flatpak das Datei-Portal).
- Flatpak: Autostart über das Hintergrund-Portal; Tray meldet sich mit dem eindeutigen D-Bus-Namen an. Ist nicht erkennbar, ob WoW läuft, meldet der Tray Updates nur, statt sie still zu installieren, und vor dem Wiederherstellen von SavedVariables kommt eine Rückfrage.

### Behoben

- `--export` und `--import` starteten bei vorhandenem Display die GUI statt der Kommandozeile.

## 0.3.0 – 2026-11-26

### Neu

- **Andere Version installieren**: Rechtsklick → „Andere Version …“ lädt die verfügbaren Versionen zur Auswahl. Danach lässt sich die Version festhalten, bis du es aufhebst, oder es werden nur die jetzt neueren Versionen ausgelassen. „Festhalten aufheben“ bzw. „Auslassen aufheben“ macht beides rückgängig.
- **Kanal pro Addon**: Rechtsklick → „Kanal“ (Standard, Nur Release, Beta, Alpha). Beta- und Alpha-Versionen sind in der Liste mit β bzw. α gekennzeichnet.
- **Fehlende Pflicht-Abhängigkeiten**: CurseForge-Relationen „erforderlich“ und TOC-Dependencies werden im Bestätigungsdialog angezeigt und auf Wunsch mitinstalliert (abwählbar). Das Auto-Update installiert nur CurseForge-Abhängigkeiten mit; der Tooltip nennt fehlende Addons („Fehlt: …“).
- **Nicht erkannte Ordner zuordnen**: Rechtsklick → „Zuordnen …“ schlägt Treffer aus der TOC (Projekt-ID, CurseForge- oder GitHub-Adresse) und der CurseForge-Suche vor. Eindeutige Fälle werden automatisch zugeordnet.
- **Addon-Liste exportieren und importieren** (☰-Menü): als JSON-Datei oder Kurztext wie `WFA1 cf:18808 cf:4646@beta gh:owner/repo`, z. B. für Discord. In der Kommandozeile mit `--export PFAD|-` und `--import PFAD|TEXT`.
- **SavedVariables-Schnappschuss vor jedem Update**: Gesichert werden `WTF/Account/*/SavedVariables` und die Charakterebene, die letzten 5 Sätze bleiben. Wiederherstellen unter ☰ → Backups, ganz oder je Addon, nur wenn WoW nicht läuft.
- **Update-Verlauf**: ☰ → „Verlauf …“ (auch per Rechtsklick, dann vorgefiltert). „Zurücksetzen“ stellt die Ordner eines Addons aus dem Backup-Satz her, „Einstellungen zurücksetzen“ die SavedVariables.
- **Kommandozeile**: neue Menütasten `v` (Version/Kanal) und `h` (Verlauf); `w` zeigt auch SavedVariables-Sätze.

### Geändert

- Der Kanal gilt jetzt je Addon; „Standard“ folgt der Einstellung „Beta-Versionen anzeigen“.
- Neuer Schalter unter ☰ → Einstellungen: „Vor Updates die Addon-Einstellungen (SavedVariables) sichern“ (Standard: an).
- Beim Ersetzen von Addon-Ordnern bleibt `WTF` weiterhin unverändert; geschrieben wird dort nur beim ausdrücklichen Wiederherstellen.

## 0.2.2 – 2026-11-26

### Behoben

- **Spalte „Forever“ zeigte fast überall „veraltet“**: Die Client-Version wurde bisher aus den Addons geschätzt, und zwar als höchste Interface-Nummer, die irgendein Addon angibt. Nannte ein einzelnes Addon schon eine künftige Nummer (z. B. ForeverThreat mit 16002), galten alle anderen als veraltet. Jetzt wird die tatsächliche Spielversion aus `.build.info` der WoW-Installation gelesen (z. B. 1.60.1 → Interface 16001), bei jeder Prüfung neu, sodass Client-Patches automatisch erkannt werden. Fehlt die Datei, zählt die Nummer, die die meisten Addons angeben.
- Die Infozeile zeigt jetzt die erkannte Client-Version, z. B. „Client 1.60.1 (Interface 16001)“, bzw. den Hinweis „aus den Addons geschätzt“.

## 0.2.1 – 2026-11-26

### Neu

- **Fortschrittsbalken im Hauptfenster**: Während Downloads zeigt eine Leiste unten im Fenster Addon, Position in der Warteschlange (z. B. 2/3), Download-Weg, geladene Menge, Gesamtgröße und Geschwindigkeit. Kommen mehrere Sekunden keine Daten an, steht dort „keine Daten seit N s“. Mit **Abbrechen** lassen sich laufende Downloads stoppen.
- **Automatische Wiederholung**: Vorübergehende Fehler (Netzwerk, hängende Verbindung, HTTP 5xx/429, beschädigte Zip-Datei) werden je Download-Weg bis zu dreimal mit kurzer Pause wiederholt.
- **Automatischer Wegwechsel**: Scheitert ein Weg endgültig (z. B. HTTP 403/404, Antwort ist keine Zip-Datei), geht es sofort mit dem nächsten weiter (CurseForge-API → CurseForge-Website → CDNs). Klappt keiner, nennt die Meldung für jeden Weg den Grund und bietet wie bisher den Browser-Download an.
- **Klare Abschlussmeldung**: Nach jeder Installation stehen Ergebnis und Fehler im Protokoll und in der Statuszeile, z. B. „Fertig: 2 Addons aktualisiert (…)“.
- Das Programm-Update zeigt den Download-Fortschritt jetzt tatsächlich an.

### Behoben

- Hängende oder abgebrochene Verbindungen während eines Downloads führten zu einem „Unerwarteten Fehler“, und die übrigen Download-Wege wurden nicht mehr versucht. Hängende Verbindungen werden jetzt nach 30 s ohne Daten erkannt.
- Unvollständige Downloads (weniger Daten als angekündigt) und Zip-Dateien mit Prüfsummenfehlern werden erkannt und neu geladen.
- Nach einem Hintergrund-Update blieb „Lade … .zip …“ in der Statuszeile stehen, obwohl die Installation längst erfolgreich war.

## 0.2.0 – 2026-11-25

### Neu

- **Direkt-Download ohne Browser**: Addons, die nicht über die CurseForge-API freigegeben sind (z. B. DBM, Auctionator), werden automatisch über den Download-Link der CurseForge-Website bzw. das CDN geladen. Der Browser mit Ordner-Überwachung ist nur noch der letzte Ausweg. Abschaltbar unter ☰ → Einstellungen.
- **Tray und Autostart**: Optional mit dem System starten und minimiert in der Menüleiste laufen. Prüft beim Start und stündlich (einstellbar), meldet sich nur bei neuen Updates.
- **Auto-Update (optional)**: Der Tray installiert Updates selbst, aber nur, solange WoW nicht läuft.
- **Selbst-Update**: Neue Versionen des Managers werden gemeldet und auf Wunsch installiert, geprüft per SHA256 gegen `SHA256SUMS`.
- **Überarbeitete Oberfläche**: Refresh-Symbol in der Titelleiste (F5), veraltete Addons sind nach jeder Prüfung angehakt, Statusanzeige mit Symbolen, Protokoll im ☰-Menü.
- **Rechtsklick-Menü**: Aktualisieren, Changelog, Updates ignorieren, Seite oder Ordner öffnen, im Browser laden, deinstallieren.
- **Changelog** der neuen Version als Tooltip und als Dialog.
- **Neues Addon**: Liste aller Forever-Addons mit Seiten, Sortierung und Tooltips mit Logo, Beschreibung und Screenshots.

### Behoben

- „Alle Updates markieren“ hakte alle Addons an statt nur die mit Update.

## 0.1.0 – 2026-11-23

Erste Version: GTK-3-Oberfläche und Kommandozeile zum Prüfen, Aktualisieren und Installieren von WoW: Forever-Addons. Erkennung installierter Addons über CurseForge-Fingerprints, GitHub-Releases und Browser-Download als Ausweichwege, Forever-Kompatibilitätsprüfung, Backups mit Wiederherstellung, Deinstallieren, klassisches Nachtblau/Gold-Theme und Erkennung der Installation beim ersten Start.
