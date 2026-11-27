"""Erweiterte Dialoge: Addons je Charakter und Sets, Aufraeumen (mit Papierkorb), Gesamtstaende, Fehleranalyse."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

import wfa_bugs  # noqa: E402
import wfa_chars  # noqa: E402
import wfa_cleanup  # noqa: E402
import wfa_core as core  # noqa: E402
import wfa_gui as G  # noqa: E402
import wfa_health  # noqa: E402
import wfa_newaddon  # noqa: E402
import wfa_sets  # noqa: E402
import wfa_snapshot  # noqa: E402
from wfa_i18n import N_, _, ngettext  # noqa: E402
from wfa_toc import clean_title, toc_meta  # noqa: E402

KIND_LABEL = {"orphan_sv": N_("Einstellungen ohne Addon"), "nested": N_("Verschachtelter Ordner"),
              "no_toc": N_("Ordner ohne TOC"), "duplicate": N_("Doppelter Ordner"), "shared": N_("Geteilter Ordner")}
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


def merge_findings(found, conflicts):
    """Funde zusammenfuehren; derselbe Ordner als Duplikat und als no_toc/nested wird nur einmal gelistet (Duplikat gewinnt)."""
    dup = {f.path for f in conflicts if f.kind == "duplicate"}
    return [f for f in found if f.path not in dup] + list(conflicts)


def esc(text):
    return GLib.markup_escape_text(text)


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
        super().__init__(app, _("Addons je Charakter und Sets"), 560, 560)
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
        self.set_plan = None   # Plan des gewaehlten Sets (Vorschau, noch nichts geschrieben)
        srow = Gtk.Box(spacing=6)
        srow.pack_start(Gtk.Label(label=_("Set")), False, False, 0)
        self.set_combo = Gtk.ComboBoxText()
        srow.pack_start(self.set_combo, True, True, 0)
        self.save_set_btn = self.button(srow, _("Speichern als …"), self.on_set_save)
        self.rename_set_btn = self.button(srow, _("Umbenennen …"), self.on_set_rename)
        self.delete_set_btn = self.button(srow, _("Löschen"), self.on_set_delete)
        self.body.pack_start(srow, False, False, 0)
        self.fill_sets()
        self.set_combo.connect("changed", lambda *_a: self.on_set_changed())
        self.hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=64,
                              label=_("Bei „Alle Charaktere“ ist ein Addon angehakt, wenn es bei allen aktiv ist."))
        self.hint.get_style_context().add_class("wfa-dim")
        self.hint.set_no_show_all(True)
        self.body.pack_start(self.hint, False, False, 0)
        self.set_hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=64, use_markup=True)
        self.set_hint.get_style_context().add_class("wfa-dim")
        self.set_hint.set_no_show_all(True)
        self.body.pack_start(self.set_hint, False, False, 0)

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
        self.combo.connect("changed", lambda *_a: self.on_char_changed())
        self.load()

    def targets(self):
        i = self.combo.get_active()
        return list(self.chars) if i >= len(self.chars) else [self.chars[i]]

    def set_name(self):
        """Name des gewaehlten Sets oder None."""
        return self.set_combo.get_active_text() if self.set_combo.get_active() > 0 else None

    def fill_sets(self, select=None):
        self.set_combo.remove_all()
        self.set_combo.append_text(_("(kein Set)"))
        names = wfa_sets.list_sets(self.mgr.cfg)
        for n in names:
            self.set_combo.append_text(n)
        self.set_combo.set_active(names.index(select) + 1 if select in names else 0)

    def sync_sets(self):
        on = self.set_name() is not None
        self.rename_set_btn.set_sensitive(on)
        self.delete_set_btn.set_sensitive(on)

    def on_char_changed(self):
        self.set_plan = None
        self.set_combo.set_active(0)   # loest on_set_changed aus; bei schon 0 laedt load() hier
        self.load()

    def on_set_changed(self):
        self.sync_sets()
        name = self.set_name()
        self.set_plan = None
        self.set_hint.set_visible(False)
        if name is None:
            self.status.set_text("")
            self.load()   # Haken wieder auf den echten Zustand
            return
        folders = wfa_sets.get_set(self.mgr.cfg, name)
        if folders is None:
            return
        plan = wfa_sets.plan_set(folders, self.mgr.addons_dir, self.mgr.client_interface)
        self.set_plan = plan
        on = 0
        for r in self.store:
            r[0] = bool(plan.changes.get(r[2], False))
            on += r[0]
        self.status.set_text(_("Set „{name}“: {on} an, {off} aus.").format(name=name, on=on, off=len(self.store) - on))
        lines = []
        if plan.deps_added:
            lines.append(esc(_("Zusätzlich aktiv (Abhängigkeit): {names}").format(names=", ".join(plan.deps_added))))
        if plan.missing:
            lines.append('<span foreground="{}">{}</span>'.format(
                G.ORANGE, esc(_("Im Set, aber nicht installiert: {names}").format(names=", ".join(plan.missing)))))
        self.set_hint.set_markup("\n".join(lines))
        self.set_hint.set_visible(bool(lines))

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
        self.sync_sets()

    def on_toggled(self, _r, path):
        self.store[path][0] = not self.store[path][0]

    def on_apply(self):
        name = self.set_name()
        if name is not None:
            changes = {r[2]: r[0] for r in self.store}   # Set geladen: voller Zustand, nicht nur die Differenz
        else:
            changes = {r[2]: r[0] for r in self.store if r[0] != r[3]}
        if not changes or (name is None and not any(r[0] != r[3] for r in self.store)):
            self.status.set_text(_("Keine Änderungen."))
            return
        targets = self.targets()
        if not wow_guard(self.d, self.mgr):
            return
        if name is not None and len(targets) > 1 and not G.ask(
                self.d, _("Set „{name}“ auf alle {n} Charaktere anwenden?").format(name=name, n=len(targets)),
                _("Die bisherigen AddOns.txt werden gesichert."), _("Anwenden")):
            return
        try:
            wfa_chars.write_states_all(targets, changes, self.mgr.paths.data_dir / "addons_txt_backups",
                                       install=self.mgr.install_id())
        except OSError as e:
            self.fail(e)
            return
        if name is not None:
            text = _("Set „{name}“ angewendet ({n} Charaktere).").format(name=name, n=len(targets))
            self.app.log(text)
        else:
            text = ngettext("{n} Änderung übernommen.", "{n} Änderungen übernommen.", len(changes)).format(n=len(changes))
            self.app.log(_("Addons je Charakter: {text}").format(text=text))
        self.load()
        self.set_combo.set_active(0)
        self.status.set_text(text)

    def ask_name(self, title, initial=""):
        d = G.make_dialog(title, self.d, 420)
        d.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        ok = G.add_button(d, _("Speichern"), Gtk.ResponseType.OK, suggested=True)
        d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.pack_start(Gtk.Label(xalign=0, label=_("Name des Sets")), False, False, 0)
        entry = Gtk.Entry(activates_default=True, text=initial)
        ok.set_sensitive(bool(initial.strip()))
        entry.connect("changed", lambda e: ok.set_sensitive(bool(e.get_text().strip())))
        box.pack_start(entry, False, False, 0)
        d.show_all()
        go = d.run() == Gtk.ResponseType.OK
        text = entry.get_text().strip()
        d.destroy()
        return text if go and text else None

    def on_set_save(self):
        name = self.ask_name(_("Set speichern"))
        if not name:
            return
        if name in wfa_sets.list_sets(self.mgr.cfg) and not G.ask(
                self.d, _("Set „{name}“ überschreiben?").format(name=name), "", _("Überschreiben"),
                kind=Gtk.MessageType.WARNING):
            return
        folders = wfa_sets.set_from_states({r[2]: r[0] for r in self.store}, [r[2] for r in self.store])
        try:
            wfa_sets.save_set(self.mgr.cfg, name, folders)
        except OSError as e:
            self.fail(e)
            return
        self.fill_sets(name)
        self.status.set_text(_("Set „{name}“ gespeichert.").format(name=name))

    def on_set_rename(self):
        old = self.set_name()
        if old is None:
            return
        new = self.ask_name(_("Set umbenennen"), old)
        if not new or new == old:
            return
        if not wfa_sets.rename_set(self.mgr.cfg, old, new):
            G.message(self.d, _("Das hat nicht geklappt"), _("Der Name „{name}“ ist schon vergeben.").format(name=new),
                      Gtk.MessageType.ERROR)
            return
        self.fill_sets(new)

    def on_set_delete(self):
        name = self.set_name()
        if name is None or not G.ask(self.d, _("Set „{name}“ löschen?").format(name=name),
                                     _("Es ändert sich nichts an den Charakteren."), _("Löschen"),
                                     kind=Gtk.MessageType.WARNING):
            return
        wfa_sets.delete_set(self.mgr.cfg, name)
        self.fill_sets()


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
        self.store = Gtk.ListStore(bool, str, str, str, object, bool, str)   # Haken, Art, Name, Groesse, Fund, ankreuzbar, Tooltip
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_tooltip_column(6)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", lambda _r, p: self.store[p][5] and self.store[p].__setitem__(0, not self.store[p][0]))
        self.tree.append_column(Gtk.TreeViewColumn("", tog, active=0, activatable=5, visible=5))
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
        pkgs = list(getattr(self.app, "pkgs", None) or [])
        self.work(lambda: (merge_findings(wfa_cleanup.scan(self.mgr.addons_dir, wtf), self.conflict_findings(pkgs)),
                           wfa_cleanup.disk_usage(self.usage_paths())), self.loaded, _("Suche …"))

    def conflict_findings(self, pkgs):
        """Konflikte der letzten Pruefung als Funde: Duplikate (ankreuzbar) und geteilte Ordner (nur Hinweis)."""
        names = {p.key: p.name for p in pkgs}
        base = Path(self.mgr.addons_dir)
        out = []
        for c in wfa_health.conflicts(pkgs, base):
            if c.kind == "duplicate":
                for f in c.folders[1:]:   # der erste ist der zu behaltende
                    path = base / f
                    out.append(wfa_cleanup.Finding("duplicate", path, wfa_cleanup._size(path),
                                                   _("Doppelt vorhanden: {folders}").format(folders=", ".join(c.folders))))
            elif c.kind == "shared_folder":
                path = base / c.folders[0]
                who = ", ".join(names.get(k, k) for k in c.keys)
                out.append(wfa_cleanup.Finding("shared", path, 0, who))
        return out

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
            tip = ""
            if f.kind == "shared":
                tip = _("Gehört zu {names}. Eines davon deinstallieren oder per Rechtsklick → „Zuordnen …“ korrigieren."
                        ).format(names=f.detail)
            elif f.kind == "duplicate":
                tip = f.detail
            self.store.append([f.kind in KIND_DEFAULT_ON, _(KIND_LABEL.get(f.kind, f.kind)), f.path.name,
                               core.fmt_size(f.size) if f.kind != "shared" else "", f, f.kind != "shared", tip])
        self.empty.set_text("" if findings else _("Nichts zum Aufräumen gefunden."))
        self.clean_btn.set_sensitive(any(f.kind != "shared" for f in findings))

    def on_clean(self):
        picked = [r[4] for r in self.store if r[0] and r[5]]
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
        # Der Kern kennt "duplicate" nicht; ein Doppelordner wandert wie ein Ordner ohne TOC in den Papierkorb
        todo = list(picked)
        legacy = self.mgr.legacy_install()
        self.work(lambda: wfa_cleanup.apply(todo, self.mgr.addons_dir, trash, legacy=legacy), self.cleaned, _("Räume auf …"))

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
        self.app.pack_install_line(self.body)
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
        for path, created, n in wfa_cleanup.list_sets(self.trash, install=self.mgr.install_id(),
                                                      legacy=self.mgr.legacy_install()):
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
        inst, legacy = self.mgr.install_id(), self.mgr.legacy_install()
        self.work(lambda: wfa_cleanup.restore_set(path, install=inst, legacy=legacy), self.restored, _("Lege zurück …"))

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
        self.app.pack_install_line(self.body)
        self.body.pack_start(Gtk.Label(xalign=0, wrap=True, max_width_chars=70,
                                       label=_("Ein Gesamtstand sichert alle Addons und die Einstellungen aller Konten (WTF)."),
                                       ), False, False, 0)
        self.store = Gtk.ListStore(str, str, str, str, object, str)   # Datum, Bezeichnung, Addons, Groesse, Satz, Art
        self.tree = Gtk.TreeView(model=self.store)
        _text_col(self.tree, _("Datum"), 0)
        _text_col(self.tree, _("Art"), 5)
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
        for s in self.mgr.list_snapshots():
            self.store.append([fmt_iso(s.created), self.snap_label(s), str(len(s.addons)), core.fmt_size(s.size), s,
                               _("automatisch") if s.auto else _("manuell")])
        self.empty.set_text("" if len(self.store) else _("Noch keine Gesamtstände vorhanden."))
        self.sync()

    @staticmethod
    def snap_label(s):
        if s.auto:
            d = s.reason_data or {}
            if s.reason_kind == "bulk" and "n" in d:
                return _("Vor Update von {n} Addons").format(n=d["n"])
            if s.reason_kind == "client" and "old" in d and "new" in d:
                return _("WoW-Update {old} → {new}").format(old=d["old"], new=d["new"])
            return s.reason or s.label or ""
        return _(s.label) if s.label else ""

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
        self.work(lambda: m.create_snapshot(label), self.created, _("Sichere …"))

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
        self.work(lambda: m.restore_snapshot(snap), self.restored, _("Stelle wieder her …"))

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


# ---------------------------------------------------------------- Fehleranalyse

def fmt_dt(t):
    return t.strftime("%d.%m.%Y %H:%M") if t else "–"


def _upd_text(e):
    """'{old} → {new}, {datum}' fuer einen Verlaufseintrag."""
    ver = "{} → {}".format(e.get("old") or "–", e.get("new") or "–")
    t = wfa_bugs._ts(e)
    return "{}, {}".format(ver, t.strftime("%d.%m.%Y")) if t else ver


class BugsDialog(_Base):
    def __init__(self, app):
        super().__init__(app, _("Fehleranalyse"), 780, 540)
        self.after = None   # Aktion, die nach dem Schliessen laeuft (Zuruecksetzen, Verlauf)
        self.groups = []
        self.head = Gtk.Label(xalign=0, wrap=True, max_width_chars=90)
        self.head.get_style_context().add_class("wfa-dim")
        self.body.pack_start(self.head, False, False, 0)
        self.running = Gtk.Label(xalign=0, wrap=True, max_width_chars=90, use_markup=True)
        self.running.set_no_show_all(True)
        self.body.pack_start(self.running, False, False, 0)
        # Addon, Fehler, Seit Update, Letztes Update, Zuletzt, Gewicht, Farbe, Gruppe
        self.store = Gtk.ListStore(str, str, str, str, str, int, str, object)
        self.tree = Gtk.TreeView(model=self.store)
        for i, (title, expand) in enumerate(((_("Addon"), True), (_("Fehler"), False), (_("Seit Update"), False),
                                              (_("Letztes Update"), False), (_("Zuletzt"), False))):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE,
                                     xalign=1.0 if i in (1, 2) else 0.0)
            c = Gtk.TreeViewColumn(title, r, text=i)
            if i == 0:
                c.add_attribute(r, "weight", 5)
                c.add_attribute(r, "foreground", 6)
            c.set_expand(expand)
            c.set_resizable(True)
            self.tree.append_column(c)
        self.list_box = _scroller(self.tree)
        self.body.pack_start(self.list_box, True, True, 0)
        self.empty = Gtk.Label(xalign=0, label=_("Keine Fehler aufgezeichnet."))
        self.empty.set_no_show_all(True)
        self.body.pack_start(self.empty, False, False, 0)
        self.verdict = Gtk.Label(xalign=0, wrap=True, max_width_chars=90)
        self.body.pack_start(self.verdict, False, False, 0)
        self.text_box = G.text_view_scroller("", 560, 160)
        self.text = self.text_box.get_child()
        self.body.pack_start(self.text_box, False, False, 0)
        foot = Gtk.Label(xalign=0, wrap=True, max_width_chars=90,
                         label=_("Ein Fehler zählt zu dem Addon, in dessen Dateien er auftritt. "
                                 "Der Auslöser kann ein anderes Addon sein."))
        foot.get_style_context().add_class("wfa-dim")
        self.body.pack_start(foot, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.rollback_btn = self.button(row, _("Zurücksetzen …"), self.on_rollback, destructive=True)
        self.hist_btn = self.button(row, _("Verlauf …"), self.on_history)
        self.copy_btn = self.button(row, _("Fehlertext kopieren"), self.on_copy)
        self.button(row, _("Neu laden"), self.load)
        self.body.pack_start(row, False, False, 0)
        self.tree.get_selection().connect("changed", lambda *_a: self.sync())
        self.load()

    def folder_map(self):
        out = {}
        for p in getattr(self.app, "pkgs", None) or []:
            for f in p.folders:
                out[f] = (p.key, p.name)
        return out

    def load(self):
        wtf, fmap = self.mgr.wtf_dir(), self.folder_map()
        hist = self.mgr.read_history()

        def job():
            errs = wfa_bugs.load_errors(wtf)
            return sum(e.count for e in errs), wfa_bugs.group_errors(errs, fmap, hist)
        self.work(job, self.loaded, _("Lese Fehler …"))

    def loaded(self, res, err):
        if not self.alive:
            return
        if err:
            self.fail(err)
            return
        total, self.groups = res
        self.store.clear()
        known = self.folder_map()
        for g in self.groups:
            new = g.since_update > 0 and g.before_update == 0 and g.last_update is not None
            name = g.name
            if g.key.startswith("folder:") and g.folders and g.folders[0] not in known:
                name = _("{name} (nicht verwaltet)").format(name=g.name)
            since = _("{n} (neu)").format(n=g.since_update) if new else (str(g.since_update) if g.last_update else "–")
            self.store.append([name, str(g.count), since, _upd_text(g.last_update) if g.last_update else "–",
                               fmt_dt(g.last), Pango.Weight.BOLD if new else Pango.Weight.NORMAL,
                               G.ORANGE if new else None, g])
        self.head.set_text(ngettext("{n} Fehler in 1 Addon, aufgezeichnet von !BugGrabber.",
                                    "{n} Fehler in {m} Addons, aufgezeichnet von !BugGrabber.", len(self.groups))
                           .format(n=total, m=len(self.groups)))
        if self.mgr.wow_running():
            self.running.set_markup('<span foreground="{}">{}</span>'.format(
                G.ORANGE, esc(_("WoW läuft: Stand vom letzten Abmelden oder /reload."))))
            self.running.show()
        else:
            self.running.hide()
        self.list_box.set_visible(bool(self.groups))
        self.text_box.set_visible(bool(self.groups))
        self.empty.set_visible(not self.groups)
        self.sync()

    def selected(self):
        model, it = self.tree.get_selection().get_selected()
        return model[it][7] if it is not None else None

    def sync(self):
        g = self.selected()
        self.hist_btn.set_sensitive(g is not None)
        self.copy_btn.set_sensitive(g is not None)
        backup = (g.last_update or {}).get("backup") if g else None
        ok = bool(backup) and backup in {b.name for b in self.mgr.list_backups()}
        self.rollback_btn.set_sensitive(ok)
        self.rollback_btn.set_tooltip_text(None if ok or g is None or not g.last_update else
                                           _("Für dieses Update gibt es kein Backup mehr."))
        if g is None:
            self.verdict.set_text("")
            self.text.get_buffer().set_text("")
            return
        lu = g.last_update
        if not lu:
            self.verdict.set_text(_("Kein Update im Verlauf – Zuordnung nicht möglich."))
        else:
            t = wfa_bugs._ts(lu)
            date = t.strftime("%d.%m.%Y") if t else "–"
            old, new = lu.get("old") or "–", lu.get("new") or "–"
            if g.before_update == 0:
                self.verdict.set_text(_("Alle {n} Fehler traten nach dem Update vom {date} auf ({old} → {new}).")
                                      .format(n=g.since_update, date=date, old=old, new=new))
            else:
                self.verdict.set_text(_("{a} Fehler seit dem Update vom {date}, {b} schon davor.")
                                      .format(a=g.since_update, date=date, b=g.before_update))
        self.text.get_buffer().set_text("\n\n----\n\n".join(g.samples))

    def on_rollback(self):
        g = self.selected()
        if g is None or not g.last_update:
            return
        backups = {b.name: b for b in self.mgr.list_backups()}
        b = backups.get(g.last_update.get("backup"))
        if b is None:
            return
        fl = g.last_update.get("folders")
        only = [f for f in fl if isinstance(f, str)] if isinstance(fl, list) else None
        if not wow_guard(self.d, self.mgr):
            return
        app = self.app

        def go():   # nach dem Schliessen, damit die Rueckfrage nicht hinter dem Dialog liegt
            def ok():
                app.log(_("Zurückgesetzt. Die Fehlerliste ändert sich erst nach dem nächsten Spielen."))
            app.restore_backup_flow(b, only, on_done=ok)
        self.after = go
        self.d.response(Gtk.ResponseType.CLOSE)

    def on_history(self):
        g = self.selected()
        if g is None:
            return
        app, name = self.app, g.name
        self.after = lambda: app.on_history(name=name)
        self.d.response(Gtk.ResponseType.CLOSE)

    def on_copy(self):
        g = self.selected()
        if g is not None:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("\n\n----\n\n".join(g.samples), -1)
            self.status.set_text(_("Fehlertext kopiert."))


def open_errors(app):
    mgr = app.mgr
    if not mgr.addons_dir:
        G.message(app.win, _("Kein AddOns-Ordner gewählt"), _("Bitte zuerst in den Einstellungen einen AddOns-Ordner wählen."))
        return
    if not wfa_bugs.bug_grabber_installed(mgr.addons_dir):
        if G.ask(app.win, _("!BugGrabber ist nicht installiert"),
                 _("Die Fehleranalyse wertet aus, was das Addon !BugGrabber im Spiel aufzeichnet. Installiere es, "
                   "spiele eine Runde und öffne die Analyse danach erneut."), _("!BugGrabber suchen …")):
            d = wfa_newaddon.NewAddonDialog(app.win, mgr, query="BugGrabber")
            r = d.run()
            if r == Gtk.ResponseType.OK:
                d.finish()
            result = d.result if r == Gtk.ResponseType.OK else None
            d.destroy()
            if result:
                app.handle_new(*result)
        return
    wtf = mgr.wtf_dir()
    if not (wtf and wfa_bugs.bug_files(wtf)):
        G.message(app.win, _("Noch keine Fehlerdaten"),
                  _("!BugGrabber hat noch nichts gespeichert. WoW schreibt die Datei beim Abmelden oder mit /reload."))
        return
    dlg = BugsDialog(app)
    dlg.run()
    if dlg.after:
        dlg.after()
