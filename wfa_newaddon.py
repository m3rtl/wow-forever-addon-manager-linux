"""Dialog „Neues Addon“: Durchsuchen mit Bildern/Tooltips, Sortierung, Seiten – und Direkt-Eingabe."""
from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

import wfa_gui as G  # noqa: E402
from wfa_core import ApiError  # noqa: E402
from wfa_i18n import N_, _, current, ngettext  # noqa: E402

PAGE_SIZE = 20
SORTS = (("downloads", N_("Downloads")), ("popularity", N_("Beliebtheit")), ("updated", N_("Zuletzt aktualisiert")),
         ("name", N_("Name")))
LOGO_SMALL, LOGO_BIG, SHOT_W, SHOT_H = 32, 96, 160, 110
CSS = """
.wfa-na-name { font-weight: bold; }
.wfa-na-tip-title { font-weight: bold; font-size: 14px; }
.wfa-na-muted { opacity: 0.7; }
"""

_img_slots = threading.Semaphore(4)


def _fit_square(pb, size):
    """Pixbuf zentriert in ein festes size x size Feld (transparent) einpassen, Seitenverhaeltnis bleibt."""
    w, h = pb.get_width(), pb.get_height()
    if w <= 0 or h <= 0:
        return pb
    k = min(size / w, size / h)
    nw, nh = max(1, round(w * k)), max(1, round(h * k))
    if (nw, nh) != (w, h):
        pb = pb.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)
    out = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, size, size)
    out.fill(0x00000000)
    pb.composite(out, (size - nw) // 2, (size - nh) // 2, nw, nh, (size - nw) // 2, (size - nh) // 2,
                 1, 1, GdkPixbuf.InterpType.NEAREST, 255)
    return out


def fmt_downloads(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return (f"{n / 1_000_000:.1f}".replace(".", ",") if current() == "de" else f"{n / 1_000_000:.1f}") + _(" Mio.")
    return f"{n:,}".replace(",", ".") if current() == "de" else f"{n:,}"


def fmt_date(iso):
    p = (iso or "")[:10].split("-")
    return _("{day}.{month}.{year}").format(day=p[2], month=p[1], year=p[0]) if len(p) == 3 and all(p) else ""


def _status(c):
    return _("installiert") if c.installed else (_("keine Forever-Datei") if c.has_forever is False else "")


class NewAddonDialog(Gtk.Dialog):
    """Ergebnis in self.result: ("cand", Candidate) | ("zip", Path) | ("input", str) | ("browser", str) | None."""

    def __init__(self, parent, mgr, query=""):
        super().__init__(title=_("Neues Addon"), transient_for=parent, modal=True, use_header_bar=True)
        self.mgr = mgr
        self.result = None
        self.featured_loaded = False
        self.loaded = False
        self.destroyed = False
        self.gen = 0
        self.page = 0
        self.sort = "downloads"
        self.query = ""
        self.forbidden = False
        self.fallback = False
        self.has_more = False
        self.pix = {}       # (url, groesse) -> Pixbuf | None
        self.pending = set()
        self._debounce = 0
        self.set_default_size(780, 600)
        self.connect("destroy", self._on_destroy)
        css = Gtk.CssProvider()
        css.load_from_data(CSS.encode())
        self.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._css = css
        self.add_button(_("Abbrechen"), Gtk.ResponseType.CANCEL)
        self.install_btn = G.add_button(self, _("Installieren"), Gtk.ResponseType.OK, suggested=True)
        self.install_btn.set_sensitive(False)
        box = self.get_content_area()
        box.set_spacing(8)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            box.set_property(m, 12)
        if G.THEME["on"]:
            box.pack_start(G.divider(False), False, False, 0)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        box.pack_start(Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.CENTER), False, False, 0)
        box.pack_start(self.stack, True, True, 0)
        self._build_browse()
        self._build_direct()
        self.stack.connect("notify::visible-child-name", lambda *_: self._update_btn())
        self.show_all()
        self.hint_box.hide()
        if query:   # vorbelegte Suche
            self.entry.set_text(query)
            self.query = query.strip()
        self._load()

    def _on_destroy(self, *_):
        self.destroyed = True
        self.gen += 1
        if self._debounce:
            GLib.source_remove(self._debounce)
            self._debounce = 0

    # ------------------------------------------------------------ Durchsuchen
    def _build_browse(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        top = Gtk.Box(spacing=6)
        self.entry = Gtk.SearchEntry(hexpand=True, placeholder_text=_("Filtern oder suchen: Addon-Name …"))
        self.entry.connect("search-changed", self._on_filter)
        self.entry.connect("activate", self._on_filter_now)
        top.pack_start(self.entry, True, True, 0)
        self.sort_box = Gtk.Box(spacing=6)
        self.sort_box.pack_start(Gtk.Label(label=_("Sortieren:")), False, False, 0)
        self.combo = Gtk.ComboBoxText()
        for k, t in SORTS:
            self.combo.append(k, _(t))
        self.combo.set_active_id("downloads")
        self.combo.connect("changed", self._on_sort)
        self.sort_box.pack_start(self.combo, False, False, 0)
        top.pack_start(self.sort_box, False, False, 0)
        page.pack_start(top, False, False, 0)

        # Kandidat, Logo, Name, Autor, Downloads, Aktualisiert, Status
        self.store = Gtk.ListStore(object, GdkPixbuf.Pixbuf, str, str, str, str, str)
        tree = self.tree = Gtk.TreeView(model=self.store)
        col = Gtk.TreeViewColumn(_("Addon"))
        col.set_expand(True)
        rp = Gtk.CellRendererPixbuf(xpad=4, ypad=2)
        col.pack_start(rp, False)
        col.add_attribute(rp, "pixbuf", 1)
        rt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        rt.set_property("xpad", 6)
        col.pack_start(rt, True)
        col.add_attribute(rt, "markup", 2)
        tree.append_column(col)
        for title, idx, align in ((_("Autor"), 3, 0), (_("Downloads"), 4, 1), (_("Aktualisiert"), 5, 0), ("", 6, 0)):
            r = Gtk.CellRendererText(xalign=align / 2 if align else 0, xpad=6)
            c = Gtk.TreeViewColumn(title, r, text=idx)
            tree.append_column(c)
        tree.get_selection().connect("changed", lambda *_: self._update_btn())
        tree.connect("row-activated", lambda *_: self.response(Gtk.ResponseType.OK))
        tree.set_has_tooltip(True)
        tree.connect("query-tooltip", self._on_tooltip)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(tree)
        page.pack_start(sw, True, True, 0)

        self.hint_box = Gtk.Box(spacing=8)
        self.hint_box.pack_start(Gtk.Label(
            xalign=0, wrap=True, hexpand=True,
            label=_("Die Suche ist für diesen API-Key nicht freigeschaltet.")), True, True, 0)
        b = Gtk.Button(label=_("Im Browser suchen"))
        b.connect("clicked", self._browser_search)
        self.hint_box.pack_start(b, False, False, 0)
        page.pack_start(self.hint_box, False, False, 0)

        bar = Gtk.Box(spacing=6)
        self.status = Gtk.Label(xalign=0, hexpand=True, label=_("Lade Addons …"))
        bar.pack_start(self.status, True, True, 0)
        self.pager = Gtk.Box(spacing=6)
        self.prev_btn = Gtk.Button(label=_("‹ Zurück"))
        self.next_btn = Gtk.Button(label=_("Weiter ›"))
        self.page_lbl = Gtk.Label(label=_("Seite {page}").format(page=1))
        self.prev_btn.connect("clicked", lambda *_: self._goto(self.page - 1))
        self.next_btn.connect("clicked", lambda *_: self._goto(self.page + 1))
        for w in (self.prev_btn, self.page_lbl, self.next_btn):
            self.pager.pack_start(w, False, False, 0)
        bar.pack_end(self.pager, False, False, 0)
        page.pack_start(bar, False, False, 0)
        self.stack.add_titled(page, "browse", _("Addons"))

    def _on_filter(self, *_):
        if self._debounce:
            GLib.source_remove(self._debounce)
        self._debounce = GLib.timeout_add(450, self._apply_filter)

    def _on_filter_now(self, *_):
        if self._debounce:
            GLib.source_remove(self._debounce)
        self._apply_filter()

    def _apply_filter(self):
        self._debounce = 0
        q = self.entry.get_text().strip()
        if q != self.query:
            self.query, self.page = q, 0
            self._load()
        return False

    def _on_sort(self, *_):
        s = self.combo.get_active_id()
        if s and s != self.sort:
            self.sort, self.page = s, 0
            self._load()

    def _goto(self, p):
        self.page = max(0, p)
        self._load()

    def _load(self):
        self.gen += 1
        gen = self.gen
        self.status.set_text(_("Lade …") if not self.query else _("Suche …"))
        self.hint_box.hide()
        self.prev_btn.set_sensitive(False)
        self.next_btn.set_sensitive(False)
        q, sort, page = self.query, self.sort, self.page
        if self.forbidden and not q:
            self._load_featured(gen)
            return
        self.fallback = False
        self._set_controls(True)

        def done(res, err):
            if self.destroyed or gen != self.gen:
                return False
            if isinstance(err, ApiError) and err.kind == "forbidden":
                self.forbidden = True
                if q:
                    self.store.clear()
                    self.status.set_text("")
                    self.hint_box.show_all()
                    self._finish_load()
                else:
                    self._load_featured(gen)
                return False
            if err:
                self.status.set_text(G.err_text(err))
                self._finish_load()
                return False
            cands, more = res
            self.has_more = more
            self._fill(cands)
            n = len(cands)
            self.status.set_text(
                (ngettext("1 Treffer", "{n} Treffer", n) if q else ngettext("1 Addon", "{n} Addons", n)).format(n=n)
                if n else (_("Keine Treffer") if q else _("Keine Addons")))
            self._finish_load()
            return False
        G.run_in_thread(lambda: self.mgr.browse(q, sort, page, PAGE_SIZE), done)

    def _load_featured(self, gen):
        self.fallback = True
        self.has_more = False
        self._set_controls(False)

        def done(res, err):
            if self.destroyed or gen != self.gen:
                return False
            if err:
                self.status.set_text(G.err_text(err))
            else:
                self._fill(res)
                self.status.set_text(
                    ngettext("1 Addon (Auswahl)", "{n} Addons (Auswahl)", len(res)).format(n=len(res)))
            self._finish_load()
            return False
        G.run_in_thread(self.mgr.featured, done)

    def _set_controls(self, full):
        self.sort_box.set_visible(full)
        self.pager.set_visible(full)

    def _finish_load(self):
        self.loaded = self.featured_loaded = True
        self.page_lbl.set_text(_("Seite {page}").format(page=self.page + 1))
        self.prev_btn.set_sensitive(self.page > 0 and not self.fallback)
        self.next_btn.set_sensitive(self.has_more and not self.fallback)

    def _fill(self, cands):
        self.store.clear()
        ph = self._placeholder()
        for c in cands:
            pb = self.pix.get((c.thumbnail_url, LOGO_SMALL)) or ph
            self.store.append([c, pb, f"<b>{GLib.markup_escape_text(c.name)}</b>", c.author or "",
                               fmt_downloads(c.downloads), fmt_date(c.updated), _status(c)])
            self._request(c.thumbnail_url, LOGO_SMALL)

    def _placeholder(self):
        pb = getattr(self, "_ph", None)
        if pb is None:
            try:
                pb = Gtk.IconTheme.get_default().load_icon("package-x-generic", LOGO_SMALL, 0)
            except GLib.Error:
                pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, LOGO_SMALL, LOGO_SMALL)
                pb.fill(0x3a446800)
            self._ph = _fit_square(pb, LOGO_SMALL)
        return pb

    # ------------------------------------------------------------ Bilder
    def _request(self, url, size):
        """Bild im Hintergrund holen und skalieren; danach Liste/Tooltip aktualisieren."""
        if not url or (url, size) in self.pix or (url, size) in self.pending:
            return
        self.pending.add((url, size))

        def work():
            pb = None
            with _img_slots:
                path = self.mgr.fetch_image(url)
                if path:
                    try:
                        sq = size in (LOGO_SMALL, LOGO_BIG)
                        w, h = (size, size) if sq else (SHOT_W, SHOT_H)
                        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(Path(path)), w, h, True)
                        if sq:
                            pb = _fit_square(pb, size)
                    except GLib.Error:
                        pb = None
            return pb

        def done(pb, err):
            self.pending.discard((url, size))
            if self.destroyed:
                return False
            self.pix[(url, size)] = None if err else pb
            if pb and size == LOGO_SMALL:
                for row in self.store:
                    if row[0].thumbnail_url == url:
                        row[1] = pb
            elif pb:
                self.tree.trigger_tooltip_query()
            return False
        G.run_in_thread(work, done)

    # ------------------------------------------------------------ Tooltip
    def _on_tooltip(self, tree, x, y, keyboard, tooltip):
        if keyboard:
            path, _c = tree.get_cursor()
        else:
            bx, by = tree.convert_widget_to_bin_window_coords(x, y)
            hit = tree.get_path_at_pos(bx, by)
            path = hit[0] if hit else None
        if path is None:
            return False
        tooltip.set_custom(self._tip_widget(self.store[path][0]))
        tree.set_tooltip_row(tooltip, path)
        return True

    def _tip_widget(self, c):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)
        head = Gtk.Box(spacing=10)
        logo = self.pix.get((c.thumbnail_url, LOGO_BIG))
        if c.thumbnail_url and logo is None and (c.thumbnail_url, LOGO_BIG) not in self.pix:
            self._request(c.thumbnail_url, LOGO_BIG)
        if logo:
            head.pack_start(Gtk.Image.new_from_pixbuf(logo), False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, valign=Gtk.Align.START)
        t = Gtk.Label(label=c.name, xalign=0, wrap=True, max_width_chars=40)
        t.get_style_context().add_class("wfa-na-tip-title")
        col.pack_start(t, False, False, 0)
        if c.author:
            col.pack_start(Gtk.Label(label=_("von {author}").format(author=c.author), xalign=0), False, False, 0)
        meta = [_("{count} Downloads").format(count=fmt_downloads(c.downloads))]
        if c.updated:
            meta.append(_("aktualisiert {date}").format(date=fmt_date(c.updated)))
        m = Gtk.Label(label=" · ".join(meta), xalign=0, wrap=True, max_width_chars=48)
        m.get_style_context().add_class("wfa-na-muted")
        col.pack_start(m, False, False, 0)
        if c.categories:
            col.pack_start(Gtk.Label(label=", ".join(c.categories), xalign=0, wrap=True, max_width_chars=48),
                           False, False, 0)
        head.pack_start(col, True, True, 0)
        outer.pack_start(head, False, False, 0)
        if c.summary:
            outer.pack_start(Gtk.Label(label=c.summary, xalign=0, wrap=True, max_width_chars=52, width_chars=40),
                             False, False, 0)
        shots = [s for s in (c.screenshots or []) if s.get("thumb")][:3]
        if shots:
            row = Gtk.Box(spacing=6)
            for s in shots:
                pb = self.pix.get((s["thumb"], SHOT_W))
                if pb:
                    row.pack_start(Gtk.Image.new_from_pixbuf(pb), False, False, 0)
                else:
                    if (s["thumb"], SHOT_W) not in self.pix:
                        self._request(s["thumb"], SHOT_W)
                    row.pack_start(Gtk.Spinner(active=True, width_request=SHOT_W // 2), False, False, 0)
            outer.pack_start(row, False, False, 0)
        outer.show_all()
        return outer

    # ------------------------------------------------------------ Direkt
    def _browser_search(self, *_):
        self.result = ("browser", self.entry.get_text().strip())
        self.response(Gtk.ResponseType.OK)

    def _build_direct(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.pack_start(Gtk.Label(
            xalign=0, wrap=True,
            label=_("CurseForge-Projekt-ID, gh:Besitzer/Repo, GitHub-URL oder direkter Zip-Link:")), False, False, 0)
        self.dentry = Gtk.Entry(placeholder_text=_("z. B. 3358  oder  gh:Besitzer/Repo  oder  https://…/addon.zip"))
        self.dentry.connect("changed", lambda *_: self._update_btn())
        self.dentry.connect("activate", lambda *_: self.install_btn.get_sensitive() and self.response(Gtk.ResponseType.OK))
        page.pack_start(self.dentry, False, False, 0)
        b = Gtk.Button(label=_("Zip-Datei wählen …"), halign=Gtk.Align.START)
        b.connect("clicked", self._pick_zip)
        page.pack_start(b, False, False, 0)
        self.stack.add_titled(page, "direct", _("Direkt"))

    def _pick_zip(self, *_a):
        f = Gtk.FileFilter()
        f.set_name(_("Zip-Archive"))
        f.add_pattern("*.zip")
        f.add_pattern("*.ZIP")
        path = G.choose_file(self, _("Zip-Datei wählen"), Gtk.FileChooserAction.OPEN, _("Öffnen"), filters=(f,))
        if path:
            self.result = ("zip", Path(path))
            self.response(Gtk.ResponseType.OK)

    # ------------------------------------------------------------ Ergebnis
    def _selected(self):
        model, it = self.tree.get_selection().get_selected()
        return model[it][0] if it else None

    def _update_btn(self):
        if self.stack.get_visible_child_name() == "direct":
            self.install_btn.set_sensitive(bool(self.dentry.get_text().strip()))
        else:
            self.install_btn.set_sensitive(self._selected() is not None)

    def finish(self):
        """Ergebnis nach response OK festhalten."""
        if self.result:
            return
        if self.stack.get_visible_child_name() == "direct":
            self.result = ("input", self.dentry.get_text().strip())
        else:
            c = self._selected()
            self.result = ("cand", c) if c else None
