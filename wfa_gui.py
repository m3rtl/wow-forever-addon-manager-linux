"""GTK-3-Oberflaeche fuer den WoW: Forever Addon-Manager."""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

import wfa_core as core  # noqa: E402
import wfa_health  # noqa: E402
from wfa_core import ApiError, Manager  # noqa: E402
from wfa_i18n import N_, _, ngettext  # noqa: E402

TITLE = "WoW: Forever Addon-Manager"
APP_ID = core.APP_ID
REPO_URL = "https://github.com/m3rtl/wow-forever-addon-manager-linux"
RED, ORANGE, GREY, GREEN = "#e74c3c", "#e67e22", "#8a8a8a", "#2e9e5b"
STATUS_COLOR = {}
SKIP, ABORT = 1, 2  # Antworten des Warte-Dialogs
BANNER_TITLE = "WoW: Forever"
BANNER_SUB = N_("Addon-Manager für Linux")
FONT_STACK = 'Cinzel, "Cormorant Garamond", "Liberation Serif", serif'
THEME = {"on": False, "provider": None, "widgets": []}


def set_status_colors(dark):
    global RED, ORANGE, GREY, GREEN
    RED, ORANGE, GREY, GREEN = ("#ff8a78", "#f2a65a", "#a9abb8", "#5fd699") if dark else \
        ("#e74c3c", "#e67e22", "#8a8a8a", "#2e9e5b")
    STATUS_COLOR.clear()
    STATUS_COLOR.update({core.UPDATE: ORANGE, core.ERROR: RED, core.NO_FOREVER: RED, core.NOKEY: GREY,
                         core.UNCHECKED: GREY, core.UNASSIGNED: GREY, core.UNKNOWN: GREY})


set_status_colors(False)

# ListStore-Spalten
(C_CHECK, C_NAME, C_LOCAL, C_REMOTE, C_SOURCE, C_FOREVER, C_STATUS, C_KEY, C_WEIGHT, C_SCOLOR, C_FCOLOR, C_CAN,
 C_SSET, C_FSET, C_STYLE, C_DIM, C_DIMCOLOR) = range(17)
COL_TYPES = (bool, str, str, str, str, str, str, str, int, str, str, bool, bool, bool, int, bool, str)
CHANNEL_MARK = {"beta": "β", "alpha": "α"}
CHANNEL_NAMES = ((N_("Standard (wie Einstellung)"), None), (N_("Nur Release"), "release"), (N_("Beta"), "beta"),
                 (N_("Alpha"), "alpha"))
FOREVER_SHOW = {"ok": "✓", "veraltet": N_("⚠ veraltet"), "nein": "✗"}


# ---------------------------------------------------------------- Theme
CSS = """
@define-color wfa_bg #141a2b;
@define-color wfa_panel #1b2338;
@define-color wfa_input #0f1424;
@define-color wfa_text #e8e2d0;
@define-color wfa_muted #a9a58f;
@define-color wfa_bronze #8c6a2f;
@define-color wfa_gold #c9a227;
@define-color wfa_gold_hi #e6c66a;
window, dialog, .background { background-color: @wfa_bg; color: @wfa_text; }
headerbar, .titlebar { background-image: linear-gradient(#27315a, #1a2240); border: none;
  border-bottom: 1px solid @wfa_bronze; box-shadow: none; color: @wfa_gold_hi; }
headerbar .title { font-family: FONTS; font-weight: bold; color: @wfa_gold_hi; }
headerbar .subtitle { color: @wfa_muted; }
.wfa-banner { background-image: linear-gradient(#222c52, #161d36); border-bottom: 2px solid @wfa_gold; }
.wfa-title { font-family: FONTS; font-weight: 700; font-size: 22px; color: @wfa_gold_hi; text-shadow: 0 1px 2px #000; }
.wfa-sub { font-family: FONTS; font-size: 11px; letter-spacing: 3px; color: @wfa_muted; }
.wfa-summary { font-weight: bold; color: @wfa_gold_hi; }
.wfa-dim { color: @wfa_muted; font-size: 90%; }
.wfa-table { border: 1px solid @wfa_bronze; border-radius: 0; }
.wfa-empty { color: @wfa_muted; }
infobar { background-image: linear-gradient(#3a3a1c, #2a2a14); border: none; border-bottom: 1px solid @wfa_gold; }
infobar label { color: @wfa_text; }
button.wfa-flat { background-image: none; background-color: transparent; border-color: transparent; color: @wfa_muted; }
button.wfa-flat:hover { background-color: rgba(230, 198, 106, 0.15); border-color: @wfa_bronze; color: @wfa_gold_hi; }
.wfa-line { min-height: 1px; background-image: linear-gradient(to right, rgba(201,162,39,0), #c9a227); }
.wfa-line-r { min-height: 1px; background-image: linear-gradient(to left, rgba(201,162,39,0), #c9a227); }
label { text-shadow: none; }
button { background-image: linear-gradient(#2c3760, #1b2340); border: 1px solid @wfa_bronze; border-radius: 4px;
  color: @wfa_text; box-shadow: none; text-shadow: none; }
button:hover { background-image: linear-gradient(#3a4777, #26325c); border-color: @wfa_gold_hi; color: #ffffff; }
button:active, button:checked { background-image: linear-gradient(#1b2340, #2c3760); border-color: @wfa_gold_hi; color: @wfa_gold_hi; }
button:disabled { opacity: 0.5; }
button.suggested-action { background-image: linear-gradient(#efd78b, #b98a1d); border-color: #f4e2a5; color: #2a1d02; font-weight: bold; }
button.suggested-action:hover { background-image: linear-gradient(#f8e4a0, #cfa52a); color: #1c1300; }
button.destructive-action { background-image: linear-gradient(#8f3030, #5c1a1a); border-color: #c97a5a; color: #ffffff; }
button.link, button.link:visited, button.link label, *:link, *:visited { background-image: none; border-color: transparent; color: @wfa_gold_hi; }
button.titlebutton { background-image: none; background-color: transparent; border-color: transparent; color: @wfa_gold_hi; }
button.titlebutton:hover { background-color: rgba(230, 198, 106, 0.2); }
entry, spinbutton { background-color: @wfa_input; background-image: none; color: @wfa_text; border: 1px solid @wfa_bronze;
  box-shadow: none; caret-color: @wfa_gold_hi; }
entry:focus { border-color: @wfa_gold_hi; }
textview, textview text, .view, iconview { background-color: @wfa_input; color: @wfa_text; }
selection, textview text selection, entry selection { background-color: #8a6a1c; color: #fff8e0; }
treeview.view { background-color: @wfa_panel; color: @wfa_text; }
treeview.view:hover { background-color: #2b3659; }
treeview.view:selected, treeview.view:selected:focus { background-color: #8a6a1c; color: #fff8e0; }
treeview.view check, treeview.view radio { color: #2a1d02; }
treeview header button { background-image: linear-gradient(#2c3760, #1e2748); color: @wfa_gold_hi; font-weight: bold;
  border: none; border-bottom: 1px solid @wfa_bronze; border-right: 1px solid #3a4468; border-radius: 0; }
scrolledwindow.frame, scrolledwindow { border-color: @wfa_bronze; }
scrollbar slider { background-color: @wfa_bronze; border-radius: 6px; }
scrollbar slider:hover { background-color: @wfa_gold; }
scrollbar trough { background-color: rgba(0, 0, 0, 0.25); }
check, radio { background-image: linear-gradient(#2c3760, #1b2340); border: 1px solid @wfa_bronze; color: #2a1d02; box-shadow: none; }
check:checked, radio:checked { background-image: linear-gradient(#efd78b, #b98a1d); border-color: #f4e2a5; }
menu, .menu, popover, popover.background { background-color: @wfa_panel; border: 1px solid @wfa_bronze; color: @wfa_text; }
menuitem:hover, modelbutton:hover { background-color: #8a6a1c; color: #fff8e0; }
stackswitcher button:checked { background-image: linear-gradient(#efd78b, #b98a1d); color: #2a1d02; }
notebook header { background-color: #1a2240; }
stacksidebar, stacksidebar list { background-color: @wfa_panel; }
stacksidebar scrolledwindow { border: 1px solid @wfa_bronze; }
stacksidebar separator { background-color: transparent; min-height: 0; }
stacksidebar row { padding: 8px 12px; }
stacksidebar row label { color: @wfa_text; }
stacksidebar row, stacksidebar row:focus { background-image: none; background-color: transparent; box-shadow: none; outline-color: @wfa_bronze; }
stacksidebar row:hover { background-color: #2b3659; }
stacksidebar row:selected, stacksidebar row:selected:focus { background-image: none; background-color: #8a6a1c; }
stacksidebar row:selected label { color: #fff8e0; font-weight: bold; }
tooltip, tooltip.background { background-color: @wfa_panel; color: @wfa_text; border: 1px solid @wfa_bronze; }
separator { background-color: @wfa_bronze; }
expander title { color: @wfa_gold_hi; }
progressbar progress { background-image: linear-gradient(#efd78b, #b98a1d); }
progressbar trough { background-color: @wfa_input; border: 1px solid @wfa_bronze; }
progressbar text { color: @wfa_muted; }
""".replace("FONTS", FONT_STACK)


def register_fonts():
    """Cinzel (OFL) zur Laufzeit bei fontconfig anmelden; Fehler bleiben still (Fallback-Schriften)."""
    try:
        fc = ctypes.CDLL("libfontconfig.so.1")
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        for f in sorted(core.asset_path("fonts/cinzel").glob("*.ttf")):
            fc.FcConfigAppFontAddFile(None, str(f).encode())
    except Exception:  # noqa: BLE001
        pass


def apply_theme(on):
    """Eigenes Fantasy-Theme nur fuer die Fenster dieses Programms (Provider auf Screen-Ebene des Prozesses)."""
    scr = Gdk.Screen.get_default()
    on = bool(on) and scr is not None
    if on and THEME["provider"] is None:
        prov = Gtk.CssProvider()
        try:
            prov.load_from_data(CSS.encode())
        except GLib.Error as e:
            print(f"Theme nicht ladbar: {e}", file=sys.stderr)
            on = False
        else:
            Gtk.StyleContext.add_provider_for_screen(scr, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            THEME["provider"] = prov
    elif not on and THEME["provider"] is not None:
        Gtk.StyleContext.remove_provider_for_screen(scr, THEME["provider"])
        THEME["provider"] = None
    THEME["on"] = on
    set_status_colors(on)
    for w in THEME["widgets"]:
        w.set_visible(on)


def _svg(name, w, h, flip=False):
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file_at_size(str(core.asset_path(name)), w, h)
        return Gtk.Image.new_from_pixbuf(pb.flip(True) if flip else pb)
    except Exception:  # noqa: BLE001
        return Gtk.Box()


def divider(register=True):
    """Ornament-Trenner: Goldlinien mit Edelstein in der Mitte."""
    box = Gtk.Box(spacing=0, margin_top=2, margin_bottom=2)
    left = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER)
    right = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER)
    left.get_style_context().add_class("wfa-line")
    right.get_style_context().add_class("wfa-line-r")
    box.pack_start(left, True, True, 0)
    box.pack_start(_svg("ornament-gem.svg", 176, 19), False, False, 0)
    box.pack_start(right, True, True, 0)
    box.show_all()
    box.set_no_show_all(True)
    box.set_visible(THEME["on"])
    if register:
        THEME["widgets"].append(box)
    return box


def make_banner():
    box = Gtk.Box(spacing=8)
    box.get_style_context().add_class("wfa-banner")
    box.pack_start(_svg("ornament-corner.svg", 66, 44), False, False, 0)
    mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, valign=Gtk.Align.CENTER, margin_top=4, margin_bottom=4)
    t = Gtk.Label(label=BANNER_TITLE)
    t.get_style_context().add_class("wfa-title")
    st = Gtk.Label(label=_(BANNER_SUB).upper())
    st.get_style_context().add_class("wfa-sub")
    mid.pack_start(t, False, False, 0)
    mid.pack_start(st, False, False, 0)
    box.pack_start(mid, True, True, 0)
    box.pack_end(_svg("ornament-corner.svg", 66, 44, flip=True), False, False, 0)
    box.show_all()
    box.set_no_show_all(True)
    box.set_visible(THEME["on"])
    THEME["widgets"].append(box)
    return box


def colored(color, text):
    """Pango-Markup: Text (wird maskiert) in Farbe."""
    return '<span foreground="{}">{}</span>'.format(color, GLib.markup_escape_text(text))


def short_path(p):
    s = str(p)
    home = str(Path.home())
    return "~" + s[len(home):] if s == home or s.startswith(home + "/") else s


def make_dialog(title, parent, width=-1, height=-1):
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True, use_header_bar=True)
    d.set_default_size(width, height)
    box = d.get_content_area()
    box.set_spacing(8)
    for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
        box.set_property(m, 12)
    if THEME["on"]:
        box.pack_start(divider(False), False, False, 0)
    return d


def add_button(d, label, response, suggested=False, destructive=False):
    b = d.add_button(label, response)
    if suggested:
        b.get_style_context().add_class("suggested-action")
    if destructive:
        b.get_style_context().add_class("destructive-action")
    return b


def fmt_time(t):
    return time.strftime(_("%d.%m.%Y %H:%M:%S"), time.localtime(t))


def message(parent, text, secondary=None, kind=Gtk.MessageType.INFO):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                          buttons=Gtk.ButtonsType.CLOSE, text=text)
    if secondary:
        d.format_secondary_text(secondary)
    d.run()
    d.destroy()


def ask(parent, text, secondary, yes, no=None, kind=Gtk.MessageType.QUESTION):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind, text=text)
    d.format_secondary_text(secondary)
    d.add_button(no or _("Abbrechen"), Gtk.ResponseType.CANCEL)
    add_button(d, yes, Gtk.ResponseType.OK, suggested=kind == Gtk.MessageType.QUESTION,
               destructive=kind == Gtk.MessageType.WARNING)
    r = d.run()
    d.destroy()
    return r == Gtk.ResponseType.OK


def text_view_scroller(text, width=560, height=300):
    sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    sw.set_min_content_width(width)
    sw.set_min_content_height(height)
    tv = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD)
    tv.set_left_margin(6)
    tv.set_right_margin(6)
    tv.set_top_margin(6)
    tv.get_buffer().set_text(text)
    sw.add(tv)
    return sw


def result_line(r):
    return "{status}  {name}: {message}".format(status=_("OK    ") if r.ok else _("FEHLER"), name=r.name, message=r.message)


def err_text(e):
    if isinstance(e, ApiError):
        return str(e)
    return _("Unerwarteter Fehler: {error}").format(error=e)


def run_in_thread(fn, cb):
    """fn im Worker-Thread, cb(result, error) im GTK-Thread."""
    def work():
        try:
            res, err = fn(), None
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            res, err = None, e
        GLib.idle_add(cb, res, err)
    threading.Thread(target=work, daemon=True).start()


def choose_file(parent, title, action, accept, filters=(), name=None):
    """Datei-/Ordnerauswahl ueber Gtk.FileChooserNative: im Flatpak laeuft sie ueber das Datei-Portal, das den
    gewaehlten Ort fuer das Programm freigibt (Pfad unter /run/user/<uid>/doc/). -> Pfad oder None."""
    fc = Gtk.FileChooserNative.new(title, parent, action, accept, _("Abbrechen"))
    if action == Gtk.FileChooserAction.SAVE:
        fc.set_do_overwrite_confirmation(True)
        if name:
            fc.set_current_name(name)
    for f in filters:
        fc.add_filter(f)
    path = fc.get_filename() if fc.run() == Gtk.ResponseType.ACCEPT else None
    fc.destroy()
    return path


def choose_folder(parent, title=None):
    return choose_file(parent, title or _("Ordner wählen"), Gtk.FileChooserAction.SELECT_FOLDER, _("Auswählen"))


def choose_addons_dir(mgr, parent=None, pick_only=False):
    """Dialog zur Auswahl des AddOns-Ordners. -> True, wenn gespeichert.
    pick_only: nichts speichern, sondern den gewaehlten Pfad (str) liefern (None bei Abbruch)."""
    d = make_dialog(_("AddOns-Ordner wählen"), parent, 640)
    d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
    add_button(d, _("Übernehmen"), Gtk.ResponseType.OK, suggested=True)
    box = d.get_content_area()
    intro = Gtk.Label(xalign=0, wrap=True,
                      label=_("Wähle den AddOns-Ordner deiner WoW: Forever-Installation (…/_forever_/Interface/AddOns)."))
    box.pack_start(intro, False, False, 0)
    if core.in_flatpak():
        txt = _("Flatpak: Freigegeben sind die üblichen Orte von Steam, Lutris, Bottles, Heroic, Wine und ~/Games. "
                "Liegt WoW woanders, wähle mit „Anderen Ordner wählen …“ den Ordner „World of Warcraft“; "
                "er wird dann dauerhaft freigegeben.")
        blocked = core.sandbox_blocked_libraries()
        if blocked:
            txt += _("\n\nNicht freigegebene Steam-Bibliotheken: {libraries}\nFreigeben (danach neu starten): {commands}").format(
                libraries=", ".join(short_path(b) for b in blocked),
                commands="; ".join(core.flatpak_override_cmd(b) for b in blocked))
        fl = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=80, label=txt)
        fl.get_style_context().add_class("dim-label")
        box.pack_start(fl, False, False, 0)
    group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.pack_start(group, False, False, 0)
    choices = []

    def add_choice(path, active=False):
        r = Gtk.RadioButton.new_with_label_from_widget(choices[0][0] if choices else None, short_path(path))
        r.set_active(active)
        group.pack_start(r, False, False, 0)
        r.show()
        choices.append((r, path))

    installs = mgr.find_installs()
    for i, p in enumerate(installs):
        add_choice(p, i == 0)
    if not installs:
        group.pack_start(Gtk.Label(xalign=0, label=_("Keine Installation automatisch gefunden.")), False, False, 0)
    hint = Gtk.Label(xalign=0, wrap=True)
    other = Gtk.Button(label=_("Anderen Ordner wählen …"), halign=Gtk.Align.START)

    def on_other(_b):
        p = choose_folder(d, _("Ordner „World of Warcraft“ oder AddOns-Ordner wählen") if core.in_flatpak()
                          else _("AddOns-Ordner wählen"))
        if p:
            ok, h = mgr.validate_addons_dir(p)
            sh = core.sandbox_hint(core.normalize_addons_dir(p)) if ok else ""
            hint.set_text("\n".join(x for x in (h, sh) if x))
            if ok:
                add_choice(core.normalize_addons_dir(p), True)
    other.connect("clicked", on_other)
    box.pack_start(other, False, False, 0)
    box.pack_start(hint, False, False, 0)
    d.show_all()
    saved = False
    picked = None
    while d.run() == Gtk.ResponseType.OK:
        sel = next((p for r, p in choices if r.get_active()), None)
        if sel is None:
            hint.set_text(_("Bitte einen Ordner wählen."))
            continue
        ok, h = mgr.validate_addons_dir(sel)
        if not ok:
            hint.set_text(h)
            continue
        if pick_only:
            picked = str(sel)
            break
        try:
            mgr.set_addons_dir(sel)
        except (ValueError, OSError) as e:
            hint.set_text(str(e))
            continue
        saved = True
        if h:
            message(d, h, kind=Gtk.MessageType.WARNING)
        break
    d.destroy()
    return picked if pick_only else saved


class App:
    def __init__(self, mgr, args, gapp=None):
        self.mgr = mgr
        self.args = args
        self.gapp = gapp
        self.pkgs = []
        self.health = {}             # Paket-Key -> wfa_health.Health (nach jeder Pruefung)
        self.conflicts = []          # wfa_health.Conflict
        self.conf_keys = {}          # Paket-Key -> [Conflict]
        self.disabled = set()        # Ordner (klein), die bei allen Charakteren deaktiviert sind
        self._shown_change = None    # zuletzt gemeldeter Client-Wechsel (alt, neu)
        self._inst_lock = False
        self.rows = {}
        self._busy = 0
        self.ready = False
        self.exit_code = 0
        self.background = None
        self.log_win = None
        self.log_view = None
        self.changelogs = {}
        self.fallback_pins = {}   # Pin je Paket-Key fuer den Browser-Fallback der Versionswahl
        self.loading_cl = set()
        self.listeners = []
        self.self_rel = None
        self._quitting = False
        self._last_log = ""
        self._asking = False
        self._prog = None            # letztes Download-Ereignis (aus dem Worker), siehe on_progress
        self._prog_ctx = None        # (Index, Anzahl) des gerade geplanten Pakets
        self._prog_pending = False
        self._prog_tick = None
        self._prog_speed = None      # (Schluessel, t0, Bytes0) fuer die Geschwindigkeit
        self.build_window()

    @property
    def busy(self):
        return self._busy > 0

    # ------------------------------------------------------------ Aufbau
    def build_window(self):
        w = self.win = Gtk.Window(title=TITLE)
        w.set_default_size(1100, 680)
        hb = self.header = Gtk.HeaderBar(show_close_button=True)
        hb.set_custom_title(Gtk.Box())   # bewusst leer: kein Titel, kein Pfad
        w.set_titlebar(hb)
        self.refresh_btn = Gtk.Button(tooltip_text=_("Auf Updates prüfen (F5)"))
        self.refresh_stack = Gtk.Stack()
        self.refresh_stack.add_named(Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON), "icon")
        self.refresh_spinner = Gtk.Spinner()
        self.refresh_stack.add_named(self.refresh_spinner, "spin")
        self.refresh_btn.add(self.refresh_stack)
        self.refresh_btn.connect("clicked", lambda *_a: self.rescan())
        hb.pack_start(self.refresh_btn)
        # Installations-Umschalter: nur bei >= 2 Installationen sichtbar (update_subtitle)
        self.inst_btn = Gtk.MenuButton(tooltip_text=_("Installation wechseln"), no_show_all=True)
        ib = Gtk.Box(spacing=4)
        self.inst_label = Gtk.Label()
        ib.pack_start(self.inst_label, False, False, 0)
        ib.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        ib.show_all()
        self.inst_btn.add(ib)
        hb.pack_start(self.inst_btn)
        ag = Gtk.AccelGroup()
        w.add_accel_group(ag)
        for key, mod in ((Gdk.KEY_F5, 0), (Gdk.KEY_r, Gdk.ModifierType.CONTROL_MASK)):
            ag.connect(key, mod, Gtk.AccelFlags.VISIBLE, lambda *_a: (self.refresh_btn.get_sensitive() and self.rescan(), True)[1])
        menu_btn = self.menu_btn = Gtk.MenuButton()
        menu_btn.add(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu = Gtk.Menu()
        managed = core.managed_install()   # Paket/Flatpak: Startmenue-Eintrag und Updates kommen von dort
        for label, cb in ((_("Protokoll …"), self.show_log), (_("Backups …"), self.on_backups), (_("Gesamtstände …"), self.on_expert_snapshots),
                          (_("Verlauf …"), self.on_history),
                          (_("Addon-Liste exportieren …"), self.on_export), (_("Addon-Liste importieren …"), self.on_import),
                          (_("Einstellungen …"), self.on_settings),
                          *(() if managed else ((_("Startmenü-Eintrag anlegen"), self.on_desktop_entry),
                                                (_("Nach Programm-Updates suchen …"),
                                                 lambda *_a: self.check_self_update(True)))),
                          (_("Neuigkeiten …"), self.on_changelog), (_("Über"), self.on_about), (None, None), (_("Beenden"), self.on_quit_item)):
            mi = Gtk.SeparatorMenuItem() if label is None else Gtk.MenuItem(label=label)
            if cb:
                mi.connect("activate", cb)
            menu.append(mi)
        # Untermenue "Erweitert": nur bei Einstellung expert sichtbar, siehe apply_expert
        sub = Gtk.Menu()
        for label, cb in ((_("Addons je Charakter und Sets …"), self.on_expert_chars), (_("Aufräumen …"), self.on_expert_cleanup),
                          (_("Fehleranalyse …"), self.on_expert_errors)):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", cb)
            sub.append(mi)
        sub.show_all()   # noetig: show_all am Hauptmenue erreicht das Untermenue des ausgeblendeten Eintrags nicht
        self.expert_item = Gtk.MenuItem(label=_("Erweitert"), no_show_all=True)
        self.expert_item.set_submenu(sub)
        menu.insert(self.expert_item, 6)   # vor _("Einstellungen …")
        menu.show_all()
        self.apply_expert()
        menu_btn.set_popup(menu)
        hb.pack_end(menu_btn)
        hb.show_all()
        self.update_subtitle()
        GLib.idle_add(lambda: (self.install_missing_bar(), False)[1])

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(make_banner(), False, False, 0)
        self.infobar_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(self.infobar_holder, False, False, 0)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            outer.set_property(m, 10)
        root.pack_start(outer, True, True, 0)
        w.add(root)

        info = Gtk.Box(spacing=8)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.summary_label = Gtk.Label(xalign=0, use_markup=True)
        self.summary_label.get_style_context().add_class("wfa-summary")
        self.info_label = Gtk.Label(xalign=0, wrap=True, use_markup=True)
        self.info_label.get_style_context().add_class("wfa-dim")
        col.pack_start(self.summary_label, False, False, 0)
        col.pack_start(self.info_label, False, False, 0)
        info.pack_start(col, True, True, 0)
        self.key_btn = Gtk.Button(label=_("Key eintragen …"), valign=Gtk.Align.CENTER)
        self.key_btn.connect("clicked", self.on_settings)
        info.pack_end(self.key_btn, False, False, 0)
        outer.pack_start(info, False, False, 0)

        self.store = Gtk.ListStore(*COL_TYPES)
        self.tree = Gtk.TreeView(model=self.store, has_tooltip=True)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self.on_toggled)
        self.tree.append_column(Gtk.TreeViewColumn("", tog, active=C_CHECK, visible=C_CAN, activatable=C_CAN))
        cols = ((_("Addon"), C_NAME, True, 0.0), (_("Installiert"), C_LOCAL, False, 0.0), (_("Verfügbar"), C_REMOTE, False, 0.0),
                (_("Quelle"), C_SOURCE, False, 0.0), ("Forever", C_FOREVER, False, 0.5), (_("Status"), C_STATUS, False, 0.0))
        for title, col_id, expand, xal in cols:
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE, xalign=xal)
            if col_id == C_STATUS:
                tc = Gtk.TreeViewColumn(title, r, text=col_id, foreground=C_SCOLOR, foreground_set=C_SSET,
                                        weight=C_WEIGHT, style=C_STYLE)
            elif col_id == C_FOREVER:
                tc = Gtk.TreeViewColumn(title, r, text=col_id, foreground=C_FCOLOR, foreground_set=C_FSET)
            else:
                tc = Gtk.TreeViewColumn(title, r, text=col_id, foreground=C_DIMCOLOR, foreground_set=C_DIM, style=C_STYLE)
            tc.set_alignment(xal)
            tc.set_resizable(True)
            tc.set_expand(expand)
            if col_id in (C_NAME, C_STATUS):
                tc.set_sort_column_id(col_id)
            if col_id == C_NAME:
                tc.set_min_width(240)
            self.tree.append_column(tc)
        self.tree.set_search_column(C_NAME)
        self.tree.connect("button-press-event", self.on_tree_button)
        self.tree.connect("popup-menu", self.on_tree_popup)
        self.tree.connect("query-tooltip", self.on_query_tooltip)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.get_style_context().add_class("wfa-table")
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(self.tree)
        self.empty_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, use_markup=True)
        self.empty_label.get_style_context().add_class("wfa-empty")
        self.table_stack = Gtk.Stack()
        self.table_stack.add_named(sw, "list")
        self.table_stack.add_named(self.empty_label, "empty")
        outer.pack_start(self.table_stack, True, True, 0)

        outer.pack_start(divider(), False, False, 0)
        bar = Gtk.Box(spacing=6)
        self.update_btn = Gtk.Button(label=_("Aktualisieren"))
        self.update_btn.get_style_context().add_class("suggested-action")
        self.update_btn.connect("clicked", self.on_update_selected)
        self.mark_btn = Gtk.Button(label=_("Alle Updates markieren"))
        self.mark_btn.connect("clicked", self.on_mark_all)
        self.uninstall_btn = Gtk.Button(label=_("Deinstallieren …"))
        self.uninstall_btn.connect("clicked", self.on_uninstall)
        self.browser_btn = Gtk.Button(label=_("Im Browser laden …"))
        self.browser_btn.connect("clicked", self.on_browser_selected)
        for b in (self.uninstall_btn, self.browser_btn):
            b.get_style_context().add_class("wfa-flat")
        self.new_btn = Gtk.Button(label=_("Neues Addon …"))
        self.new_btn.connect("clicked", self.on_new_addon)
        for b in (self.update_btn, self.mark_btn, self.uninstall_btn, self.browser_btn):
            bar.pack_start(b, False, False, 0)
        bar.pack_end(self.new_btn, False, False, 0)
        self.buttons = [self.update_btn, self.mark_btn, self.uninstall_btn, self.browser_btn, self.new_btn]
        outer.pack_start(bar, False, False, 0)

        # Download-Fortschritt: nur sichtbar, solange etwas geladen wird
        self.prog_box = Gtk.Box(spacing=8, no_show_all=True)
        self.prog_bar = Gtk.ProgressBar(show_text=True, hexpand=True, valign=Gtk.Align.CENTER,
                                        ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.prog_cancel = Gtk.Button(label=_("Abbrechen"))
        self.prog_cancel.get_style_context().add_class("wfa-flat")
        self.prog_cancel.set_tooltip_text(_("Bricht die laufenden Downloads ab"))
        self.prog_cancel.connect("clicked", self.on_cancel_downloads)
        self.prog_box.pack_start(self.prog_bar, True, True, 0)
        self.prog_box.pack_start(self.prog_cancel, False, False, 0)
        self.prog_bar.show()
        self.prog_cancel.show()
        outer.pack_start(self.prog_box, False, False, 0)

        self.log_buf = Gtk.TextBuffer()
        status = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        self.status_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.status_label.get_style_context().add_class("wfa-dim")
        status.pack_start(self.spinner, False, False, 0)
        status.pack_start(self.status_label, True, True, 0)
        outer.pack_start(status, False, False, 0)
        root.show_all()
        self.spinner.set_visible(False)
        self.update_info()
        self.update_actions()

    def present(self):
        self.win.show()
        self.win.deiconify()
        self.win.present()

    def log(self, text):
        def add():
            self.log_buf.insert(self.log_buf.get_end_iter(), text + "\n")
            if self.log_view is not None:
                mark = self.log_buf.create_mark(None, self.log_buf.get_end_iter(), False)
                self.log_view.scroll_to_mark(mark, 0, False, 0, 0)
                self.log_buf.delete_mark(mark)
            self._last_log = text.split("\n")[0]
            if not self.busy:
                self.status_label.set_text(self._last_log)
            return False
        GLib.idle_add(add)

    def show_log(self, *_a):
        if self.log_win is not None:
            self.log_win.present()
            return
        w = self.log_win = Gtk.Window(title=_("Protokoll"))
        w.set_default_size(760, 420)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            box.set_property(m, 10)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        self.log_view = Gtk.TextView(buffer=self.log_buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        sw.add(self.log_view)
        box.pack_start(sw, True, True, 0)
        row = Gtk.Box(spacing=6)
        cp = Gtk.Button(label=_("Kopieren"))
        cp.connect("clicked", lambda *_a: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(
            self.log_buf.get_text(self.log_buf.get_start_iter(), self.log_buf.get_end_iter(), False), -1))
        cl = Gtk.Button(label=_("Schließen"))
        cl.connect("clicked", lambda *_a: w.destroy())
        row.pack_end(cl, False, False, 0)
        row.pack_end(cp, False, False, 0)
        box.pack_start(row, False, False, 0)
        w.add(box)

        def gone(*_a):
            self.log_win = None
            self.log_view = None
        w.connect("destroy", gone)
        w.show_all()
        GLib.idle_add(lambda: (self.log_view.scroll_to_iter(self.log_buf.get_end_iter(), 0, False, 0, 0), False)[1])

    def update_subtitle(self):
        """Installations-Umschalter in der Kopfzeile pflegen (Titel und Pfad stehen dort bewusst nicht mehr)."""
        insts = self.mgr.installations()
        cur = next((e for e in insts if e["active"]), None)
        many = len(insts) >= 2
        if cur:
            self.inst_btn.set_tooltip_text("{}\n{}".format(_("Installation wechseln"), short_path(cur["path"])))
        self.inst_btn.set_visible(many)
        if many:
            self.inst_label.set_text(cur["name"] if cur else "–")
            self.build_inst_menu(insts)

    def build_inst_menu(self, insts):
        menu = Gtk.Menu()
        grp = None
        self._inst_lock = True
        for e in insts:
            label = e["name"] if e["ok"] else "{} {}".format(e["name"], _("(nicht gefunden)"))
            mi = Gtk.RadioMenuItem.new_with_label_from_widget(grp, label)
            grp = grp or mi
            mi.set_active(e["active"])
            mi.set_sensitive(e["ok"])
            mi.connect("toggled", self.on_inst_toggled, e)
            menu.append(mi)
        self._inst_lock = False
        menu.append(Gtk.SeparatorMenuItem())
        mi = Gtk.MenuItem(label=_("Installationen verwalten …"))
        mi.connect("activate", lambda *_a: self.on_settings(focus="installations"))
        menu.append(mi)
        menu.show_all()
        self.inst_btn.set_popup(menu)
        self.inst_menu = menu

    def on_inst_toggled(self, mi, e):
        if self._inst_lock or not mi.get_active() or e["active"] or self.busy:
            return
        GLib.idle_add(lambda: (self.switch_install(e["path"]), False)[1])

    def switch_install(self, path):
        """Wechselt die aktive Installation (nur Lesen, WoW darf laufen). -> True bei Erfolg."""
        ok, hint = self.mgr.switch_installation(path)
        if not ok:
            message(self.win, _("Wechsel nicht möglich"), hint, Gtk.MessageType.WARNING)
            self.update_subtitle()   # Radio springt zurueck
            return False
        self.after_switch()
        return True

    def after_switch(self):
        cur = next((e for e in self.mgr.installations() if e["active"]), None)
        self.pkgs, self.ready = [], False
        self.health, self.conflicts, self.conf_keys = {}, [], {}
        self.show_infobar(None)
        self.update_subtitle()
        self.render()
        self.rescan()
        if cur:
            self.log(_("Installation gewechselt: {name}").format(name=cur["name"]))

    def install_missing_bar(self):
        """Infobar, wenn die aktive Installation nicht mehr erreichbar ist (Platte nicht eingehaengt)."""
        insts = self.mgr.installations()
        cur = next((e for e in insts if e["active"]), None)
        if cur is None or cur["ok"]:
            return
        other = next((e for e in insts if e["ok"]), None)
        text = _("Installation „{name}“ nicht gefunden.").format(name=cur["name"])
        if other is None:
            self.show_infobar(text)
            return
        self.show_infobar(text, [(_("Zu „{other}“ wechseln").format(other=other["name"]), 1, True)],
                          lambda r: self.switch_install(other["path"]) if r == 1 else None)

    def update_info(self):
        m = self.mgr
        state = m.cf_key_state()
        parts = [_("Client {version} (Interface {interface})").format(version=m.client_version, interface=m.client_interface)
                 if m.client_version
                 else _("Client-Interface {interface} (aus den Addons geschätzt)").format(interface=m.client_interface)]
        if state == "fehlt":
            parts.append(colored(ORANGE, _("CurseForge: kein API-Key – kostenlos unter {url} erzeugen.").format(
                url=core.CF_KEY_URL)))
        elif state == "ungültig":
            parts.append(colored(RED, _("CurseForge: Key ungültig oder abgelehnt.")))
        else:
            parts.append(GLib.markup_escape_text(_("CurseForge: Key {state}").format(state=_(state))))
        for n in dict.fromkeys(list(m.notes) + list(m.snapshot_notes)):
            parts.append(colored(ORANGE, n))
        self.info_label.set_markup("  ·  ".join(parts))
        self.key_btn.set_visible(state in ("fehlt", "ungültig"))
        n, u = len(self.pkgs), len(self.mgr.updatable(self.pkgs))
        ign = sum(1 for p in self.pkgs if p.ignored)
        s = "{} · {}".format(ngettext("1 Addon", "{n} Addons", n).format(n=n), ngettext("1 Update", "{n} Updates", u).format(n=u))
        if ign:
            s += " · " + _("{n} ignoriert").format(n=ign)
        dis = sum(1 for p in self.pkgs if self.pkg_disabled(p))
        if dis:
            s += " · " + _("{n} deaktiviert").format(n=dis)
        aband = sum(1 for p in self.pkgs if getattr(self.health.get(p.key), "status", "") == "abandoned")
        if aband:
            s += " · " + _("{n} verwaist").format(n=aband)
        if self.conflicts:
            s += " · " + ngettext("1 Konflikt", "{n} Konflikte", len(self.conflicts)).format(n=len(self.conflicts))
        self.summary_label.set_markup("<b>{}</b>".format(GLib.markup_escape_text(s if self.ready or n else _("Prüfe …"))))

    def update_actions(self):
        working = self.busy
        n = sum(1 for r in self.store if r[C_CHECK] and self.rows.get(r[C_KEY]) is not None
                and self.rows[r[C_KEY]].status == core.UPDATE and self.rows[r[C_KEY]].remote is not None)
        self.update_btn.set_label(ngettext("1 aktualisieren", "{n} aktualisieren", n).format(n=n) if n else _("Aktualisieren"))
        self.update_btn.set_sensitive(n > 0 and not working)
        self.mark_btn.set_sensitive(not working)
        for b in (self.uninstall_btn, self.browser_btn, self.new_btn):
            b.set_sensitive(not working)

    def on_delete(self, *_a):
        bg = self.background
        if bg is not None and bg.available and self.mgr.cfg["close_to_tray"]:
            self.win.hide()
            return True
        if self.busy and not ask(self.win, _("Vorgang läuft"), _("Vorgang läuft – trotzdem beenden?"),
                                 _("Beenden"), kind=Gtk.MessageType.WARNING):
            return True
        self.quit(force=True)
        return True

    def on_quit_item(self, *_a):
        if self.busy and not ask(self.win, _("Vorgang läuft"), _("Vorgang läuft – trotzdem beenden?"),
                                 _("Beenden"), kind=Gtk.MessageType.WARNING):
            return
        self.quit(force=True)

    def confirm_quit_busy(self):
        """Nachfrage bei laufendem Vorgang; waehrend der Dialog offen ist, kein zweiter."""
        if self._asking:
            return False
        self._asking = True
        try:
            self.present()
            return ask(self.win, _("Vorgang läuft"), _("Vorgang läuft – trotzdem beenden?"),
                       _("Beenden"), kind=Gtk.MessageType.WARNING)
        finally:
            self._asking = False

    def quit(self, force=False):
        """Echtes Beenden (nicht nur ins Tray). Ohne force wird bei laufendem Vorgang nachgefragt
        (Aufrufer aus dem Hintergrund, z. B. Tray-Menue)."""
        if self._quitting:
            return
        if self.busy and not force and not self.confirm_quit_busy():
            return
        self._quitting = True
        if self.background is not None:
            try:
                self.background.stop()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        self.win.destroy()
        if self.gapp is not None:
            self.gapp.quit()
        else:
            Gtk.main_quit()

    def set_busy(self, on, text=""):
        self._busy = max(0, self._busy + (1 if on else -1))
        working = self.busy
        for b in (self.menu_btn, self.key_btn, self.refresh_btn, self.inst_btn):
            b.set_sensitive(not working)
        self.tree.set_sensitive(not working)
        self.spinner.set_visible(working)
        self.refresh_stack.set_visible_child_name("spin" if working else "icon")
        if working:
            self.spinner.start()
            self.refresh_spinner.start()
            self.status_label.set_text(text)
        else:
            self.spinner.stop()
            self.refresh_spinner.stop()
            self.hide_progress()
        self.update_actions()

    # ------------------------------------------------------------ Download-Fortschritt
    def on_progress(self, **ev):
        """Aus dem Worker-Thread (Manager.progress). Bündelt die Ereignisse zu höchstens einem idle-Aufruf."""
        ev["ctx"] = self._prog_ctx
        ev["t"] = time.monotonic()
        self._prog = ev
        if not self._prog_pending:
            self._prog_pending = True
            GLib.idle_add(self._progress_idle)

    def _progress_idle(self):
        self._prog_pending = False
        self.render_progress()
        return False

    def render_progress(self):
        ev = self._prog
        if ev is None or not self.busy:
            return
        now = time.monotonic()
        i, n = ev.get("ctx") or (0, 1)
        name = ev.get("name") or _("Download")
        head = "{name} ({i}/{n})".format(name=name, i=i + 1, n=n) if n > 1 else name
        state, frac = ev.get("state"), None
        if state == "download":
            done, total = ev.get("done") or 0, ev.get("total")
            key = (name, ev.get("way"), ev.get("attempt"))
            if not self._prog_speed or self._prog_speed[0] != key:
                self._prog_speed = (key, ev["t"], done)
            _k, t0, b0 = self._prog_speed
            parts = [head, ev.get("way") or "", core.fmt_size(done) + (f" / {core.fmt_size(total)}" if total else "")]
            if ev["t"] - t0 >= 1 and done > b0:
                parts.append(core.fmt_size((done - b0) / (ev["t"] - t0)) + "/s")
            if (ev.get("attempt") or 1) > 1:
                parts.append(_("Versuch {attempt}/{total}").format(attempt=ev["attempt"], total=core.DL_ATTEMPTS))
            idle = now - ev["t"]
            if idle >= 5:
                parts.append(_("keine Daten seit {seconds} s").format(seconds="{:.0f}".format(idle)))
            text = " · ".join(p for p in parts if p)
            frac = done / total if total else None
        elif state == "verify":
            text, frac = _("{head} · prüfe Zip-Datei …").format(head=head), 1.0
        elif state == "retry":
            left = max(0, ev.get("wait", 0) - (now - ev["t"]))
            text = _("{head} · {way}: {error} – neuer Versuch {attempt}/{total} in {seconds} s").format(
                head=head, way=ev.get("way"), error=ev.get("error"), attempt=ev.get("attempt"),
                total=core.DL_ATTEMPTS, seconds="{:.0f}".format(left))
        elif state == "fallback":
            text = _("{head} · {way}: {error} – wechsle zu {next}").format(
                head=head, way=ev.get("way"), error=ev.get("error"), next=ev.get("next"))
        else:
            return
        if self.mgr.dl_cancel.is_set():
            text = _("Breche ab …")
        if frac is None and state == "download":
            self.prog_bar.pulse()
        else:
            self.prog_bar.set_fraction(max(0.0, min(1.0, (i + (frac or 0.0)) / max(n, 1))))
        self.prog_bar.set_text(text)
        self.prog_bar.set_tooltip_text(text)
        if not self.prog_box.get_visible():
            self.prog_cancel.set_sensitive(True)
            self.prog_box.show()
        if self._prog_tick is None:
            # aktualisiert Wartezeiten und die "keine Daten"-Anzeige auch ohne neue Ereignisse
            self._prog_tick = GLib.timeout_add(500, self._progress_tick)

    def _progress_tick(self):
        if not self.prog_box.get_visible():
            self._prog_tick = None
            return False
        self.render_progress()
        return True

    def hide_progress(self):
        self._prog = None
        self._prog_speed = None
        self.prog_box.hide()
        self.prog_bar.set_fraction(0.0)

    def on_cancel_downloads(self, *_a):
        self.mgr.dl_cancel.set()
        self.prog_cancel.set_sensitive(False)
        self.prog_bar.set_text(_("Breche ab …"))
        self.log(_("Downloads werden abgebrochen …"))

    def log_results(self, results, installed=False):
        """Ergebnis einer Installation ins Protokoll; die letzte Zeile landet in der Statuszeile."""
        ok = [r.name for r in results if r.ok]
        for r in results:
            if not r.ok:
                self.log(_("FEHLER {name}: {message}").format(name=r.name, message=r.message))
        if ok:
            if installed:
                msg = ngettext("Fertig: 1 Addon installiert ({names})", "Fertig: {n} Addons installiert ({names})", len(ok))
            else:
                msg = ngettext("Fertig: 1 Addon aktualisiert ({names})", "Fertig: {n} Addons aktualisiert ({names})", len(ok))
            self.log(msg.format(n=len(ok), names=", ".join(ok)))
        elif results:
            self.log(_("Fertig: nichts installiert"))

    def bg(self, fn, cb, text=None):
        self.set_busy(True, text or _("Arbeite …"))

        def done(res, err):
            self.set_busy(False)
            if err:
                self.log(_("Fehler: {error}").format(error=err_text(err)))
            cb(res, err)
            return False
        run_in_thread(fn, done)

    # ------------------------------------------------------------ Liste
    def row_values(self, p, checked=False):
        upd = p.status == core.UPDATE
        if p.ignored:
            stext, scolor, sset, weight, style = _("ignoriert"), GREY, True, 400, 2
        elif upd:
            stext, scolor, sset, weight, style = _("▲ Update"), ORANGE, True, 700, 0
        elif self.pkg_disabled(p):
            stext, scolor, sset, weight, style = _("⏸ deaktiviert"), GREY, True, 400, 2
        elif p.status == core.CURRENT and self.health_status(p) == "abandoned":
            stext, scolor, sset, weight, style = _("⚠ verwaist"), ORANGE, True, 400, 0
        elif p.status == core.CURRENT and self.health_status(p) == "stale":
            stext, scolor, sset, weight, style = _("◷ lange kein Update"), GREY, True, 400, 2
        elif p.status == core.CURRENT:
            stext, scolor, sset, weight, style = _("✓ aktuell"), GREEN, True, 400, 0
        elif p.status in (core.HELD, core.SKIPPED):
            stext, scolor, sset, weight, style = _(p.status), GREY, True, 400, 2
        else:
            stext, scolor, sset, weight, style = _(p.status), STATUS_COLOR.get(p.status, GREY), p.status in STATUS_COLOR, 400, 0
        fcolor = {"ok": GREEN, "veraltet": ORANGE, "nein": RED}.get(p.forever)
        remote = core.display_version(p.remote.version) if p.remote else "–"
        if p.channel in CHANNEL_MARK:
            remote += " " + CHANNEL_MARK[p.channel]
        name = p.name + (" ⚠" if p.key in self.conf_keys else "")
        return [checked, name, core.display_version(p.local_version) or "?",
                remote, p.source,
                _(FOREVER_SHOW.get(p.forever, p.forever)), stext, p.key, weight, scolor, fcolor or GREY, True, sset,
                fcolor is not None, style, p.ignored, GREY]

    def health_status(self, p):
        return getattr(self.health.get(p.key), "status", "ok")

    def health_tip(self, p):
        """Tooltip-Text zu verwaist / lange kein Update / Konflikten ('' = nichts zu sagen)."""
        lines = []
        h = self.health.get(p.key)
        if h is not None and h.status != "ok":
            lines += list(h.reasons)
            if h.last_file:
                lines.append(_("Letzte Datei für Forever: {date}").format(date=h.last_file.strftime("%x")))
            if h.status == "abandoned":
                lines.append(_("Es kommen voraussichtlich keine Updates mehr. Ersatz suchen: „Neues Addon …“."))
        names = lambda keys: ", ".join(self.rows[k].name if k in self.rows else k for k in keys)  # noqa: E731
        conf = []
        for c in self.conf_keys.get(p.key, ()):
            if c.kind == "duplicate":
                conf.append(_("Doppelt vorhanden: {folders}").format(folders=", ".join(c.folders)))
            else:
                conf.append(_("Der Ordner {folder} gehört auch zu: {names}").format(
                    folder=c.folders[0], names=names([k for k in c.keys if k != p.key])))
        return "\n\n".join(x for x in ("\n".join(lines), "\n".join(conf)) if x)

    def read_disabled(self):
        try:
            import wfa_chars
            wtf = self.mgr.wtf_dir()
            return wfa_chars.disabled_folders(wfa_chars.list_characters(wtf) if wtf else [])
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return set()

    def pkg_disabled(self, p):
        return bool(p.folders) and all(f.lower() in self.disabled for f in p.folders)

    def toggle_disabled(self, p):
        """Addon bei allen Charakteren aus- oder wieder einschalten (AddOns.txt, mit Backup)."""
        import wfa_chars
        import wfa_expert
        wtf = self.mgr.wtf_dir()
        chars = wfa_chars.list_characters(wtf) if wtf else []
        if not chars:
            message(self.win, _("Keine Charaktere gefunden"),
                    _("Deaktivieren wirkt über die Addon-Liste der Charaktere. Melde dich dafür zuerst einmal "
                      "mit einem Charakter in WoW an."))
            return
        if not wfa_expert.wow_guard(self.win, self.mgr):
            return
        enable = self.pkg_disabled(p)
        try:
            wfa_chars.write_states_all(chars, {f: enable for f in p.folders},
                                       self.mgr.paths.data_dir / "addons_txt_backups", install=self.mgr.install_id())
        except OSError as e:
            message(self.win, _("Fehler"), str(e), Gtk.MessageType.ERROR)
            self.disabled = self.read_disabled()
            self.refresh_row(p)
            return
        low = {f.lower() for f in p.folders}
        self.disabled = (self.disabled - low) if enable else (self.disabled | low)
        if enable:
            self.log(ngettext("„{name}“ bei 1 Charakter wieder aktiviert.",
                              "„{name}“ bei {n} Charakteren wieder aktiviert.", len(chars)).format(name=p.name, n=len(chars)))
        else:
            self.log(ngettext("„{name}“ bei 1 Charakter deaktiviert. Wieder einschalten: Rechtsklick → „Wieder aktivieren“.",
                              "„{name}“ bei {n} Charakteren deaktiviert. Wieder einschalten: Rechtsklick → „Wieder aktivieren“.",
                              len(chars)).format(name=p.name, n=len(chars)))
        self.refresh_row(p)

    def update_health(self, pkgs, health, conflicts):
        self.health, self.conflicts = health, conflicts
        self.conf_keys = {}
        for c in conflicts:
            for k in c.keys:
                self.conf_keys.setdefault(k, []).append(c)

    def render(self, marked=()):
        self.store.clear()
        self.rows = {}
        for p in self.pkgs:
            self.rows[p.key] = p
            self.store.append(self.row_values(p, p.key in marked))
        self.update_info()
        self.update_actions()
        if not self.pkgs and self.ready:
            ad = short_path(self.mgr.addons_dir) if self.mgr.addons_dir else "–"
            self.empty_label.set_markup(
                "<big><b>{title}</b></big>\n\n{empty}\n{path}\n\n{hint}".format(
                    title=GLib.markup_escape_text(_("Keine Addons gefunden")),
                    empty=GLib.markup_escape_text(_("Im AddOns-Ordner liegen keine Addons.")),
                    path=GLib.markup_escape_text(ad),
                    hint=GLib.markup_escape_text(_("Über „Neues Addon …“ lassen sich Addons installieren."))))
            self.table_stack.set_visible_child_name("empty")
        else:
            self.table_stack.set_visible_child_name("list")

    def refresh_row(self, p):
        for row in self.store:
            if row[C_KEY] == p.key:
                vals = self.row_values(p, row[C_CHECK] and not p.ignored and p.status == core.UPDATE)
                for i, v in enumerate(vals):
                    row[i] = v
                break
        self.update_info()
        self.update_actions()

    def on_toggled(self, _r, path):
        row = self.store[path]
        if row[C_CAN]:
            row[C_CHECK] = not row[C_CHECK]
            self.update_actions()

    def mark_updates(self, only_new_from=None):
        """Alle Updates anhaken; mit only_new_from (Menge vorheriger Update-Keys) nur neu hinzugekommene,
        bestehende Haken des Nutzers bleiben."""
        ok = {p.key for p in self.mgr.updatable(self.pkgs)}
        for row in self.store:
            if only_new_from is None:
                row[C_CHECK] = row[C_KEY] in ok
            elif row[C_KEY] in ok and row[C_KEY] not in only_new_from:
                row[C_CHECK] = True
            elif row[C_KEY] not in ok:
                row[C_CHECK] = False
        self.update_actions()

    def on_mark_all(self, *_a):
        ok = {p.key for p in self.mgr.updatable(self.pkgs)}
        for row in self.store:
            if row[C_KEY] in ok:
                row[C_CHECK] = True
        self.update_actions()

    def selected_pkg(self):
        model, it = self.tree.get_selection().get_selected()
        return self.rows.get(model[it][C_KEY]) if it else None

    def add_check_listener(self, fn):
        self.listeners.append(fn)

    def rescan(self, then=None, quiet=False):
        """then(pkgs, err) nach Scan und Pruefung; quiet: Hintergrundlauf; wird abgewiesen, wenn
        gerade etwas laeuft, und behaelt die Haken des Nutzers (nur neue Updates werden angehakt)."""
        if not self.mgr.addons_dir:
            if then:
                then(self.pkgs, _("Kein AddOns-Ordner gewählt"))
            return
        if self.busy and quiet:
            if then:
                then(self.pkgs, _("Programm ist beschäftigt"))
            return

        before = {p.key for p in self.mgr.updatable(self.pkgs)}

        def work():
            pkgs = self.mgr.scan()
            self.mgr.check(pkgs, lambda d, t, s: GLib.idle_add(self.status_label.set_text, _("Prüfe … {done}/{total} {name}").format(done=d, total=t, name=s)))
            try:
                health = wfa_health.assess(pkgs, self.mgr.cfg, self.mgr.client_interface)
                conf = wfa_health.conflicts(pkgs, self.mgr.addons_dir)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                health, conf = {}, []
            return pkgs, health, conf, self.read_disabled()

        def done(res, err):
            if res is not None:
                res, health, conf, self.disabled = res
                self.update_health(res, health, conf)
                self.pkgs = res
                self.ready = True
                self.render()
                self.client_change_bar()
                self.mark_updates(before if quiet else None)
                self.status_label.set_text(self._last_log)
            else:
                self.ready = True
                self.update_info()
                self.status_label.set_text(err_text(err))
            if res is not None:
                for fn in list(self.listeners):
                    try:
                        fn(self.pkgs)
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
            if then:
                then(self.pkgs, err)
        self.bg(work, done, _("Lese AddOns-Ordner und prüfe Versionen … (der erste Lauf dauert etwas länger)"))

    def client_change_bar(self):
        """Infobar nach einem erkannten Client-Wechsel (einmal je Wechsel)."""
        ch = self.mgr.last_client_change
        if not ch or ch == self._shown_change:
            return
        self._shown_change = ch
        text = _("WoW wurde aktualisiert ({old} → {new}).").format(old=ch[0], new=ch[1])
        if not self.mgr.cfg["auto_snapshot_client"]:
            self.show_infobar(text, closable=True)
            return
        if not self.mgr.last_client_snapshot:
            self.show_infobar(_("WoW wurde aktualisiert ({old} → {new}). Die automatische Sicherung ist fehlgeschlagen – "
                                "Details im Protokoll.").format(old=ch[0], new=ch[1]), closable=True)
            return
        self.show_infobar(text + " " + _("Der vorherige Stand wurde gesichert."), [(_("Gesamtstände …"), 1, False)],
                          lambda r: self.on_expert_snapshots() if r == 1 else None, closable=True)

    # ------------------------------------------------------------ Kontextmenue, Ignorieren, Changelog
    def on_tree_button(self, tree, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS or ev.button != 3:
            return False
        hit = tree.get_path_at_pos(int(ev.x), int(ev.y))
        if not hit:
            return False
        tree.get_selection().select_path(hit[0])
        self.popup_context(lambda m: m.popup_at_pointer(ev))
        return True

    def on_tree_popup(self, tree):
        model, it = tree.get_selection().get_selected()
        if not it:
            return False
        rect = tree.get_cell_area(model.get_path(it), tree.get_column(1))
        self.popup_context(lambda m: m.popup_at_rect(tree.get_bin_window(), rect, Gdk.Gravity.SOUTH_WEST,
                                                      Gdk.Gravity.NORTH_WEST, None))
        return True

    def popup_context(self, show):
        p = self.selected_pkg()
        if p is None:
            return
        m = self.ctx_menu = Gtk.Menu()
        url = p.page_url or (p.remote.page_url if p.remote else None)
        items = (
            (_("Zuordnen …"), lambda: self.assign_dialog(p), bool(p.meta.get("unassigned")) and not self.busy),
            (_("Aktualisieren"), lambda: self.install_flow([(p.name, (lambda: self.mgr.plan_update(p)), p)]),
             p.status == core.UPDATE and p.remote is not None),
            (_("Changelog …"), lambda: self.show_changelog(p), p.remote is not None),
            (_("Verlauf …"), lambda: self.on_history(name=p.name), True),
            (_("Andere Version …"), lambda: self.pick_version(p),
             not p.meta.get("unassigned") and bool(p.cf_mod_id or p.meta.get("gh")) and not self.busy),
            *(((_("Festhalten aufheben") if p.pin["mode"] == "hold" else _("Auslassen aufheben"), lambda: self.release_pin(p), not self.busy),)
              if p.pin else ()),
            ("@channel", p),
            (_("Updates nicht mehr ignorieren") if p.ignored else _("Updates ignorieren"), lambda: self.toggle_ignore(p), True),
            (_("Wieder aktivieren") if self.pkg_disabled(p) else _("Deaktivieren (alle Charaktere)"),
             lambda: self.toggle_disabled(p), bool(p.folders) and not self.busy),
            None,
            (_("Seite öffnen"), lambda: self.open_uri(url), bool(url)),
            (_("Ordner öffnen"), lambda: self.open_folder(p), bool(p.folders)),
            (_("Im Browser laden …"), lambda: self.browser_flow(p), True),
            None,
            (_("Deinstallieren …"), lambda: self.uninstall([p]), True),
        )
        for it in items:
            if it is None:
                m.append(Gtk.SeparatorMenuItem())
                continue
            if it[0] == "@channel":
                m.append(self.channel_item(it[1]))
                continue
            label, cb, en = it
            mi = Gtk.MenuItem(label=label, sensitive=en)
            mi.connect("activate", lambda _w, cb=cb: cb())
            m.append(mi)
        m.show_all()
        show(m)

    def assign_dialog(self, p):
        """„Zuordnen …“: Vorschläge aus TOC/Suche oder Freitext (ID, Adresse, gh:owner/repo)."""
        def got(sugs, err):
            d = make_dialog(_("{name} zuordnen").format(name=p.name), self.win, 560)
            d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
            add_button(d, _("Zuordnen"), Gtk.ResponseType.OK, suggested=True)
            box = d.get_content_area()
            radios, group = [], None
            none_rb = Gtk.RadioButton.new_with_label_from_widget(None, _("Keine Auswahl (Eingabe unten verwenden)"))
            group = none_rb
            if sugs:
                box.pack_start(none_rb, False, False, 0)
            for sg in sugs or []:
                src = "CurseForge" if sg.cand.source == "CF" else "GitHub"
                rb = Gtk.RadioButton.new_with_label_from_widget(
                    group, "{name}  ({src} {ident})\n{reason}".format(name=sg.cand.name, src=src, ident=sg.cand.ident, reason=sg.reason)
                    + (_("  – eindeutig") if sg.strong else ""))
                rb.get_child().set_xalign(0)
                radios.append((rb, sg))
                box.pack_start(rb, False, False, 0)
            first_strong = next((rb for rb, sg in radios if sg.strong), None)
            if first_strong:   # nur eindeutige Vorschläge werden vorgewählt
                first_strong.set_active(True)
            if not radios:
                lb = Gtk.Label(label=_("Keine Vorschläge gefunden.") if not err
                               else _("Vorschläge nicht ermittelbar: {error}").format(error=err_text(err)),
                               xalign=0, wrap=True)
                box.pack_start(lb, False, False, 0)
            box.pack_start(Gtk.Label(label=_("Oder Projekt-ID, CurseForge-/GitHub-Adresse, gh:owner/repo:"), xalign=0), False, False, 0)
            entry = Gtk.Entry(activates_default=True)
            box.pack_start(entry, False, False, 0)
            d.set_default_response(Gtk.ResponseType.OK)
            d.show_all()
            ok = d.run() == Gtk.ResponseType.OK
            text = entry.get_text().strip()
            chosen = next((sg for rb, sg in radios if rb.get_active()), None)
            d.destroy()
            if not ok:
                return
            if text:
                def target(cand, e):
                    if e:
                        message(self.win, _("Zuordnung nicht möglich"), err_text(e), Gtk.MessageType.WARNING)
                    else:
                        self.do_assign(p, cand)
                self.bg(lambda: self.mgr.assign_target(text), target, _("Prüfe Eingabe …"))
            elif chosen:
                self.do_assign(p, chosen.cand)
        self.bg(lambda: self.mgr.suggest_assignments(p), got, _("Suche Zuordnungen …"))

    def do_assign(self, p, cand):
        if cand.source == "CF":
            self.mgr.assign_folders(p.folders, cand.name, cf_id=int(cand.ident))
        else:
            self.mgr.assign_folders(p.folders, cand.name, gh=str(cand.ident))
        self.log(_("Zugeordnet: {folders} → {name} ({source} {ident})").format(
            folders=", ".join(p.folders), name=cand.name, source=cand.source, ident=cand.ident))
        self.rescan()

    def channel_item(self, p):
        sub = Gtk.Menu()
        group = None
        for label, ch in CHANNEL_NAMES:
            mi = Gtk.RadioMenuItem(label=_(label), group=group)
            group = group or mi
            mi.set_active(p.channel == ch)
            mi.connect("activate", lambda w, ch=ch: w.get_active() and self.set_channel(p, ch))
            sub.append(mi)
        top = Gtk.MenuItem(label=_("Kanal"), sensitive=not self.busy and not p.meta.get("unassigned"))
        top.set_submenu(sub)
        return top

    def recheck_pkg(self, p, text=None):
        def done(_res, err):
            if err:
                self.log(_("Prüfung fehlgeschlagen: {error}").format(error=err_text(err)))
            self.refresh_row(p)
            refresh = getattr(self.background, "refresh", None)
            if refresh:
                refresh()
        self.bg(lambda: self.mgr.recheck(p), done, text or _("Prüfe …"))

    def set_channel(self, p, ch):
        if p.channel == ch:
            return
        self.mgr.set_channel(p.key, ch)
        p.channel = ch
        self.log(_("{name}: Kanal {channel}").format(name=p.name, channel=_(dict((v, k) for k, v in CHANNEL_NAMES)[ch])))
        self.recheck_pkg(p)

    def release_pin(self, p):
        if self.busy:
            return
        hold = bool(p.pin and p.pin["mode"] == "hold")
        self.mgr.clear_pin(p.key)
        p.pin = None
        self.log((_("{name}: Festhalten aufgehoben") if hold else _("{name}: Auslassen aufgehoben")).format(name=p.name))
        self.recheck_pkg(p)

    def pick_version(self, p):
        """Dialog „Andere Version …“: Liste laden, wählen, installieren (optional festhalten/auslassen)."""
        pages = []

        def load(page, cb):
            self.bg(lambda: self.mgr.versions(p, page), cb, _("Lade Versionsliste …"))

        def first(res, err):
            if err:
                message(self.win, _("Versionsliste nicht verfügbar"), err_text(err), Gtk.MessageType.ERROR)
                return
            if not res[0]:
                message(self.win, _("Keine Versionen"), _("Es wurden keine Forever-Versionen gefunden."))
                return
            pages.extend(res[0])
            self.version_dialog(p, pages, res[1], load)
        load(0, first)

    def version_dialog(self, p, remotes, more, load):
        """remotes wird bei „Mehr laden“ in place erweitert."""
        mgr = self.mgr
        d = make_dialog(_("Andere Version – {name}").format(name=p.name), self.win, 640, 480)
        d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        inst = add_button(d, _("Installieren"), Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        store = Gtk.ListStore(str, str, str, str, int)
        installed = mgr.installed_ident(p)

        def fill():
            store.clear()
            for i, r in enumerate(remotes):
                mark = _("✓ installiert") if installed is not None and r.ident == installed else ""
                store.append([r.display or r.version, (r.file_date or "")[:10], _(core.TYPE_NAMES.get(r.rtype, "Release")), mark, i])
        fill()
        tree = Gtk.TreeView(model=store)
        for i, (title, expand) in enumerate(((_("Version"), True), (_("Datum"), False), (_("Typ"), False), ("", False))):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE)
            tc = Gtk.TreeViewColumn(title, r, text=i)
            tc.set_expand(expand)
            tc.set_resizable(True)
            tree.append_column(tc)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tree)
        box.pack_start(sw, True, True, 0)
        more_btn = Gtk.Button(label=_("Mehr laden"), halign=Gtk.Align.START, no_show_all=True)
        more_btn.set_visible(more)
        box.pack_start(more_btn, False, False, 0)
        hold = Gtk.RadioButton(label=_("Auf dieser Version festhalten, bis ich es aufhebe"))
        skip = Gtk.RadioButton.new_with_label_from_widget(
            hold, _("Nur die jetzt neueren Versionen auslassen (Updates wieder ab einer noch neueren Version)"))
        skip.set_active(True)
        opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        opts.pack_start(Gtk.Label(label=_("Danach gilt:"), xalign=0), False, False, 0)
        opts.pack_start(skip, False, False, 0)
        opts.pack_start(hold, False, False, 0)
        box.pack_start(opts, False, False, 0)
        note = Gtk.Label(xalign=0, wrap=True, no_show_all=True)
        box.pack_start(note, False, False, 0)
        state = dict(more=more, page=0)

        def chosen():
            model, it = tree.get_selection().get_selected()
            return remotes[model[it][4]] if it else None

        def sync(*_a):
            r = chosen()
            newest = mgr.newest_allowed(p, remotes)
            is_new = r is not None and newest is not None and r.ident == newest.ident
            inst.set_sensitive(r is not None and not (installed is not None and r.ident == installed and is_new))
            opts.set_visible(r is not None and not is_new)
            note.set_visible(is_new)
            note.set_text(_("Das ist die neueste Version – normales Update, ohne Festhalten.") if is_new else "")
        tree.get_selection().connect("changed", sync)

        def on_more(_b):
            more_btn.set_sensitive(False)

            def got(res, err):
                more_btn.set_sensitive(True)
                if err:
                    state["page"] -= 1
                    message(d, _("Laden fehlgeschlagen"), err_text(err), Gtk.MessageType.ERROR)
                    return
                remotes.extend(res[0])
                state["more"] = res[1]
                more_btn.set_visible(res[1])
                fill()
                sync()
            state["page"] += 1
            load(state["page"], got)
        more_btn.connect("clicked", on_more)
        d.show_all()
        more_btn.set_visible(state["more"])
        sync()
        ok = d.run() == Gtk.ResponseType.OK
        r = chosen()
        newest = mgr.newest_allowed(p, remotes)
        mode = None
        if r is not None and newest is not None and r.ident != newest.ident:
            mode = "hold" if hold.get_active() else "skip"
        d.destroy()
        self.fallback_pins.pop(p.key, None)
        if ok and r is not None:
            if mode:   # bleibt wirksam, falls der Download im Browser nachgeholt wird
                self.fallback_pins[p.key] = core._pin_record(mode, r if mode == "hold" else newest)
            self.install_flow([(p.name, (lambda: mgr.plan_version(p, r, mode, newest)), p)])

    def open_uri(self, url):
        if not url or not url.startswith(("http://", "https://", "file://")):
            return
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error as e:
            message(self.win, _("Öffnen fehlgeschlagen"), e.message, Gtk.MessageType.ERROR)

    def open_folder(self, p):
        base = self.mgr.addons_dir
        if base and p.folders:
            self.open_uri(Path(base, p.folders[0]).as_uri())

    def toggle_ignore(self, p):
        on = not p.ignored
        self.mgr.set_ignored(p.key, on)
        p.ignored = on
        self.refresh_row(p)
        refresh = getattr(self.background, "refresh", None)
        if refresh:
            refresh()

    def changelog_key(self, p):
        return (p.key, str(p.remote.ident if p.remote else ""))

    def load_changelog(self, p, cb=None):
        k = self.changelog_key(p)
        if k in self.changelogs:
            return
        if k in self.loading_cl:
            return
        self.loading_cl.add(k)

        def done(res, err):
            self.loading_cl.discard(k)
            self.changelogs[k] = "" if err else (res or "")
            self.tree.trigger_tooltip_query()
            if cb:
                cb()
            return False
        run_in_thread(lambda: self.mgr.changelog(p), done)

    def on_query_tooltip(self, tree, x, y, kbd, tip):
        if kbd:
            return False
        bx, by = tree.convert_widget_to_bin_window_coords(x, y)
        hit = tree.get_path_at_pos(bx, by)
        if not hit or hit[1].get_title() not in (_("Addon"), _("Verfügbar"), _("Status")):
            return False
        p = self.rows.get(self.store[hit[0]][C_KEY])
        if p is None:
            return False
        missing = _("Fehlt: {names} (Abhängigkeit laut TOC)").format(names=", ".join(p.missing)) if p.missing else ""
        if hit[1].get_title() in (_("Addon"), _("Status")):
            missing = "\n\n".join(x for x in (missing, self.health_tip(p)) if x)
        if p.status not in (core.UPDATE, core.HELD, core.SKIPPED) or p.remote is None or hit[1].get_title() == _("Addon"):
            if not missing:
                return False
            tip.set_text(missing)
            tree.set_tooltip_cell(tip, hit[0], hit[1], None)
            return True
        k = self.changelog_key(p)
        if k not in self.changelogs:
            self.load_changelog(p)
            text = _("Changelog wird geladen …")
        else:
            lines = self.changelogs[k].strip().splitlines()
            text = "\n".join(lines[:12]) + ("\n…" if len(lines) > 12 else "") if lines else _("Kein Changelog verfügbar.")
        if p.status != core.UPDATE:
            text = core.pin_text(p.pin) + "\n\n" + _("Neueste Version: {version}").format(
                version=core.display_version(p.remote.version) or "?") + "\n" + text
        if p.channel in CHANNEL_MARK:
            text = _("Kanal: {channel}").format(channel=_(dict((v, k) for k, v in CHANNEL_NAMES)[p.channel])) + "\n\n" + text
        tip.set_text(text + ("\n\n" + missing if missing else ""))
        tree.set_tooltip_cell(tip, hit[0], hit[1], None)
        return True

    def show_changelog(self, p):
        def show():
            text = self.changelogs.get(self.changelog_key(p)) or _("Kein Changelog verfügbar.")
            d = make_dialog(_("Changelog – {name}").format(name=p.name), self.win, 640, 420)
            add_button(d, _("Schließen"), Gtk.ResponseType.CLOSE, suggested=True)
            d.get_content_area().pack_start(text_view_scroller(text, 560, 320), True, True, 0)
            d.show_all()
            d.run()
            d.destroy()
        if self.changelog_key(p) in self.changelogs:
            show()
            return

        def fetched(res, err):
            self.changelogs[self.changelog_key(p)] = "" if err else (res or "")
            show()
        self.bg(lambda: self.mgr.changelog(p), fetched, _("Lade Changelog …"))

    # ------------------------------------------------------------ Installieren
    def on_update_selected(self, *_a):
        marked = [self.rows[r[C_KEY]] for r in self.store if r[C_CHECK]]
        if not marked:
            message(self.win, _("Nichts ausgewählt"), _("Markiere Addons mit einem Häkchen."))
            return
        sel = [p for p in marked if p.status == core.UPDATE and p.remote is not None]
        if len(sel) < len(marked):
            skipped = ", ".join(p.name for p in marked if p not in sel)
            message(self.win, _("Ohne Update übersprungen"), skipped)
            if not sel:
                return
        self.install_flow([(p.name, (lambda p=p: self.mgr.plan_update(p)), p) for p in sel])

    def on_uninstall(self, *_a):
        self.uninstall([self.rows[r[C_KEY]] for r in self.store if r[C_CHECK]])

    def uninstall(self, sel):
        if not sel:
            message(self.win, _("Nichts ausgewählt"), _("Markiere die Addons mit einem Häkchen."))
            return

        def planned(plans, err):
            if err:
                message(self.win, _("Deinstallation nicht möglich"), err_text(err), Gtk.MessageType.ERROR)
                return
            plans = [p for p in plans if p.folders]
            if not plans:
                message(self.win, _("Nichts zu deinstallieren"), _("Die Ordner existieren nicht mehr."))
                self.rescan()
                return
            lines = []
            running = self.mgr.wow_running()
            if running:
                lines.append(_("ACHTUNG: WoW scheint zu laufen (heuristisch erkannt). Bitte vorher beenden.\n"))
            elif running is None:
                lines.append(_("Hinweis: Im Flatpak ist nicht erkennbar, ob WoW läuft. Bitte vorher beenden.\n"))
            for p in plans:
                lines.append("• {name}\n    {folders}".format(name=p.name, folders=_("Ordner: {names}").format(names=", ".join(p.folders))))
                lines += ["    ! {}".format(w) for w in p.warnings]
            lines.append(_("\nDie Ordner werden in ein Backup verschoben und lassen sich unter ☰ → Backups "
                           "wiederherstellen. Einstellungen (SavedVariables/WTF) bleiben erhalten."))
            d = make_dialog(_("Deinstallation bestätigen"), self.win, 640, 420)
            d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
            add_button(d, _("Deinstallieren"), Gtk.ResponseType.OK, destructive=True)
            d.get_content_area().pack_start(text_view_scroller("\n".join(lines)), True, True, 0)
            d.show_all()
            ok = d.run() == Gtk.ResponseType.OK
            d.destroy()
            if not ok:
                return

            def finished(results, err2):
                if err2:
                    message(self.win, _("Deinstallation fehlgeschlagen"), err_text(err2), Gtk.MessageType.ERROR)
                else:
                    out = [result_line(r) for r in results]
                    message(self.win, _("Deinstallation abgeschlossen"), "\n".join(out))
                self.rescan()
            self.bg(lambda: self.mgr.uninstall(plans), finished, _("Deinstalliere …"))
        self.bg(lambda: [self.mgr.plan_uninstall(p) for p in sel], planned, _("Prüfe Abhängigkeiten …"))

    def plan_all(self, planners):
        """Im Worker: plant (laedt) alle Pakete nacheinander; nach _("Abbrechen") werden die restlichen übersprungen."""
        plans, errs = [], []
        self.mgr.dl_cancel.clear()
        try:
            for i, (label, fn, ctx) in enumerate(planners):
                self._prog_ctx = (i, len(planners))
                if self.mgr.dl_cancel.is_set():
                    errs.append((label, ApiError("Download abgebrochen", "cancel"), ctx))
                    continue
                try:
                    plans.append(fn())
                except Exception as e:  # noqa: BLE001
                    errs.append((label, e, ctx))
        finally:
            self._prog_ctx = None
        return plans, errs

    @staticmethod
    def split_cancelled(errs):
        """-> (Fehler ohne Abbrüche, Namen der abgebrochenen Pakete)"""
        def cancelled(e):
            return isinstance(e, ApiError) and e.kind == "cancel"
        return [x for x in errs if not cancelled(x[1])], [n for n, e, _c in errs if cancelled(e)]

    def install_flow(self, planners, finish=None, planned=None):
        """planners: [(Name, Callable -> InstallPlan, Kontext)]. Planen im Worker, dann Bestaetigung und apply.
        Pakete mit Download-Fehler werden danach nacheinander im Browser geladen.
        finish(col): Sammelmodus (kein Einzelergebnis, kein Rescan); planned: fertiges (plans, errs)."""
        def is_dl(e):
            return isinstance(e, ApiError) and e.kind == "download"

        def done(res, _err):
            plans, errs = res
            errs, cancelled = self.split_cancelled(errs)
            if cancelled:
                self.log(_("Abgebrochen: {names}").format(names=", ".join(cancelled)))
            queue = []
            if errs:
                lines = ["{}: {}".format(n, err_text(e)) for n, e, _c in errs]
                dl = [(n, c) for n, e, c in errs if is_dl(e)]
                if dl:
                    what = ngettext("Datei stattdessen im Browser herunterladen?",
                                    "Die {n} Dateien nacheinander im Browser herunterladen?", len(dl)).format(n=len(dl))
                    if ask(self.win, _("Download fehlgeschlagen"), "\n".join(lines) + "\n\n" + what, _("Im Browser laden")):
                        queue = [(n, c, None) for n, c in dl]
                else:
                    message(self.win, _("Nicht alles konnte vorbereitet werden"), "\n".join(lines), Gtk.MessageType.WARNING)
            if queue or finish:
                col = dict(installed=[], skipped=list(cancelled), errors=[])
                col["errors"] += [(n, err_text(e)) for n, e, _c in errs if not is_dl(e)]
                if not queue:
                    col["skipped"] += [n for n, e, _c in errs if is_dl(e)]
                tail = (lambda: self.browser_queue(queue, col, finish)) if queue else (lambda: finish(col))
                self.confirm_and_apply(plans, tail, col)
            else:
                self.confirm_and_apply(plans)
        if planned is not None:
            done(planned, None)
        else:
            self.bg(lambda: self.plan_all(planners), done, _("Lade und prüfe Pakete …"))

    def update_packages(self, pkgs, background=False, done=None):
        """done(dict(ok, failed, interactive)). background: ohne Dialog, solange nichts Interaktives noetig ist."""
        pkgs = [p for p in pkgs if p.remote is not None and p.status == core.UPDATE
                and not (background and p.ignored)]

        def report(col, interactive, deferred=False):
            res = dict(ok=list(col["installed"]), interactive=interactive, deferred=deferred,
                       failed=[e if isinstance(e, str) else e[0] for e in col["errors"]])
            if done:
                try:
                    done(res)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()

        if not pkgs:
            report(dict(installed=[], skipped=[], errors=[]), False)
            return
        if background and self.busy:
            GLib.timeout_add_seconds(30, lambda: (self.update_packages(pkgs, True, done), False)[1])
            return
        planners = [(p.name, (lambda p=p: self.mgr.plan_update(p)), p) for p in pkgs]

        def fin_interactive(col):
            self.show_summary(col)
            self.rescan(then=lambda *_a: report(col, True))

        if not background:
            self.install_flow(planners, finish=fin_interactive)
            return

        def planned(res, _err):
            plans, errs, running = res
            errs, cancelled = self.split_cancelled(errs)
            if cancelled:
                self.log(_("Abgebrochen: {names}").format(names=", ".join(cancelled)))
                if not plans and not errs:
                    report(dict(installed=[], skipped=cancelled, errors=[]), False)
                    return
            if running:
                # WoW laeuft: nichts installieren, kein Fenster, Plaene verwerfen
                for p in plans:
                    self.mgr.discard(p)
                report(dict(installed=[], skipped=[], errors=[]), False, True)
                return
            if not errs and plans and not running and not any(p.needs_strong_confirm for p in plans):
                def applied(results, err):
                    col = dict(installed=[], skipped=list(cancelled), errors=[])
                    if err:
                        col["errors"] += [(p.name, err_text(err)) for p in plans]
                    else:
                        self.log_results(results)
                        for r in results:
                            (col["installed"] if r.ok else col["errors"]).append(r.name if r.ok else (r.name, r.message))
                    self.rescan(quiet=True, then=lambda *_a: report(col, False))
                self.bg(lambda: self.apply_plans(plans, origin="auto"), applied, _("Installiere Updates …"))
            else:
                self.present()
                self.install_flow(planners, finish=fin_interactive, planned=(plans, errs))
        def work():
            # unbekannt (Flatpak ohne Host-Zugriff) zaehlt hier wie "laeuft": still wird nichts installiert
            if self.mgr.wow_running() is not False:
                return [], [], True
            plans, errs = self.plan_all(planners)
            running = self.mgr.wow_running() is not False
            return (plans if running else self.auto_deps(plans)), errs, running
        self.bg(work, planned, _("Lade Updates …"))

    def apply_plans(self, plans, origin=None):
        """Worker: mgr.apply; ein dabei angelegter automatischer Gesamtstand kommt ins Protokoll."""
        m = self.mgr
        need = int(m.cfg["auto_snapshot_min"] or 0)
        n = sum(1 for p in plans if p.extra.get("dirs"))
        before = None
        if need > 0 and n >= need:
            GLib.idle_add(self.status_label.set_text, _("Sichere Gesamtstand …"))
            before = {x.id for x in m.list_snapshots()}
        res = m.apply(plans, origin=origin)
        if before is not None:
            for x in m.list_snapshots():
                if x.auto and x.id not in before:
                    self.log(_("Automatischer Gesamtstand {id} angelegt ({reason}).").format(id=x.id, reason=x.reason))
        return res

    def auto_deps(self, plans):
        """Hintergrund-Update: fehlende CF-Pflicht-Abhängigkeiten mitladen, alles andere nur ins Protokoll (Worker)."""
        if not plans:
            return plans
        try:
            needs = self.mgr.resolve_deps(plans, cf_only=True)
        except Exception as e:  # noqa: BLE001
            self.log(_("Abhängigkeiten nicht prüfbar: {error}").format(error=err_text(e)))
            return plans
        take = [d for d in needs if d.cand and d.via == "cf"]
        for d in needs:
            if d not in take:
                self.log(_("Abhängigkeit fehlt: {name} ({reason}) – {note}").format(
                    name=d.name, reason=d.reason, note=d.note or _("nicht automatisch installierbar")))
        dplans, errs = self.plan_all([(d.name, (lambda d=d: self.mgr.plan_candidate(d.cand)), None) for d in take])
        for n, e, _c in errs:
            self.log(_("Abhängigkeit {name}: {error}").format(name=n, error=err_text(e)))
        if dplans:
            self.log(_("Abhängigkeiten werden mitinstalliert: {names}").format(names=", ".join(p.name for p in dplans)))
        return plans + dplans

    def confirm_and_apply(self, plans, after=None, col=None):
        """col: Sammler (installed/skipped/errors) für Durchläufe mit Abschlussübersicht; dann kein Einzelergebnis
        und kein Rescan. Fehlende Pflicht-Abhängigkeiten werden vor der Bestätigung ermittelt."""
        if not plans:
            if after:
                after()
            return
        self.bg(lambda: self.mgr.resolve_deps(plans),
                lambda deps, _err: self.confirm_dialog(plans, deps or [], after, col), _("Prüfe Abhängigkeiten …"))

    def confirm_dialog(self, plans, deps, after, col):
        lines = []
        for p in plans:
            lines.append("• {name}: {old} → {new} ({source})".format(
                name=p.name, old=core.display_version(p.old_version) or "–", new=core.display_version(p.new_version) or "?",
                source=p.source))
            lines.append("    " + _("Ordner: {names}").format(names=", ".join(p.install_folders)))
            if p.skipped_folders:
                lines.append("    " + _("Übersprungen (werden von WoW: Forever nicht geladen): {names}").format(
                    names=", ".join(p.skipped_folders)))
            lines += ["    ! {}".format(w) for w in p.warnings]
        running = self.mgr.wow_running()
        if running:
            lines.insert(0, _("ACHTUNG: WoW scheint zu laufen (heuristisch erkannt). Bitte vorher beenden, sonst können Dateien gesperrt sein.\n"))
        elif running is None:
            lines.insert(0, _("Hinweis: Im Flatpak ist nicht erkennbar, ob WoW läuft. Bitte vorher beenden, sonst können Dateien gesperrt sein.\n"))
        d = make_dialog(_("Installation bestätigen"), self.win, 640, 420)
        d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        add_button(d, _("Installieren"), Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        box.pack_start(text_view_scroller("\n".join(lines)), True, True, 0)
        checks = []
        for dn in deps:
            if dn.cand:
                cb = Gtk.CheckButton(label=_("Benötigt: {name} (wird mitinstalliert)").format(name=dn.name), active=True,
                                     tooltip_text=dn.reason)
                checks.append((cb, dn))
                box.pack_start(cb, False, False, 0)
            else:
                lb = Gtk.Label(label=_("Benötigt: {name} – {note} ({reason})").format(name=dn.name, note=dn.note, reason=dn.reason),
                             xalign=0, wrap=True)
                lb.get_style_context().add_class("wfa-dim")
                box.pack_start(lb, False, False, 0)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        wanted = [dn for cb, dn in checks if cb.get_active()]
        d.destroy()
        if not ok:
            for p in plans:
                self.mgr.discard(p)
                if col is not None:
                    col["skipped"].append(p.name)
            if after:
                after()
            return
        keep = self.confirm_strong(plans, col)
        if not wanted:
            self.apply_plans(keep, after, col)
            return
        planners = [(dn.name, (lambda dn=dn: self.mgr.plan_candidate(dn.cand)), None) for dn in wanted]

        def planned(res, _err):
            dplans, errs = res
            errs, cancelled = self.split_cancelled(errs)
            for n, e, _c in errs:
                self.log(_("Abhängigkeit {name}: {error}").format(name=n, error=err_text(e)))
                if col is not None:
                    col["errors"].append((n, err_text(e)))
            if errs and col is None:
                message(self.win, _("Abhängigkeiten nicht vollständig"),
                        "\n".join("{}: {}".format(n, err_text(e)) for n, e, _c in errs), Gtk.MessageType.WARNING)
            if cancelled and col is not None:
                col["skipped"] += cancelled
            self.apply_plans(keep + self.confirm_strong(dplans, col), after, col)
        self.bg(lambda: self.plan_all(planners), planned, _("Lade Abhängigkeiten …"))

    def confirm_strong(self, plans, col):
        """Pakete ohne Forever-Hauptdatei brauchen eine eigene Bestätigung; -> Liste der weiter zu installierenden."""
        keep = []
        for p in plans:
            if p.needs_strong_confirm and not ask(
                    self.win, _("{name}: nicht für WoW: Forever gedacht").format(name=p.name),
                    _("Das Hauptpaket enthält keine kompatible Forever-Datei (Interface 16xxx). "
                      "Es wird möglicherweise nicht geladen oder verursacht Fehler."), _("Trotzdem installieren"),
                    kind=Gtk.MessageType.WARNING):
                self.mgr.discard(p)
                if col is not None:
                    col["skipped"].append(p.name)
            else:
                keep.append(p)
        return keep

    def apply_plans(self, keep, after, col):
        if not keep:
            if after:
                after()
            return

        def finished(results, err):
            if not err:
                self.log_results(results, installed=True)
            if col is not None:
                if err:
                    col["errors"] += [(p.name, err_text(err)) for p in keep]
                else:
                    for r in results:
                        (col["installed"] if r.ok else col["errors"]).append(
                            r.name if r.ok else (r.name, r.message))
                if after:
                    after()
                return
            if err:
                message(self.win, _("Installation fehlgeschlagen"), err_text(err), Gtk.MessageType.ERROR)
            else:
                sets = {r.backup_set for r in results if r.backup_set}
                out = [result_line(r) for r in results]
                if sets:
                    out.append(_("\nBackup-Satz: {names}").format(names=", ".join(sorted(sets))))
                d2 = make_dialog(_("Ergebnis"), self.win, 600, 300)
                add_button(d2, _("Schließen"), Gtk.ResponseType.CLOSE, suggested=True)
                d2.get_content_area().pack_start(text_view_scroller("\n".join(out), 520, 200), True, True, 0)
                d2.show_all()
                d2.run()
                d2.destroy()
            self.rescan(after)
        self.bg(lambda: self.apply_plans(keep), finished, _("Installiere …"))

    # ------------------------------------------------------------ Browser
    def on_browser_selected(self, *_a):
        p = self.selected_pkg()
        if not p:
            message(self.win, _("Kein Addon gewählt"), _("Wähle eine Zeile in der Liste."))
            return
        self.browser_flow(p)

    def browser_flow(self, target=None, url=None):
        """target: Package/Candidate (oder None mit url). Öffnet Browser, wartet auf neue Zip, installiert."""
        self.browser_queue([(getattr(target, "name", None) or _("Download"), target, url)])

    def show_summary(self, col):
        parts = []
        for title, key in ((N_("Installiert"), "installed"), (N_("Übersprungen"), "skipped"), (N_("Fehler"), "errors")):
            items = [i if isinstance(i, str) else "{}: {}".format(i[0], i[1]) for i in col[key]]
            if items:
                parts.append("{title} ({n}):\n".format(title=_(title), n=len(items)) + "\n".join("  • {}".format(i) for i in items))
        d = make_dialog(_("Gesamtergebnis"), self.win, 600, 320)
        add_button(d, _("Schließen"), Gtk.ResponseType.CLOSE, suggested=True)
        d.get_content_area().pack_start(
            text_view_scroller("\n\n".join(parts) or _("Nichts zu tun."), 520, 220), True, True, 0)
        d.show_all()
        d.run()
        d.destroy()

    def browser_queue(self, items, col=None, finish_cb=None):
        """items: [(Name, Package/Candidate/None, url/None)]. Nacheinander: Browser öffnen, auf Zip warten,
        planen, bestätigen, installieren. col=None: Einzel-Download (ein Eintrag), sonst Sammelübersicht am Ende."""
        mgr, n, solo = self.mgr, len(items), col is None

        def finish():
            if finish_cb:
                finish_cb(col)
            elif not solo:
                self.show_summary(col)
                self.rescan()

        def step(i):
            if i >= n:
                return finish()
            name, target, url = items[i]
            url = url or mgr.browser_url(target)
            hint = getattr(target, "key", None)
            since = time.time()
            watch = mgr.download_watch()
            folders = watch["folders"]
            mgr.open_browser(url)
            cancel, state = threading.Event(), {}
            d = make_dialog(_("Browser-Download"), self.win, 500)
            if solo:
                add_button(d, _("Abbrechen"), Gtk.ResponseType.CANCEL)
            else:
                d.add_button(_("Überspringen"), SKIP)
                d.add_button(_("Alle abbrechen"), ABORT)
            head = (_("Browser-Download {i} von {n}: {name}").format(i=i + 1, n=n, name=name) if n > 1
                    else _("Browser-Download: {name}").format(name=name))
            text = "<b>{head}</b>\n\n{body}".format(head=GLib.markup_escape_text(head), body=GLib.markup_escape_text(
                _("Lade die Datei für WoW: Forever herunter …\n"
                  "Falls nicht vorgefiltert: Filter „Game Version/Flavor“ → „Forever“ wählen.\n\n"
                  "Überwachte Ordner: {folders}").format(
                      folders=", ".join(core.tilde(f) for f in folders) or _("(keiner gefunden)"))))
            if watch["ask"]:
                text += "\n\n" + GLib.markup_escape_text(
                    _("Browser fragt nach Speicherort – bitte in einen dieser Ordner speichern."))
            row = Gtk.Box(spacing=12)
            sp = Gtk.Spinner()
            sp.start()
            row.pack_start(sp, False, False, 0)
            row.pack_start(Gtk.Label(xalign=0, wrap=True, use_markup=True, label=text, max_width_chars=60),
                           True, True, 0)
            d.get_content_area().pack_start(row, True, True, 0)

            def on_resp(_d, r):
                state["resp"] = r
                cancel.set()
            d.connect("response", on_resp)
            d.show_all()

            def done(path, err):
                d.destroy()
                resp = state.get("resp")
                if err or path is None:
                    self.fallback_pins.pop(hint, None)
                if err:
                    if solo:
                        message(self.win, _("Fehler beim Warten"), err_text(err), Gtk.MessageType.ERROR)
                    else:
                        col["errors"].append((name, err_text(err)))
                        step(i + 1)
                elif path is None:
                    if resp is None:
                        if solo:
                            message(self.win, _("Keine Datei erkannt"),
                                    _("Es wurde keine neue Zip-Datei gefunden (Zeitlimit)."))
                        else:
                            col["errors"].append((name, _("Zeitlimit: keine neue Zip gefunden")))
                    if solo:
                        return False
                    if resp == SKIP:
                        col["skipped"].append(name)
                        step(i + 1)
                    elif resp is None:
                        step(i + 1)
                    else:
                        col["skipped"] += [x[0] for x in items[i:]]
                        finish()
                elif solo:
                    self.install_flow([(path.name, lambda: mgr.plan_zip(path, hint), None)])
                else:
                    def planned(plan, perr):
                        if perr:
                            self.fallback_pins.pop(hint, None)
                            col["errors"].append((name, err_text(perr)))
                            step(i + 1)
                        else:
                            pin = self.fallback_pins.pop(hint, None)
                            if pin and plan.key == hint:
                                plan.extra["pin"] = pin
                            self.confirm_and_apply([plan], lambda: step(i + 1), col)
                    self.bg(lambda: mgr.plan_zip(path, hint), planned, _("Prüfe Zip …"))
                return False
            run_in_thread(lambda: mgr.wait_for_download(since, cancel=cancel, folders=folders), done)
        step(0)

    # ------------------------------------------------------------ Neues Addon
    def on_new_addon(self, *_a, query=""):
        if not self.mgr.addons_dir:
            return
        try:
            from wfa_newaddon import NewAddonDialog
        except ImportError as e:
            message(self.win, _("Dialog nicht verfügbar"), _("wfa_newaddon fehlt: {error}").format(error=e), Gtk.MessageType.ERROR)
            return
        d = NewAddonDialog(self.win, self.mgr, query=query)
        r = d.run()
        if r == Gtk.ResponseType.OK:
            d.finish()
        result = d.result if r == Gtk.ResponseType.OK else None
        d.destroy()
        if result:
            self.handle_new(*result)

    def handle_new(self, kind, value):
        mgr = self.mgr
        if kind == "cand":
            self.install_flow([(value.name, lambda: mgr.plan_candidate(value), value)])
        elif kind == "zip":
            self.install_flow([(value.name, lambda: mgr.plan_zip(value), None)])
        elif kind == "browser":
            self.browser_flow(url=mgr.browser_url(query=value))
        elif kind == "input":
            def done(res, err):
                if isinstance(err, ApiError) and err.kind == "download" and value.lower().startswith("http"):
                    if ask(self.win, _("Download fehlgeschlagen"), _("{error}\n\nDatei stattdessen im Browser herunterladen?").format(error=err),
                           _("Im Browser laden")):
                        self.browser_flow(url=value)
                elif err:
                    message(self.win, _("Eingabe nicht verarbeitbar"), err_text(err), Gtk.MessageType.WARNING)
                elif isinstance(res, list):
                    if len(res) == 1:
                        self.install_flow([(res[0].name, lambda: mgr.plan_candidate(res[0]), res[0])])
                    else:
                        message(self.win, _("Nichts Eindeutiges gefunden"),
                                _("Für Suchbegriffe bitte den Tab „Suchen“ verwenden."))
                else:
                    self.confirm_and_apply([res])
            self.bg(lambda: mgr.resolve_input(value), done, _("Prüfe Eingabe …"))

    # ------------------------------------------------------------ Erweiterte Funktionen
    def apply_expert(self):
        on = bool(self.mgr.cfg["expert"])
        self.expert_item.set_visible(on)
        if on:
            self.expert_item.show_all()

    def _expert(self, name):
        try:
            import wfa_expert
        except ImportError as e:
            message(self.win, _("Dialog nicht verfügbar"), _("wfa_expert fehlt: {error}").format(error=e), Gtk.MessageType.ERROR)
            return
        getattr(wfa_expert, name)(self)

    def on_expert_chars(self, *_a):
        self._expert("open_characters")

    def on_expert_cleanup(self, *_a):
        self._expert("open_cleanup")

    def on_expert_snapshots(self, *_a):
        self._expert("open_snapshots")

    def on_expert_errors(self, *_a):
        self._expert("open_errors")

    # ------------------------------------------------------------ Backups
    def on_backups(self, *_a):
        entries = [(b.created, b, ", ".join(b.folders)) for b in self.mgr.list_backups()]
        entries += [(v.created, v, ngettext("Einstellungen (SavedVariables) vom {date} – 1 Addon",
                                            "Einstellungen (SavedVariables) vom {date} – {n} Addons",
                                            len(v.addons)).format(date=fmt_time(v.created), n=len(v.addons)))
                    for v in self.mgr.list_sv_backups()]
        entries.sort(key=lambda e: e[0], reverse=True)
        d = make_dialog(_("Backups"), self.win, 560, 380)
        d.add_button(_("Schließen"), Gtk.ResponseType.CLOSE)
        rb = add_button(d, _("Wiederherstellen"), Gtk.ResponseType.OK, destructive=True)
        rb.set_sensitive(False)
        store = Gtk.ListStore(object, str, str)
        for created, obj, text in entries:
            store.append([obj, fmt_time(created), text])
        tree = Gtk.TreeView(model=store)
        for i, t in enumerate((_("Datum"), _("Ordner"))):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(t, r, text=i + 1)
            c.set_expand(i == 1)
            tree.append_column(c)
        tree.get_selection().connect("changed", lambda s: rb.set_sensitive(s.get_selected()[1] is not None))
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tree)
        self.pack_install_line(d.get_content_area())
        if entries:
            d.get_content_area().pack_start(sw, True, True, 0)
        else:
            d.get_content_area().pack_start(Gtk.Label(label=_("Noch keine Backups vorhanden.")), True, True, 0)
        d.show_all()
        chosen = None
        if d.run() == Gtk.ResponseType.OK:
            model, it = tree.get_selection().get_selected()
            chosen = model[it][0] if it else None
        d.destroy()
        if isinstance(chosen, core.SvSet):
            self.restore_sv_flow(chosen)
        elif chosen:
            self.restore_backup_flow(chosen)

    def pack_install_line(self, box):
        """Graue Zeile 'Installation: {name}' ueber Listen, die nur die aktive Installation zeigen (>= 2 Eintraege)."""
        insts = self.mgr.installations()
        cur = next((e for e in insts if e["active"]), None)
        if len(insts) >= 2 and cur:
            lb = Gtk.Label(xalign=0, label=_("Installation: {name}").format(name=cur["name"]))
            lb.get_style_context().add_class("dim-label")
            box.pack_start(lb, False, False, 0)

    def restore_backup_flow(self, chosen, only=None, on_done=None):
        names = [f for f in chosen.folders if only is None or f in only]
        text = _("Die aktuellen Ordner werden vorher selbst gesichert.\n{names}").format(names=", ".join(names))
        if self.mgr.wow_running():
            text = _("Hinweis: WoW scheint zu laufen (heuristisch erkannt). Besser vorher beenden.") + "\n\n" + text
        if not ask(self.win, _("Backup wiederherstellen?"), text, _("Wiederherstellen"), kind=Gtk.MessageType.WARNING):
            return

        def done(res, err):
            if err:
                message(self.win, _("Wiederherstellung fehlgeschlagen"), err_text(err), Gtk.MessageType.ERROR)
            else:
                message(self.win, _("Wiederherstellung abgeschlossen") if res.ok else _("Wiederherstellung fehlgeschlagen"), res.message,
                        Gtk.MessageType.INFO if res.ok else Gtk.MessageType.ERROR)
                if res.ok and on_done:
                    on_done()
            self.rescan()
        self.bg(lambda: self.mgr.restore(chosen, only), done, _("Stelle wieder her …"))

    def restore_sv_flow(self, sset):
        """Einstellungen (SavedVariables) wiederherstellen: ganzer Satz oder einzelne Addons."""
        running = self.mgr.wow_running()
        if running:
            message(self.win, _("WoW läuft"), _("Einstellungen lassen sich nur wiederherstellen, solange WoW beendet ist – "
                                              "sonst überschreibt WoW sie beim Beenden wieder."), Gtk.MessageType.WARNING)
            return
        if running is None and not ask(self.win, _("Ist WoW beendet?"),
                                       _("Im Flatpak kann der Manager nicht sehen, ob WoW läuft. Läuft es noch, "
                                         "überschreibt es die wiederhergestellten Einstellungen beim Beenden wieder."),
                                       _("WoW ist beendet"), kind=Gtk.MessageType.WARNING):
            return
        d = make_dialog(_("Einstellungen wiederherstellen"), self.win, 460, 420)
        d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        add_button(d, _("Wiederherstellen"), Gtk.ResponseType.OK, destructive=True)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(xalign=0, wrap=True, max_width_chars=56,
                                 label=_("Einstellungen vom {date}. Der aktuelle Stand wird vorher "
                                         "selbst gesichert. Nur angehakte Addons werden zurückgeschrieben.").format(
                                     date=fmt_time(sset.created))), False, False, 0)
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        checks = []
        for a in sset.addons:
            c = Gtk.CheckButton(label=a, active=True)
            vb.pack_start(c, False, False, 0)
            checks.append(c)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(vb)
        box.pack_start(sw, True, True, 0)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        picked = [c.get_label() for c in checks if c.get_active()]
        d.destroy()
        if not ok:
            return
        if not picked:
            message(self.win, _("Nichts ausgewählt"), _("Es ist kein Addon angehakt."))
            return

        def done(res, err):
            if err:
                message(self.win, _("Wiederherstellung fehlgeschlagen"), err_text(err), Gtk.MessageType.ERROR)
                return
            self.log(_("Einstellungen: {message}").format(message=res.message))
            message(self.win, _("Einstellungen wiederhergestellt") if res.ok else _("Wiederherstellung fehlgeschlagen"),
                    res.message, Gtk.MessageType.INFO if res.ok else Gtk.MessageType.ERROR)
        self.bg(lambda: self.mgr.restore_sv(sset, None if len(picked) == len(sset.addons) else picked),
                done, _("Stelle Einstellungen wieder her …"))

    # ------------------------------------------------------------ Verlauf
    def on_history(self, *_a, name=""):
        entries = self.mgr.read_history()
        backups = {b.name: b for b in self.mgr.list_backups()}
        svs = {v.name: v for v in self.mgr.list_sv_backups()}
        d = make_dialog(_("Verlauf"), self.win, 720, 460)
        d.add_button(_("Schließen"), Gtk.ResponseType.CLOSE)
        rs = add_button(d, _("Einstellungen zurücksetzen"), 2)
        rb = add_button(d, _("Zurücksetzen"), 1, destructive=True)
        rs.set_sensitive(False)
        rb.set_sensitive(False)
        box = d.get_content_area()
        self.pack_install_line(box)
        search = Gtk.SearchEntry(placeholder_text=_("Nach Addon filtern …"), text=name)
        box.pack_start(search, False, False, 0)
        store = Gtk.ListStore(object, str, str, str, str)
        for e in entries:
            try:
                t = time.mktime(time.strptime(str(e.get("ts", "")), "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, OverflowError):
                t = 0
            old, new = e.get("old"), e.get("new")
            ver = "{} → {}".format(old or "–", new or "–") if (old or new) else ""
            kind = str(e.get("kind") or "")
            store.append([e, fmt_time(t) if t else "?", _(kind) if kind else "", str(e.get("name") or ""), str(ver)])
        flt = store.filter_new()

        def visible(model, it, _d):
            q = search.get_text().strip().lower()
            e = model[it][0]
            return not q or q in str(e.get("name") or "").lower() or q in str(e.get("key") or "").lower()
        flt.set_visible_func(visible)
        tree = Gtk.TreeView(model=flt)
        for i, t in enumerate((_("Zeitpunkt"), _("Aktion"), _("Addon"), _("Version"))):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(t, r, text=i + 1)
            c.set_expand(i == 2)
            tree.append_column(c)

        def sel_changed(sel):
            model, it = sel.get_selected()
            e = model[it][0] if it else {}
            rb.set_sensitive(e.get("backup") in backups)
            rs.set_sensitive(e.get("sv") in svs)
        tree.get_selection().connect("changed", sel_changed)
        search.connect("search-changed", lambda *_a: flt.refilter())
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tree)
        if entries:
            box.pack_start(sw, True, True, 0)
        else:
            box.pack_start(Gtk.Label(label=_("Noch keine Änderungen protokolliert.")), True, True, 0)
        d.show_all()
        resp = d.run()
        model, it = tree.get_selection().get_selected()
        e = model[it][0] if it else None
        d.destroy()
        if e and resp == 1 and e.get("backup") in backups:
            fl = e.get("folders")
            self.restore_backup_flow(backups[e["backup"]], [f for f in fl if isinstance(f, str)] if isinstance(fl, list) else None)
        elif e and resp == 2 and e.get("sv") in svs:
            self.restore_sv_flow(svs[e["sv"]])

    # ------------------------------------------------------------ Addon-Liste exportieren / importieren
    def on_export(self, *_a):
        data = self.mgr.export_data(self.pkgs)
        n, lost = len(data["packages"]), data["untransferable"]
        info = ngettext("1 Addon in der Liste.", "{n} Addons in der Liste.", n).format(n=n)
        if not self.mgr.api_key:
            info += "\n" + _("Hinweis: Ohne CurseForge-Key sind Namen und Zuordnungen evtl. unvollständig.")
        if not n:
            info += "\n" + _("Keine übertragbaren Addons (CurseForge-/GitHub-Zuordnung fehlt).")
        if lost:
            info += "\n" + _("Nicht übertragbar (keine CurseForge-/GitHub-Quelle): {names}").format(names=", ".join(lost))
        d = make_dialog(_("Addon-Liste exportieren"), self.win, 480)
        d.add_button(_("Schließen"), Gtk.ResponseType.CLOSE)
        add_button(d, _("Als Text kopieren"), 2)
        add_button(d, _("Als Datei speichern …"), 1, suggested=True)
        lb = Gtk.Label(label=info, xalign=0, wrap=True)
        done = Gtk.Label(label="", xalign=0, wrap=True)
        done.get_style_context().add_class("wfa-dim")
        d.get_content_area().pack_start(lb, False, False, 0)
        d.get_content_area().pack_start(done, False, False, 0)
        d.show_all()
        while True:
            r = d.run()
            if r == 2:
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(core.export_text(data), -1)
                done.set_text(_("Als Text in die Zwischenablage kopiert."))
                self.log(_("Addon-Liste ({n}) als Text kopiert").format(n=n))
            elif r == 1:
                path = choose_file(d, _("Addon-Liste speichern"), Gtk.FileChooserAction.SAVE, _("Speichern"),
                                   name="wow-forever-addons.json")
                if path:
                    try:
                        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
                        done.set_text(_("Gespeichert: {path}").format(path=short_path(path)))
                        self.log(_("Addon-Liste ({n}) gespeichert: {path}").format(n=n, path=short_path(path)))
                    except OSError as e:
                        message(d, _("Speichern fehlgeschlagen"), str(e), Gtk.MessageType.ERROR)
            else:
                break
        d.destroy()

    def on_import(self, *_a):
        if not self.mgr.addons_dir:
            return
        d = make_dialog(_("Addon-Liste importieren"), self.win, 560, 360)
        d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        add_button(d, _("Weiter"), Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(label=_("Liste einfügen (Text oder JSON) oder eine Datei laden:"), xalign=0), False, False, 0)
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.CHAR, monospace=True)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)
        fb = Gtk.Button(label=_("Datei laden …"), halign=Gtk.Align.START)

        def load_file(*_a):
            path = choose_file(d, _("Addon-Liste wählen"), Gtk.FileChooserAction.OPEN, _("Öffnen"))
            if path:
                try:
                    with open(path, encoding="utf-8-sig") as f:
                        tv.get_buffer().set_text(f.read(1_000_000))
                except (OSError, UnicodeDecodeError) as e:
                    message(d, _("Datei nicht lesbar"), str(e), Gtk.MessageType.ERROR)
        fb.connect("clicked", load_file)
        box.pack_start(fb, False, False, 0)
        d.show_all()
        while True:
            if d.run() != Gtk.ResponseType.OK:
                d.destroy()
                return
            buf = tv.get_buffer()
            try:
                entries = core.parse_import(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))
                break
            except ApiError as e:
                message(d, _("Liste nicht lesbar"), str(e), Gtk.MessageType.WARNING)
        d.destroy()
        self.bg(lambda: self.mgr.import_preview(entries), self.import_preview, _("Prüfe Liste …"))

    def import_preview(self, items, err):
        if err or not items:
            message(self.win, _("Liste nicht prüfbar"), err_text(err) if err else _("Die Liste enthält keine Addons."),
                    Gtk.MessageType.WARNING)
            return
        d = make_dialog(_("Addon-Liste importieren"), self.win, 520, 420)
        d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        add_button(d, _("Installieren"), Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(label=_("Diese Addons installieren:"), xalign=0), False, False, 0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        checks = []
        for it in items:
            ch = "  [{}]".format(it["channel"]) if it.get("channel") else ""
            cb = Gtk.CheckButton(label=("{}  ({})".format(it["name"], it["source"]) if it["name"] != it["source"] else it["name"]) + ch
                                 + (_("  – schon installiert") if it["installed"] else ""),
                                 active=not it["installed"], sensitive=not it["installed"])
            checks.append((cb, it))
            inner.pack_start(cb, False, False, 0)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(inner)
        box.pack_start(sw, True, True, 0)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        chosen = [it for cb, it in checks if cb.get_active()]
        d.destroy()
        if not ok or not chosen:
            return
        mgr = self.mgr
        planners = [(it["name"], (lambda it=it: mgr.plan_candidate(mgr.import_candidate(it), it.get("channel"))), None)
                    for it in chosen]

        def fin(col):
            self.show_summary(col)
            self.rescan()
        self.install_flow(planners, finish=fin)

    # ------------------------------------------------------------ Einstellungen u. a.
    def on_settings(self, *_a, focus=None):
        m = self.mgr
        d = make_dialog(_("Einstellungen"), self.win, 760, 540)
        d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        add_button(d, _("Speichern"), Gtk.ResponseType.OK, suggested=True)
        stack = Gtk.Stack(hexpand=True, vexpand=True)
        side = Gtk.StackSidebar(stack=stack, vexpand=True)
        side.set_size_request(170, -1)
        body = Gtk.Box(spacing=12)
        body.pack_start(side, False, False, 0)
        body.pack_start(stack, True, True, 0)
        d.get_content_area().pack_start(body, True, True, 0)

        def page(name, title):
            sc = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
            sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_end=12, margin_bottom=8)
            sc.add(b)
            stack.add_titled(sc, name, title)
            return b

        def section(box, text, top=14):
            box.pack_start(Gtk.Label(xalign=0, use_markup=True, margin_top=top,
                                     label="<b>{}</b>".format(GLib.markup_escape_text(text))), False, False, 0)

        def note(box, text, markup=False):
            lb = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=64, margin_start=26)
            lb.set_markup(text) if markup else lb.set_text(text)
            lb.get_style_context().add_class("dim-label")
            box.pack_start(lb, False, False, 0)
            return lb

        def check(box, label, active, sens=True, hint=None):
            c = Gtk.CheckButton(label=label)
            c.set_active(bool(active))
            c.set_sensitive(sens)
            box.pack_start(c, False, False, 0)
            if hint:
                note(box, hint)
            return c

        def spin_row(box, before, lo, hi, step, value, after):
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Label(label=before), False, False, 0)
            sp = Gtk.SpinButton.new_with_range(lo, hi, step)
            sp.set_value(max(lo, min(hi, int(value or 0))))
            row.pack_start(sp, False, False, 0)
            if after:
                row.pack_start(Gtk.Label(label=after), False, False, 0)
            box.pack_start(row, False, False, 0)
            return sp, row

        # --- Allgemein
        gbox = page("general", _("Allgemein"))
        section(gbox, _("Sprache"), 0)
        lang_row = Gtk.Box(spacing=8)
        lang = Gtk.ComboBoxText()
        for lid, text in (("auto", _("Automatisch")), ("de", "Deutsch"), ("en", "English")):
            lang.append(lid, text)
        lang.set_active_id(m.cfg["language"] if m.cfg["language"] in ("auto", "de", "en") else "auto")
        lang_row.pack_start(lang, False, False, 0)
        lang_hint = Gtk.Label(label=_("Wirkt nach einem Neustart"))
        lang_hint.get_style_context().add_class("dim-label")
        lang_row.pack_start(lang_hint, False, False, 0)
        gbox.pack_start(lang_row, False, False, 0)
        section(gbox, _("Darstellung"))
        classic = check(gbox, _("Klassisches Theme (dunkel, Gold-Akzente)"), m.cfg["classic_theme"])
        expert = check(gbox, _("Erweiterte Funktionen anzeigen"), m.cfg["expert"],
                       hint=_("Blendet im Menü „Erweitert“ ein: Addons je Charakter und Sets, Aufräumen, Fehleranalyse."))
        section(gbox, _("Programm-Updates"))
        su_check = check(gbox, _("Beim Start nach Programm-Updates suchen"), m.cfg["self_update_check"])
        su_auto = check(gbox, _("Programm-Updates automatisch installieren"), m.cfg["self_auto_update"])
        su_check.connect("toggled", lambda c: su_auto.set_sensitive(c.get_active()))
        su_auto.set_sensitive(su_check.get_active())
        if core.managed_install():
            for c in (su_check, su_auto):
                c.set_no_show_all(True)
            note(gbox, _("Programm-Updates kommen über {channel}.").format(channel=core.package_channel()))

        # --- Installationen
        ibox = page("installations", _("Installationen"))
        section(ibox, _("WoW-Installationen"), 0)
        changed = []
        switched = []   # aktive Installation gewechselt
        inst_store = Gtk.ListStore(str, str, str, int)   # Pfad, Name, Ordner, Gewicht
        inst_tree = Gtk.TreeView(model=inst_store)
        for i, t in enumerate((_("Name"), _("Ordner"))):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(t, r, text=i + 1, weight=3)
            c.set_expand(i == 1)
            inst_tree.append_column(c)
        isw = Gtk.ScrolledWindow(hexpand=True, propagate_natural_height=True, max_content_height=240, min_content_height=120)
        isw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        isw.add(inst_tree)
        ibox.pack_start(isw, False, False, 0)
        inst_hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=70)
        irow2 = Gtk.Box(spacing=6)
        b_add = Gtk.Button(label=_("Hinzufügen …"))
        b_ren = Gtk.Button(label=_("Umbenennen …"))
        b_del = Gtk.Button(label=_("Entfernen"))
        b_act = Gtk.Button(label=_("Aktivieren"))
        for b in (b_add, b_ren, b_del, b_act):
            irow2.pack_start(b, False, False, 0)
        ibox.pack_start(irow2, False, False, 0)
        ibox.pack_start(inst_hint, False, False, 0)

        def sel_inst():
            model, it = inst_tree.get_selection().get_selected()
            if not it:
                return None
            return next((e for e in m.installations() if e["path"] == model[it][0]), None)

        def reload_insts(select=None):
            inst_store.clear()
            for e in m.installations():
                inst_store.append([e["path"], e["name"] if e["ok"] else "{} {}".format(e["name"], _("(nicht gefunden)")),
                                   short_path(e["path"]), 700 if e["active"] else 400])
            for row in inst_store:
                if row[0] == select or (select is None and row[3] == 700):
                    inst_tree.get_selection().select_iter(row.iter)
            sync_btns()

        def sync_btns(*_a):
            e = sel_inst()
            b_ren.set_sensitive(e is not None)
            b_act.set_sensitive(bool(e and e["ok"] and not e["active"]))
            b_del.set_sensitive(bool(e and not e["active"]))
            b_del.set_tooltip_text(_("Die aktive Installation kann nicht entfernt werden.") if e and e["active"] else None)
        inst_tree.get_selection().connect("changed", sync_btns)

        def add_inst(*_a):
            pth = choose_addons_dir(m, d, pick_only=True)
            if not pth:
                return
            had = bool(m.addons_dir)
            ok, h = m.add_installation(pth)
            inst_hint.set_markup(colored(ORANGE, h) if h and not ok else "")
            if ok and not had and not self.busy:
                ok2, h2 = m.switch_installation(pth)
                if ok2:
                    changed.append(True)
                    switched.append(True)
            if ok:
                self.update_subtitle()
            reload_insts(pth if ok else None)

        def rename_inst(*_a):
            e = sel_inst()
            if e is None:
                return
            rd = make_dialog(_("Umbenennen"), d, 360)
            rd.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
            add_button(rd, _("Speichern"), Gtk.ResponseType.OK, suggested=True)
            rd.get_content_area().pack_start(Gtk.Label(xalign=0, label=_("Name")), False, False, 0)
            ent = Gtk.Entry(text=e["name"], activates_default=True)
            rd.get_content_area().pack_start(ent, False, False, 0)
            rd.set_default_response(Gtk.ResponseType.OK)
            rd.show_all()
            if rd.run() == Gtk.ResponseType.OK and ent.get_text().strip():
                m.rename_installation(e["path"], ent.get_text())
                changed.append(True)
                self.update_subtitle()
            rd.destroy()
            reload_insts(e["path"])

        def remove_inst(*_a):
            e = sel_inst()
            if e is None or e["active"]:
                return
            if ask(d, _("Installation „{name}“ aus der Liste entfernen?").format(name=e["name"]),
                   _("Es werden keine Dateien gelöscht. Backups und Gesamtstände dieser Installation bleiben erhalten."),
                   _("Entfernen"), kind=Gtk.MessageType.WARNING):
                m.remove_installation(e["path"])
                self.update_subtitle()
                reload_insts()

        def activate_inst(*_a):
            e = sel_inst()
            if e is None or e["active"]:
                return
            if self.busy:
                inst_hint.set_markup(colored(ORANGE, _("Es läuft gerade ein Vorgang. Bitte warten, bis er fertig ist.")))
                return
            ok, h = m.switch_installation(e["path"])
            if ok:
                changed.append(True)
                switched.append(True)
                self.update_subtitle()
                inst_hint.set_text("")
            else:
                inst_hint.set_markup(colored(ORANGE, h))
            reload_insts(e["path"] if not ok else None)
        b_add.connect("clicked", add_inst)
        b_ren.connect("clicked", rename_inst)
        b_del.connect("clicked", remove_inst)
        b_act.connect("clicked", activate_inst)
        reload_insts()
        section(ibox, _("Download-Ordner"))
        note(ibox, _("Hier sucht das Programm nach Addon-Dateien, die du im Browser heruntergeladen hast."))
        dl_label = Gtk.Label(xalign=0, selectable=True, wrap=True, max_width_chars=60, margin_start=26,
                             label=m.download_summary())
        ibox.pack_start(dl_label, False, False, 0)
        drow = Gtk.Box(spacing=6, margin_start=26)

        def pick_dl(*_a):
            f = choose_folder(d, _("Download-Ordner wählen"))
            if f:
                m.set_download_dir(f)
                dl_label.set_text(m.download_summary())

        def auto_dl(*_a):
            m.set_download_dir(None)
            dl_label.set_text(m.download_summary())
        b2 = Gtk.Button(label=_("Ordner wählen …"))
        b2.connect("clicked", pick_dl)
        b3 = Gtk.Button(label=_("Automatisch (aus Browser)"))
        b3.connect("clicked", auto_dl)
        drow.pack_start(b2, False, False, 0)
        drow.pack_start(b3, False, False, 0)
        ibox.pack_start(drow, False, False, 0)

        # --- Addons
        abox = page("addons", _("Addons"))
        section(abox, _("CurseForge-API-Key"), 0)
        key = Gtk.Entry(visibility=False, hexpand=True)
        current = m.cfg["curseforge_api_key"]
        key.set_placeholder_text(core.mask(current) if current else _("Key einfügen …"))
        key.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
        key.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, _("Eingabe anzeigen"))
        key.connect("icon-press", lambda e, *_a: e.set_visibility(not e.get_visibility()))
        abox.pack_start(key, False, False, 0)
        link = Gtk.LinkButton.new_with_label(core.CF_KEY_URL, _("Kostenlosen Key erzeugen (console.curseforge.com)"))
        link.set_halign(Gtk.Align.START)
        abox.pack_start(link, False, False, 0)
        clear = check(abox, _("Gespeicherten Key löschen"), False, bool(current))
        clear.connect("toggled", lambda c: key.set_sensitive(not c.get_active()))
        section(abox, _("Downloads"))
        beta = check(abox, _("Beta-Versionen anzeigen"), m.cfg["include_beta"])
        direct = check(abox, _("Direkt-Download für Addons ohne API-Freigabe"), m.cfg["direct_download"])
        section(abox, _("Hinweise"))
        stale, _r = spin_row(abox, _("Hinweis „lange kein Update“ nach"), 0, 720, 30, m.cfg["stale_days"],
                             _("Tagen (0 = aus)"))

        # --- Sicherungen
        sbox = page("backups", _("Sicherungen"))
        section(sbox, _("Addon-Einstellungen"), 0)
        sv = check(sbox, _("Vor Updates die Addon-Einstellungen (SavedVariables) sichern"), m.cfg["sv_backup"])
        section(sbox, _("Automatische Gesamtstände"))
        arow = Gtk.Box(spacing=8)
        snap_min = int(m.cfg["auto_snapshot_min"] or 0)
        snap_on = Gtk.CheckButton(label=_("Vor Updates automatisch sichern, ab"), active=snap_min > 0)
        snap_n = Gtk.SpinButton.new_with_range(2, 50, 1)
        snap_n.set_value(max(2, min(50, snap_min or 5)))
        snap_n.set_sensitive(snap_min > 0)
        snap_on.connect("toggled", lambda c: snap_n.set_sensitive(c.get_active()))
        arow.pack_start(snap_on, False, False, 0)
        arow.pack_start(snap_n, False, False, 0)
        arow.pack_start(Gtk.Label(label=_("Addons")), False, False, 0)
        sbox.pack_start(arow, False, False, 0)
        snap_client = check(sbox, _("Bei neuer WoW-Version automatisch sichern"), m.cfg["auto_snapshot_client"])
        note(sbox, _("Es bleiben die letzten 2 automatischen Stände; eigene Stände werden nie verdrängt. "
                     "Wiederherstellen: ☰ → Gesamtstände."))

        # --- Hintergrund
        bbox = page("background", _("Hintergrund"))
        section(bbox, _("Tray"), 0)
        bgd = self.background
        if bgd is None or not bgd.available:
            hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=64, use_markup=True,
                             label=colored(ORANGE, _("Kein Tray verfügbar (kein StatusNotifier-Host gefunden). "
                                                     "Das Schließen des Fensters beendet dann das Programm.")))
            bbox.pack_start(hint, False, False, 0)
        autostart_on = bool(m.cfg["autostart_portal"]) if core.in_flatpak() else core.autostart_enabled()
        autostart = check(bbox, _("Beim Systemstart im Tray starten"), autostart_on)
        to_tray = check(bbox, _("Fenster schließen minimiert in den Tray"), m.cfg["close_to_tray"])
        section(bbox, _("Update-Prüfung"))
        spin, _r = spin_row(bbox, _("Prüfintervall (Minuten)"), 15, 1440, 5, m.cfg["check_interval_min"], None)
        auto = check(bbox, _("Updates automatisch installieren (nur wenn WoW nicht läuft)"), m.cfg["auto_update"])
        if core.in_flatpak() and not core.host_spawn_available():
            note(bbox, _("Im Flatpak ist nicht erkennbar, ob WoW läuft; Updates werden deshalb nur gemeldet, "
                         "nicht still installiert. Erkennung freigeben (erlaubt dem Programm, Befehle "
                         "außerhalb der Sandbox zu starten):\n{command}").format(command=core.WOW_DETECT_OVERRIDE))
        section(bbox, _("Updates vor dem Spielstart"))
        note(bbox, _("Steam, Lutris oder Heroic können Addons vor jedem Spielstart aktualisieren."))
        pre = Gtk.Button(label=_("Updates vor dem Spielstart …"), halign=Gtk.Align.START, margin_start=26)
        pre.connect("clicked", lambda *_a: self.on_prelaunch_info(d))
        bbox.pack_start(pre, False, False, 0)
        d.show_all()
        if focus:
            stack.set_visible_child_name(focus)
            if focus == "installations":
                inst_tree.grab_focus()
        if d.run() == Gtk.ResponseType.OK:
            old_interval = m.cfg["check_interval_min"]
            new = dict(classic_theme=classic.get_active(), direct_download=direct.get_active(),
                       close_to_tray=to_tray.get_active(), check_interval_min=int(spin.get_value()),
                       auto_update=auto.get_active(), sv_backup=sv.get_active(), self_update_check=su_check.get_active(),
                       self_auto_update=su_auto.get_active(), expert=expert.get_active(),
                       language=lang.get_active_id() or "auto", stale_days=int(stale.get_value()),
                       auto_snapshot_min=int(snap_n.get_value()) if snap_on.get_active() else 0,
                       auto_snapshot_client=snap_client.get_active())
            theme_changed = new["classic_theme"] != bool(m.cfg["classic_theme"])
            stale_changed = new["stale_days"] != m.cfg["stale_days"]
            with m.cfg.lock:
                for k, v in new.items():
                    m.cfg[k] = v
                m.cfg.save()
            if theme_changed:
                self.set_theme(new["classic_theme"])
            self.apply_expert()
            if stale_changed and self.pkgs and not changed:
                self.update_health(self.pkgs, wfa_health.assess(self.pkgs, m.cfg, m.client_interface), self.conflicts)
                for p in self.pkgs:
                    self.refresh_row(p)
            if autostart.get_active() != autostart_on:
                self.set_autostart(autostart.get_active(), d)
            if clear.get_active():
                m.set_cf_key("")
            elif key.get_text().strip():
                m.set_cf_key(key.get_text())
            m.set_include_beta(beta.get_active())
            if self.background is not None and new["check_interval_min"] != old_interval:
                try:
                    self.background.reschedule()
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
            changed.append(True)
        d.destroy()
        if switched:
            self.after_switch()
        elif changed:
            self.update_subtitle()
            self.rescan()

    def on_prelaunch_info(self, parent=None):
        """Erklaerdialog: Updates vor dem Spielstart (Steam/Lutris/Heroic), Startskript speichern."""
        import wfa_unattended
        flat = core.in_flatpak()
        cmd = wfa_unattended.launch_command()
        d = make_dialog(_("Updates vor dem Spielstart"), parent or self.win, 620)
        add_button(d, _("Schließen"), Gtk.ResponseType.CLOSE, suggested=True)
        box = d.get_content_area()
        status = Gtk.Label(xalign=0)
        status.get_style_context().add_class("dim-label")

        def para(text, dim=False, bold=False):
            lb = Gtk.Label(xalign=0, wrap=True, max_width_chars=80, label=text)
            if bold:
                lb.set_markup("<b>{}</b>".format(GLib.markup_escape_text(text)))
            if dim:
                lb.get_style_context().add_class("dim-label")
            box.pack_start(lb, False, False, 0)
            return lb

        def command(text):
            row = Gtk.Box(spacing=6)
            lb = Gtk.Label(xalign=0, selectable=True, wrap=True, max_width_chars=60)
            lb.set_markup("<tt>{}</tt>".format(GLib.markup_escape_text(text)))
            row.pack_start(lb, True, True, 0)
            b = Gtk.Button(label=_("Kopieren"))

            def copy(*_a):
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
                status.set_text(_("Kopiert."))
            b.connect("clicked", copy)
            row.pack_start(b, False, False, 0)
            box.pack_start(row, False, False, 0)
        if not self.mgr.addons_dir:
            box.pack_start(Gtk.Label(xalign=0, use_markup=True, label=colored(ORANGE, _("Erst einen AddOns-Ordner einrichten."))),
                           False, False, 0)
        para(_("Der Manager kann Addons aktualisieren, bevor WoW startet. Dazu ruft der Launcher ihn vor dem Spiel auf. "
               "Läuft WoW schon oder fehlt das Netz, startet das Spiel trotzdem."))
        para(_("Steam"), bold=True)
        para(_("Bibliothek → WoW → Eigenschaften → Startoptionen:"))
        command(cmd + (" --update --quiet ; %command%" if flat else " --update --quiet --run %command%"))
        if flat:
            para(_("Im Flatpak kann der Manager das Spiel nicht selbst starten, deshalb ohne --run."), dim=True)
        para(_("Lutris"), bold=True)
        para(_("Spiel konfigurieren → Systemoptionen → „Pre-launch script“ auf das Startskript setzen und "
               "„Wait for pre-launch script completion“ einschalten."))
        para(_("Heroic"), bold=True)
        para(_("Spieleinstellungen → Erweitert → Skript vor dem Start: das Startskript wählen."))
        save = Gtk.Button(label=_("Startskript speichern …"), halign=Gtk.Align.START)

        def save_script(*_a):
            f = choose_file(d, _("Startskript speichern"), Gtk.FileChooserAction.SAVE, _("Speichern"), name="wfa-vor-dem-start.sh")
            if not f:
                return
            try:
                wfa_unattended.write_prelaunch_script(f)
            except OSError as e:
                message(d, _("Speichern fehlgeschlagen"), str(e), Gtk.MessageType.ERROR)
                return
            status.set_text(_("Gespeichert: {path}").format(path=f))
        save.connect("clicked", save_script)
        box.pack_start(save, False, False, 0)
        para(_("Die Menünamen können je nach Launcher-Version abweichen. Ergebnis jedes Laufs: ☰ → Verlauf."), dim=True)
        box.pack_start(status, False, False, 0)
        d.show_all()
        d.run()
        d.destroy()

    def set_autostart(self, on, parent=None):
        if not core.in_flatpak():
            try:
                core.set_autostart(on)
            except OSError as e:
                message(parent or self.win, _("Autostart fehlgeschlagen"), str(e), Gtk.MessageType.ERROR)
            return
        import wfa_portal

        def done(ok, text):
            if ok:
                with self.mgr.cfg.lock:
                    self.mgr.cfg["autostart_portal"] = bool(on)
                    self.mgr.cfg.save()
                self.log(_("Autostart eingerichtet.") if on else _("Autostart entfernt."))
            else:
                self.log(_("Autostart: {text}").format(text=text))
                message(self.win, _("Autostart fehlgeschlagen"), text, Gtk.MessageType.ERROR)
        wfa_portal.request_autostart(on, done)

    def set_theme(self, on):
        marked = {r[C_KEY] for r in self.store if r[C_CHECK]}
        apply_theme(on)
        self.render(marked)

    def on_desktop_entry(self, *_a):
        try:
            p = core.install_desktop_entry()
        except OSError as e:
            message(self.win, _("Startmenü-Eintrag fehlgeschlagen"), str(e), Gtk.MessageType.ERROR)
            return
        message(self.win, _("Startmenü-Eintrag angelegt"), short_path(p))

    def on_changelog(self, *_a):
        """Changelog des Managers (CHANGELOG.md) mit einfacher Markdown-Darstellung."""
        try:
            text = core.changelog_path().read_text("utf-8")
        except OSError:
            text = None
        d = make_dialog(_("Neuigkeiten"), self.win, 720, 560)
        add_button(d, _("Schließen"), Gtk.ResponseType.CLOSE, suggested=True)
        box = d.get_content_area()
        if text is None:
            box.pack_start(Gtk.Label(xalign=0, wrap=True, label=_("Der Changelog liegt dieser Installation nicht bei.")), False, False, 0)
            link = Gtk.LinkButton.new_with_label(REPO_URL + "/releases", _("Versionshinweise auf GitHub"))
            link.set_halign(Gtk.Align.START)
            box.pack_start(link, False, False, 0)
        else:
            sw = text_view_scroller("", 680, 460)
            tv = sw.get_child()
            tv.set_left_margin(12)
            tv.set_right_margin(12)
            buf = tv.get_buffer()
            tags = {"h2": buf.create_tag("h2", weight=Pango.Weight.BOLD, scale=1.35, pixels_above_lines=14, pixels_below_lines=4),
                    "h3": buf.create_tag("h3", weight=Pango.Weight.BOLD, scale=1.1, pixels_above_lines=8, pixels_below_lines=2),
                    "b": buf.create_tag("b", weight=Pango.Weight.BOLD),
                    "code": buf.create_tag("code", family="monospace"),
                    "li": buf.create_tag("li", left_margin=30, indent=-14, pixels_below_lines=3),
                    "li2": buf.create_tag("li2", left_margin=50, indent=-14, pixels_below_lines=2)}
            inline = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
            lines = text.splitlines()
            start = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), 0)   # Vorspann weglassen
            for ln in lines[start:]:
                end = buf.get_end_iter
                if ln.startswith("## "):
                    buf.insert_with_tags(end(), ln[3:] + "\n", tags["h2"])
                    continue
                if ln.startswith("### "):
                    buf.insert_with_tags(end(), ln[4:] + "\n", tags["h3"])
                    continue
                if not ln.strip():
                    continue
                m = re.match(r"(\s*)- (.*)", ln)
                block = []
                if m:
                    block = [tags["li2" if m.group(1) else "li"]]
                    buf.insert_with_tags(end(), ("◦ " if m.group(1) else "• "), *block)
                    ln = m.group(2)
                for part in inline.split(ln):
                    if part.startswith("**") and part.endswith("**") and len(part) > 4:
                        buf.insert_with_tags(end(), part[2:-2], tags["b"], *block)
                    elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                        buf.insert_with_tags(end(), part[1:-1], tags["code"], *block)
                    elif part:
                        buf.insert_with_tags(end(), part, *block) if block else buf.insert(end(), part)
                buf.insert_with_tags(end(), "\n", *block) if block else buf.insert(end(), "\n")
            buf.place_cursor(buf.get_start_iter())
            box.pack_start(sw, True, True, 0)
        d.show_all()
        d.run()
        d.destroy()

    def on_about(self, *_a):
        d = Gtk.AboutDialog(transient_for=self.win, modal=True, program_name=TITLE, version=core.__version__,
                            comments=_("Inoffizieller Addon-Manager für WoW: Forever unter Linux.\n"
                                       "Nicht mit Blizzard oder CurseForge verbunden."),
                            website=REPO_URL, license_type=Gtk.License.MIT_X11, copyright="© 2026 m3rtl")
        logo = load_icon(96)
        if logo:
            d.set_logo(logo)
        d.run()
        d.destroy()

    # ------------------------------------------------------------ Hintergrund und Programm-Updates
    def start_background(self, initial_check):
        try:
            from wfa_background import Background
        except ImportError as e:
            print(f"Kein Tray-Betrieb (wfa_background fehlt: {e})", file=sys.stderr)
            return None
        try:
            self.background = Background(self)
            self.background.start(initial_check)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self.background = None
        return self.background

    @staticmethod
    def selfupdate_module():
        try:
            import wfa_selfupdate
            return wfa_selfupdate
        except ImportError:
            return None

    def check_self_update(self, manual=False):
        su = self.selfupdate_module()
        if su is None or not su.enabled():
            if manual:
                message(self.win, _("Nicht verfügbar"), _("Programm-Updates kommen über {channel}.").format(channel=core.package_channel())
                        if su is not None else _("Die Programm-Updates sind in dieser Version nicht enthalten."))
            return

        def done(rel, err):
            if err:
                self.log(_("Programm-Update-Prüfung fehlgeschlagen: {error}").format(error=err_text(err)))
                if manual:
                    message(self.win, _("Prüfung fehlgeschlagen"), err_text(err), Gtk.MessageType.ERROR)
            elif rel:
                self.on_self_update_available(rel, manual)
                if manual:
                    self.self_update(rel, True)
            elif manual:
                message(self.win, _("Kein Update"), _("Du nutzt die aktuelle Version ({version}).").format(version=core.__version__))
            return False
        run_in_thread(su.check, done)

    def on_self_update_available(self, rel, force=False):
        if not force and rel.version == self.mgr.cfg["self_update_skipped"]:
            return
        self.self_rel = rel
        self.show_infobar(_("Version {version} des Addon-Managers ist verfügbar.").format(version=rel.version),
                          [(_("Aktualisieren"), 1, True), (_("Details"), 2, False), (_("Überspringen"), 3, False)],
                          lambda r: self.on_infobar(rel, r))

    def on_infobar(self, rel, r):
        if r == 1:
            self.self_install(rel, True)
        elif r == 2:
            self.self_update(rel, False)
        elif r == 3:
            with self.mgr.cfg.lock:
                self.mgr.cfg["self_update_skipped"] = rel.version
                self.mgr.cfg.save()
            self.show_infobar(None)
        elif r == 4:
            self.restart_self()

    def show_infobar(self, text, buttons=(), on_response=None, closable=False):
        for c in self.infobar_holder.get_children():
            c.destroy()
        if text is None:
            return
        ib = Gtk.InfoBar(message_type=Gtk.MessageType.INFO)
        ib.get_content_area().add(Gtk.Label(label=text, xalign=0))
        for label, rid, suggested in buttons:
            b = ib.add_button(label, rid)
            if suggested:
                b.get_style_context().add_class("suggested-action")
        if closable:
            ib.set_show_close_button(True)
        ib.connect("response", lambda _i, r: self.show_infobar(None) if r == Gtk.ResponseType.CLOSE
                   else (on_response(r) if on_response else None))
        self.infobar_holder.pack_start(ib, False, False, 0)
        ib.show_all()

    def self_update(self, rel, interactive=True):
        """Dialog mit Release-Notes; installiert wird nur nach Klick auf den Knopf."""
        su = self.selfupdate_module()
        can = bool(su and su.can_self_update())
        if interactive:
            self.present()
        d = make_dialog(_("Programm-Update {version}").format(version=rel.version), self.win, 600, 420)
        d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        add_button(d, _("Jetzt aktualisieren") if can else _("Release-Seite öffnen"), Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(xalign=0, use_markup=True, wrap=True, label="<b>{}</b>{}".format(
            GLib.markup_escape_text(_("Version {version}").format(version=rel.version)),
            GLib.markup_escape_text(_(" (installiert: {version})").format(version=core.__version__)))), False, False, 0)
        if not can:
            box.pack_start(Gtk.Label(xalign=0, wrap=True, label=_("Dieses Programm läuft nicht als einzelne ausführbare "
                                       "Datei und kann sich nicht selbst ersetzen. Die Release-Seite wird im Browser geöffnet.")),
                           False, False, 0)
        box.pack_start(text_view_scroller(rel.notes or _("(Keine Release-Notes vorhanden.)"), 540, 260), True, True, 0)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        d.destroy()
        if not ok:
            return
        if can:
            self.self_install(rel, True)
        else:
            self.open_uri(rel.page_url or REPO_URL + "/releases")

    def self_install(self, rel, show_progress=True):
        su = self.selfupdate_module()
        if su is None or not su.can_self_update():
            self.open_uri(rel.page_url or REPO_URL + "/releases")
            return
        cancel = threading.Event()
        d = bar = None
        if show_progress:
            d = make_dialog(_("Programm-Update"), self.win, 420)
            d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
            d.connect("response", lambda *_a: cancel.set())
            bar = Gtk.ProgressBar(show_text=True, text=_("Lade Version {version} …").format(version=rel.version))
            d.get_content_area().pack_start(bar, False, False, 6)
            d.show_all()

        def progress(*a, **_k):
            try:
                frac = a[0] / a[1] if len(a) > 1 and a[1] else float(a[0])
            except (TypeError, ValueError, ZeroDivisionError):
                return
            if bar is not None:
                GLib.idle_add(bar.set_fraction, max(0.0, min(1.0, frac)))

        def done(_path, err):
            if d is not None:
                d.destroy()
            if err:
                self.log(_("Programm-Update fehlgeschlagen: {error}").format(error=err_text(err)))
                if not cancel.is_set():
                    message(self.win, _("Programm-Update fehlgeschlagen"), err_text(err), Gtk.MessageType.ERROR)
                return False
            self.log(_("Programm-Update {version} installiert.").format(version=rel.version))
            self.show_infobar(_("Version {version} installiert – Neustart nötig.").format(version=rel.version), [(_("Neu starten"), 4, True)],
                              lambda r: self.restart_self())
            if show_progress and ask(self.win, _("Update installiert"), _("Jetzt neu starten?"), _("Neu starten")):
                self.restart_self()
            return False
        run_in_thread(lambda: su.install(rel, progress=progress, cancel=cancel), done)

    def restart_self(self):
        su = self.selfupdate_module()
        if su is None:
            return
        # Neustart beendet den Prozess: bei laufendem Vorgang erst nachfragen, vorher nichts spawnen
        if self.busy and not self.confirm_quit_busy():
            return
        try:
            cmd = su.restart_command()
            env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
            # Der neue Prozess startet erst nach Ende dieses Prozesses (Application-ID frei), hoechstens 15 s.
            wait = 'i=0; while kill -0 "$0" 2>/dev/null && [ $i -lt 75 ]; do sleep 0.2; i=$((i+1)); done; exec "$@"'
            subprocess.Popen(["sh", "-c", wait, str(os.getpid()), *cmd], env=env, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:  # noqa: BLE001
            message(self.win, _("Neustart fehlgeschlagen"), str(e), Gtk.MessageType.ERROR)
            return
        self.quit(force=True)

    # ------------------------------------------------------------ Screenshot-Modus
    def run_screenshots(self):
        a = self.args
        delay = int(a.screenshot_delay * 1000)

        # Zeiger in die Ecke: steht er ueber einer Liste, oeffnet sich ein Tooltip, der im Bild als
        # schwarze Flaeche landet (unter Xvfb steht der Zeiger anfangs in der Bildschirmmitte).
        with contextlib.suppress(Exception):
            Gdk.Display.get_default().get_default_seat().get_pointer().warp(self.win.get_screen(), 0, 0)

        def save(win, path):
            gw = win.get_window()
            pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
            pb.savev(str(path), "png", [], [])

        def fail(msg):
            print(msg, file=sys.stderr)
            self.exit_code = 1
            self.quit(force=True)
            return False

        def wait_ready(start=time.time()):
            if not self.ready or self.busy:
                return fail("Zeitüberschreitung beim Prüfen.") if time.time() - start > 180 else True
            GLib.timeout_add(delay, shoot_main)
            return False

        def shoot_main():
            save(self.win, a.screenshot)
            if a.screenshot_dialog == "new":
                from wfa_newaddon import NewAddonDialog
                dlg = NewAddonDialog(self.win, self.mgr)
                dlg.connect("response", lambda *_a: None)
                start = time.time()

                def wait_dialog():
                    if getattr(dlg, "featured_loaded", None) is False and time.time() - start < 60:
                        return True
                    GLib.timeout_add(delay, shoot_dialog, dlg)
                    return False
                GLib.timeout_add(200, wait_dialog)
            else:
                self.quit(force=True)
            return False

        def shoot_dialog(dlg):
            save(dlg, Path(a.screenshot).with_name(Path(a.screenshot).stem + "-dialog.png"))
            dlg.destroy()
            self.quit(force=True)
            return False
        GLib.timeout_add(300, wait_ready)


def load_icon(size):
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_size(str(core.asset_path("icon.svg")), size, size)
    except Exception:  # noqa: BLE001
        return None


def main(argv):
    ap = argparse.ArgumentParser(prog="wow-forever-addon-manager", add_help=False)
    ap.add_argument("--screenshot")
    ap.add_argument("--screenshot-delay", type=float, default=1.0)
    ap.add_argument("--screenshot-dialog", choices=["new"])
    ap.add_argument("--tray", action="store_true")
    args, _rest = ap.parse_known_args(argv)

    GLib.set_prgname(core.APP_NAME)
    GLib.set_application_name(TITLE)
    icon = load_icon(128)
    if icon:
        Gtk.Window.set_default_icon(icon)

    flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
    if args.screenshot:
        flags |= Gio.ApplicationFlags.NON_UNIQUE
    gapp = Gtk.Application(application_id=APP_ID, flags=flags)
    try:
        gapp.register(None)
    except GLib.Error:
        gapp = Gtk.Application(application_id=APP_ID, flags=flags | Gio.ApplicationFlags.NON_UNIQUE)
    if gapp.get_is_remote():
        return gapp.run([sys.argv[0]] + list(argv))  # vorhandene Instanz meldet sich

    holder = {}
    mgr = Manager(log=lambda s: holder["app"].log(s) if "app" in holder else None,
                  progress=lambda **kw: holder["app"].on_progress(**kw) if "app" in holder else None)
    register_fonts()
    apply_theme(mgr.cfg["classic_theme"])
    state = {"code": 0}

    def start(tray):
        setup = mgr.needs_setup()
        if setup and not tray:
            if args.screenshot or not choose_addons_dir(mgr):
                state["code"] = 1
                return
        app = holder["app"] = App(mgr, args, gapp)
        gapp.hold()
        gapp.add_window(app.win)
        app.win.connect("delete-event", app.on_delete)
        if args.screenshot:
            app.present()
            app.rescan()
            app.run_screenshots()
            return
        if tray and setup:
            app.present()
            if not choose_addons_dir(mgr, app.win):
                app.quit()
                return
            app.update_subtitle()
            tray = False
        if tray:
            if app.start_background(True) is None:
                app.present()
                app.rescan()

            def fallback():
                if not app.win.get_visible() and not (app.background and app.background.available):
                    app.present()
                    if not app.pkgs:
                        app.rescan()
                return False
            GLib.timeout_add_seconds(30, fallback)
        else:
            app.present()
            app.rescan()
            app.start_background(False)
        if app.background is None and mgr.cfg["self_update_check"] and not core.managed_install():
            app.check_self_update()

    def on_command_line(_gapp, cl):
        a = cl.get_arguments()[1:]
        tray = "--tray" in a
        if "app" not in holder:
            if not state.get("started"):
                state["started"] = True
                start(tray)
                if state["code"]:
                    return state["code"]
        elif not tray:
            holder["app"].present()
        return 0

    gapp.connect("command-line", on_command_line)
    code = gapp.run([sys.argv[0]] + list(argv))
    return state["code"] or (holder["app"].exit_code if "app" in holder else 0) or code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
