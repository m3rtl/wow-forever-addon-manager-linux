"""Hintergrundbetrieb: Tray, periodische Pruefung, Benachrichtigungen, Auto-Update."""
import threading
import time

from gi.repository import GLib

import wfa_core as core
import wfa_selfupdate as selfupdate
import wfa_tray

APP_ID = "wow-forever-addon-manager"
TITLE = "WoW: Forever Addon-Manager"
WOW_WAIT_S = 300
BUSY_RETRY_S = 60


class Background:
    def __init__(self, app):
        self.app = app
        self.mgr = app.mgr
        self.cfg = app.mgr.cfg
        self.tray = None
        self.pkgs = []
        self.last_check = None
        self.wow_wait_s = WOW_WAIT_S
        self.interval_s = None      # ueberschreibt das Pruefintervall aus der Konfiguration
        self.release = None         # gefundene Programmversion
        self.restart_pending = False
        self._timer = 0
        self._retry = 0
        self._wow_wait = 0
        self._unknown_logged = False
        self._updating = False
        self._self_busy = False
        self._stopped = False

    @property
    def available(self):
        return bool(self.tray and self.tray.available)

    # --- Lebenszyklus ---
    def start(self, initial_check=True):
        try:
            self.tray = wfa_tray.Tray(APP_ID, TITLE, core.asset_path("icon.svg"), self._on_activate)
            self.tray.connect_availability(self._availability)
        except Exception as e:
            self.tray = None
            self._log(f"Tray nicht verfügbar: {e}")
        self.app.add_check_listener(self.on_checked)
        self._refresh()
        self.reschedule()
        if initial_check:
            GLib.idle_add(self._initial)
        else:
            GLib.idle_add(self._self_check)

    def _availability(self, avail):
        self._refresh()
        try:
            hidden = not self.app.win.get_visible()
        except Exception:
            hidden = False
        if not avail and hidden and not self._stopped:
            self.app.present()

    def refresh(self):
        """Menue, Tooltip und Attention aus app.pkgs neu berechnen (ohne Benachrichtigung)."""
        self.pkgs = list(getattr(self.app, "pkgs", self.pkgs))
        self._refresh()

    def _initial(self):
        self.check_now()
        self._self_check()
        return False

    def stop(self):
        self._stopped = True
        for n in ("_timer", "_retry", "_wow_wait"):
            if getattr(self, n):
                GLib.source_remove(getattr(self, n))
                setattr(self, n, 0)
        if self.tray:
            self.tray.close()
            self.tray = None

    def reschedule(self):
        if self._timer:
            GLib.source_remove(self._timer)
        secs = self.interval_s or max(15, int(self.cfg["check_interval_min"])) * 60
        self._timer = GLib.timeout_add_seconds(int(secs), self._tick)

    def _tick(self):
        if self._stopped:
            return False
        self.check_now()
        self._self_check()
        return True

    def check_now(self):
        if self._stopped:
            return
        if self.app.busy:
            if not self._retry:
                self._retry = GLib.timeout_add_seconds(BUSY_RETRY_S, self._retry_cb)
            return
        try:
            self.app.rescan(then=self._scan_done, quiet=True)
        except Exception as e:
            self._log(f"Hintergrundprüfung fehlgeschlagen: {e}")

    def _retry_cb(self):
        self._retry = 0
        self.check_now()
        return False

    def _scan_done(self, pkgs, err):
        if err:
            self._log(f"Hintergrundprüfung: {err}")

    def _log(self, msg):
        try:
            self.app.log(msg)
        except Exception:
            print(msg)

    # --- Ergebnis einer Pruefung ---
    def on_checked(self, pkgs):
        self.pkgs = list(pkgs)
        self.last_check = time.localtime()
        self._refresh()
        ups = self.mgr.updatable(self.pkgs)
        self._notify_updates(ups)
        if ups and self.cfg["auto_update"]:
            self._auto_update()

    def _sig(self, ups):
        return sorted(f"{p.key}={p.remote.version if p.remote else ''}" for p in ups)

    def _notify_updates(self, ups):
        sig = self._sig(ups)
        with self.cfg.lock:
            d = dict(self.cfg["tray_notified"] or {})
            if d.get("sig") == sig:
                return
            d["sig"] = sig
            self.cfg["tray_notified"] = d
            self.cfg.save()
        if not ups:
            return
        names = [p.name for p in ups]
        body = ", ".join(names[:5]) + (f" und {len(names) - 5} weitere" if len(names) > 5 else "")
        n = len(ups)
        wfa_tray.notify(f"{n} Update{'s' if n != 1 else ''} verfügbar", body, core.asset_path("icon.svg"),
                        [("default", "Öffnen"), ("update", "Aktualisieren"), ("open", "Öffnen")],
                        self._on_notify_action)

    def _on_notify_action(self, aid):
        if aid == "update":
            self._update_now(background=False)
        else:
            self.app.present()

    # --- Aktualisieren ---
    def _update_now(self, background=True):
        ups = self.mgr.updatable(self.pkgs)
        if not ups or self._updating:
            if not background:
                self.app.present()
            return
        if not background:
            self.app.present()
        self._updating = True
        self._refresh()
        try:
            self.app.update_packages(ups, background=background, done=self._update_done)
        except Exception as e:
            self._updating = False
            self._refresh()
            self._log(f"Update fehlgeschlagen: {e}")

    def _tray_update(self):
        """Klick im Tray: still im Hintergrund (wartet ggf., bis WoW beendet ist). Ist nicht erkennbar, ob WoW
        laeuft (Flatpak ohne Host-Zugriff), wuerde das nie installieren -> dann der Weg mit Bestaetigung."""
        self._update_now(background=self.mgr.wow_running() is not None)

    def _update_done(self, res):
        self._updating = False
        self._refresh()
        res = res or {}
        if res.get("interactive"):
            return
        if res.get("deferred"):
            if not self._wow_wait and not self._stopped:
                self._wow_wait = GLib.timeout_add_seconds(self.wow_wait_s, self._wow_cb)
            return
        ok, failed = res.get("ok") or [], res.get("failed") or []
        if ok:
            n = len(ok)
            body = ", ".join(ok[:5]) + (f" und {n - 5} weitere" if n > 5 else "")
            if failed:
                body += "\nFehlgeschlagen: " + ", ".join(failed)
            wfa_tray.notify(f"{n} Addon{'s' if n != 1 else ''} aktualisiert", body, core.asset_path("icon.svg"),
                            [("open", "Öffnen")], lambda _a: self.app.present())
        elif failed:
            wfa_tray.notify("Aktualisierung fehlgeschlagen", "Fehlgeschlagen: " + ", ".join(failed),
                            core.asset_path("icon.svg"), [("open", "Öffnen")], lambda _a: self.app.present())

    def _auto_update(self):
        if self._wow_wait or self._updating:
            return
        running = self.mgr.wow_running()
        if running is None:
            # Flatpak ohne Host-Zugriff: nicht erkennbar, ob WoW laeuft -> nur benachrichtigen
            if not self._unknown_logged:
                self._unknown_logged = True
                self._log("Auto-Update ausgesetzt: Im Flatpak ist nicht erkennbar, ob WoW läuft "
                          f"(Freigabe: {core.WOW_DETECT_OVERRIDE}).")
            return
        if running:
            self._wow_wait = GLib.timeout_add_seconds(self.wow_wait_s, self._wow_cb)
            return
        self._update_now(background=True)

    def _wow_cb(self):
        if self._stopped:
            return False
        running = self.mgr.wow_running()
        if running:
            return True
        self._wow_wait = 0
        if running is None:
            return False
        if self.app.busy:
            self._wow_wait = GLib.timeout_add_seconds(BUSY_RETRY_S, self._wow_cb)
            return False
        if self.mgr.updatable(self.pkgs):
            self._update_now(background=True)
        return False

    # --- Tray ---
    def _on_activate(self):
        win = self.app.win
        try:
            if win.get_visible() and win.is_active():
                win.hide()
                return
        except Exception:
            pass
        self.app.present()

    def _refresh(self):
        if not self.tray or self._stopped:
            return
        n = len(self.mgr.updatable(self.pkgs))
        if self._updating:
            first = dict(label="Aktualisiere …", callback=None, enabled=False, bold=True)
        elif n:
            first = dict(label=f"{n} Addon{'s' if n != 1 else ''} aktualisieren",
                         callback=self._tray_update, bold=True)
        else:
            first = dict(label="Keine Updates", callback=None, enabled=False, bold=True)
        items = [first]
        if self.release:
            items.append(dict(label=f"Addon-Manager v{self.release.version} installieren",
                              callback=self._self_install_clicked))
        items += [
            dict(label="Jetzt prüfen", callback=self.check_now),
            dict(label="App öffnen", callback=self.app.present),
            dict(label="Einstellungen …", callback=self._settings),
            dict(label="Protokoll …", callback=self._show_log),
            None,
            dict(label="Beenden", callback=self.app.quit),
        ]
        self.tray.set_menu(items)
        when = time.strftime("%H:%M", self.last_check) if self.last_check else "–"
        self.tray.set_tooltip(f"{n} Update{'s' if n != 1 else ''} verfügbar" if n else "Alle Addons aktuell",
                              f"Zuletzt geprüft: {when}")
        self.tray.set_attention(n > 0)

    def _settings(self):
        self.app.present()
        self.app.on_settings()

    def _show_log(self):
        self.app.present()
        self.app.show_log()

    # --- Programm-Update ---
    def _self_check(self):
        if self._stopped or self._self_busy or not self.cfg["self_update_check"] or not selfupdate.enabled() \
                or not selfupdate.due(self.cfg):
            return False
        self._self_busy = True

        def work():
            rel = err = None
            try:
                rel = selfupdate.check()
            except Exception as e:
                err = e
            GLib.idle_add(self._self_checked, rel, err)

        threading.Thread(target=work, daemon=True).start()
        return False

    def _self_checked(self, rel, err):
        self._self_busy = False
        if err:
            self._log(f"Programm-Updateprüfung: {err}")
            return False
        selfupdate.mark_checked(self.cfg)
        if rel is None or rel.version == self.cfg["self_update_skipped"] \
                or rel.version == selfupdate.installed_pending():
            return False
        self.release = rel
        self._refresh()
        try:
            self.app.on_self_update_available(rel)
        except Exception:
            pass
        with self.cfg.lock:
            d = dict(self.cfg["tray_notified"] or {})
            seen = d.get("self_notified") == rel.version
            d["self_notified"] = rel.version
            self.cfg["tray_notified"] = d
            self.cfg.save()
        if self.cfg["self_auto_update"] and selfupdate.can_self_update():
            self._self_auto(rel)
        elif not seen:
            wfa_tray.notify(f"Addon-Manager v{rel.version} verfügbar", "Eine neue Programmversion ist erschienen.",
                            core.asset_path("icon.svg"),
                            [("default", "Details"), ("update", "Aktualisieren"), ("details", "Details")],
                            self._on_self_action)
        return False

    def _on_self_action(self, aid):
        if not self.release:
            return
        self.app.present()
        self.app.self_update(self.release, interactive=(aid == "update"))

    def _self_install_clicked(self):
        if self.release:
            self.app.present()
            self.app.self_update(self.release, interactive=True)

    def _self_auto(self, rel):
        if rel.version == selfupdate.installed_pending():
            return

        def work():
            err = None
            try:
                selfupdate.install(rel)
            except Exception as e:
                err = e
            GLib.idle_add(self._self_installed, rel, err)

        threading.Thread(target=work, daemon=True).start()

    def _self_installed(self, rel, err):
        if err:
            self._log(f"Programm-Update fehlgeschlagen: {err}")
            return False
        self.release = None
        hidden = not self.app.win.get_visible()
        if hidden and not self.app.busy:
            self.app.restart_self()
        else:
            wfa_tray.notify("Update installiert – Neustart", f"Version {rel.version} ist installiert.",
                            core.asset_path("icon.svg"), [("default", "Neu starten"), ("restart", "Neu starten")],
                            lambda _a: self.app.restart_self())
        return False
