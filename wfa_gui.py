"""GTK-3-Oberflaeche fuer den WoW: Forever Addon-Manager."""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
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
from wfa_core import ApiError, Manager  # noqa: E402
from wfa_i18n import _  # noqa: E402

TITLE = "WoW: Forever Addon-Manager"
APP_ID = core.APP_ID
REPO_URL = "https://github.com/m3rtl/wow-forever-addon-manager-linux"
RED, ORANGE, GREY, GREEN = "#e74c3c", "#e67e22", "#8a8a8a", "#2e9e5b"
STATUS_COLOR = {}
SKIP, ABORT = 1, 2  # Antworten des Warte-Dialogs
BANNER_TITLE = "WoW: Forever"
BANNER_SUB = "Addon-Manager für Linux"
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
CHANNEL_NAMES = (("Standard (wie Einstellung)", None), ("Nur Release", "release"), ("Beta", "beta"), ("Alpha", "alpha"))
FOREVER_SHOW = {"ok": "✓", "veraltet": "⚠ veraltet", "nein": "✗"}


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
    st = Gtk.Label(label=BANNER_SUB.upper())
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
    return time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(t))


def message(parent, text, secondary=None, kind=Gtk.MessageType.INFO):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                          buttons=Gtk.ButtonsType.CLOSE, text=text)
    if secondary:
        d.format_secondary_text(secondary)
    d.run()
    d.destroy()


def ask(parent, text, secondary, yes, no="Abbrechen", kind=Gtk.MessageType.QUESTION):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind, text=text)
    d.format_secondary_text(secondary)
    d.add_button(no, Gtk.ResponseType.CANCEL)
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


def err_text(e):
    if isinstance(e, ApiError):
        return str(e)
    return f"Unerwarteter Fehler: {e}"


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
    fc = Gtk.FileChooserNative.new(title, parent, action, accept, "Abbrechen")
    if action == Gtk.FileChooserAction.SAVE:
        fc.set_do_overwrite_confirmation(True)
        if name:
            fc.set_current_name(name)
    for f in filters:
        fc.add_filter(f)
    path = fc.get_filename() if fc.run() == Gtk.ResponseType.ACCEPT else None
    fc.destroy()
    return path


def choose_folder(parent, title="Ordner wählen"):
    return choose_file(parent, title, Gtk.FileChooserAction.SELECT_FOLDER, "Auswählen")


def choose_addons_dir(mgr, parent=None):
    """Dialog zur Auswahl des AddOns-Ordners. -> True, wenn gespeichert."""
    d = make_dialog("AddOns-Ordner wählen", parent, 640)
    d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
    add_button(d, "Übernehmen", Gtk.ResponseType.OK, suggested=True)
    box = d.get_content_area()
    intro = Gtk.Label(xalign=0, wrap=True,
                      label="Wähle den AddOns-Ordner deiner WoW: Forever-Installation (…/_forever_/Interface/AddOns).")
    box.pack_start(intro, False, False, 0)
    if core.in_flatpak():
        txt = ("Flatpak: Freigegeben sind die üblichen Orte von Steam, Lutris, Bottles, Heroic, Wine und ~/Games. "
               "Liegt WoW woanders, wähle mit „Anderen Ordner wählen …“ den Ordner „World of Warcraft“; "
               "er wird dann dauerhaft freigegeben.")
        blocked = core.sandbox_blocked_libraries()
        if blocked:
            txt += ("\n\nNicht freigegebene Steam-Bibliotheken: " + ", ".join(short_path(b) for b in blocked)
                    + "\nFreigeben (danach neu starten): " + "; ".join(core.flatpak_override_cmd(b) for b in blocked))
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
        group.pack_start(Gtk.Label(xalign=0, label="Keine Installation automatisch gefunden."), False, False, 0)
    hint = Gtk.Label(xalign=0, wrap=True)
    other = Gtk.Button(label="Anderen Ordner wählen …", halign=Gtk.Align.START)

    def on_other(_b):
        p = choose_folder(d, "Ordner „World of Warcraft“ oder AddOns-Ordner wählen" if core.in_flatpak()
                          else "AddOns-Ordner wählen")
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
    while d.run() == Gtk.ResponseType.OK:
        sel = next((p for r, p in choices if r.get_active()), None)
        if sel is None:
            hint.set_text("Bitte einen Ordner wählen.")
            continue
        ok, h = mgr.validate_addons_dir(sel)
        if not ok:
            hint.set_text(h)
            continue
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
    return saved


class App:
    def __init__(self, mgr, args, gapp=None):
        self.mgr = mgr
        self.args = args
        self.gapp = gapp
        self.pkgs = []
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
        hb = self.header = Gtk.HeaderBar(show_close_button=True, title=TITLE)
        w.set_titlebar(hb)
        self.refresh_btn = Gtk.Button(tooltip_text="Auf Updates prüfen (F5)")
        self.refresh_stack = Gtk.Stack()
        self.refresh_stack.add_named(Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON), "icon")
        self.refresh_spinner = Gtk.Spinner()
        self.refresh_stack.add_named(self.refresh_spinner, "spin")
        self.refresh_btn.add(self.refresh_stack)
        self.refresh_btn.connect("clicked", lambda *_: self.rescan())
        hb.pack_start(self.refresh_btn)
        ag = Gtk.AccelGroup()
        w.add_accel_group(ag)
        for key, mod in ((Gdk.KEY_F5, 0), (Gdk.KEY_r, Gdk.ModifierType.CONTROL_MASK)):
            ag.connect(key, mod, Gtk.AccelFlags.VISIBLE, lambda *_: (self.refresh_btn.get_sensitive() and self.rescan(), True)[1])
        menu_btn = self.menu_btn = Gtk.MenuButton()
        menu_btn.add(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu = Gtk.Menu()
        managed = core.managed_install()   # Paket/Flatpak: Startmenue-Eintrag und Updates kommen von dort
        for label, cb in (("Protokoll …", self.show_log), ("Backups …", self.on_backups), ("Verlauf …", self.on_history),
                          ("Addon-Liste exportieren …", self.on_export), ("Addon-Liste importieren …", self.on_import),
                          ("Einstellungen …", self.on_settings),
                          *(() if managed else (("Startmenü-Eintrag anlegen", self.on_desktop_entry),
                                                ("Nach Programm-Updates suchen …",
                                                 lambda *_: self.check_self_update(True)))),
                          ("Über", self.on_about), (None, None), ("Beenden", self.on_quit_item)):
            mi = Gtk.SeparatorMenuItem() if label is None else Gtk.MenuItem(label=label)
            if cb:
                mi.connect("activate", cb)
            menu.append(mi)
        # Untermenue "Erweitert": nur bei Einstellung expert sichtbar, siehe apply_expert
        sub = Gtk.Menu()
        for label, cb in ((_("Addons je Charakter …"), self.on_expert_chars), (_("Aufräumen …"), self.on_expert_cleanup),
                          (_("Gesamtstände …"), self.on_expert_snapshots)):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", cb)
            sub.append(mi)
        self.expert_item = Gtk.MenuItem(label=_("Erweitert"), no_show_all=True)
        self.expert_item.set_submenu(sub)
        menu.insert(self.expert_item, 5)   # vor "Einstellungen …"
        menu.show_all()
        self.apply_expert()
        menu_btn.set_popup(menu)
        hb.pack_end(menu_btn)
        hb.show_all()
        self.update_subtitle()

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
        self.key_btn = Gtk.Button(label="Key eintragen …", valign=Gtk.Align.CENTER)
        self.key_btn.connect("clicked", self.on_settings)
        info.pack_end(self.key_btn, False, False, 0)
        outer.pack_start(info, False, False, 0)

        self.store = Gtk.ListStore(*COL_TYPES)
        self.tree = Gtk.TreeView(model=self.store, has_tooltip=True)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self.on_toggled)
        self.tree.append_column(Gtk.TreeViewColumn("", tog, active=C_CHECK, visible=C_CAN, activatable=C_CAN))
        cols = (("Addon", C_NAME, True, 0.0), ("Installiert", C_LOCAL, False, 0.0), ("Verfügbar", C_REMOTE, False, 0.0),
                ("Quelle", C_SOURCE, False, 0.0), ("Forever", C_FOREVER, False, 0.5), ("Status", C_STATUS, False, 0.0))
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
        self.update_btn = Gtk.Button(label="Aktualisieren")
        self.update_btn.get_style_context().add_class("suggested-action")
        self.update_btn.connect("clicked", self.on_update_selected)
        self.mark_btn = Gtk.Button(label="Alle Updates markieren")
        self.mark_btn.connect("clicked", self.on_mark_all)
        self.uninstall_btn = Gtk.Button(label="Deinstallieren …")
        self.uninstall_btn.connect("clicked", self.on_uninstall)
        self.browser_btn = Gtk.Button(label="Im Browser laden …")
        self.browser_btn.connect("clicked", self.on_browser_selected)
        for b in (self.uninstall_btn, self.browser_btn):
            b.get_style_context().add_class("wfa-flat")
        self.new_btn = Gtk.Button(label="Neues Addon …")
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
        self.prog_cancel = Gtk.Button(label="Abbrechen")
        self.prog_cancel.get_style_context().add_class("wfa-flat")
        self.prog_cancel.set_tooltip_text("Bricht die laufenden Downloads ab")
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

    def show_log(self, *_):
        if self.log_win is not None:
            self.log_win.present()
            return
        w = self.log_win = Gtk.Window(title="Protokoll")
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
        cp = Gtk.Button(label="Kopieren")
        cp.connect("clicked", lambda *_: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(
            self.log_buf.get_text(self.log_buf.get_start_iter(), self.log_buf.get_end_iter(), False), -1))
        cl = Gtk.Button(label="Schließen")
        cl.connect("clicked", lambda *_: w.destroy())
        row.pack_end(cl, False, False, 0)
        row.pack_end(cp, False, False, 0)
        box.pack_start(row, False, False, 0)
        w.add(box)

        def gone(*_):
            self.log_win = None
            self.log_view = None
        w.connect("destroy", gone)
        w.show_all()
        GLib.idle_add(lambda: (self.log_view.scroll_to_iter(self.log_buf.get_end_iter(), 0, False, 0, 0), False)[1])

    def update_subtitle(self):
        self.header.set_subtitle(short_path(self.mgr.addons_dir) if self.mgr.addons_dir else "")

    def update_info(self):
        m = self.mgr
        state = m.cf_key_state()
        parts = [f"Client {m.client_version} (Interface {m.client_interface})" if m.client_version
                 else f"Client-Interface {m.client_interface} (aus den Addons geschätzt)"]
        if state == "fehlt":
            parts.append(f'<span foreground="{ORANGE}">CurseForge: kein API-Key – kostenlos unter '
                         f'{GLib.markup_escape_text(core.CF_KEY_URL)} erzeugen.</span>')
        elif state == "ungültig":
            parts.append(f'<span foreground="{RED}">CurseForge: Key ungültig oder abgelehnt.</span>')
        else:
            parts.append(f"CurseForge: Key {state}")
        for n in dict.fromkeys(m.notes):
            parts.append(f'<span foreground="{ORANGE}">{GLib.markup_escape_text(n)}</span>')
        self.info_label.set_markup("  ·  ".join(parts))
        self.key_btn.set_visible(state in ("fehlt", "ungültig"))
        n, u = len(self.pkgs), len(self.mgr.updatable(self.pkgs))
        ign = sum(1 for p in self.pkgs if p.ignored)
        s = f"{n} {'Addon' if n == 1 else 'Addons'} · {u} {'Update' if u == 1 else 'Updates'}"
        if ign:
            s += f" · {ign} ignoriert"
        self.summary_label.set_markup(f"<b>{s if self.ready or n else 'Prüfe …'}</b>")

    def update_actions(self):
        working = self.busy
        n = sum(1 for r in self.store if r[C_CHECK] and self.rows.get(r[C_KEY]) is not None
                and self.rows[r[C_KEY]].status == core.UPDATE and self.rows[r[C_KEY]].remote is not None)
        self.update_btn.set_label(f"{n} aktualisieren" if n else "Aktualisieren")
        self.update_btn.set_sensitive(n > 0 and not working)
        self.mark_btn.set_sensitive(not working)
        for b in (self.uninstall_btn, self.browser_btn, self.new_btn):
            b.set_sensitive(not working)

    def on_delete(self, *_):
        bg = self.background
        if bg is not None and bg.available and self.mgr.cfg["close_to_tray"]:
            self.win.hide()
            return True
        if self.busy and not ask(self.win, "Vorgang läuft", "Vorgang läuft – trotzdem beenden?",
                                 "Beenden", kind=Gtk.MessageType.WARNING):
            return True
        self.quit(force=True)
        return True

    def on_quit_item(self, *_):
        if self.busy and not ask(self.win, "Vorgang läuft", "Vorgang läuft – trotzdem beenden?",
                                 "Beenden", kind=Gtk.MessageType.WARNING):
            return
        self.quit(force=True)

    def confirm_quit_busy(self):
        """Nachfrage bei laufendem Vorgang; waehrend der Dialog offen ist, kein zweiter."""
        if self._asking:
            return False
        self._asking = True
        try:
            self.present()
            return ask(self.win, "Vorgang läuft", "Vorgang läuft – trotzdem beenden?",
                       "Beenden", kind=Gtk.MessageType.WARNING)
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
        for b in (self.menu_btn, self.key_btn, self.refresh_btn):
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
        name = ev.get("name") or "Download"
        head = f"{name} ({i + 1}/{n})" if n > 1 else name
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
                parts.append(f"Versuch {ev['attempt']}/{core.DL_ATTEMPTS}")
            idle = now - ev["t"]
            if idle >= 5:
                parts.append(f"keine Daten seit {idle:.0f} s")
            text = " · ".join(p for p in parts if p)
            frac = done / total if total else None
        elif state == "verify":
            text, frac = f"{head} · prüfe Zip-Datei …", 1.0
        elif state == "retry":
            left = max(0, ev.get("wait", 0) - (now - ev["t"]))
            text = (f"{head} · {ev.get('way')}: {ev.get('error')} – neuer Versuch "
                    f"{ev.get('attempt')}/{core.DL_ATTEMPTS} in {left:.0f} s")
        elif state == "fallback":
            text = f"{head} · {ev.get('way')}: {ev.get('error')} – wechsle zu {ev.get('next')}"
        else:
            return
        if self.mgr.dl_cancel.is_set():
            text = "Breche ab …"
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

    def on_cancel_downloads(self, *_):
        self.mgr.dl_cancel.set()
        self.prog_cancel.set_sensitive(False)
        self.prog_bar.set_text("Breche ab …")
        self.log("Downloads werden abgebrochen …")

    def log_results(self, results, what="aktualisiert"):
        """Ergebnis einer Installation ins Protokoll; die letzte Zeile landet in der Statuszeile."""
        ok = [r.name for r in results if r.ok]
        for r in results:
            if not r.ok:
                self.log(f"FEHLER {r.name}: {r.message}")
        if ok:
            self.log(f"Fertig: {len(ok)} Addon{'s' if len(ok) != 1 else ''} {what} ({', '.join(ok)})")
        elif results:
            self.log("Fertig: nichts installiert")

    def bg(self, fn, cb, text="Arbeite …"):
        self.set_busy(True, text)

        def done(res, err):
            self.set_busy(False)
            if err:
                self.log(f"Fehler: {err_text(err)}")
            cb(res, err)
            return False
        run_in_thread(fn, done)

    # ------------------------------------------------------------ Liste
    def row_values(self, p, checked=False):
        upd = p.status == core.UPDATE
        if p.ignored:
            stext, scolor, sset, weight, style = "ignoriert", GREY, True, 400, 2
        elif upd:
            stext, scolor, sset, weight, style = "▲ Update", ORANGE, True, 700, 0
        elif p.status == core.CURRENT:
            stext, scolor, sset, weight, style = "✓ aktuell", GREEN, True, 400, 0
        elif p.status in (core.HELD, core.SKIPPED):
            stext, scolor, sset, weight, style = p.status, GREY, True, 400, 2
        else:
            stext, scolor, sset, weight, style = p.status, STATUS_COLOR.get(p.status, GREY), p.status in STATUS_COLOR, 400, 0
        fcolor = {"ok": GREEN, "veraltet": ORANGE, "nein": RED}.get(p.forever)
        remote = core.display_version(p.remote.version) if p.remote else "–"
        if p.channel in CHANNEL_MARK:
            remote += " " + CHANNEL_MARK[p.channel]
        return [checked, p.name, core.display_version(p.local_version) or "?",
                remote, p.source,
                FOREVER_SHOW.get(p.forever, p.forever), stext, p.key, weight, scolor, fcolor or GREY, True, sset,
                fcolor is not None, style, p.ignored, GREY]

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
                "<big><b>Keine Addons gefunden</b></big>\n\nIm AddOns-Ordner liegen keine Addons.\n"
                f"{GLib.markup_escape_text(ad)}\n\nÜber „Neues Addon …“ lassen sich Addons installieren.")
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

    def on_mark_all(self, *_):
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
                then(self.pkgs, "Kein AddOns-Ordner gewählt")
            return
        if self.busy and quiet:
            if then:
                then(self.pkgs, "Programm ist beschäftigt")
            return

        before = {p.key for p in self.mgr.updatable(self.pkgs)}

        def work():
            pkgs = self.mgr.scan()
            self.mgr.check(pkgs, lambda d, t, s: GLib.idle_add(self.status_label.set_text, f"Prüfe … {d}/{t} {s}"))
            return pkgs

        def done(res, err):
            if res is not None:
                self.pkgs = res
                self.ready = True
                self.render()
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
        self.bg(work, done, "Lese AddOns-Ordner und prüfe Versionen … (der erste Lauf dauert etwas länger)")

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
            ("Zuordnen …", lambda: self.assign_dialog(p), bool(p.meta.get("unassigned")) and not self.busy),
            ("Aktualisieren", lambda: self.install_flow([(p.name, (lambda: self.mgr.plan_update(p)), p)]),
             p.status == core.UPDATE and p.remote is not None),
            ("Changelog …", lambda: self.show_changelog(p), p.remote is not None),
            ("Verlauf …", lambda: self.on_history(name=p.name), True),
            ("Andere Version …", lambda: self.pick_version(p),
             not p.meta.get("unassigned") and bool(p.cf_mod_id or p.meta.get("gh")) and not self.busy),
            *((("Festhalten aufheben" if p.pin["mode"] == "hold" else "Auslassen aufheben", lambda: self.release_pin(p), not self.busy),)
              if p.pin else ()),
            ("@channel", p),
            ("Updates nicht mehr ignorieren" if p.ignored else "Updates ignorieren", lambda: self.toggle_ignore(p), True),
            None,
            ("Seite öffnen", lambda: self.open_uri(url), bool(url)),
            ("Ordner öffnen", lambda: self.open_folder(p), bool(p.folders)),
            ("Im Browser laden …", lambda: self.browser_flow(p), True),
            None,
            ("Deinstallieren …", lambda: self.uninstall([p]), True),
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
            d = make_dialog(f"{p.name} zuordnen", self.win, 560)
            d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
            add_button(d, "Zuordnen", Gtk.ResponseType.OK, suggested=True)
            box = d.get_content_area()
            radios, group = [], None
            none_rb = Gtk.RadioButton.new_with_label_from_widget(None, "Keine Auswahl (Eingabe unten verwenden)")
            group = none_rb
            if sugs:
                box.pack_start(none_rb, False, False, 0)
            for sg in sugs or []:
                src = "CurseForge" if sg.cand.source == "CF" else "GitHub"
                rb = Gtk.RadioButton.new_with_label_from_widget(
                    group, f"{sg.cand.name}  ({src} {sg.cand.ident})\n{sg.reason}" + ("  – eindeutig" if sg.strong else ""))
                rb.get_child().set_xalign(0)
                radios.append((rb, sg))
                box.pack_start(rb, False, False, 0)
            first_strong = next((rb for rb, sg in radios if sg.strong), None)
            if first_strong:   # nur eindeutige Vorschläge werden vorgewählt
                first_strong.set_active(True)
            if not radios:
                lb = Gtk.Label(label="Keine Vorschläge gefunden." if not err else f"Vorschläge nicht ermittelbar: {err_text(err)}",
                               xalign=0, wrap=True)
                box.pack_start(lb, False, False, 0)
            box.pack_start(Gtk.Label(label="Oder Projekt-ID, CurseForge-/GitHub-Adresse, gh:owner/repo:", xalign=0), False, False, 0)
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
                        message(self.win, "Zuordnung nicht möglich", err_text(e), Gtk.MessageType.WARNING)
                    else:
                        self.do_assign(p, cand)
                self.bg(lambda: self.mgr.assign_target(text), target, "Prüfe Eingabe …")
            elif chosen:
                self.do_assign(p, chosen.cand)
        self.bg(lambda: self.mgr.suggest_assignments(p), got, "Suche Zuordnungen …")

    def do_assign(self, p, cand):
        if cand.source == "CF":
            self.mgr.assign_folders(p.folders, cand.name, cf_id=int(cand.ident))
        else:
            self.mgr.assign_folders(p.folders, cand.name, gh=str(cand.ident))
        self.log(f"Zugeordnet: {', '.join(p.folders)} → {cand.name} ({cand.source} {cand.ident})")
        self.rescan()

    def channel_item(self, p):
        sub = Gtk.Menu()
        group = None
        for label, ch in CHANNEL_NAMES:
            mi = Gtk.RadioMenuItem(label=label, group=group)
            group = group or mi
            mi.set_active(p.channel == ch)
            mi.connect("activate", lambda w, ch=ch: w.get_active() and self.set_channel(p, ch))
            sub.append(mi)
        top = Gtk.MenuItem(label="Kanal", sensitive=not self.busy and not p.meta.get("unassigned"))
        top.set_submenu(sub)
        return top

    def recheck_pkg(self, p, text="Prüfe …"):
        def done(_res, err):
            if err:
                self.log(f"Prüfung fehlgeschlagen: {err_text(err)}")
            self.refresh_row(p)
            refresh = getattr(self.background, "refresh", None)
            if refresh:
                refresh()
        self.bg(lambda: self.mgr.recheck(p), done, text)

    def set_channel(self, p, ch):
        if p.channel == ch:
            return
        self.mgr.set_channel(p.key, ch)
        p.channel = ch
        self.log(f"{p.name}: Kanal {dict((v, k) for k, v in CHANNEL_NAMES)[ch]}")
        self.recheck_pkg(p)

    def release_pin(self, p):
        if self.busy:
            return
        what = "Festhalten" if p.pin and p.pin["mode"] == "hold" else "Auslassen"
        self.mgr.clear_pin(p.key)
        p.pin = None
        self.log(f"{p.name}: {what} aufgehoben")
        self.recheck_pkg(p)

    def pick_version(self, p):
        """Dialog „Andere Version …“: Liste laden, wählen, installieren (optional festhalten/auslassen)."""
        pages = []

        def load(page, cb):
            self.bg(lambda: self.mgr.versions(p, page), cb, "Lade Versionsliste …")

        def first(res, err):
            if err:
                message(self.win, "Versionsliste nicht verfügbar", err_text(err), Gtk.MessageType.ERROR)
                return
            if not res[0]:
                message(self.win, "Keine Versionen", "Es wurden keine Forever-Versionen gefunden.")
                return
            pages.extend(res[0])
            self.version_dialog(p, pages, res[1], load)
        load(0, first)

    def version_dialog(self, p, remotes, more, load):
        """remotes wird bei „Mehr laden“ in place erweitert."""
        mgr = self.mgr
        d = make_dialog(f"Andere Version – {p.name}", self.win, 640, 480)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        inst = add_button(d, "Installieren", Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        store = Gtk.ListStore(str, str, str, str, int)
        installed = mgr.installed_ident(p)

        def fill():
            store.clear()
            for i, r in enumerate(remotes):
                mark = "✓ installiert" if installed is not None and r.ident == installed else ""
                store.append([r.display or r.version, (r.file_date or "")[:10], core.TYPE_NAMES.get(r.rtype, "Release"), mark, i])
        fill()
        tree = Gtk.TreeView(model=store)
        for i, (title, expand) in enumerate((("Version", True), ("Datum", False), ("Typ", False), ("", False))):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE)
            tc = Gtk.TreeViewColumn(title, r, text=i)
            tc.set_expand(expand)
            tc.set_resizable(True)
            tree.append_column(tc)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tree)
        box.pack_start(sw, True, True, 0)
        more_btn = Gtk.Button(label="Mehr laden", halign=Gtk.Align.START, no_show_all=True)
        more_btn.set_visible(more)
        box.pack_start(more_btn, False, False, 0)
        hold = Gtk.RadioButton(label="Auf dieser Version festhalten, bis ich es aufhebe")
        skip = Gtk.RadioButton.new_with_label_from_widget(
            hold, "Nur die jetzt neueren Versionen auslassen (Updates wieder ab einer noch neueren Version)")
        skip.set_active(True)
        opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        opts.pack_start(Gtk.Label(label="Danach gilt:", xalign=0), False, False, 0)
        opts.pack_start(skip, False, False, 0)
        opts.pack_start(hold, False, False, 0)
        box.pack_start(opts, False, False, 0)
        note = Gtk.Label(xalign=0, wrap=True, no_show_all=True)
        box.pack_start(note, False, False, 0)
        state = dict(more=more, page=0)

        def chosen():
            model, it = tree.get_selection().get_selected()
            return remotes[model[it][4]] if it else None

        def sync(*_):
            r = chosen()
            newest = mgr.newest_allowed(p, remotes)
            is_new = r is not None and newest is not None and r.ident == newest.ident
            inst.set_sensitive(r is not None and not (installed is not None and r.ident == installed and is_new))
            opts.set_visible(r is not None and not is_new)
            note.set_visible(is_new)
            note.set_text("Das ist die neueste Version – normales Update, ohne Festhalten." if is_new else "")
        tree.get_selection().connect("changed", sync)

        def on_more(_b):
            more_btn.set_sensitive(False)

            def got(res, err):
                more_btn.set_sensitive(True)
                if err:
                    state["page"] -= 1
                    message(d, "Laden fehlgeschlagen", err_text(err), Gtk.MessageType.ERROR)
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
            message(self.win, "Öffnen fehlgeschlagen", e.message, Gtk.MessageType.ERROR)

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
        if not hit or hit[1].get_title() not in ("Addon", "Verfügbar", "Status"):
            return False
        p = self.rows.get(self.store[hit[0]][C_KEY])
        if p is None:
            return False
        missing = f"Fehlt: {', '.join(p.missing)} (Abhängigkeit laut TOC)" if p.missing else ""
        if p.status not in (core.UPDATE, core.HELD, core.SKIPPED) or p.remote is None or hit[1].get_title() == "Addon":
            if not missing:
                return False
            tip.set_text(missing)
            tree.set_tooltip_cell(tip, hit[0], hit[1], None)
            return True
        k = self.changelog_key(p)
        if k not in self.changelogs:
            self.load_changelog(p)
            text = "Changelog wird geladen …"
        else:
            lines = self.changelogs[k].strip().splitlines()
            text = "\n".join(lines[:12]) + ("\n…" if len(lines) > 12 else "") if lines else "Kein Changelog verfügbar."
        if p.status != core.UPDATE:
            text = core.pin_text(p.pin) + "\n\nNeueste Version: " + (core.display_version(p.remote.version) or "?") + "\n" + text
        if p.channel in CHANNEL_MARK:
            text = f"Kanal: {dict((v, k) for k, v in CHANNEL_NAMES)[p.channel]}\n\n" + text
        tip.set_text(text + ("\n\n" + missing if missing else ""))
        tree.set_tooltip_cell(tip, hit[0], hit[1], None)
        return True

    def show_changelog(self, p):
        def show():
            text = self.changelogs.get(self.changelog_key(p)) or "Kein Changelog verfügbar."
            d = make_dialog(f"Changelog – {p.name}", self.win, 640, 420)
            add_button(d, "Schließen", Gtk.ResponseType.CLOSE, suggested=True)
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
        self.bg(lambda: self.mgr.changelog(p), fetched, "Lade Changelog …")

    # ------------------------------------------------------------ Installieren
    def on_update_selected(self, *_):
        marked = [self.rows[r[C_KEY]] for r in self.store if r[C_CHECK]]
        if not marked:
            message(self.win, "Nichts ausgewählt", "Markiere Addons mit einem Häkchen.")
            return
        sel = [p for p in marked if p.status == core.UPDATE and p.remote is not None]
        if len(sel) < len(marked):
            skipped = ", ".join(p.name for p in marked if p not in sel)
            message(self.win, "Ohne Update übersprungen", skipped)
            if not sel:
                return
        self.install_flow([(p.name, (lambda p=p: self.mgr.plan_update(p)), p) for p in sel])

    def on_uninstall(self, *_):
        self.uninstall([self.rows[r[C_KEY]] for r in self.store if r[C_CHECK]])

    def uninstall(self, sel):
        if not sel:
            message(self.win, "Nichts ausgewählt", "Markiere die Addons mit einem Häkchen.")
            return

        def planned(plans, err):
            if err:
                message(self.win, "Deinstallation nicht möglich", err_text(err), Gtk.MessageType.ERROR)
                return
            plans = [p for p in plans if p.folders]
            if not plans:
                message(self.win, "Nichts zu deinstallieren", "Die Ordner existieren nicht mehr.")
                self.rescan()
                return
            lines = []
            running = self.mgr.wow_running()
            if running:
                lines.append("ACHTUNG: WoW scheint zu laufen (heuristisch erkannt). Bitte vorher beenden.\n")
            elif running is None:
                lines.append("Hinweis: Im Flatpak ist nicht erkennbar, ob WoW läuft. Bitte vorher beenden.\n")
            for p in plans:
                lines.append(f"• {p.name}\n    Ordner: " + ", ".join(p.folders))
                lines += [f"    ! {w}" for w in p.warnings]
            lines.append("\nDie Ordner werden in ein Backup verschoben und lassen sich unter ☰ → Backups "
                         "wiederherstellen. Einstellungen (SavedVariables/WTF) bleiben erhalten.")
            d = make_dialog("Deinstallation bestätigen", self.win, 640, 420)
            d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
            add_button(d, "Deinstallieren", Gtk.ResponseType.OK, destructive=True)
            d.get_content_area().pack_start(text_view_scroller("\n".join(lines)), True, True, 0)
            d.show_all()
            ok = d.run() == Gtk.ResponseType.OK
            d.destroy()
            if not ok:
                return

            def finished(results, err2):
                if err2:
                    message(self.win, "Deinstallation fehlgeschlagen", err_text(err2), Gtk.MessageType.ERROR)
                else:
                    out = [f"{'OK    ' if r.ok else 'FEHLER'}  {r.name}: {r.message}" for r in results]
                    message(self.win, "Deinstallation abgeschlossen", "\n".join(out))
                self.rescan()
            self.bg(lambda: self.mgr.uninstall(plans), finished, "Deinstalliere …")
        self.bg(lambda: [self.mgr.plan_uninstall(p) for p in sel], planned, "Prüfe Abhängigkeiten …")

    def plan_all(self, planners):
        """Im Worker: plant (laedt) alle Pakete nacheinander; nach "Abbrechen" werden die restlichen übersprungen."""
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
                self.log(f"Abgebrochen: {', '.join(cancelled)}")
            queue = []
            if errs:
                lines = [f"{n}: {err_text(e)}" for n, e, _c in errs]
                dl = [(n, c) for n, e, c in errs if is_dl(e)]
                if dl:
                    what = ("Datei stattdessen im Browser herunterladen?" if len(dl) == 1 else
                            f"Die {len(dl)} Dateien nacheinander im Browser herunterladen?")
                    if ask(self.win, "Download fehlgeschlagen", "\n".join(lines) + "\n\n" + what, "Im Browser laden"):
                        queue = [(n, c, None) for n, c in dl]
                else:
                    message(self.win, "Nicht alles konnte vorbereitet werden", "\n".join(lines), Gtk.MessageType.WARNING)
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
            self.bg(lambda: self.plan_all(planners), done, "Lade und prüfe Pakete …")

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
            self.rescan(then=lambda *_: report(col, True))

        if not background:
            self.install_flow(planners, finish=fin_interactive)
            return

        def planned(res, _err):
            plans, errs, running = res
            errs, cancelled = self.split_cancelled(errs)
            if cancelled:
                self.log(f"Abgebrochen: {', '.join(cancelled)}")
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
                    self.rescan(quiet=True, then=lambda *_: report(col, False))
                self.bg(lambda: self.mgr.apply(plans, origin="auto"), applied, "Installiere Updates …")
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
        self.bg(work, planned, "Lade Updates …")

    def auto_deps(self, plans):
        """Hintergrund-Update: fehlende CF-Pflicht-Abhängigkeiten mitladen, alles andere nur ins Protokoll (Worker)."""
        if not plans:
            return plans
        try:
            needs = self.mgr.resolve_deps(plans, cf_only=True)
        except Exception as e:  # noqa: BLE001
            self.log(f"Abhängigkeiten nicht prüfbar: {err_text(e)}")
            return plans
        take = [d for d in needs if d.cand and d.via == "cf"]
        for d in needs:
            if d not in take:
                self.log(f"Abhängigkeit fehlt: {d.name} ({d.reason}) – {d.note or 'nicht automatisch installierbar'}")
        dplans, errs = self.plan_all([(d.name, (lambda d=d: self.mgr.plan_candidate(d.cand)), None) for d in take])
        for n, e, _c in errs:
            self.log(f"Abhängigkeit {n}: {err_text(e)}")
        if dplans:
            self.log("Abhängigkeiten werden mitinstalliert: " + ", ".join(p.name for p in dplans))
        return plans + dplans

    def confirm_and_apply(self, plans, after=None, col=None):
        """col: Sammler (installed/skipped/errors) für Durchläufe mit Abschlussübersicht; dann kein Einzelergebnis
        und kein Rescan. Fehlende Pflicht-Abhängigkeiten werden vor der Bestätigung ermittelt."""
        if not plans:
            if after:
                after()
            return
        self.bg(lambda: self.mgr.resolve_deps(plans),
                lambda deps, _err: self.confirm_dialog(plans, deps or [], after, col), "Prüfe Abhängigkeiten …")

    def confirm_dialog(self, plans, deps, after, col):
        lines = []
        for p in plans:
            lines.append(f"• {p.name}: {core.display_version(p.old_version) or '–'} → "
                         f"{core.display_version(p.new_version) or '?'} ({p.source})")
            lines.append("    Ordner: " + ", ".join(p.install_folders))
            if p.skipped_folders:
                lines.append("    Übersprungen (werden von WoW: Forever nicht geladen): " + ", ".join(p.skipped_folders))
            lines += [f"    ! {w}" for w in p.warnings]
        running = self.mgr.wow_running()
        if running:
            lines.insert(0, "ACHTUNG: WoW scheint zu laufen (heuristisch erkannt). Bitte vorher beenden, sonst können Dateien gesperrt sein.\n")
        elif running is None:
            lines.insert(0, "Hinweis: Im Flatpak ist nicht erkennbar, ob WoW läuft. Bitte vorher beenden, sonst können Dateien gesperrt sein.\n")
        d = make_dialog("Installation bestätigen", self.win, 640, 420)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        add_button(d, "Installieren", Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        box.pack_start(text_view_scroller("\n".join(lines)), True, True, 0)
        checks = []
        for dn in deps:
            if dn.cand:
                cb = Gtk.CheckButton(label=f"Benötigt: {dn.name} (wird mitinstalliert)", active=True,
                                     tooltip_text=dn.reason)
                checks.append((cb, dn))
                box.pack_start(cb, False, False, 0)
            else:
                lb = Gtk.Label(label=f"Benötigt: {dn.name} – {dn.note} ({dn.reason})", xalign=0, wrap=True)
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
                self.log(f"Abhängigkeit {n}: {err_text(e)}")
                if col is not None:
                    col["errors"].append((n, err_text(e)))
            if errs and col is None:
                message(self.win, "Abhängigkeiten nicht vollständig",
                        "\n".join(f"{n}: {err_text(e)}" for n, e, _c in errs), Gtk.MessageType.WARNING)
            if cancelled and col is not None:
                col["skipped"] += cancelled
            self.apply_plans(keep + self.confirm_strong(dplans, col), after, col)
        self.bg(lambda: self.plan_all(planners), planned, "Lade Abhängigkeiten …")

    def confirm_strong(self, plans, col):
        """Pakete ohne Forever-Hauptdatei brauchen eine eigene Bestätigung; -> Liste der weiter zu installierenden."""
        keep = []
        for p in plans:
            if p.needs_strong_confirm and not ask(
                    self.win, f"{p.name}: nicht für WoW: Forever gedacht",
                    "Das Hauptpaket enthält keine kompatible Forever-Datei (Interface 16xxx). "
                    "Es wird möglicherweise nicht geladen oder verursacht Fehler.", "Trotzdem installieren",
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
                self.log_results(results, "installiert")
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
                message(self.win, "Installation fehlgeschlagen", err_text(err), Gtk.MessageType.ERROR)
            else:
                sets = {r.backup_set for r in results if r.backup_set}
                out = [f"{'OK    ' if r.ok else 'FEHLER'}  {r.name}: {r.message}" for r in results]
                if sets:
                    out.append("\nBackup-Satz: " + ", ".join(sorted(sets)))
                d2 = make_dialog("Ergebnis", self.win, 600, 300)
                add_button(d2, "Schließen", Gtk.ResponseType.CLOSE, suggested=True)
                d2.get_content_area().pack_start(text_view_scroller("\n".join(out), 520, 200), True, True, 0)
                d2.show_all()
                d2.run()
                d2.destroy()
            self.rescan(after)
        self.bg(lambda: self.mgr.apply(keep), finished, "Installiere …")

    # ------------------------------------------------------------ Browser
    def on_browser_selected(self, *_):
        p = self.selected_pkg()
        if not p:
            message(self.win, "Kein Addon gewählt", "Wähle eine Zeile in der Liste.")
            return
        self.browser_flow(p)

    def browser_flow(self, target=None, url=None):
        """target: Package/Candidate (oder None mit url). Öffnet Browser, wartet auf neue Zip, installiert."""
        self.browser_queue([(getattr(target, "name", None) or "Download", target, url)])

    def show_summary(self, col):
        parts = []
        for title, key in (("Installiert", "installed"), ("Übersprungen", "skipped"), ("Fehler", "errors")):
            items = [i if isinstance(i, str) else f"{i[0]}: {i[1]}" for i in col[key]]
            if items:
                parts.append(f"{title} ({len(items)}):\n" + "\n".join(f"  • {i}" for i in items))
        d = make_dialog("Gesamtergebnis", self.win, 600, 320)
        add_button(d, "Schließen", Gtk.ResponseType.CLOSE, suggested=True)
        d.get_content_area().pack_start(
            text_view_scroller("\n\n".join(parts) or "Nichts zu tun.", 520, 220), True, True, 0)
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
            d = make_dialog("Browser-Download", self.win, 500)
            if solo:
                add_button(d, "Abbrechen", Gtk.ResponseType.CANCEL)
            else:
                d.add_button("Überspringen", SKIP)
                d.add_button("Alle abbrechen", ABORT)
            head = f"Browser-Download {i + 1} von {n}: {name}" if n > 1 else f"Browser-Download: {name}"
            text = (f"<b>{GLib.markup_escape_text(head)}</b>\n\nLade die Datei für WoW: Forever herunter …\n"
                    "Falls nicht vorgefiltert: Filter „Game Version/Flavor“ → „Forever“ wählen.\n\n"
                    "Überwachte Ordner: " + (", ".join(core.tilde(f) for f in folders) or "(keiner gefunden)"))
            if watch["ask"]:
                text += "\n\nBrowser fragt nach Speicherort – bitte in einen dieser Ordner speichern."
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
                        message(self.win, "Fehler beim Warten", err_text(err), Gtk.MessageType.ERROR)
                    else:
                        col["errors"].append((name, err_text(err)))
                        step(i + 1)
                elif path is None:
                    if resp is None:
                        if solo:
                            message(self.win, "Keine Datei erkannt",
                                    "Es wurde keine neue Zip-Datei gefunden (Zeitlimit).")
                        else:
                            col["errors"].append((name, "Zeitlimit: keine neue Zip gefunden"))
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
                    self.bg(lambda: mgr.plan_zip(path, hint), planned, "Prüfe Zip …")
                return False
            run_in_thread(lambda: mgr.wait_for_download(since, cancel=cancel, folders=folders), done)
        step(0)

    # ------------------------------------------------------------ Neues Addon
    def on_new_addon(self, *_):
        if not self.mgr.addons_dir:
            return
        try:
            from wfa_newaddon import NewAddonDialog
        except ImportError as e:
            message(self.win, "Dialog nicht verfügbar", f"wfa_newaddon fehlt: {e}", Gtk.MessageType.ERROR)
            return
        d = NewAddonDialog(self.win, self.mgr)
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
                    if ask(self.win, "Download fehlgeschlagen", f"{err}\n\nDatei stattdessen im Browser herunterladen?",
                           "Im Browser laden"):
                        self.browser_flow(url=value)
                elif err:
                    message(self.win, "Eingabe nicht verarbeitbar", err_text(err), Gtk.MessageType.WARNING)
                elif isinstance(res, list):
                    if len(res) == 1:
                        self.install_flow([(res[0].name, lambda: mgr.plan_candidate(res[0]), res[0])])
                    else:
                        message(self.win, "Nichts Eindeutiges gefunden",
                                "Für Suchbegriffe bitte den Tab „Suchen“ verwenden.")
                else:
                    self.confirm_and_apply([res])
            self.bg(lambda: mgr.resolve_input(value), done, "Prüfe Eingabe …")

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
            message(self.win, _("Dialog nicht verfügbar"), f"wfa_expert: {e}", Gtk.MessageType.ERROR)
            return
        getattr(wfa_expert, name)(self)

    def on_expert_chars(self, *_a):
        self._expert("open_characters")

    def on_expert_cleanup(self, *_a):
        self._expert("open_cleanup")

    def on_expert_snapshots(self, *_a):
        self._expert("open_snapshots")

    # ------------------------------------------------------------ Backups
    def on_backups(self, *_):
        entries = [(b.created, b, ", ".join(b.folders)) for b in self.mgr.list_backups()]
        entries += [(v.created, v, f"Einstellungen (SavedVariables) vom {fmt_time(v.created)} – {len(v.addons)} Addons")
                    for v in self.mgr.list_sv_backups()]
        entries.sort(key=lambda e: e[0], reverse=True)
        d = make_dialog("Backups", self.win, 560, 380)
        d.add_button("Schließen", Gtk.ResponseType.CLOSE)
        rb = add_button(d, "Wiederherstellen", Gtk.ResponseType.OK, destructive=True)
        rb.set_sensitive(False)
        store = Gtk.ListStore(object, str, str)
        for created, obj, text in entries:
            store.append([obj, fmt_time(created), text])
        tree = Gtk.TreeView(model=store)
        for i, t in enumerate(("Datum", "Ordner")):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(t, r, text=i + 1)
            c.set_expand(i == 1)
            tree.append_column(c)
        tree.get_selection().connect("changed", lambda s: rb.set_sensitive(s.get_selected()[1] is not None))
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tree)
        if entries:
            d.get_content_area().pack_start(sw, True, True, 0)
        else:
            d.get_content_area().pack_start(Gtk.Label(label="Noch keine Backups vorhanden."), True, True, 0)
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

    def restore_backup_flow(self, chosen, only=None):
        names = [f for f in chosen.folders if only is None or f in only]
        text = "Die aktuellen Ordner werden vorher selbst gesichert.\n" + ", ".join(names)
        if self.mgr.wow_running():
            text = "Hinweis: WoW scheint zu laufen (heuristisch erkannt). Besser vorher beenden.\n\n" + text
        if not ask(self.win, "Backup wiederherstellen?", text, "Wiederherstellen", kind=Gtk.MessageType.WARNING):
            return

        def done(res, err):
            if err:
                message(self.win, "Wiederherstellung fehlgeschlagen", err_text(err), Gtk.MessageType.ERROR)
            else:
                message(self.win, "Wiederherstellung" + (" abgeschlossen" if res.ok else " fehlgeschlagen"), res.message,
                        Gtk.MessageType.INFO if res.ok else Gtk.MessageType.ERROR)
            self.rescan()
        self.bg(lambda: self.mgr.restore(chosen, only), done, "Stelle wieder her …")

    def restore_sv_flow(self, sset):
        """Einstellungen (SavedVariables) wiederherstellen: ganzer Satz oder einzelne Addons."""
        running = self.mgr.wow_running()
        if running:
            message(self.win, "WoW läuft", "Einstellungen lassen sich nur wiederherstellen, solange WoW beendet ist – "
                    "sonst überschreibt WoW sie beim Beenden wieder.", Gtk.MessageType.WARNING)
            return
        if running is None and not ask(self.win, "Ist WoW beendet?",
                                       "Im Flatpak kann der Manager nicht sehen, ob WoW läuft. Läuft es noch, "
                                       "überschreibt es die wiederhergestellten Einstellungen beim Beenden wieder.",
                                       "WoW ist beendet", kind=Gtk.MessageType.WARNING):
            return
        d = make_dialog("Einstellungen wiederherstellen", self.win, 460, 420)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        add_button(d, "Wiederherstellen", Gtk.ResponseType.OK, destructive=True)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(xalign=0, wrap=True, max_width_chars=56,
                                 label=f"Einstellungen vom {fmt_time(sset.created)}. Der aktuelle Stand wird vorher "
                                       "selbst gesichert. Nur angehakte Addons werden zurückgeschrieben."), False, False, 0)
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
            message(self.win, "Nichts ausgewählt", "Es ist kein Addon angehakt.")
            return

        def done(res, err):
            if err:
                message(self.win, "Wiederherstellung fehlgeschlagen", err_text(err), Gtk.MessageType.ERROR)
                return
            self.log(f"Einstellungen: {res.message}")
            message(self.win, "Einstellungen wiederhergestellt" if res.ok else "Wiederherstellung fehlgeschlagen",
                    res.message, Gtk.MessageType.INFO if res.ok else Gtk.MessageType.ERROR)
        self.bg(lambda: self.mgr.restore_sv(sset, None if len(picked) == len(sset.addons) else picked),
                done, "Stelle Einstellungen wieder her …")

    # ------------------------------------------------------------ Verlauf
    def on_history(self, *_, name=""):
        entries = self.mgr.read_history()
        backups = {b.name: b for b in self.mgr.list_backups()}
        svs = {v.name: v for v in self.mgr.list_sv_backups()}
        d = make_dialog("Verlauf", self.win, 720, 460)
        d.add_button("Schließen", Gtk.ResponseType.CLOSE)
        rs = add_button(d, "Einstellungen zurücksetzen", 2)
        rb = add_button(d, "Zurücksetzen", 1, destructive=True)
        rs.set_sensitive(False)
        rb.set_sensitive(False)
        box = d.get_content_area()
        search = Gtk.SearchEntry(placeholder_text="Nach Addon filtern …", text=name)
        box.pack_start(search, False, False, 0)
        store = Gtk.ListStore(object, str, str, str, str)
        for e in entries:
            try:
                t = time.mktime(time.strptime(str(e.get("ts", "")), "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, OverflowError):
                t = 0
            old, new = e.get("old"), e.get("new")
            ver = f"{old or '–'} → {new or '–'}" if (old or new) else ""
            store.append([e, fmt_time(t) if t else "?", str(e.get("kind") or ""), str(e.get("name") or ""), str(ver)])
        flt = store.filter_new()

        def visible(model, it, _d):
            q = search.get_text().strip().lower()
            e = model[it][0]
            return not q or q in str(e.get("name") or "").lower() or q in str(e.get("key") or "").lower()
        flt.set_visible_func(visible)
        tree = Gtk.TreeView(model=flt)
        for i, t in enumerate(("Zeitpunkt", "Aktion", "Addon", "Version")):
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
        search.connect("search-changed", lambda *_: flt.refilter())
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tree)
        if entries:
            box.pack_start(sw, True, True, 0)
        else:
            box.pack_start(Gtk.Label(label="Noch keine Änderungen protokolliert."), True, True, 0)
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
    def on_export(self, *_):
        data = self.mgr.export_data(self.pkgs)
        n, lost = len(data["packages"]), data["untransferable"]
        info = f"{n} Addon{'s' if n != 1 else ''} in der Liste."
        if not self.mgr.api_key:
            info += "\nHinweis: Ohne CurseForge-Key sind Namen und Zuordnungen evtl. unvollständig."
        if not n:
            info += "\nKeine übertragbaren Addons (CurseForge-/GitHub-Zuordnung fehlt)."
        if lost:
            info += f"\nNicht übertragbar (keine CurseForge-/GitHub-Quelle): {', '.join(lost)}"
        d = make_dialog("Addon-Liste exportieren", self.win, 480)
        d.add_button("Schließen", Gtk.ResponseType.CLOSE)
        add_button(d, "Als Text kopieren", 2)
        add_button(d, "Als Datei speichern …", 1, suggested=True)
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
                done.set_text("Als Text in die Zwischenablage kopiert.")
                self.log(f"Addon-Liste ({n}) als Text kopiert")
            elif r == 1:
                path = choose_file(d, "Addon-Liste speichern", Gtk.FileChooserAction.SAVE, "Speichern",
                                   name="wow-forever-addons.json")
                if path:
                    try:
                        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
                        done.set_text(f"Gespeichert: {short_path(path)}")
                        self.log(f"Addon-Liste ({n}) gespeichert: {short_path(path)}")
                    except OSError as e:
                        message(d, "Speichern fehlgeschlagen", str(e), Gtk.MessageType.ERROR)
            else:
                break
        d.destroy()

    def on_import(self, *_):
        if not self.mgr.addons_dir:
            return
        d = make_dialog("Addon-Liste importieren", self.win, 560, 360)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        add_button(d, "Weiter", Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(label="Liste einfügen (Text oder JSON) oder eine Datei laden:", xalign=0), False, False, 0)
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.CHAR, monospace=True)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)
        fb = Gtk.Button(label="Datei laden …", halign=Gtk.Align.START)

        def load_file(*_a):
            path = choose_file(d, "Addon-Liste wählen", Gtk.FileChooserAction.OPEN, "Öffnen")
            if path:
                try:
                    with open(path, encoding="utf-8-sig") as f:
                        tv.get_buffer().set_text(f.read(1_000_000))
                except (OSError, UnicodeDecodeError) as e:
                    message(d, "Datei nicht lesbar", str(e), Gtk.MessageType.ERROR)
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
                message(d, "Liste nicht lesbar", str(e), Gtk.MessageType.WARNING)
        d.destroy()
        self.bg(lambda: self.mgr.import_preview(entries), self.import_preview, "Prüfe Liste …")

    def import_preview(self, items, err):
        if err or not items:
            message(self.win, "Liste nicht prüfbar", err_text(err) if err else "Die Liste enthält keine Addons.",
                    Gtk.MessageType.WARNING)
            return
        d = make_dialog("Addon-Liste importieren", self.win, 520, 420)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        add_button(d, "Installieren", Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(label="Diese Addons installieren:", xalign=0), False, False, 0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        checks = []
        for it in items:
            ch = f"  [{it['channel']}]" if it.get("channel") else ""
            cb = Gtk.CheckButton(label=(f"{it['name']}  ({it['source']})" if it["name"] != it["source"] else it["name"]) + ch + ("  – schon installiert" if it["installed"] else ""),
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
    def on_settings(self, *_a):
        m = self.mgr
        d = make_dialog("Einstellungen", self.win, 540)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        add_button(d, "Speichern", Gtk.ResponseType.OK, suggested=True)
        sc = Gtk.ScrolledWindow(hexpand=True, vexpand=True, propagate_natural_height=True, max_content_height=540)
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_end=6)
        sc.add(box)
        d.get_content_area().pack_start(sc, True, True, 0)

        def section(text, top=8):
            box.pack_start(Gtk.Label(xalign=0, use_markup=True, label=f"<b>{text}</b>", margin_top=top), False, False, 0)

        def check(label, active, sens=True):
            c = Gtk.CheckButton(label=label)
            c.set_active(bool(active))
            c.set_sensitive(sens)
            box.pack_start(c, False, False, 0)
            return c
        section("CurseForge-API-Key", 0)
        key = Gtk.Entry(visibility=False, hexpand=True)
        current = m.cfg["curseforge_api_key"]
        key.set_placeholder_text(core.mask(current) if current else "Key einfügen …")
        box.pack_start(key, False, False, 0)
        link = Gtk.LinkButton.new_with_label(core.CF_KEY_URL, "Kostenlosen Key erzeugen (console.curseforge.com)")
        link.set_halign(Gtk.Align.START)
        box.pack_start(link, False, False, 0)
        clear = check("Gespeicherten Key löschen", False, bool(current))
        section("Anzeige und Download")
        beta = check("Beta-Versionen anzeigen", m.cfg["include_beta"])
        classic = check("Klassisches Theme (dunkel, Gold-Akzente)", m.cfg["classic_theme"])
        direct = check("Direkt-Download für Addons ohne API-Freigabe", m.cfg["direct_download"])
        sv = check("Vor Updates die Addon-Einstellungen (SavedVariables) sichern", m.cfg["sv_backup"])
        section(_("Sprache"))
        lang_row = Gtk.Box(spacing=8)
        lang = Gtk.ComboBoxText()
        for lid, text in (("auto", _("Automatisch")), ("de", "Deutsch"), ("en", "English")):
            lang.append(lid, text)
        lang.set_active_id(m.cfg["language"] if m.cfg["language"] in ("auto", "de", "en") else "auto")
        lang_row.pack_start(lang, False, False, 0)
        lang_hint = Gtk.Label(label=_("Wirkt nach einem Neustart"))
        lang_hint.get_style_context().add_class("wfa-dim")
        lang_row.pack_start(lang_hint, False, False, 0)
        box.pack_start(lang_row, False, False, 0)
        section("AddOns-Ordner")
        path = Gtk.Label(xalign=0, selectable=True, wrap=True, label=short_path(m.addons_dir) if m.addons_dir else "–")
        box.pack_start(path, False, False, 0)
        changed = []

        def change(*_):
            if choose_addons_dir(m, d):
                path.set_text(short_path(m.addons_dir))
                changed.append(True)
        b1 = Gtk.Button(label="Ändern / automatisch suchen …", halign=Gtk.Align.START)
        b1.connect("clicked", change)
        box.pack_start(b1, False, False, 0)
        section("Download-Ordner")
        dl_label = Gtk.Label(xalign=0, selectable=True, wrap=True, max_width_chars=60, label=m.download_summary())
        box.pack_start(dl_label, False, False, 0)
        drow = Gtk.Box(spacing=6)

        def pick_dl(*_):
            f = choose_folder(d, "Download-Ordner wählen")
            if f:
                m.set_download_dir(f)
                dl_label.set_text(m.download_summary())

        def auto_dl(*_):
            m.set_download_dir(None)
            dl_label.set_text(m.download_summary())
        b2 = Gtk.Button(label="Ordner wählen …")
        b2.connect("clicked", pick_dl)
        b3 = Gtk.Button(label="Automatisch (aus Browser)")
        b3.connect("clicked", auto_dl)
        drow.pack_start(b2, False, False, 0)
        drow.pack_start(b3, False, False, 0)
        box.pack_start(drow, False, False, 0)

        section("Hintergrund")
        bgd = self.background
        if bgd is None or not bgd.available:
            hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=60, use_markup=True,
                             label=f'<span foreground="{ORANGE}">Kein Tray verfügbar (kein StatusNotifier-Host gefunden). '
                                   "Das Schließen des Fensters beendet dann das Programm.</span>")
            box.pack_start(hint, False, False, 0)
        autostart_on = bool(m.cfg["autostart_portal"]) if core.in_flatpak() else core.autostart_enabled()
        autostart = check("Beim Systemstart im Tray starten", autostart_on)
        to_tray = check("Fenster schließen minimiert in den Tray", m.cfg["close_to_tray"])
        irow = Gtk.Box(spacing=8)
        irow.pack_start(Gtk.Label(label="Prüfintervall (Minuten)"), False, False, 0)
        spin = Gtk.SpinButton.new_with_range(15, 1440, 5)
        spin.set_value(max(15, min(1440, int(m.cfg["check_interval_min"]))))
        irow.pack_start(spin, False, False, 0)
        box.pack_start(irow, False, False, 0)
        auto = check("Updates automatisch installieren (nur wenn WoW nicht läuft)", m.cfg["auto_update"])
        if core.in_flatpak() and not core.host_spawn_available():
            wl = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=70,
                           label="Im Flatpak ist nicht erkennbar, ob WoW läuft; Updates werden deshalb nur gemeldet, "
                                 "nicht still installiert. Erkennung freigeben (erlaubt dem Programm, Befehle "
                                 f"außerhalb der Sandbox zu starten):\n{core.WOW_DETECT_OVERRIDE}")
            wl.get_style_context().add_class("dim-label")
            box.pack_start(wl, False, False, 0)
        section("Programm-Updates")
        su_check = check("Beim Start nach Programm-Updates suchen", m.cfg["self_update_check"])
        su_auto = check("Programm-Updates automatisch installieren", m.cfg["self_auto_update"])
        if core.managed_install():
            for c in (su_check, su_auto):
                c.set_no_show_all(True)
            box.pack_start(Gtk.Label(xalign=0, wrap=True, max_width_chars=70,
                                     label=f"Programm-Updates kommen über {core.package_channel()}."), False, False, 0)
        section(_("Erweitert"))
        expert = check(_("Erweiterte Funktionen anzeigen"), m.cfg["expert"])
        box.pack_start(Gtk.Label(xalign=0, wrap=True, max_width_chars=70,
                                 label=_("Blendet im Menü „Erweitert“ ein: Addons je Charakter, Aufräumen und Gesamtstände.")),
                       False, False, 0)
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            old_interval = m.cfg["check_interval_min"]
            new = dict(classic_theme=classic.get_active(), direct_download=direct.get_active(),
                       close_to_tray=to_tray.get_active(), check_interval_min=int(spin.get_value()),
                       auto_update=auto.get_active(), sv_backup=sv.get_active(), self_update_check=su_check.get_active(),
                       self_auto_update=su_auto.get_active(), expert=expert.get_active(),
                       language=lang.get_active_id() or "auto")
            theme_changed = new["classic_theme"] != bool(m.cfg["classic_theme"])
            with m.cfg.lock:
                for k, v in new.items():
                    m.cfg[k] = v
                m.cfg.save()
            if theme_changed:
                self.set_theme(new["classic_theme"])
            self.apply_expert()
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
        if changed:
            self.update_subtitle()
            self.rescan()

    def set_autostart(self, on, parent=None):
        if not core.in_flatpak():
            try:
                core.set_autostart(on)
            except OSError as e:
                message(parent or self.win, "Autostart fehlgeschlagen", str(e), Gtk.MessageType.ERROR)
            return
        import wfa_portal

        def done(ok, text):
            if ok:
                with self.mgr.cfg.lock:
                    self.mgr.cfg["autostart_portal"] = bool(on)
                    self.mgr.cfg.save()
                self.log("Autostart " + ("eingerichtet." if on else "entfernt."))
            else:
                self.log(f"Autostart: {text}")
                message(self.win, "Autostart fehlgeschlagen", text, Gtk.MessageType.ERROR)
        wfa_portal.request_autostart(on, done)

    def set_theme(self, on):
        marked = {r[C_KEY] for r in self.store if r[C_CHECK]}
        apply_theme(on)
        self.render(marked)

    def on_desktop_entry(self, *_):
        try:
            p = core.install_desktop_entry()
        except OSError as e:
            message(self.win, "Startmenü-Eintrag fehlgeschlagen", str(e), Gtk.MessageType.ERROR)
            return
        message(self.win, "Startmenü-Eintrag angelegt", short_path(p))

    def on_about(self, *_):
        d = Gtk.AboutDialog(transient_for=self.win, modal=True, program_name=TITLE, version=core.__version__,
                            comments="Inoffizieller Addon-Manager für WoW: Forever unter Linux.\n"
                                     "Nicht mit Blizzard oder CurseForge verbunden.",
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
                message(self.win, "Nicht verfügbar", f"Programm-Updates kommen über {core.package_channel()}."
                        if su is not None else "Die Programm-Updates sind in dieser Version nicht enthalten.")
            return

        def done(rel, err):
            if err:
                self.log(f"Programm-Update-Prüfung fehlgeschlagen: {err_text(err)}")
                if manual:
                    message(self.win, "Prüfung fehlgeschlagen", err_text(err), Gtk.MessageType.ERROR)
            elif rel:
                self.on_self_update_available(rel, manual)
                if manual:
                    self.self_update(rel, True)
            elif manual:
                message(self.win, "Kein Update", f"Du nutzt die aktuelle Version ({core.__version__}).")
            return False
        run_in_thread(su.check, done)

    def on_self_update_available(self, rel, force=False):
        if not force and rel.version == self.mgr.cfg["self_update_skipped"]:
            return
        self.self_rel = rel
        self.show_infobar(f"Version {rel.version} des Addon-Managers ist verfügbar.",
                          [("Aktualisieren", 1, True), ("Details", 2, False), ("Überspringen", 3, False)],
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

    def show_infobar(self, text, buttons=(), on_response=None):
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
        ib.connect("response", lambda _i, r: on_response(r) if on_response else None)
        self.infobar_holder.pack_start(ib, False, False, 0)
        ib.show_all()

    def self_update(self, rel, interactive=True):
        """Dialog mit Release-Notes; installiert wird nur nach Klick auf den Knopf."""
        su = self.selfupdate_module()
        can = bool(su and su.can_self_update())
        if interactive:
            self.present()
        d = make_dialog(f"Programm-Update {rel.version}", self.win, 600, 420)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        add_button(d, "Jetzt aktualisieren" if can else "Release-Seite öffnen", Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(xalign=0, use_markup=True, wrap=True, label=(
            f"<b>Version {GLib.markup_escape_text(rel.version)}</b> (installiert: {core.__version__})")), False, False, 0)
        if not can:
            box.pack_start(Gtk.Label(xalign=0, wrap=True, label="Dieses Programm läuft nicht als einzelne ausführbare "
                                     "Datei und kann sich nicht selbst ersetzen. Die Release-Seite wird im Browser geöffnet."),
                           False, False, 0)
        box.pack_start(text_view_scroller(rel.notes or "(Keine Release-Notes vorhanden.)", 540, 260), True, True, 0)
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
            d = make_dialog("Programm-Update", self.win, 420)
            d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
            d.connect("response", lambda *_: cancel.set())
            bar = Gtk.ProgressBar(show_text=True, text=f"Lade Version {rel.version} …")
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
                self.log(f"Programm-Update fehlgeschlagen: {err_text(err)}")
                if not cancel.is_set():
                    message(self.win, "Programm-Update fehlgeschlagen", err_text(err), Gtk.MessageType.ERROR)
                return False
            self.log(f"Programm-Update {rel.version} installiert.")
            self.show_infobar(f"Version {rel.version} installiert – Neustart nötig.", [("Neu starten", 4, True)],
                              lambda r: self.restart_self())
            if show_progress and ask(self.win, "Update installiert", "Jetzt neu starten?", "Neu starten"):
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
            message(self.win, "Neustart fehlgeschlagen", str(e), Gtk.MessageType.ERROR)
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
                dlg.connect("response", lambda *_: None)
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
