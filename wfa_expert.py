"""Erweiterte Dialoge: Addons je Charakter, Aufraeumen (mit Papierkorb) und Gesamtstaende."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango  # noqa: E402

import wfa_chars  # noqa: E402
import wfa_cleanup  # noqa: E402
import wfa_core as core  # noqa: E402
import wfa_gui as G  # noqa: E402
import wfa_snapshot  # noqa: E402
from wfa_i18n import N_, _, ngettext  # noqa: E402
from wfa_toc import clean_title, toc_meta  # noqa: E402

KIND_LABEL = {"orphan_sv": N_("Einstellungen ohne Addon"), "nested": N_("Verschachtelter Ordner"),
              "no_toc": N_("Ordner ohne TOC")}
KIND_DEFAULT_ON = ("orphan_sv", "nested")


def wow_guard(parent, mgr):
    """True, wenn geschrieben werden darf: WoW laeuft nicht (bei unbekanntem Zustand nach Rueckfrage)."""
    running = mgr.wow_running()
    if running:
        G.message(parent, _("WoW läuft"), _("Bitte WoW zuerst beenden. Sonst überschreibt es die Änderungen "
                                             "beim Beenden wieder."), Gtk.MessageType.WARNING)
        return False
    if running is None and not G.ask(parent, _("Ist WoW beendet?"),
                                     _("Im Flatpak kann der Manager nicht sehen, ob WoW läuft. Läuft es noch, "
                                       "überschreibt es die Änderungen beim Beenden wieder."),
                                     _("WoW ist beendet"), no=_("Abbrechen"), kind=Gtk.MessageType.WARNING):
        return False
    return True


def fmt_iso(s):
    try:
        return datetime.fromisoformat(s).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return s


def _text_col(tree, title, col, expand=False, xalign=0.0):
    r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE, xalign=xalign)
    c = Gtk.TreeViewColumn(title, r, text=col)
    c.set_expand(expand)
    c.set_resizable(True)
    tree.append_column(c)


def _scroller(tree):
    sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    sw.set_shadow_type(Gtk.ShadowType.IN)
    sw.add(tree)
    return sw


class _Base:
    """Dialoggeruest: Inhalt in self.body, unten Status mit Spinner; self.work() faehrt lange Arbeit im Thread."""

    def __init__(self, app, title, width, height, parent=None):
        self.app, self.mgr = app, app.mgr
        self.d = G.make_dialog(title, parent or app.win, width, height)
        self.d.add_button(_("Schließen"), Gtk.ResponseType.CLOSE)
        self.alive = True
        self.busy = False
        self.d.connect("destroy", lambda *_a: setattr(self, "alive", False))
        box = self.d.get_content_area()
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(self.body, True, True, 0)
        row = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.status.get_style_context().add_class("wfa-dim")
        row.pack_start(self.spinner, False, False, 0)
        row.pack_start(self.status, True, True, 0)
        box.pack_start(row, False, False, 0)

    @property
    def parent(self):
        return self.d if self.alive else self.app.win

    def run(self):
        self.d.show_all()
        self.d.run()
        self.d.destroy()

    def work(self, fn, cb, text):
        """fn im Thread, danach cb(res, err) im GTK-Thread (auch bei geschlossenem Dialog; dann self.alive pruefen)."""
        if self.busy:
            return
        self.busy = True
        self.body.set_sensitive(False)
        self.spinner.start()
        self.status.set_text(text)

        def done(res, err):
            self.busy = False
            if self.alive:
                self.spinner.stop()
                self.status.set_text("")
                self.body.set_sensitive(True)
            cb(res, err)
        G.run_in_thread(fn, done)

    def fail(self, err):
        G.message(self.parent, _("Das hat nicht geklappt"), G.err_text(err), Gtk.MessageType.ERROR)

    def button(self, row, label, cb, **kw):
        b = Gtk.Button(label=label)
        if kw.get("suggested"):
            b.get_style_context().add_class("suggested-action")
        if kw.get("destructive"):
            b.get_style_context().add_class("destructive-action")
        b.connect("clicked", lambda *_a: cb())
        row.pack_start(b, False, False, 0)
        return b


# ---------------------------------------------------------------- Addons je Charakter

class CharactersDialog(_Base):
    def __init__(self, app, chars, folders):
        super().__init__(app, _("Addons je Charakter"), 560, 560)
        self.chars, self.folders = chars, folders
        multi = len({c.account for c in chars}) > 1
        names = [_("{name} – {realm} (Konto {account})").format(name=c.name, realm=c.realm, account=c.account) if multi
                 else _("{name} – {realm}").format(name=c.name, realm=c.realm) for c in chars]
        self.combo = Gtk.ComboBoxText()
        for n in names + [_("Alle Charaktere")]:
            self.combo.append_text(n)
        self.combo.set_active(0)
        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Label(label=_("Charakter")), False, False, 0)
        top.pack_start(self.combo, True, True, 0)
        self.body.pack_start(top, False, False, 0)
        self.hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=64,
                              label=_("Bei „Alle Charaktere“ ist ein Addon angehakt, wenn es bei allen aktiv ist."))
        self.hint.get_style_context().add_class("wfa-dim")
        self.hint.set_no_show_all(True)
        self.body.pack_start(self.hint, False, False, 0)

        self.store = Gtk.ListStore(bool, str, str, bool)   # aktiv, Titel, Ordner, Ausgangswert
        self.tree = Gtk.TreeView(model=self.store)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self.on_toggled)
        self.tree.append_column(Gtk.TreeViewColumn("", tog, active=0))
        _text_col(self.tree, _("Addon"), 1, expand=True)
        _text_col(self.tree, _("Ordner"), 2)
        self.tree.set_search_column(1)
        self.body.pack_start(_scroller(self.tree), True, True, 0)
        row = Gtk.Box(spacing=6)
        self.apply_btn = self.button(row, _("Übernehmen"), self.on_apply, suggested=True)
        self.body.pack_start(row, False, False, 0)
        self.combo.connect("changed", lambda *_a: self.load())
        self.load()

    def targets(self):
        i = self.combo.get_active()
        return list(self.chars) if i >= len(self.chars) else [self.chars[i]]

    def load(self):
        self.hint.set_visible(self.combo.get_active() >= len(self.chars))
        try:
            states = [wfa_chars.read_states(c) for c in self.targets()]
        except OSError as e:
            states = []
            self.fail(e)
        self.store.clear()
        for folder, title in self.folders:
            on = bool(states) and all(wfa_chars.is_enabled(s, folder) for s in states)
            self.store.append([on, title or folder, folder, on])

    def on_toggled(self, _r, path):
        self.store[path][0] = not self.store[path][0]

    def on_apply(self):
        changes = {r[2]: r[0] for r in self.store if r[0] != r[3]}
        if not changes:
            self.status.set_text(_("Keine Änderungen."))
            return
        if not wow_guard(self.d, self.mgr):
            return
        try:
            wfa_chars.write_states_all(self.targets(), changes, self.mgr.paths.data_dir / "addons_txt_backups")
        except OSError as e:
            self.fail(e)
            return
        text = ngettext("{n} Änderung übernommen.", "{n} Änderungen übernommen.", len(changes)).format(n=len(changes))
        self.app.log(_("Addons je Charakter: {text}").format(text=text))
        self.load()
        self.status.set_text(text)


def open_characters(app):
    mgr = app.mgr
    if not mgr.addons_dir:
        G.message(app.win, _("Kein AddOns-Ordner gewählt"), _("Bitte zuerst in den Einstellungen einen AddOns-Ordner wählen."))
        return
    wtf = mgr.wtf_dir()
    chars = wfa_chars.list_characters(wtf) if wtf else []
    if not chars:
        G.message(app.win, _("Keine Charaktere gefunden"),
                  _("Im WTF-Ordner gibt es noch keine Charaktere. Sobald du dich mit einem Charakter in WoW "
                    "angemeldet hast, erscheint er hier."))
        return
    folders = []
    try:
        subdirs = sorted((c for c in Path(mgr.addons_dir).iterdir() if c.is_dir() and not c.name.startswith(".")),
                         key=lambda c: c.name.lower())
    except OSError as e:
        G.message(app.win, _("Das hat nicht geklappt"), G.err_text(e), Gtk.MessageType.ERROR)
        return
    for c in subdirs:
        if any(f.name.lower().endswith(".toc") for f in c.iterdir() if f.is_file()):
            folders.append((c.name, clean_title(toc_meta(c).get("title", ""))))
    CharactersDialog(app, chars, folders).run()


# ---------------------------------------------------------------- Aufraeumen

class CleanupDialog(_Base):
    def __init__(self, app):
        super().__init__(app, _("Aufräumen"), 620, 560)
        self.grid = Gtk.Grid(column_spacing=16, row_spacing=2)
        self.body.pack_start(self.grid, False, False, 0)
        self.body.pack_start(Gtk.Label(xalign=0, use_markup=True, label="<b>{}</b>".format(_("Gefundenes"))), False, False, 0)
        self.store = Gtk.ListStore(bool, str, str, str, object)   # Haken, Art, Name, Groesse, Fund
        self.tree = Gtk.TreeView(model=self.store)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", lambda _r, p: self.store[p].__setitem__(0, not self.store[p][0]))
        self.tree.append_column(Gtk.TreeViewColumn("", tog, active=0))
        _text_col(self.tree, _("Art"), 1)
        _text_col(self.tree, _("Name"), 2, expand=True)
        _text_col(self.tree, _("Größe"), 3, xalign=1.0)
        self.body.pack_start(_scroller(self.tree), True, True, 0)
        self.empty = Gtk.Label(xalign=0)
        self.empty.get_style_context().add_class("wfa-dim")
        self.body.pack_start(self.empty, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.clean_btn = self.button(row, _("Ausgewählte aufräumen"), self.on_clean, suggested=True)
        self.button(row, _("Papierkorb …"), self.on_trash)
        self.body.pack_start(row, False, False, 0)
        self.refresh()

    def usage_paths(self):
        p = self.mgr.paths
        return {_("Addons"): self.mgr.addons_dir, _("Backups"): p.backups,
                _("Einstellungs-Schnappschüsse (SavedVariables)"): p.sv_backups,
                _("Gesamtstände"): p.data_dir / "snapshots", _("Papierkorb"): p.data_dir / "trash",
                _("Cache"): p.cache}

    def refresh(self):
        wtf = self.mgr.wtf_dir()
        self.work(lambda: (wfa_cleanup.scan(self.mgr.addons_dir, wtf), wfa_cleanup.disk_usage(self.usage_paths())),
                  self.loaded, _("Suche …"))

    def loaded(self, res, err):
        if not self.alive:
            return
        if err:
            self.fail(err)
            return
        findings, usage = res
        for c in self.grid.get_children():
            self.grid.remove(c)
        for i, (name, size) in enumerate(usage.items()):
            self.grid.attach(Gtk.Label(label=name, xalign=0), 0, i, 1, 1)
            self.grid.attach(Gtk.Label(label=core.fmt_size(size), xalign=1.0), 1, i, 1, 1)
        self.grid.show_all()
        self.store.clear()
        for f in findings:
            self.store.append([f.kind in KIND_DEFAULT_ON, _(KIND_LABEL.get(f.kind, f.kind)), f.path.name,
                               core.fmt_size(f.size), f])
        self.empty.set_text("" if findings else _("Nichts zum Aufräumen gefunden."))
        self.clean_btn.set_sensitive(bool(findings))

    def on_clean(self):
        picked = [r[4] for r in self.store if r[0]]
        if not picked:
            self.status.set_text(_("Nichts angehakt."))
            return
        if not wow_guard(self.d, self.mgr):
            return
        if not G.ask(self.d, _("Ausgewählte Funde aufräumen?"),
                     _("Sie werden in den Papierkorb des Managers verschoben und lassen sich dort über "
                       "„Papierkorb …“ zurücklegen."), _("Aufräumen")):
            return
        trash = self.mgr.paths.data_dir / "trash"
        self.work(lambda: wfa_cleanup.apply(picked, self.mgr.addons_dir, trash), self.cleaned, _("Räume auf …"))

    def cleaned(self, res, err):
        if err:
            self.fail(err)
            return
        bad = [msg for _f, ok, msg in res if not ok]
        self.app.log(_("Aufräumen: {n} von {m} verschoben.").format(n=len(res) - len(bad), m=len(res)))
        if bad:
            G.message(self.parent, _("Nicht alles ließ sich aufräumen"), "\n".join(bad), Gtk.MessageType.WARNING)
        if any(f.kind != "orphan_sv" and ok for f, ok, _m in res):
            self.app.rescan()
        if self.alive:
            self.refresh()

    def on_trash(self):
        TrashDialog(self.app, self.d, self.refresh_if_alive).run()

    def refresh_if_alive(self):
        if self.alive:
            self.refresh()


class TrashDialog(_Base):
    def __init__(self, app, parent, changed):
        super().__init__(app, _("Papierkorb"), 480, 360, parent)
        self.trash = self.mgr.paths.data_dir / "trash"
        self.changed = changed
        self.store = Gtk.ListStore(str, str, object)   # Datum, Anzahl, Pfad
        self.tree = Gtk.TreeView(model=self.store)
        _text_col(self.tree, _("Datum"), 0, expand=True)
        _text_col(self.tree, _("Einträge"), 1, xalign=1.0)
        self.body.pack_start(_scroller(self.tree), True, True, 0)
        self.empty = Gtk.Label(xalign=0)
        self.empty.get_style_context().add_class("wfa-dim")
        self.body.pack_start(self.empty, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.back_btn = self.button(row, _("Zurücklegen"), self.on_back, suggested=True)
        self.body.pack_start(row, False, False, 0)
        self.tree.get_selection().connect("changed", lambda *_a: self.sync())
        self.load()

    def load(self):
        self.store.clear()
        for path, created, n in wfa_cleanup.list_sets(self.trash):
            self.store.append([created.strftime("%d.%m.%Y %H:%M:%S"), str(n), path])
        self.empty.set_text("" if len(self.store) else _("Der Papierkorb ist leer."))
        self.sync()

    def sync(self):
        self.back_btn.set_sensitive(self.tree.get_selection().get_selected()[1] is not None)

    def on_back(self):
        model, it = self.tree.get_selection().get_selected()
        if it is None or not wow_guard(self.d, self.mgr):
            return
        path = model[it][2]
        self.work(lambda: wfa_cleanup.restore_set(path), self.restored, _("Lege zurück …"))

    def restored(self, errors, err):
        self.app.rescan()
        if err:
            self.fail(err)
        elif errors:
            G.message(self.parent, _("Nicht alles ließ sich zurücklegen"),
                      _("Konflikte, bereits Vorhandenes wurde nicht überschrieben:") + "\n" + "\n".join(errors),
                      Gtk.MessageType.WARNING)
        else:
            self.app.log(_("Papierkorb: Satz zurückgelegt."))
        self.changed()
        if self.alive:
            self.load()


def open_cleanup(app):
    if not app.mgr.addons_dir:
        G.message(app.win, _("Kein AddOns-Ordner gewählt"), _("Bitte zuerst in den Einstellungen einen AddOns-Ordner wählen."))
        return
    CleanupDialog(app).run()


# ---------------------------------------------------------------- Gesamtstaende

class SnapshotsDialog(_Base):
    def __init__(self, app):
        super().__init__(app, _("Gesamtstände"), 620, 420)
        self.root = self.mgr.paths.data_dir / "snapshots"
        self.body.pack_start(Gtk.Label(xalign=0, wrap=True, max_width_chars=70,
                                       label=_("Ein Gesamtstand sichert alle Addons und die Einstellungen aller Konten (WTF)."),
                                       ), False, False, 0)
        self.store = Gtk.ListStore(str, str, str, str, object)   # Datum, Bezeichnung, Addons, Groesse, Satz
        self.tree = Gtk.TreeView(model=self.store)
        _text_col(self.tree, _("Datum"), 0)
        _text_col(self.tree, _("Bezeichnung"), 1, expand=True)
        _text_col(self.tree, _("Addons"), 2, xalign=1.0)
        _text_col(self.tree, _("Größe"), 3, xalign=1.0)
        self.body.pack_start(_scroller(self.tree), True, True, 0)
        self.empty = Gtk.Label(xalign=0)
        self.empty.get_style_context().add_class("wfa-dim")
        self.body.pack_start(self.empty, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.button(row, _("Jetzt sichern …"), self.on_create, suggested=True)
        self.restore_btn = self.button(row, _("Wiederherstellen"), self.on_restore, destructive=True)
        self.delete_btn = self.button(row, _("Löschen"), self.on_delete)
        self.body.pack_start(row, False, False, 0)
        self.tree.get_selection().connect("changed", lambda *_a: self.sync())
        self.load()

    def load(self):
        self.store.clear()
        for s in wfa_snapshot.list_snapshots(self.root):
            self.store.append([fmt_iso(s.created), s.label, str(len(s.addons)), core.fmt_size(s.size), s])
        self.empty.set_text("" if len(self.store) else _("Noch keine Gesamtstände vorhanden."))
        self.sync()

    def selected(self):
        model, it = self.tree.get_selection().get_selected()
        return model[it][4] if it is not None else None

    def sync(self):
        on = self.selected() is not None
        self.restore_btn.set_sensitive(on)
        self.delete_btn.set_sensitive(on)

    def on_create(self):
        d = G.make_dialog(_("Gesamtstand sichern"), self.d, 420)
        d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        G.add_button(d, _("Sichern"), Gtk.ResponseType.OK, suggested=True)
        d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(xalign=0, label=_("Bezeichnung (optional)")), False, False, 0)
        entry = Gtk.Entry(activates_default=True)
        box.pack_start(entry, False, False, 0)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        label = entry.get_text().strip()
        d.destroy()
        if not ok:
            return
        m = self.mgr
        self.work(lambda: wfa_snapshot.create(m.addons_dir, m.wtf_dir(), self.root, label, m.client_version or ""),
                  self.created, _("Sichere …"))

    def created(self, snap, err):
        if err:
            self.fail(err)
            return
        self.app.log(_("Gesamtstand {id} angelegt.").format(id=snap.id))
        if self.alive:
            self.load()
            self.status.set_text(_("Gesamtstand angelegt."))

    def on_restore(self):
        snap = self.selected()
        if snap is None or not wow_guard(self.d, self.mgr):
            return
        if not G.ask(self.d, _("Gesamtstand wiederherstellen?"),
                     _("Die aktuellen Ordner AddOns und WTF werden durch den Stand vom {date} ersetzt. "
                       "Vorher wird der jetzige Stand automatisch gesichert.").format(date=fmt_iso(snap.created)),
                     _("Wiederherstellen"), kind=Gtk.MessageType.WARNING):
            return
        m = self.mgr
        self.work(lambda: wfa_snapshot.restore(snap, m.addons_dir, m.wtf_dir(), self.root),
                  self.restored, _("Stelle wieder her …"))

    def restored(self, safety, err):
        if err:
            self.fail(err)
            return
        self.app.log(_("Gesamtstand wiederhergestellt, vorheriger Stand: {id}.").format(id=safety.id))
        self.app.rescan()
        G.message(self.parent, _("Gesamtstand wiederhergestellt"),
                  _("Der vorherige Stand wurde als {id} gesichert.").format(id=safety.id))
        if self.alive:
            self.load()

    def on_delete(self):
        snap = self.selected()
        if snap is None:
            return
        if not G.ask(self.d, _("Gesamtstand löschen?"), _("Der Stand vom {date} wird endgültig gelöscht.")
                     .format(date=fmt_iso(snap.created)), _("Löschen"), kind=Gtk.MessageType.WARNING):
            return
        try:
            wfa_snapshot.delete(snap)
        except OSError as e:
            self.fail(e)
        self.load()


def open_snapshots(app):
    if not app.mgr.addons_dir:
        G.message(app.win, _("Kein AddOns-Ordner gewählt"), _("Bitte zuerst in den Einstellungen einen AddOns-Ordner wählen."))
        return
    SnapshotsDialog(app).run()
