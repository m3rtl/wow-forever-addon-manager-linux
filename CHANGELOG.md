# Changelog

Alle nennenswerten Änderungen am WoW: Forever Addon-Manager. Die Abschnitte dienen zugleich als Text der GitHub-Releases.

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
