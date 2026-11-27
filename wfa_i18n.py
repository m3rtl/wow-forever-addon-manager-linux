"""Uebersetzung der Oberflaeche.

Die Texte im Code sind deutsch und dienen als Schluessel (msgid). Kataloge fuer andere Sprachen liegen als
assets/locale/<sprache>.po und werden zur Laufzeit gelesen, ein .mo-Build entfaellt damit.

Regeln fuer den Code:
- _("Text {name}").format(name=...) statt f-Strings, damit der Schluessel fest ist.
- ngettext("1 Addon", "{n} Addons", n).format(n=n) fuer Mehrzahl.
- Kein _() auf Modulebene (laeuft vor setup()); dort N_("...") markieren und erst bei der Anzeige _() anwenden.
- Nur Anzeigetexte uebersetzen, nie Werte, die verglichen, gespeichert oder als Schluessel benutzt werden.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

LANGUAGES = ("de", "en")
SOURCE = "de"

_lang = SOURCE
_catalog: dict[str, object] = {}


def locale_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent)
    return base / "assets" / "locale"


def detect(env=None) -> str:
    """Sprache aus der Umgebung: deutsche Locale -> de, sonst en."""
    env = os.environ if env is None else env
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = (env.get(var) or "").split(":")[0].strip()
        if val and val not in ("C", "POSIX") and not val.startswith("C."):
            return "de" if val.lower().startswith("de") else "en"
    return "en"


def _unquote(s: str) -> str:
    return ast.literal_eval(s) if s.startswith('"') else ""


def parse_po(text: str) -> dict[str, object]:
    """Liest einen .po-Katalog. Einfache Eintraege -> str, Mehrzahl -> tuple der Formen.
    Leere und als fuzzy markierte Uebersetzungen werden ausgelassen."""
    out: dict[str, object] = {}
    entry: dict[str, str] = {}
    fuzzy = False
    key = None

    def flush():
        nonlocal entry, fuzzy, key
        mid = entry.get("msgid")
        if mid and not fuzzy:
            if "msgid_plural" in entry:
                forms = tuple(entry.get(f"msgstr[{i}]", "") for i in range(2))
                if all(forms):
                    out[mid] = forms
            elif entry.get("msgstr"):
                out[mid] = entry["msgstr"]
        entry, fuzzy, key = {}, False, None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("#,") and "fuzzy" in line:
            if "msgid" in entry:
                flush()
            fuzzy = True
        elif line.startswith("#"):
            continue
        elif line.startswith('"'):
            if key:
                entry[key] += _unquote(line)
        else:
            k, _sep, rest = line.partition(" ")
            if k == "msgid" and "msgid" in entry:
                keep = fuzzy
                flush()
                fuzzy = keep
            key = k
            entry[k] = _unquote(rest.strip())
    flush()
    return out


def setup(lang: str | None = "auto") -> str:
    """Stellt die Sprache ein ("auto", "de", "en") und laedt den Katalog. Gibt die gewaehlte Sprache zurueck."""
    global _lang, _catalog
    lang = (lang or "auto").lower()
    if lang not in LANGUAGES:
        lang = detect()
    _lang, _catalog = lang, {}
    if lang != SOURCE:
        try:
            _catalog = parse_po((locale_dir() / f"{lang}.po").read_text(encoding="utf-8"))
        except (OSError, ValueError, SyntaxError):
            _catalog = {}
    return _lang


def current() -> str:
    return _lang


def _(s: str) -> str:
    t = _catalog.get(s)
    return t if isinstance(t, str) else s


def ngettext(singular: str, plural: str, n: int) -> str:
    t = _catalog.get(singular)
    if isinstance(t, tuple):
        return t[0] if n == 1 else t[1]
    return singular if n == 1 else plural


def N_(s: str) -> str:
    return s


setup(os.environ.get("WFA_LANG", "auto"))
