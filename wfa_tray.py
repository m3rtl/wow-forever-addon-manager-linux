"""Tray-Icon (StatusNotifierItem + dbusmenu) und Desktop-Benachrichtigungen, nur ueber Gio.DBus."""
import os
import sys
from pathlib import Path

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GLib, GdkPixbuf

_WATCHER = "org.kde.StatusNotifierWatcher"
_SNI_XML = """<node><interface name="org.kde.StatusNotifierItem">
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
<property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
<property name="WindowId" type="i" access="read"/><property name="IconName" type="s" access="read"/>
<property name="IconPixmap" type="a(iiay)" access="read"/>
<property name="OverlayIconName" type="s" access="read"/>
<property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
<property name="AttentionIconName" type="s" access="read"/>
<property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
<property name="AttentionMovieName" type="s" access="read"/>
<property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
<property name="ItemIsMenu" type="b" access="read"/><property name="Menu" type="o" access="read"/>
<signal name="NewTitle"/><signal name="NewIcon"/><signal name="NewAttentionIcon"/>
<signal name="NewOverlayIcon"/><signal name="NewToolTip"/>
<signal name="NewStatus"><arg type="s"/></signal>
</interface></node>"""
_MENU_XML = """<node><interface name="com.canonical.dbusmenu">
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
<arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/>
<arg type="a(ia{sv})" direction="out"/></method>
<method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<method name="AboutToShowGroup"><arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/></method>
<property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/>
<property name="Status" type="s" access="read"/><property name="IconThemePath" type="as" access="read"/>
<signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})"/><arg type="a(ia{sv})"/></signal>
<signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
<signal name="ItemActivationRequested"><arg type="i"/><arg type="u"/></signal>
</interface></node>"""

_instance_counter = 0


def _bus():
    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        return None


def _render(path, size, badge=False):
    """Icon als SNI-Pixmap (size, size, ARGB32 in Netzwerk-Byteorder); badge = goldener Punkt unten rechts."""
    pb = GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), size, size)
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    w, h, rs, nc = pb.get_width(), pb.get_height(), pb.get_rowstride(), pb.get_n_channels()
    src = pb.get_pixels()
    out = bytearray(size * size * 4)
    ox, oy = (size - w) // 2, (size - h) // 2
    for y in range(h):
        for x in range(w):
            i = y * rs + x * nc
            o = ((y + oy) * size + x + ox) * 4
            out[o:o + 4] = bytes((src[i + 3], src[i], src[i + 1], src[i + 2]))
    if badge:
        r = size * 0.24
        cx = cy = size - r - max(1.0, size / 32)
        for y in range(size):
            for x in range(size):
                d = ((x + .5 - cx) ** 2 + (y + .5 - cy) ** 2) ** .5
                if d <= r:
                    col = (0xFF, 0xD0, 0x2A) if d <= r - max(1.0, size / 24) else (0x3A, 0x2A, 0x00)
                    o = (y * size + x) * 4
                    out[o:o + 4] = bytes((255,) + col)
    return (size, size, bytes(out))


class Tray:
    def __init__(self, app_id, title, icon_path, on_activate):
        global _instance_counter
        _instance_counter += 1
        self.app_id, self.title, self.on_activate = app_id, title, on_activate
        self.available = False
        self._reg_ok = False      # beim Watcher registriert
        self._host_ok = True      # IsStatusNotifierHostRegistered
        self._sig_id = 0
        self._cbs = []
        self._tip = (title, "")
        self._status = "Active"
        self._items = []          # Liste (id, dict|None)
        self._revision = 1
        self._regs = []
        self._own_id = self._watch_id = 0
        self._closed = False
        self._pix = {False: [], True: []}
        try:
            for badge in (False, True):
                self._pix[badge] = [_render(icon_path, s, badge) for s in (22, 32, 48, 64)]
        except Exception as e:
            print(f"wfa_tray: Icon nicht renderbar: {e}", file=sys.stderr)
        self._conn = _bus()
        if self._conn is None:
            return
        try:
            if os.environ.get("FLATPAK_ID") or os.path.exists("/.flatpak-info"):
                # Im Flatpak darf das Programm keinen fremden Busnamen belegen; die Watcher (KDE, GNOME-Erweiterung)
                # akzeptieren auch den eindeutigen Namen der Verbindung (Objektpfad dann /StatusNotifierItem).
                self._name = self._conn.get_unique_name()
            else:
                self._name = f"org.kde.StatusNotifierItem-{os.getpid()}-{_instance_counter}"
            sni = Gio.DBusNodeInfo.new_for_xml(_SNI_XML).interfaces[0]
            menu = Gio.DBusNodeInfo.new_for_xml(_MENU_XML).interfaces[0]
            self._regs.append(self._conn.register_object(
                "/StatusNotifierItem", sni, self._sni_call, self._sni_get, None))
            self._regs.append(self._conn.register_object(
                "/MenuBar", menu, self._menu_call, self._menu_get, None))
            if not self._name.startswith(":"):
                self._own_id = Gio.bus_own_name_on_connection(
                    self._conn, self._name, Gio.BusNameOwnerFlags.NONE, None, None)
            self._watch_id = Gio.bus_watch_name_on_connection(
                self._conn, _WATCHER, Gio.BusNameWatcherFlags.NONE, self._appeared, self._vanished)
        except Exception as e:
            print(f"wfa_tray: Start fehlgeschlagen: {e}", file=sys.stderr)

    # --- oeffentliche API ---
    def connect_availability(self, cb):
        self._cbs.append(cb)

    def set_menu(self, items):
        self._items = []
        for n, it in enumerate(items, 1):
            self._items.append((n, it))
        self._revision += 1
        self._emit("/MenuBar", "com.canonical.dbusmenu", "LayoutUpdated",
                   GLib.Variant("(ui)", (self._revision, 0)))

    def set_tooltip(self, title, text=""):
        self._tip = (title, text)
        self._emit("/StatusNotifierItem", "org.kde.StatusNotifierItem", "NewToolTip", None)

    def set_attention(self, on):
        st = "NeedsAttention" if on else "Active"
        if st == self._status:
            return
        self._status = st
        base = "org.kde.StatusNotifierItem"
        self._emit("/StatusNotifierItem", base, "NewIcon", None)
        self._emit("/StatusNotifierItem", base, "NewAttentionIcon", None)
        self._emit("/StatusNotifierItem", base, "NewStatus", GLib.Variant("(s)", (st,)))

    def close(self):
        self._closed = True
        was = self.available
        self.available = False
        try:
            if self._sig_id:
                self._conn.signal_unsubscribe(self._sig_id)
            if self._watch_id:
                Gio.bus_unwatch_name(self._watch_id)
            for r in self._regs:
                self._conn.unregister_object(r)
            if self._own_id:
                Gio.bus_unown_name(self._own_id)
        except Exception:
            pass
        self._watch_id = self._own_id = self._sig_id = 0
        self._regs = []
        if was:
            self._fire()

    # --- Watcher ---
    def _appeared(self, conn, name, owner):
        if self._closed:
            return
        try:
            if not self._sig_id:
                self._sig_id = conn.signal_subscribe(
                    _WATCHER, _WATCHER, None, "/StatusNotifierWatcher", None, Gio.DBusSignalFlags.NONE,
                    self._host_signal)
            conn.call(_WATCHER, "/StatusNotifierWatcher", _WATCHER, "RegisterStatusNotifierItem",
                      GLib.Variant("(s)", (self._name,)), None, Gio.DBusCallFlags.NONE, 3000, None,
                      self._registered)
        except Exception as e:
            print(f"wfa_tray: Registrierung fehlgeschlagen: {e}", file=sys.stderr)
            self._set_available(False)

    def _registered(self, conn, res):
        try:
            conn.call_finish(res)
            ok = True
        except GLib.Error as e:
            print(f"wfa_tray: Registrierung fehlgeschlagen: {e.message}", file=sys.stderr)
            ok = False
        if self._closed:
            return
        self._reg_ok = ok
        if ok:
            self._query_host()
        else:
            self._update()

    def _vanished(self, conn, name):
        self._reg_ok = False
        self._update()

    def _host_signal(self, conn, sender, path, iface, sig, params):
        if sig.startswith("StatusNotifierHost") and not self._closed:
            self._query_host()

    def _query_host(self):
        def done(conn, res):
            if self._closed:
                return
            try:
                v = conn.call_finish(res).unpack()[0]
                self._host_ok = bool(v)
            except Exception:
                self._host_ok = True    # Property fehlt beim Watcher -> als vorhanden werten
            self._update()
        try:
            self._conn.call(_WATCHER, "/StatusNotifierWatcher", "org.freedesktop.DBus.Properties", "Get",
                            GLib.Variant("(ss)", (_WATCHER, "IsStatusNotifierHostRegistered")), None,
                            Gio.DBusCallFlags.NONE, 3000, None, done)
        except Exception:
            self._host_ok = True
            self._update()

    def _update(self):
        self._set_available(self._reg_ok and self._host_ok)

    def _set_available(self, v):
        if v != self.available:
            self.available = v
            self._fire()

    def _fire(self):
        for cb in list(self._cbs):
            try:
                cb(self.available)
            except Exception as e:
                print(f"wfa_tray: Callback-Fehler: {e}", file=sys.stderr)

    def _emit(self, path, iface, sig, params):
        if self._conn is None or self._closed:
            return
        try:
            self._conn.emit_signal(None, path, iface, sig, params)
        except GLib.Error:
            pass

    def _call(self, fn):
        if fn:
            try:
                fn()
            except Exception as e:
                print(f"wfa_tray: Callback-Fehler: {e}", file=sys.stderr)

    # --- StatusNotifierItem ---
    def _sni_get(self, conn, sender, path, iface, prop):
        att = self._status == "NeedsAttention"
        pix = lambda b: GLib.Variant("a(iiay)", self._pix[b])
        if prop == "Category": return GLib.Variant("s", "ApplicationStatus")
        if prop == "Id": return GLib.Variant("s", self.app_id)
        if prop == "Title": return GLib.Variant("s", self.title)
        if prop == "Status": return GLib.Variant("s", self._status)
        if prop == "WindowId": return GLib.Variant("i", 0)
        if prop in ("IconName", "OverlayIconName", "AttentionIconName", "AttentionMovieName"):
            return GLib.Variant("s", "")
        if prop == "IconPixmap": return pix(att)
        if prop == "AttentionIconPixmap": return pix(True)
        if prop == "OverlayIconPixmap": return GLib.Variant("a(iiay)", [])
        if prop == "ToolTip":
            return GLib.Variant("(sa(iiay)ss)", ("", self._pix[att], self._tip[0], self._tip[1]))
        if prop == "ItemIsMenu": return GLib.Variant("b", False)
        if prop == "Menu": return GLib.Variant("o", "/MenuBar")
        return None

    def _sni_call(self, conn, sender, path, iface, method, params, inv):
        if method in ("Activate", "SecondaryActivate"):
            self._call(self.on_activate)
        inv.return_value(None)

    # --- dbusmenu ---
    def _props(self, it):
        if it is None:
            return {"type": GLib.Variant("s", "separator")}
        return {"label": GLib.Variant("s", it.get("label", "")),
                "enabled": GLib.Variant("b", bool(it.get("enabled", True))),
                "visible": GLib.Variant("b", True)}

    def _tup(self, nid, depth):
        if nid == 0:
            kids = []
            if depth != 0:
                kids = [self._node(i, depth - 1) for i, _ in self._items]
            return (0, {"children-display": GLib.Variant("s", "submenu")}, kids)
        return (nid, self._props(dict(self._items).get(nid)), [])

    def _node(self, nid, depth):
        return GLib.Variant("(ia{sv}av)", self._tup(nid, depth))

    def _known(self, nid):
        return nid == 0 or nid in dict(self._items)

    def _menu_get(self, conn, sender, path, iface, prop):
        return {"Version": GLib.Variant("u", 3), "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"),
                "IconThemePath": GLib.Variant("as", [])}.get(prop)

    def _event(self, nid, etype):
        it = dict(self._items).get(nid)
        if etype == "clicked" and it and it.get("enabled", True):
            self._call(it.get("callback"))

    def _menu_call(self, conn, sender, path, iface, method, params, inv):
        try:
            if method == "GetLayout":
                pid, depth, _ = params.unpack()
                if not self._known(pid):
                    inv.return_dbus_error("com.canonical.dbusmenu.Error", "unknown id")
                    return
                inv.return_value(GLib.Variant("(u(ia{sv}av))", (self._revision, self._tup(pid, depth))))
            elif method == "GetGroupProperties":
                ids, _ = params.unpack()
                ids = ids or [0] + [i for i, _ in self._items]
                res = [(i, self._tup(i, 0)[1]) for i in ids if self._known(i)]
                inv.return_value(GLib.Variant("(a(ia{sv}))", (res,)))
            elif method == "GetProperty":
                nid, name = params.unpack()
                props = self._tup(nid, 0)[1] if self._known(nid) else {}
                if name not in props:
                    inv.return_dbus_error("com.canonical.dbusmenu.Error", "no property")
                    return
                inv.return_value(GLib.Variant("(v)", (props[name],)))
            elif method == "Event":
                nid, etype, _, _ = params.unpack()
                inv.return_value(None)
                self._event(nid, etype)
                return
            elif method == "EventGroup":
                evs = params.unpack()[0]
                inv.return_value(GLib.Variant("(ai)", ([],)))
                for nid, etype, _, _ in evs:
                    self._event(nid, etype)
                return
            elif method == "AboutToShow":
                inv.return_value(GLib.Variant("(b)", (False,)))
            elif method == "AboutToShowGroup":
                inv.return_value(GLib.Variant("(aiai)", ([], [])))
            else:
                inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
        except Exception as e:
            inv.return_dbus_error("com.canonical.dbusmenu.Error", str(e))


# --- Benachrichtigungen (org.freedesktop.Notifications) ---
_notif = {"sub": False, "actions": {}}


def _notif_signal(conn, sender, path, iface, sig, params):
    nid = params.unpack()[0]
    if sig == "ActionInvoked":
        cb = _notif["actions"].get(nid)
        if cb:
            try:
                cb(params.unpack()[1])
            except Exception as e:
                print(f"wfa_tray: Aktions-Fehler: {e}", file=sys.stderr)
    elif sig == "NotificationClosed":
        _notif["actions"].pop(nid, None)


def notify(title, body, icon_path=None, actions=None, on_action=None, replaces_id=0):
    """Sendet eine Benachrichtigung; -> id oder 0 bei Fehler. actions = [(id, label)]."""
    try:
        conn = _bus()
        if conn is None:
            return 0
        if not _notif["sub"]:
            conn.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications",
                                  None, "/org/freedesktop/Notifications", None,
                                  Gio.DBusSignalFlags.NONE, _notif_signal)
            _notif["sub"] = True
        flat = []
        for aid, label in actions or []:
            flat += [str(aid), str(label)]
        r = conn.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                           "org.freedesktop.Notifications", "Notify",
                           GLib.Variant("(susssasa{sv}i)", (
                               "WoW Forever Addon Manager", int(replaces_id or 0),
                               str(icon_path) if icon_path else "", str(title), str(body), flat,
                               {"desktop-entry": GLib.Variant("s", "wow-forever-addon-manager")}, -1)),
                           GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 3000, None)
        nid = r.unpack()[0]
        if on_action and flat:
            _notif["actions"][nid] = on_action
        return nid
    except Exception:
        return 0


def _demo():
    icon = Path(__file__).resolve().parent / "assets" / "icon.svg"
    loop = GLib.MainLoop()
    log = lambda s: print(s, flush=True)
    t = Tray("wfa-demo", "WFA Demo", icon, lambda: log("ACTIVATE"))
    t.connect_availability(lambda a: log(f"AVAILABLE {a}"))
    t.set_menu([dict(label="Aktualisieren", callback=lambda: log("CLICK aktualisieren"), bold=True),
                None, dict(label="Pruefen", callback=lambda: log("CLICK pruefen")),
                dict(label="Beenden", callback=loop.quit)])
    t.set_tooltip("WFA Demo", "Tooltip-Text")

    def later():
        t.set_attention(True)
        log(f"NOTIFY {notify('WFA Demo', 'Testbenachrichtigung', icon, [('open', 'Oeffnen')], lambda a: log('ACTION ' + a))}")
        return False
    GLib.timeout_add_seconds(3, later)
    loop.run()
    t.close()


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
