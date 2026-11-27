"""Hilfen fuer festgehaltene/ausgelassene Versionen."""
from __future__ import annotations

import time

from wfa_toc import display_version

def _pin_record(mode, rem):
    return dict(mode=mode, since=time.strftime("%Y-%m-%dT%H:%M:%S"),
                ref=dict(ident=rem.ident, file_date=rem.file_date, display=rem.display, version=rem.version))


def pin_text(pin):
    if not pin:
        return ""
    ref = pin.get("ref") or {}
    ver = display_version(ref.get("version")) or ref.get("display") or "?"
    since = (pin.get("since") or "?")[:10]
    if pin["mode"] == "hold":
        return f"Auf Version {ver} festgehalten (seit {since}); Updates werden nicht angeboten."
    return f"Ausgelassen bis eine Version neuer als {ver} erscheint (seit {since})."


def _remote_newer(rem, ref):
    """Ist `rem` neuer als die Referenz eines Pins? Vergleich ueber Datum bzw. Datei-ID, nicht ueber Versionstexte."""
    if not isinstance(ref, dict) or rem.ident == ref.get("ident"):
        return not isinstance(ref, dict)
    if rem.file_date and ref.get("file_date"):
        return rem.file_date > ref["file_date"]
    if isinstance(rem.ident, int) and isinstance(ref.get("ident"), int):
        return rem.ident > ref["ident"]
    return not isinstance(rem.ident, int) and not isinstance(ref.get("ident"), int)   # z. B. GitHub-Tags: ungleich = neuer
