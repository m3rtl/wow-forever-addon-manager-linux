#!/usr/bin/env python3
"""Einstiegspunkt: GUI (falls verfuegbar), sonst Kommandozeile."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CLI_FLAGS = {"--cli", "--check", "--addons-dir", "--version", "-h", "--help"}


def _wants_cli(argv):
    return any(a.split("=", 1)[0] in CLI_FLAGS for a in argv)


def _gui(argv):
    """-> Exit-Code oder None, wenn keine GUI verfuegbar ist."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        if not Gtk.init_check()[0]:
            return None
        import wfa_gui
    except ModuleNotFoundError as e:
        if e.name not in ("gi", "wfa_gui"):
            print(f"GUI nicht startbar ({e}); verwende Kommandozeile.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"GUI nicht startbar ({e}); verwende Kommandozeile.", file=sys.stderr)
        return None
    return wfa_gui.main(argv)


def _setup_language():
    """Sprache vor dem ersten Text festlegen: WFA_LANG, sonst Einstellung "language", sonst Locale."""
    import json
    import wfa_i18n
    lang = os.environ.get("WFA_LANG")
    if not lang:
        try:
            import wfa_paths
            with open(wfa_paths.Paths().config_file, encoding="utf-8") as f:
                lang = json.load(f).get("language")
        except (OSError, ValueError, AttributeError):
            lang = None
    wfa_i18n.setup(lang if isinstance(lang, str) else "auto")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    _setup_language()
    if "--install-desktop-entry" in argv:
        import wfa_core
        try:
            print(f"Startmenü-Eintrag angelegt: {wfa_core.install_desktop_entry()}")
        except OSError as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    if not _wants_cli(argv):
        code = _gui(argv)
        if code is not None:
            return code
    import wfa_cli
    return wfa_cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
