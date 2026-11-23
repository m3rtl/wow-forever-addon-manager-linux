"""GTK-3-Oberflaeche fuer den WoW: Forever Addon-Manager."""
from __future__ import annotations

import argparse
import sys
import threading
import time
import traceback
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

import wfa_core as core  # noqa: E402
from wfa_core import ApiError, Manager  # noqa: E402

TITLE = "WoW: Forever Addon-Manager"
REPO_URL = "https://github.com/m3rtl/wow-forever-addon-manager-linux"
RED, ORANGE, GREY, GREEN = "#e74c3c", "#e67e22", "#8a8a8a", "#2e9e5b"
STATUS_COLOR = {core.UPDATE: ORANGE, core.ERROR: RED, core.NO_FOREVER: RED, core.NOKEY: GREY,
                core.UNCHECKED: GREY, core.UNASSIGNED: GREY, core.UNKNOWN: GREY}

# ListStore-Spalten
C_CHECK, C_NAME, C_LOCAL, C_REMOTE, C_SOURCE, C_FOREVER, C_STATUS, C_KEY, C_WEIGHT, C_SCOLOR, C_FCOLOR, C_CAN, C_SSET, C_FSET = range(14)


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
    return d


def add_button(d, label, response, suggested=False, destructive=False):
    b = d.add_button(label, response)
    if suggested:
        b.get_style_context().add_class("suggested-action")
    if destructive:
        b.get_style_context().add_class("destructive-action")
    return b


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


def choose_folder(parent, title="Ordner wählen"):
    d = Gtk.FileChooserDialog(title=title, transient_for=parent, action=Gtk.FileChooserAction.SELECT_FOLDER)
    d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
    add_button(d, "Auswählen", Gtk.ResponseType.OK, suggested=True)
    path = d.get_filename() if d.run() == Gtk.ResponseType.OK else None
    d.destroy()
    return path


def choose_addons_dir(mgr, parent=None):
    """Dialog zur Auswahl des AddOns-Ordners. -> True, wenn gespeichert."""
    d = make_dialog("AddOns-Ordner wählen", parent, 640)
    d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
    add_button(d, "Übernehmen", Gtk.ResponseType.OK, suggested=True)
    box = d.get_content_area()
    intro = Gtk.Label(xalign=0, wrap=True,
                      label="Wähle den AddOns-Ordner deiner WoW: Forever-Installation (…/_forever_/Interface/AddOns).")
    box.pack_start(intro, False, False, 0)
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
        p = choose_folder(d, "AddOns-Ordner wählen")
        if p:
            ok, h = mgr.validate_addons_dir(p)
            hint.set_text(h)
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


class NewAddonDialog(Gtk.Dialog):
    """Ergebnis in self.result: ("cand", Candidate) | ("zip", Path) | ("input", str) | ("browser", str) | None."""

    def __init__(self, parent, mgr):
        super().__init__(title="Neues Addon", transient_for=parent, modal=True, use_header_bar=True)
        self.mgr = mgr
        self.result = None
        self.featured_loaded = False
        self.set_default_size(720, 520)
        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.install_btn = add_button(self, "Installieren", Gtk.ResponseType.OK, suggested=True)
        self.install_btn.set_sensitive(False)
        box = self.get_content_area()
        box.set_spacing(8)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            box.set_property(m, 12)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        sw = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.CENTER)
        box.pack_start(sw, False, False, 0)
        box.pack_start(self.stack, True, True, 0)
        self.fstore, self.ftree, fpage = self._list_page()
        self.fstatus = Gtk.Label(xalign=0, label="Lade beliebte Addons …")
        fpage.pack_end(self.fstatus, False, False, 0)
        self.stack.add_titled(fpage, "featured", "Beliebt")
        self._build_search()
        self._build_direct()
        self.stack.connect("notify::visible-child-name", lambda *_: self._update_btn())
        self.show_all()
        self.search_hint_box.hide()
        run_in_thread(mgr.featured, self._featured_done)

    def _list_page(self):
        store = Gtk.ListStore(object, str, str, str, str)  # Candidate, Name, Autor, Downloads, Status
        tree = Gtk.TreeView(model=store)
        for i, (t, expand) in enumerate((("Addon", True), ("Autor", False), ("Downloads", False), ("", False))):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE)
            c = Gtk.TreeViewColumn(t, r, text=i + 1)
            c.set_expand(expand)
            tree.append_column(c)
        tree.get_selection().connect("changed", lambda *_: self._update_btn())
        tree.connect("row-activated", lambda *_: self.response(Gtk.ResponseType.OK))
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tree)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page.pack_start(sw, True, True, 0)
        return store, tree, page

    @staticmethod
    def _fill(store, cands):
        store.clear()
        for c in cands:
            store.append([c, c.name, c.author or "", f"{c.downloads:,}".replace(",", "."),
                          "installiert" if c.installed else ("keine Forever-Datei" if c.has_forever is False else "")])

    def _featured_done(self, res, err):
        self.featured_loaded = True
        if err:
            self.fstatus.set_text(err_text(err))
        else:
            self._fill(self.fstore, res)
            self.fstatus.set_text(f"{len(res)} Addons")
        return False

    def _build_search(self):
        self.sstore, self.stree, page = self._list_page()
        row = Gtk.Box(spacing=6)
        self.sentry = Gtk.SearchEntry(hexpand=True, placeholder_text="Addon-Name …")
        self.sbtn = Gtk.Button(label="Suchen")
        row.pack_start(self.sentry, True, True, 0)
        row.pack_start(self.sbtn, False, False, 0)
        page.pack_start(row, False, False, 0)
        page.reorder_child(row, 0)
        self.sstatus = Gtk.Label(xalign=0)
        page.pack_end(self.sstatus, False, False, 0)
        self.search_hint_box = Gtk.Box(spacing=8)
        self.search_hint_box.pack_start(Gtk.Label(
            xalign=0, wrap=True, hexpand=True,
            label="Die Suche ist für diesen API-Key nicht freigeschaltet."), True, True, 0)
        b = Gtk.Button(label="Im Browser suchen")
        b.connect("clicked", self._browser_search)
        self.search_hint_box.pack_start(b, False, False, 0)
        page.pack_end(self.search_hint_box, False, False, 0)
        self.sentry.connect("activate", self._do_search)
        self.sbtn.connect("clicked", self._do_search)
        self.stack.add_titled(page, "search", "Suchen")

    def _do_search(self, *_):
        q = self.sentry.get_text().strip()
        if not q:
            return
        self.sbtn.set_sensitive(False)
        self.sstatus.set_text("Suche …")
        self.search_hint_box.hide()

        def done(res, err):
            self.sbtn.set_sensitive(True)
            if isinstance(err, ApiError) and err.kind == "forbidden":
                self.sstatus.set_text("")
                self.search_hint_box.show_all()
            elif err:
                self.sstatus.set_text(err_text(err))
            else:
                self._fill(self.sstore, res)
                self.sstatus.set_text(f"{len(res)} Treffer")
            return False
        run_in_thread(lambda: self.mgr.search(q), done)

    def _browser_search(self, *_):
        self.result = ("browser", self.sentry.get_text().strip())
        self.response(Gtk.ResponseType.OK)

    def _build_direct(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.pack_start(Gtk.Label(
            xalign=0, wrap=True,
            label="CurseForge-Projekt-ID, gh:Besitzer/Repo, GitHub-URL oder direkter Zip-Link:"), False, False, 0)
        self.dentry = Gtk.Entry(placeholder_text="z. B. 3358  oder  gh:Besitzer/Repo  oder  https://…/addon.zip")
        self.dentry.connect("changed", lambda *_: self._update_btn())
        self.dentry.connect("activate", lambda *_: self.install_btn.get_sensitive() and self.response(Gtk.ResponseType.OK))
        page.pack_start(self.dentry, False, False, 0)
        b = Gtk.Button(label="Zip-Datei wählen …", halign=Gtk.Align.START)
        b.connect("clicked", self._pick_zip)
        page.pack_start(b, False, False, 0)
        self.stack.add_titled(page, "direct", "Direkt")

    def _pick_zip(self, *_):
        d = Gtk.FileChooserDialog(title="Zip-Datei wählen", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        add_button(d, "Öffnen", Gtk.ResponseType.OK, suggested=True)
        f = Gtk.FileFilter()
        f.set_name("Zip-Archive")
        f.add_pattern("*.zip")
        f.add_pattern("*.ZIP")
        d.add_filter(f)
        path = d.get_filename() if d.run() == Gtk.ResponseType.OK else None
        d.destroy()
        if path:
            self.result = ("zip", Path(path))
            self.response(Gtk.ResponseType.OK)

    def _selected(self):
        tree = self.ftree if self.stack.get_visible_child_name() == "featured" else self.stree
        model, it = tree.get_selection().get_selected()
        return model[it][0] if it else None

    def _update_btn(self):
        page = self.stack.get_visible_child_name()
        if page == "direct":
            self.install_btn.set_sensitive(bool(self.dentry.get_text().strip()))
        else:
            self.install_btn.set_sensitive(self._selected() is not None)

    def finish(self):
        """Ergebnis nach response OK festhalten."""
        if self.result:
            return
        page = self.stack.get_visible_child_name()
        if page == "direct":
            self.result = ("input", self.dentry.get_text().strip())
        else:
            c = self._selected()
            self.result = ("cand", c) if c else None


class App:
    def __init__(self, mgr, args):
        self.mgr = mgr
        self.args = args
        self.pkgs = []
        self.rows = {}
        self.busy = 0
        self.ready = False
        self.build_window()

    # ------------------------------------------------------------ Aufbau
    def build_window(self):
        w = self.win = Gtk.Window(title=TITLE)
        w.set_default_size(1100, 640)
        hb = self.header = Gtk.HeaderBar(show_close_button=True, title=TITLE)
        w.set_titlebar(hb)
        menu_btn = self.menu_btn = Gtk.MenuButton()
        menu_btn.add(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu = Gtk.Menu()
        for label, cb in (("Backups …", self.on_backups), ("Einstellungen …", self.on_settings),
                          ("Startmenü-Eintrag anlegen", self.on_desktop_entry), ("Über", self.on_about)):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", cb)
            menu.append(mi)
        menu.show_all()
        menu_btn.set_popup(menu)
        hb.pack_end(menu_btn)
        self.update_subtitle()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            outer.set_property(m, 10)
        w.add(outer)

        info = Gtk.Box(spacing=8)
        self.info_label = Gtk.Label(xalign=0, wrap=True, use_markup=True)
        info.pack_start(self.info_label, True, True, 0)
        self.key_btn = Gtk.Button(label="Key eintragen …")
        self.key_btn.connect("clicked", self.on_settings)
        info.pack_end(self.key_btn, False, False, 0)
        outer.pack_start(info, False, False, 0)

        self.store = Gtk.ListStore(bool, str, str, str, str, str, str, str, int, str, str, bool, bool, bool)
        self.tree = Gtk.TreeView(model=self.store)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self.on_toggled)
        c = Gtk.TreeViewColumn("", tog, active=C_CHECK, visible=C_CAN, activatable=C_CAN)
        self.tree.append_column(c)
        cols = (("Addon", C_NAME, True, C_NAME), ("Installiert", C_LOCAL, False, None),
                ("Verfügbar", C_REMOTE, False, None), ("Quelle", C_SOURCE, False, None),
                ("Forever", C_FOREVER, False, None), ("Status", C_STATUS, False, C_STATUS))
        for title, col, expand, sort in cols:
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE)
            tc = Gtk.TreeViewColumn(title, r, text=col)
            if col in (C_STATUS, C_FOREVER):
                tc.set_cell_data_func(r, self.style_cell, col)
            tc.set_resizable(True)
            tc.set_expand(expand)
            if sort is not None:
                tc.set_sort_column_id(sort)
            self.tree.append_column(tc)
        self.tree.set_search_column(C_NAME)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(self.tree)
        outer.pack_start(sw, True, True, 0)

        bar = Gtk.Box(spacing=6)
        self.buttons = []

        def btn(label, cb, suggested=False):
            b = Gtk.Button(label=label)
            if suggested:
                b.get_style_context().add_class("suggested-action")
            b.connect("clicked", cb)
            bar.pack_start(b, False, False, 0)
            self.buttons.append(b)
            return b
        btn("Prüfen", lambda *_: self.rescan())
        btn("Alle Updates markieren", self.on_mark_all)
        btn("Ausgewählte aktualisieren", self.on_update_selected, True)
        btn("Neues Addon …", self.on_new_addon)
        btn("Deinstallieren …", self.on_uninstall)
        btn("Im Browser laden …", self.on_browser_selected)
        outer.pack_start(bar, False, False, 0)

        self.log_buf = Gtk.TextBuffer()
        exp = Gtk.Expander(label="Protokoll")
        lsw = Gtk.ScrolledWindow()
        lsw.set_min_content_height(130)
        self.log_view = Gtk.TextView(buffer=self.log_buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        lsw.add(self.log_view)
        exp.add(lsw)
        outer.pack_start(exp, False, False, 0)

        status = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        self.status_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        status.pack_start(self.spinner, False, False, 0)
        status.pack_start(self.status_label, True, True, 0)
        outer.pack_start(status, False, False, 0)
        self.update_info()

    def log(self, text):
        def add():
            self.log_buf.insert(self.log_buf.get_end_iter(), text + "\n")
            mark = self.log_buf.create_mark(None, self.log_buf.get_end_iter(), False)
            self.log_view.scroll_to_mark(mark, 0, False, 0, 0)
            self.log_buf.delete_mark(mark)
            return False
        GLib.idle_add(add)

    def update_subtitle(self):
        self.header.set_subtitle(short_path(self.mgr.addons_dir) if self.mgr.addons_dir else "")

    def update_info(self):
        m = self.mgr
        state = m.cf_key_state()
        parts = [f"Client-Interface: <b>{m.client_interface}</b>"]
        if state == "fehlt":
            parts.append(f'<span foreground="{ORANGE}">CurseForge: kein API-Key – kostenlos unter '
                         f'{GLib.markup_escape_text(core.CF_KEY_URL)} erzeugen.</span>')
        elif state == "ungültig":
            parts.append(f'<span foreground="{RED}">CurseForge: Key ungültig oder abgelehnt.</span>')
        else:
            parts.append(f"CurseForge: Key {state}")
        for n in dict.fromkeys(m.notes):
            parts.append(f'<span foreground="{ORANGE}">{GLib.markup_escape_text(n)}</span>')
        self.info_label.set_markup("   ·   ".join(parts))
        self.key_btn.set_visible(state in ("fehlt", "ungültig"))

    @staticmethod
    def style_cell(_col, cell, model, it, col):
        val = model[it][col]
        color = {"ok": GREEN, "veraltet": ORANGE, "nein": RED, core.UPDATE: ORANGE}.get(val)
        cell.set_property("text", val)
        cell.set_property("foreground-set", color is not None)
        if color:
            cell.set_property("foreground", color)
        if col == C_STATUS:
            cell.set_property("weight", 700 if val == core.UPDATE else 400)

    def on_delete(self, *_):
        if self.busy and not ask(self.win, "Vorgang läuft", "Vorgang läuft – trotzdem beenden?",
                                 "Beenden", kind=Gtk.MessageType.WARNING):
            return True
        return False

    def set_busy(self, on, text=""):
        self.busy = max(0, self.busy + (1 if on else -1))
        working = self.busy > 0
        for b in self.buttons + [self.menu_btn, self.key_btn]:
            b.set_sensitive(not working)
        self.tree.set_sensitive(not working)
        self.spinner.set_visible(working)
        if working:
            self.spinner.start()
            self.status_label.set_text(text)
        else:
            self.spinner.stop()

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
    def render(self):
        self.store.clear()
        self.rows = {}
        for p in self.pkgs:
            self.rows[p.key] = p
            can = True
            self.store.append([False, p.name, core.display_version(p.local_version) or "?",
                               core.display_version(p.remote.version) if p.remote else "–", p.source,
                               p.forever, p.status, p.key, 700 if p.status == core.UPDATE else 400,
                               STATUS_COLOR.get(p.status, GREY), RED, can, p.status in STATUS_COLOR,
                               p.forever == "nein"])
        self.update_info()

    def on_toggled(self, _r, path):
        row = self.store[path]
        if row[C_CAN]:
            row[C_CHECK] = not row[C_CHECK]

    def on_mark_all(self, *_):
        for row in self.store:
            if row[C_CAN]:
                row[C_CHECK] = True

    def selected_pkg(self):
        model, it = self.tree.get_selection().get_selected()
        return self.rows.get(model[it][C_KEY]) if it else None

    def rescan(self, then=None):
        if not self.mgr.addons_dir:
            return

        def work():
            pkgs = self.mgr.scan()
            self.mgr.check(pkgs, lambda d, t, s: GLib.idle_add(self.status_label.set_text, f"Prüfe … {d}/{t} {s}"))
            return pkgs

        def done(res, err):
            if res is not None:
                self.pkgs = res
                self.render()
                n = sum(1 for p in res if p.status == core.UPDATE)
                self.status_label.set_text(f"{len(res)} Pakete, {n} Update(s) verfügbar")
            else:
                self.update_info()
                self.status_label.set_text(err_text(err))
            self.ready = True
            if then:
                then()
        self.bg(work, done, "Lese AddOns-Ordner und prüfe Versionen … (der erste Lauf dauert etwas länger)")

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
        sel = [self.rows[r[C_KEY]] for r in self.store if r[C_CHECK]]
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
            if self.mgr.wow_running():
                lines.append("ACHTUNG: WoW scheint zu laufen (heuristisch erkannt). Bitte vorher beenden.\n")
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

    def install_flow(self, planners):
        """planners: [(Name, Callable -> InstallPlan, Kontext)]. Planen im Worker, dann Bestätigung und apply."""
        def work():
            plans, errs = [], []
            for label, fn, ctx in planners:
                try:
                    plans.append(fn())
                except Exception as e:  # noqa: BLE001
                    errs.append((label, e, ctx))
            return plans, errs

        def done(res, _err):
            plans, errs = res
            browser = None
            if errs:
                lines = [f"{n}: {err_text(e)}" for n, e, _c in errs]
                dl = next((c for _n, e, c in errs if isinstance(e, ApiError) and e.kind == "download"), None)
                if dl is not None and ask(self.win, "Download fehlgeschlagen", "\n".join(lines) +
                                          "\n\nDatei stattdessen im Browser herunterladen?", "Im Browser laden"):
                    browser = dl
                elif dl is None:
                    message(self.win, "Nicht alles konnte vorbereitet werden", "\n".join(lines), Gtk.MessageType.WARNING)
            after = (lambda: self.browser_flow(browser)) if browser is not None else None
            self.confirm_and_apply(plans, after)
        self.bg(work, done, "Lade und prüfe Pakete …")

    def confirm_and_apply(self, plans, after=None):
        if not plans:
            if after:
                after()
            return
        lines = []
        for p in plans:
            lines.append(f"• {p.name}: {core.display_version(p.old_version) or '–'} → "
                         f"{core.display_version(p.new_version) or '?'} ({p.source})")
            lines.append("    Ordner: " + ", ".join(p.install_folders))
            if p.skipped_folders:
                lines.append("    Übersprungen (werden von WoW: Forever nicht geladen): " + ", ".join(p.skipped_folders))
            lines += [f"    ! {w}" for w in p.warnings]
        if self.mgr.wow_running():
            lines.insert(0, "ACHTUNG: WoW scheint zu laufen (heuristisch erkannt). Bitte vorher beenden, sonst können Dateien gesperrt sein.\n")
        d = make_dialog("Installation bestätigen", self.win, 640, 420)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        add_button(d, "Installieren", Gtk.ResponseType.OK, suggested=True)
        d.get_content_area().pack_start(text_view_scroller("\n".join(lines)), True, True, 0)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        d.destroy()
        keep = []
        for p in plans:
            if ok and p.needs_strong_confirm and not ask(
                    self.win, f"{p.name}: nicht für WoW: Forever gedacht",
                    "Das Hauptpaket enthält keine kompatible Forever-Datei (Interface 16xxx). "
                    "Es wird möglicherweise nicht geladen oder verursacht Fehler.", "Trotzdem installieren",
                    kind=Gtk.MessageType.WARNING):
                self.mgr.discard(p)
            elif ok:
                keep.append(p)
            else:
                self.mgr.discard(p)
        if not keep:
            if after:
                after()
            return

        def finished(results, err):
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
        mgr = self.mgr
        url = url or mgr.browser_url(target)
        hint = target.key if hasattr(target, "key") else None
        since = time.time()
        mgr.open_browser(url)
        cancel = threading.Event()
        d = make_dialog("Browser-Download", self.win, 480)
        add_button(d, "Abbrechen", Gtk.ResponseType.CANCEL)
        row = Gtk.Box(spacing=12)
        sp = Gtk.Spinner()
        sp.start()
        row.pack_start(sp, False, False, 0)
        row.pack_start(Gtk.Label(xalign=0, wrap=True, label=(
            "Lade die Datei für WoW: Forever herunter …\n\n"
            f"Warte auf neue Zip in {short_path(mgr.cfg['download_dir'])}")), True, True, 0)
        d.get_content_area().pack_start(row, True, True, 0)
        d.connect("response", lambda *_: cancel.set())
        d.show_all()

        def done(path, err):
            d.destroy()
            if err:
                message(self.win, "Fehler beim Warten", err_text(err), Gtk.MessageType.ERROR)
            elif path is None:
                if not cancel.is_set():
                    message(self.win, "Keine Datei erkannt", "Es wurde keine neue Zip-Datei gefunden (Zeitlimit).")
            else:
                self.install_flow([(path.name, lambda: mgr.plan_zip(path, hint), None)])
            return False
        run_in_thread(lambda: mgr.wait_for_download(since, cancel=cancel), done)

    # ------------------------------------------------------------ Neues Addon
    def on_new_addon(self, *_):
        if not self.mgr.addons_dir:
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

    # ------------------------------------------------------------ Backups
    def on_backups(self, *_):
        sets = self.mgr.list_backups()
        d = make_dialog("Backups", self.win, 560, 380)
        d.add_button("Schließen", Gtk.ResponseType.CLOSE)
        rb = add_button(d, "Wiederherstellen", Gtk.ResponseType.OK, destructive=True)
        rb.set_sensitive(False)
        store = Gtk.ListStore(object, str, str)
        for b in sets:
            store.append([b, time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(b.created)), ", ".join(b.folders)])
        tree = Gtk.TreeView(model=store)
        for i, t in enumerate(("Datum", "Ordner")):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(t, r, text=i + 1)
            c.set_expand(i == 1)
            tree.append_column(c)
        tree.get_selection().connect("changed", lambda s: rb.set_sensitive(s.get_selected()[1] is not None))
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tree)
        if sets:
            d.get_content_area().pack_start(sw, True, True, 0)
        else:
            d.get_content_area().pack_start(Gtk.Label(label="Noch keine Backups vorhanden."), True, True, 0)
        d.show_all()
        chosen = None
        if d.run() == Gtk.ResponseType.OK:
            model, it = tree.get_selection().get_selected()
            chosen = model[it][0] if it else None
        d.destroy()
        if not chosen:
            return
        text = "Die aktuellen Ordner werden vorher selbst gesichert.\n" + ", ".join(chosen.folders)
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
        self.bg(lambda: self.mgr.restore(chosen), done, "Stelle wieder her …")

    # ------------------------------------------------------------ Einstellungen u. a.
    def on_settings(self, *_):
        m = self.mgr
        d = make_dialog("Einstellungen", self.win, 520)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        add_button(d, "Speichern", Gtk.ResponseType.OK, suggested=True)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(xalign=0, use_markup=True, label="<b>CurseForge-API-Key</b>"), False, False, 0)
        key = Gtk.Entry(visibility=False, hexpand=True)
        current = m.cfg["curseforge_api_key"]
        key.set_placeholder_text(core.mask(current) if current else "Key einfügen …")
        box.pack_start(key, False, False, 0)
        link = Gtk.LinkButton.new_with_label(core.CF_KEY_URL, "Kostenlosen Key erzeugen (console.curseforge.com)")
        link.set_halign(Gtk.Align.START)
        box.pack_start(link, False, False, 0)
        clear = Gtk.CheckButton(label="Gespeicherten Key löschen")
        clear.set_sensitive(bool(current))
        box.pack_start(clear, False, False, 0)
        beta = Gtk.CheckButton(label="Beta-Versionen anzeigen")
        beta.set_active(bool(m.cfg["include_beta"]))
        box.pack_start(beta, False, False, 6)
        box.pack_start(Gtk.Label(xalign=0, use_markup=True, label="<b>AddOns-Ordner</b>"), False, False, 0)
        path = Gtk.Label(xalign=0, selectable=True, wrap=True, label=short_path(m.addons_dir) if m.addons_dir else "–")
        box.pack_start(path, False, False, 0)
        changed = []
        row = Gtk.Box(spacing=6)

        def change(*_):
            if choose_addons_dir(m, d):
                path.set_text(short_path(m.addons_dir))
                changed.append(True)
        b1 = Gtk.Button(label="Ändern / automatisch suchen …")
        b1.connect("clicked", change)
        row.pack_start(b1, False, False, 0)
        box.pack_start(row, False, False, 0)
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            if clear.get_active():
                m.set_cf_key("")
            elif key.get_text().strip():
                m.set_cf_key(key.get_text())
            m.set_include_beta(beta.get_active())
            changed.append(True)
        d.destroy()
        if changed:
            self.update_subtitle()
            self.rescan()

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

    # ------------------------------------------------------------ Screenshot-Modus
    def run_screenshots(self):
        a = self.args
        delay = int(a.screenshot_delay * 1000)

        def save(win, path):
            gw = win.get_window()
            pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
            pb.savev(str(path), "png", [], [])

        def fail(msg):
            print(msg, file=sys.stderr)
            self.exit_code = 1
            Gtk.main_quit()
            return False

        def wait_ready(start=time.time()):
            if not self.ready:
                return fail("Zeitüberschreitung beim Prüfen.") if time.time() - start > 180 else True
            GLib.timeout_add(delay, shoot_main)
            return False

        def shoot_main():
            save(self.win, a.screenshot)
            if a.screenshot_dialog == "new":
                dlg = NewAddonDialog(self.win, self.mgr)
                dlg.connect("response", lambda *_: None)
                start = time.time()

                def wait_dialog():
                    if not dlg.featured_loaded and time.time() - start < 60:
                        return True
                    GLib.timeout_add(delay, shoot_dialog, dlg)
                    return False
                GLib.timeout_add(200, wait_dialog)
            else:
                Gtk.main_quit()
            return False

        def shoot_dialog(dlg):
            save(dlg, Path(a.screenshot).with_name(Path(a.screenshot).stem + "-dialog.png"))
            dlg.destroy()
            Gtk.main_quit()
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
    args, _rest = ap.parse_known_args(argv)

    GLib.set_prgname(core.APP_NAME)
    GLib.set_application_name(TITLE)
    icon = load_icon(128)
    if icon:
        Gtk.Window.set_default_icon(icon)

    holder = {}
    mgr = Manager(log=lambda s: holder["app"].log(s) if "app" in holder else None)
    if mgr.needs_setup():
        if args.screenshot or not choose_addons_dir(mgr):
            return 1
    app = holder["app"] = App(mgr, args)
    app.exit_code = 0
    app.win.connect("delete-event", app.on_delete)
    app.win.connect("destroy", Gtk.main_quit)
    app.win.show_all()
    app.key_btn.set_visible(mgr.cf_key_state() in ("fehlt", "ungültig"))
    app.rescan()
    if args.screenshot:
        app.run_screenshots()
    Gtk.main()
    return app.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
