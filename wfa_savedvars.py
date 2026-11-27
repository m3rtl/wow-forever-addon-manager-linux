"""Manager-Teil: SavedVariables-Schnappschuesse und Update-Verlauf."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from wfa_i18n import N_, _
from wfa_base import HISTORY_MAX, Result, SvSet

class SavedVarsMixin:
    # -- SavedVariables-Schnappschuesse (nur WTF/Account/*/SavedVariables und .../<Realm>/<Char>/SavedVariables)
    def wtf_dir(self):
        if not self.addons_dir:
            return None
        base = self.addons_dir.parent.parent
        return self._ci_child(base, "WTF") or base / "WTF"

    @staticmethod
    def _ci_child(parent, name):
        """Unterordner ohne Beachtung der Gross-/Kleinschreibung (Wine/Proton auf Linux ist case-sensitiv)."""
        with contextlib.suppress(OSError):
            for c in parent.iterdir():
                if c.name.lower() == name.lower() and c.is_dir():
                    return c
        return None

    @staticmethod
    def _subdirs(d):
        try:
            return [c for c in d.iterdir() if c.is_dir()]
        except OSError:
            return []

    @classmethod
    def _sv_files(cls, root):
        """Relative Pfade aller SavedVariables-*.lua unter root (WTF bzw. Schnappschuss)."""
        acc = cls._ci_child(root, "Account")
        out = set()

        def grab(d):
            sv = cls._ci_child(d, "SavedVariables")
            with contextlib.suppress(OSError):
                out.update(f.relative_to(root) for f in (sv.iterdir() if sv else ()) if f.suffix.lower() == ".lua" and f.is_file())
        for a in cls._subdirs(acc) if acc else ():
            grab(a)
            for realm in cls._subdirs(a):
                for char in cls._subdirs(realm):
                    grab(char)
        return sorted(out)

    @classmethod
    def _ci_dest(cls, base, rel):
        """Zielpfad unter base; vorhandene Ordner werden ohne Beachtung der Schreibweise gefunden."""
        cur = base
        for part in rel.parts[:-1]:
            cur = cls._ci_child(cur, part) or cur / part
        return cur / rel.name

    def snapshot_sv(self, prune=True):
        """Kopiert die SavedVariables in einen neuen Satz. -> Satzname oder None (Fehler landen im Protokoll)."""
        wtf = self.wtf_dir()
        try:
            if not wtf or not wtf.is_dir():
                raise OSError(_("WTF-Ordner nicht gefunden ({path})").format(path=wtf))
            files = self._sv_files(wtf)
            if not files:
                self.log(_("SavedVariables-Sicherung übersprungen: keine Dateien gefunden."))
                return None
            root = self.paths.sv_backups
            root.mkdir(parents=True, exist_ok=True)
            base = time.strftime("%Y%m%d-%H%M%S")
            d, n = root / base, 0
            while d.exists():
                n += 1
                d = root / f"{base}-{n}"
            try:
                for rel in files:
                    (d / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(wtf / rel, d / rel)
                self._mark_set(d)
            except BaseException:
                shutil.rmtree(d, ignore_errors=True)
                raise
            if prune:
                self._prune_sv()
            self.log(_("SavedVariables gesichert: {name} ({count} Dateien)").format(name=d.name, count=len(files)))
            return d.name
        except Exception as e:  # noqa: BLE001
            self.log(_("SavedVariables-Sicherung fehlgeschlagen: {error}").format(error=e))
            return None

    def _prune_sv(self):
        root = self.paths.sv_backups

        def age(p):
            try:
                t = datetime.strptime(p.name[:15], "%Y%m%d-%H%M%S").timestamp()
            except ValueError:
                t = p.stat().st_mtime
            suffix = p.name[16:]
            return t, int(suffix) if suffix.isdigit() else 0, p.name
        self._prune_sets(root, age)

    def list_sv_backups(self):
        root = self.paths.sv_backups
        out = []
        for p in sorted((x for x in root.iterdir() if x.is_dir()), reverse=True) if root.exists() else []:
            if not self._mine(p):
                continue
            try:
                created = datetime.strptime(p.name[:15], "%Y%m%d-%H%M%S").timestamp()
            except ValueError:
                created = p.stat().st_mtime
            files = self._sv_files(p)
            out.append(SvSet(p.name, p, created, sorted({f.stem for f in files}, key=str.lower), len(files)))
        return out

    def restore_sv(self, sset, addons=None):
        """Schreibt die Dateien eines Satzes (optional nur bestimmte Addons) nach WTF zurueck; vorher Schnappschuss
        des aktuellen Stands. Nicht bei laufendem WoW."""
        label = _("Einstellungen {name}").format(name=sset.name)
        if self.wow_running():
            return Result(sset.name, label, False, _("WoW läuft – bitte beenden, sonst überschreibt es die "
                                                         "wiederhergestellten Einstellungen beim Beenden wieder."))
        if not self._mine(sset.path):
            return Result(sset.name, label, False, _("Der Satz gehört zu einer anderen Installation."))
        wtf = self.wtf_dir()
        if not wtf or not wtf.is_dir():
            return Result(sset.name, label, False, _("WTF-Ordner nicht gefunden ({path}).").format(path=wtf))
        want = {a.lower() for a in addons} if addons is not None else None
        files = [f for f in self._sv_files(Path(sset.path)) if want is None or f.stem.lower() in want]
        if not files:
            return Result(sset.name, label, False, _("Keine passenden Dateien im Satz."))
        with self._apply_lock:
            pre = self.snapshot_sv(prune=False)
            if pre is None and self._sv_files(wtf):
                return Result(sset.name, label, False,
                              _("Aktueller Stand konnte nicht gesichert werden – abgebrochen."))
            try:
                for rel in files:
                    dest = self._ci_dest(wtf, rel)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(Path(sset.path) / rel, dest)
            except OSError as e:
                return Result(sset.name, label, False,
                              _("Fehler beim Zurückschreiben: {error} (aktueller Stand: {snapshot})").format(error=e, snapshot=pre),
                              None, pre)
            self._prune_sv()
        names = sorted({f.stem for f in files}, key=str.lower)
        self.add_history(N_("Einstellungen"), "", ", ".join(names), None, None, None, None, pre)
        return Result(sset.name, label, True,
                      _("{files} Dateien zurückgeschrieben ({addons} Addons)").format(files=len(files), addons=len(names)), None, pre)

    # -- Update-Verlauf (JSON-Lines, neueste zuletzt)
    def add_history(self, kind, key, name, old, new, source, backup, sv=None, folders=None):
        e = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), kind=kind, key=key, name=name, old=old, new=new,
                 source=source, backup=backup, sv=sv)
        if self.addons_dir:
            e["install"] = str(self.addons_dir)
        if folders is not None:
            e["folders"] = list(folders)
        hist = self.paths.history
        tmp = hist.with_name(f"{hist.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            hist.parent.mkdir(parents=True, exist_ok=True)
            with self._hist_lock, open(hist.with_name(hist.name + ".lock"), "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)   # schuetzt auch gegen parallele Prozesse (GUI + CLI)
                lines = self._hist_lines()[-(HISTORY_MAX - 1):] + [json.dumps(e, ensure_ascii=False)]
                tmp.write_text("\n".join(lines) + "\n", "utf-8")
                os.replace(tmp, hist)
        except OSError as ex:
            with contextlib.suppress(OSError):
                tmp.unlink()
            self.log(_("Verlauf konnte nicht gespeichert werden: {error}").format(error=ex))

    def _hist_lines(self):
        try:
            return [l for l in self.paths.history.read_text("utf-8", "replace").splitlines() if l.strip()]
        except OSError:
            return []

    def read_history(self, limit=None):
        """Eintraege, neueste zuerst."""
        out = []
        for l in reversed(self._hist_lines()):
            try:
                e = json.loads(l)
            except ValueError:
                continue
            if isinstance(e, dict):
                out.append(e)
                if limit and len(out) >= limit:
                    break
        return out
