"""Flatpak: Autostart ueber das Hintergrund-Portal (org.freedesktop.portal.Background), nur ueber Gio.DBus.

In der Sandbox liegt ~/.config/autostart nicht auf dem Host; das Portal legt den Eintrag dort an
(Exec = flatpak run ... --tray) bzw. entfernt ihn wieder."""
from gi.repository import Gio, GLib

import wfa_core as core

_BUS = "org.freedesktop.portal.Desktop"
_PATH = "/org/freedesktop/portal/desktop"
_REQUEST = "org.freedesktop.portal.Request"
_counter = 0


def request_autostart(on, done, parent_window=""):
    """Autostart (Start im Tray) setzen bzw. entfernen. done(ok, text) kommt im Hauptthread;
    ok=True heisst: der gewuenschte Zustand ist erreicht."""
    global _counter
    try:
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as e:
        done(False, e.message)
        return
    _counter += 1
    token = f"wfa_autostart_{_counter}_{GLib.random_int()}"
    sender = conn.get_unique_name().lstrip(":").replace(".", "_")
    handle = f"{_PATH}/request/{sender}/{token}"
    state = {"sub": 0, "done": False}

    def finish(ok, text):
        if state["sub"]:
            conn.signal_unsubscribe(state["sub"])
            state["sub"] = 0
        if not state["done"]:
            state["done"] = True
            done(ok, text)

    def on_response(_c, _sender, _path, _iface, _sig, params):
        code, results = params.unpack()
        if code != 0:
            finish(False, "Abgebrochen." if code == 1 else "Das Hintergrund-Portal hat die Anfrage abgelehnt.")
            return
        got = bool(results.get("autostart", False))
        if got == bool(on):
            finish(True, "")
        else:
            finish(False, "Autostart wurde nicht erlaubt (Einstellungen → Apps → Hintergrund).")

    # vor dem Aufruf abonnieren, sonst kann die Antwort verloren gehen
    state["sub"] = conn.signal_subscribe(_BUS, _REQUEST, "Response", handle, None,
                                         Gio.DBusSignalFlags.NO_MATCH_RULE, on_response)
    opts = {
        "handle_token": GLib.Variant("s", token),
        "reason": GLib.Variant("s", "Beim Systemstart im Tray auf Addon-Updates prüfen"),
        "autostart": GLib.Variant("b", bool(on)),
        "commandline": GLib.Variant("as", [core.APP_NAME, "--tray"]),
        "dbus-activatable": GLib.Variant("b", False),
    }

    def called(c, res):
        try:
            c.call_finish(res)
        except GLib.Error as e:
            finish(False, f"Hintergrund-Portal nicht erreichbar: {e.message}")

    try:
        conn.call(_BUS, _PATH, "org.freedesktop.portal.Background", "RequestBackground",
                  GLib.Variant("(sa{sv})", (parent_window, opts)), GLib.VariantType("(o)"),
                  Gio.DBusCallFlags.NONE, -1, None, called)
    except Exception as e:  # noqa: BLE001
        finish(False, str(e))
