"""Unbeaufsichtigtes Update (z. B. als Steam-Startoption vor dem Spielstart). GUI-frei, ohne Rueckfragen."""
from __future__ import annotations

import os
import shlex
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from wfa_base import APP_ID, APP_NAME, ApiError, ERROR, install_kind
from wfa_i18n import _, ngettext

TOTAL_TIMEOUT_S = 150   # Planung (Pruefen, Laden) darf den Spielstart nicht laenger aufhalten
EXIT_OK, EXIT_ERROR, EXIT_SKIPPED = 0, 1, 2


@dataclass
class UnattendedResult:
    updated: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: str | None = None
    exit_code: int = EXIT_OK


def _err(e):
    return str(e) or type(e).__name__


def plan_with_deps(mgr, pkgs, log=None):
    """Plaene fuer pkgs samt fehlenden CurseForge-Pflichtabhaengigkeiten. -> (plans, [(name, fehler)])."""
    log = log or (lambda s: None)
    plans, errs = [], []
    for p in pkgs:
        try:
            plans.append(mgr.plan_update(p))
        except Exception as e:  # noqa: BLE001
            errs.append((p.name, _err(e)))
    if plans:
        try:
            needs = mgr.resolve_deps(plans, cf_only=True)
        except Exception as e:  # noqa: BLE001
            log(_("Abhängigkeiten nicht prüfbar: {error}").format(error=_err(e)))
            needs = []
        for d in needs:
            if not (d.cand and d.via == "cf"):
                log(_("Abhängigkeit fehlt: {name} ({reason}) – {note}").format(
                    name=d.name, reason=d.reason, note=d.note or _("nicht automatisch installierbar")))
                continue
            try:
                plans.append(mgr.plan_candidate(d.cand))
                log(_("Abhängigkeit wird mitinstalliert: {name}").format(name=d.name))
            except Exception as e:  # noqa: BLE001
                errs.append((d.name, _err(e)))
    return plans, errs


def launch_command(flatpak=None) -> str:
    """Aufruf des laufenden Programms fuer Startoptionen/Skripte (Shell-quotiert, ohne Argumente)."""
    kind = install_kind()
    if flatpak or (flatpak is None and kind == "flatpak"):
        return "flatpak run " + APP_ID
    if kind == "binary":
        return shlex.quote(sys.executable)
    if kind == "package":
        return shlex.quote(shutil.which(APP_NAME) or APP_NAME)
    return shlex.quote(str(Path(__file__).resolve().parent / "start.sh"))


def write_prelaunch_script(path) -> Path:
    """Schreibt ein ausfuehrbares sh-Skript (0755), das vor dem Spielstart still aktualisiert."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n{} --update --quiet\n".format(launch_command()), "utf-8")
    os.chmod(path, 0o755)
    return path


def run_update(manager, log=print, quiet=False, timeout=None) -> UnattendedResult:
    """Prueft und aktualisiert veraltete Addons ohne Rueckfragen (ignorierte und festgehaltene bleiben aussen vor,
    der Kanal wird beachtet). Laeuft WoW, passiert nichts. Zeitlimit gilt fuer Pruefung und Download."""
    res = UnattendedResult()
    say = (lambda s: None) if quiet else log
    limit = TOTAL_TIMEOUT_S if timeout is None else timeout

    def summary():
        n = len(res.updated)
        if res.skipped:
            log(res.skipped)
        elif n:
            log(ngettext("1 Addon aktualisiert: {names}", "{n} Addons aktualisiert: {names}", n)
                .format(n=n, names=", ".join(res.updated)))
        elif not res.failed:
            log(_("Alle Addons aktuell."))
        for name, msg in res.failed:
            log(_("Fehler bei {name}: {error}").format(name=name, error=msg))
        return res

    if manager.needs_setup():
        res.failed.append((_("Einrichtung"), _("Kein AddOns-Ordner eingerichtet.")))
        res.exit_code = EXIT_ERROR
        return summary()
    # None (Flatpak ohne Host-Zugriff): nicht erkennbar; als Pre-Launch laeuft WoW noch nicht, also aktualisieren
    if manager.wow_running():
        res.skipped = _("WoW läuft: keine Aktualisierung.")
        res.exit_code = EXIT_SKIPPED
        return summary()

    state = {"phase": "plan", "plans": [], "errs": [], "results": None, "error": None}

    def work():
        try:
            say(_("Prüfe Versionen ..."))
            pkgs = manager.scan()
            manager.check(pkgs, cancel=manager.dl_cancel)
            for n in manager.notes:
                say(n)
            state["errs"] += [(p.name, p.note or _("Prüfung fehlgeschlagen")) for p in pkgs if p.status == ERROR]
            ups = [p for p in manager.updatable(pkgs) if p.remote is not None]
            if not ups:
                return
            say(ngettext("1 Update gefunden.", "{n} Updates gefunden.", len(ups)).format(n=len(ups)))
            plans, errs = plan_with_deps(manager, ups, say)
            state["errs"] += errs
            keep = []
            for p in plans:
                if p.needs_strong_confirm:   # ohne Rueckfrage nicht
                    state["errs"].append((p.name, _("erfordert eine Bestätigung, übersprungen")))
                    manager.discard(p)
                else:
                    keep.append(p)
            state["plans"] = keep
            if manager.dl_cancel.is_set() or not keep:
                return
            if manager.wow_running():   # inzwischen gestartet?
                state["errs"].append((_("WoW"), _("WoW wurde währenddessen gestartet, nichts installiert.")))
                return
            state["phase"] = "apply"                   # ab hier wird nicht mehr abgebrochen
            state["results"] = manager.apply(keep, origin="auto")
        except ApiError as e:
            state["error"] = _err(e)
        except Exception as e:  # noqa: BLE001
            state["error"] = "{}: {}".format(type(e).__name__, _err(e))
        finally:
            for p in state["plans"]:
                manager.discard(p)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    deadline = time.monotonic() + limit
    while t.is_alive():
        t.join(0.2)
        if time.monotonic() > deadline and state["phase"] == "plan":
            manager.dl_cancel.set()
            t.join(3)
            res.failed.append((_("Zeitlimit"), _("Netzwerk zu langsam: nach {s} s abgebrochen.").format(s=int(limit))))
            res.exit_code = EXIT_ERROR
            return summary()
    if state["error"]:
        res.failed.append((_("Prüfung"), state["error"]))
    res.failed += list(state["errs"])
    for r in state["results"] or []:
        if r.ok:
            res.updated.append(r.name)
        else:
            res.failed.append((r.name, r.message))
    res.exit_code = EXIT_ERROR if res.failed else EXIT_OK
    return summary()
