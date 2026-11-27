"""Manager-Teil: Browser-Download, Installieren, Deinstallieren, Backups."""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

from wfa_i18n import N_, _, ngettext
from wfa_base import ApiError, BackupSet, Candidate, KEEP_BACKUPS, Package, Result, UninstallPlan, host_spawn_available, in_flatpak
from wfa_files import _remove
from wfa_paths import browser_download_dirs, tilde, xdg_user_dir
from wfa_sources import CurseForge
from wfa_toc import toc_dependencies

def _own_pids():
    """PID dieses Prozesses und aller Vorfahren (aus /proc)."""
    out, pid = set(), os.getpid()
    while pid > 1 and pid not in out:
        out.add(pid)
        try:
            with open(f"/proc/{pid}/stat", "rb") as f:
                pid = int(f.read().rsplit(b")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


INSTALL_MARK = ".wfa-install"   # Kennung der Installation in Ordner-Backups und SavedVariables-Saetzen


class ApplyMixin:
    # -- Browser
    def browser_url(self, pkg_or_cand=None, query=None):
        """Seite fuer den Browser-Download, soweit moeglich auf Forever vorgefiltert (Parameter unverifiziert)."""
        o, tid = pkg_or_cand, self._tid()
        file_id = None
        if isinstance(o, Package):
            url = o.page_url or (o.remote.page_url if o.remote else None)
            if o.remote and o.remote.source == "CF" and isinstance(o.remote.ident, int):
                file_id = o.remote.ident
        elif isinstance(o, Candidate):
            url = o.page_url or (self._mod_url(o.ident) if o.source == "CF" else None)
        else:
            url = None
        if url and "curseforge.com/" in url:
            base = re.sub(r"/files(/.*)?$", "", url.split("?")[0].rstrip("/"))
            if file_id:
                return f"{base}/files/{file_id}"
            return f"{base}/files/all?page=1&pageSize=20&gameVersionTypeId={tid}"
        if url:
            return url
        if query:
            return ("https://www.curseforge.com/wow/search?page=1&pageSize=20&search="
                    + urllib.parse.quote(query) + f"&gameVersionTypeId={tid}")
        return "https://www.curseforge.com/wow/addons"

    def download_watch(self):
        """-> dict(folders=[Path], ask=bool, auto=bool, source=str, entries=[...]).
        folders: manueller Ordner, Standardbrowser, weitere Browser, XDG (nur existierende, ohne Duplikate)."""
        entries = browser_download_dirs()
        manual = self.cfg["download_dir"]
        paths = ([manual] if manual else []) + [e["path"] for e in entries] + [str(xdg_user_dir("DOWNLOAD"))]
        folders, seen = [], set()
        for p in paths:
            q = Path(p).expanduser()
            if q not in seen and q.is_dir():
                seen.add(q)
                folders.append(q)
        d = entries[0] if entries and entries[0]["default"] else None
        return dict(folders=folders, ask=bool(d and d["ask"]), auto=not manual, entries=entries,
                    source=(f"{d['browser']} → {tilde(d['path'])}" if d else tilde(xdg_user_dir("DOWNLOAD"))))

    def download_summary(self):
        w = self.download_watch()
        if not w["auto"]:
            return _("manuell ({path})").format(path=tilde(self.cfg["download_dir"]))
        return _("automatisch (aus Browser: {source})").format(source=w["source"]) \
            if w["entries"] and w["entries"][0]["default"] else _("automatisch ({source})").format(source=w["source"])

    def set_download_dir(self, p):
        with self.cfg.lock:
            self.cfg["download_dir"] = str(p) if p else None
            self.cfg.save()

    def open_browser(self, url):
        if urllib.parse.urlparse(url).scheme in ("http", "https"):
            with contextlib.suppress(Exception):
                webbrowser.open(url)

    def wait_for_download(self, since, timeout=600, cancel=None, folders=None):
        folders = list(folders) if folders is not None else self.download_watch()["folders"]
        seen = {}
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cancel is not None and cancel.is_set():
                return None
            for p in (z for f in folders for z in f.glob("*.zip")):
                try:
                    s = p.stat()
                except OSError:
                    continue
                if s.st_mtime <= since or any((p.parent / (p.name + e)).exists() for e in (".crdownload", ".part")) \
                        or (p.parent / (p.stem + ".crdownload")).exists():
                    continue
                prev = seen.get(p)
                if prev and prev[0] == s.st_size and time.time() - prev[1] >= 2:
                    return p
                if not prev or prev[0] != s.st_size:
                    seen[p] = (s.st_size, time.time())
            time.sleep(0.5)
        return None

    # -- Installieren / Backups
    def wow_running(self):
        """True/False; None = nicht feststellbar (Flatpak ohne Zugriff auf die Host-Prozesse)."""
        cmd = ["pgrep", "-f", "-i", r"wow\.exe"]
        if in_flatpak():
            if not host_spawn_available():
                return None
            cmd = ["flatpak-spawn", "--host"] + cmd
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=5)
            rc = proc.returncode
        except Exception:
            return None if in_flatpak() else False
        if rc in (0, 1):
            if rc == 0 and not in_flatpak():
                # eigener Prozess und Eltern (z. B. Steam-Startoption "wfa --update --run .../Wow.exe") zaehlen nicht
                pids = {int(x) for x in proc.stdout.split() if x.isdigit()}
                return bool(pids - _own_pids()) if pids else True
            return rc == 0
        return None if in_flatpak() else False

    def _new_backup_dir(self):
        self.paths.backups.mkdir(parents=True, exist_ok=True)
        base = time.strftime("%Y%m%d-%H%M%S")
        d, n = self.paths.backups / base, 0
        while d.exists():
            n += 1
            d = self.paths.backups / f"{base}-{n}"
        d.mkdir()
        self._mark_set(d)
        return d

    # Kennung der Installation: Datei INSTALL_MARK im Satz (Saetze ohne Datei sind alt und gehoeren zu legacy_install())
    def _mark_set(self, d):
        with contextlib.suppress(OSError):
            (d / INSTALL_MARK).write_text(str(self.addons_dir or ""), "utf-8")

    def _set_owner(self, d):
        try:
            return (Path(d) / INSTALL_MARK).read_text("utf-8").strip()
        except OSError:
            return self.legacy_install() or ""

    def _mine(self, d):
        o = self._set_owner(d)
        return not o or o == str(self.addons_dir)

    @staticmethod
    def _rm_empty_set(d):
        """Entfernt einen Satz, der nur noch die Kennung enthaelt."""
        with contextlib.suppress(OSError):
            if [c.name for c in Path(d).iterdir()] == [INSTALL_MARK]:
                (Path(d) / INSTALL_MARK).unlink()
            Path(d).rmdir()

    def _prune_sets(self, root, key=lambda p: p.name):
        """Je Installation die neuesten KEEP_BACKUPS Saetze behalten."""
        sets = sorted((p for p in root.iterdir() if p.is_dir()), key=key) if root.exists() else []
        groups = {}
        for p in sets:
            groups.setdefault(self._set_owner(p), []).append(p)
        for lst in groups.values():
            for p in lst[:-KEEP_BACKUPS]:
                shutil.rmtree(p, ignore_errors=True)

    def _prune_backups(self):
        self._prune_sets(self.paths.backups)

    def _swap(self, items, bdir):
        """Ersetzt Ordner im AddOns-Ordner (alt -> bdir, neu -> AddOns). Rollback bei jedem Abbruch,
        auch KeyboardInterrupt. -> Liste der gesicherten Ordnernamen."""
        a = self.addons_dir
        pre = {n for n in items if (a / n).exists() or (a / n).is_symlink()}
        moved = []
        try:
            for n in items:
                if n in pre:
                    if (bdir / n).exists() or (bdir / n).is_symlink():
                        _remove(a / n)  # erstes Backup im Satz bleibt erhalten
                    else:
                        shutil.move(str(a / n), str(bdir / n))
                        moved.append(n)
            for n, src in items.items():
                shutil.move(str(src), str(a / n))
        except BaseException:
            for n in items:
                with contextlib.suppress(OSError):
                    if n in moved:
                        _remove(a / n)  # auch halb kopierte Ziele
                        shutil.move(str(bdir / n), str(a / n))
                    elif n not in pre:
                        _remove(a / n)
            raise
        return moved

    def apply(self, plans, origin=None):
        """Installiert alle Plaene in einem gemeinsamen Backup-Satz. Fehler je Plan -> Rollback dieses Plans.
        origin="auto": Hintergrund-Update (nur fuer den Verlauf)."""
        results = []
        with self._apply_lock:
            need = int(self.cfg["auto_snapshot_min"] or 0)
            n = sum(1 for p in plans if p.extra.get("dirs"))
            if need > 0 and n >= need:
                self.auto_snapshot(ngettext("Vor dem Update von 1 Addon", "Vor dem Update von {n} Addons", n).format(n=n), "bulk", {"n": n})
            sv = self.snapshot_sv() if self.cfg["sv_backup"] and any(p.extra.get("dirs") for p in plans) else None
            bdir = self._new_backup_dir()
            try:
                for plan in plans:
                    dirs = {n: Path(p) for n, p in (plan.extra.get("dirs") or {}).items() if n in plan.install_folders}
                    try:
                        moved = self._swap(dirs, bdir)
                    except Exception as e:
                        results.append(Result(plan.key, plan.name, False,
                                              _("Fehler bei der Installation: {error} (Zustand wiederhergestellt)").format(error=e),
                                              None))
                        self.discard(plan)
                        continue
                    try:
                        self._record(plan, list(dirs))
                    except Exception as e:
                        self.log(_("Konfiguration konnte nicht gespeichert werden: {error}").format(error=e))
                    kind = N_("Automatisch") if origin == "auto" else (
                        N_("Installation") if not plan.old_version else N_("Versionswechsel") if plan.extra.get("pin") else N_("Update"))
                    self.add_history(kind, plan.key, plan.name, plan.old_version, plan.new_version, plan.source,
                                     bdir.name if moved else None, sv, list(dirs))
                    results.append(Result(plan.key, plan.name, True, ngettext("1 Ordner installiert", "{n} Ordner installiert", len(dirs)).format(n=len(dirs)),
                                          bdir.name if moved else None, sv))
                    self.discard(plan)
            finally:
                for plan in plans:
                    self.discard(plan)
                self._rm_empty_set(bdir)  # leerer Satz
                with contextlib.suppress(OSError):
                    self._prune_backups()
        return results

    def _record(self, plan, names):
        info = plan.extra
        src = info.get("source") or plan.source
        mod_id = info.get("cf_mod_id")
        with self.cfg.lock:
            rec = dict(source=src, version=plan.new_version, folders=names, installed_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
            if info.get("ident_key"):
                rec[info["ident_key"]] = info["ident"]
            self.cfg["installed"][plan.key] = rec
            self.cfg["pins"].pop(plan.key, None)  # ein Update loest „Auslassen“/„Festhalten“ ab
            if info.get("pin"):
                self.cfg["pins"][plan.key] = info["pin"]
            if info.get("channel") in ("release", "beta", "alpha"):
                self.cfg["channels"][plan.key] = info["channel"]
            if info.get("save_package"):
                meta = info.get("meta") or {}
                sp = {k: meta.get(k) for k in ("gh", "tag_prefix", "asset_regex") if meta.get(k)}
                self.cfg["packages"][plan.key] = dict(sp, key=plan.key, name=plan.name, folders=names,
                                                      vfolder=info.get("vfolder"))
            elif plan.key in self.cfg["packages"]:
                pk = self.cfg["packages"][plan.key]
                pk["folders"] = sorted(set(pk.get("folders", [])) | set(names))
            learned = False
            for n in names:
                self.cfg["cf_fp_cache"].pop(n, None)
                if src == "CF" and mod_id:
                    with contextlib.suppress(OSError):
                        fp = self._fingerprint(self.addons_dir / n)
                        self.cfg["cf_fp_cache"][n] = dict(fp=fp, mod_id=mod_id, file_id=info.get("ident"),
                                                          display=info.get("display") or "", file_date=info.get("file_date") or "")
                        learned = True
            self.cfg.save()
        if not learned and self.api_key and not self._key_invalid:  # Zip/Browser: Mod ueber Fingerprint lernen
            try:
                for n in names:
                    with contextlib.suppress(OSError):
                        self._fps[n] = self._fingerprint(self.addons_dir / n)
                self._query_fingerprints(CurseForge(self.api_key), names)
                self._fill_mod_info(CurseForge(self.api_key),
                                    sorted({self.cfg["cf_fp_cache"][n]["mod_id"] for n in names
                                            if (self.cfg["cf_fp_cache"].get(n) or {}).get("mod_id")}))
            except ApiError as e:
                self.log(_("Erkennung nach Installation nicht möglich: {error}").format(error=e))

    def plan_uninstall(self, pkg):
        names = [n for n in pkg.folders if (self.addons_dir / n).exists() or (self.addons_dir / n).is_symlink()]
        gone = {n.lower() for n in names}
        warnings = []
        if len(names) < len(pkg.folders):
            warnings.append(_("Nicht vorhanden: ") + ", ".join(n for n in pkg.folders if n not in names))
        dependents = {}
        for f in self._addon_folders():
            if f.lower() in gone:
                continue
            deps = toc_dependencies(self.addons_dir / f, self.client_interface)
            need = sorted(n for n in names if n.lower() in deps)
            if need:
                dependents[f] = need
        for f, need in dependents.items():
            warnings.append(_("{folder} benötigt {needed}").format(folder=f, needed=", ".join(need)))
        return UninstallPlan(pkg.key, pkg.name, names, dependents, warnings)

    def uninstall(self, plans):
        """Verschiebt die Ordner in einen neuen Backup-Satz (per restore rueckgaengig machbar)."""
        results = []
        with self._apply_lock:
            bdir = self._new_backup_dir()
            try:
                for plan in plans:
                    if not plan.folders:
                        results.append(Result(plan.key, plan.name, False, _("Keine Ordner vorhanden.")))
                        continue
                    try:
                        self._move_out(plan.folders, bdir)
                    except Exception as e:
                        results.append(Result(plan.key, plan.name, False,
                                              _("Fehler: {error} (Zustand wiederhergestellt)").format(error=e)))
                        continue
                    rec = self.cfg["installed"].get(plan.key) or {}
                    self.add_history(N_("Deinstallation"), plan.key, plan.name, rec.get("version"), None, rec.get("source"),
                                     bdir.name, None, plan.folders)
                    try:
                        self._forget(plan.folders)
                        self.clear_pin(plan.key)
                        self.set_channel(plan.key, None)
                    except Exception as e:
                        self.log(_("Konfiguration konnte nicht gespeichert werden: {error}").format(error=e))
                    results.append(Result(plan.key, plan.name, True, ngettext("1 Ordner entfernt", "{n} Ordner entfernt", len(plan.folders)).format(n=len(plan.folders)), bdir.name))
            finally:
                self._rm_empty_set(bdir)
                with contextlib.suppress(OSError):
                    self._prune_backups()
        return results

    def _move_out(self, names, bdir):
        a, moved = self.addons_dir, []
        try:
            for n in names:
                shutil.move(str(a / n), str(bdir / n))
                moved.append(n)
        except BaseException:
            for n in moved:
                with contextlib.suppress(OSError):
                    shutil.move(str(bdir / n), str(a / n))
            raise

    def _forget(self, names):
        gone = set(names)
        with self.cfg.lock:
            for sect in ("installed", "packages"):
                for k, rec in list(self.cfg[sect].items()):
                    old = rec.get("folders", [])
                    left = [f for f in old if f not in gone]
                    if len(left) != len(old):
                        if left:
                            rec["folders"] = left
                        else:
                            del self.cfg[sect][k]
            for n in names:
                self.cfg["cf_fp_cache"].pop(n, None)
            self.cfg.save()

    def list_backups(self):
        root = self.paths.backups
        out = []
        for p in sorted((x for x in root.iterdir() if x.is_dir()), reverse=True) if root.exists() else []:
            if not self._mine(p):
                continue
            try:
                created = datetime.strptime(p.name[:15], "%Y%m%d-%H%M%S").timestamp()
            except ValueError:
                created = p.stat().st_mtime
            out.append(BackupSet(p.name, p, created, sorted(x.name for x in p.iterdir() if x.name != INSTALL_MARK)))
        return out

    def restore(self, bset, only=None):
        """Stellt den Satz wieder her; `only` (Ordnernamen) beschraenkt auf diese Ordner des Satzes."""
        if not self._mine(bset.path):
            return Result(bset.name, bset.name, False, _("Die Sicherung gehört zu einer anderen Installation."))
        names = sorted(x.name for x in Path(bset.path).iterdir() if x.name != INSTALL_MARK) if Path(bset.path).is_dir() else []
        if only is not None:
            names = [n for n in names if n in set(only)]
        if not names:
            return Result(bset.name, bset.name, False, _("Sicherung ist leer oder fehlt."))
        with self._apply_lock:
            bdir = self._new_backup_dir()
            try:
                self._swap({n: Path(bset.path) / n for n in names}, bdir)
            except Exception as e:
                return Result(bset.name, bset.name, False, _("Fehler: {error} (Zustand wiederhergestellt)").format(error=e))
            finally:
                self._rm_empty_set(bdir)
            self._rm_empty_set(bset.path)
            with self.cfg.lock:
                for k, rec in list(self.cfg["installed"].items()):
                    if set(rec.get("folders", [])) & set(names):
                        del self.cfg["installed"][k]
                for n in names:
                    self.cfg["cf_fp_cache"].pop(n, None)
                with contextlib.suppress(OSError):
                    self.cfg.save()
            with contextlib.suppress(OSError):
                self._prune_backups()
        self.add_history(N_("Wiederherstellung"), "", ", ".join(names), None, None, None, bdir.name, folders=names)
        return Result(bset.name, bset.name, True, _("Wiederhergestellt: {names}").format(names=", ".join(names)), bdir.name)
