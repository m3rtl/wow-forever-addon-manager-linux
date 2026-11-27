"""Gesamtstand (AddOns + WTF/Account) sichern und wiederherstellen. GUI-frei, ohne globalen Zustand."""
from __future__ import annotations

import json
import os
import re
import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import wfa_core
from wfa_i18n import N_, _

_ID = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
_ADDONS, _WTF, _META = "addons.tar.gz", "wtf.tar.gz", "meta.json"


@dataclass
class Snapshot:
    id: str
    path: Path
    created: str
    label: str
    size: int
    addons: list[str]
    client: str
    manager_version: str


def _ci_child(parent, name):
    try:
        for c in parent.iterdir():
            if c.name.lower() == name.lower() and c.is_dir():
                return c
    except OSError:
        pass
    return None


def _account_dir(wtf):
    wtf = Path(wtf)
    return _ci_child(wtf, "Account") or wtf / "Account"


def _pack(src, out):
    """Inhalt von src als tar.gz (nur Dateien/Ordner, Links werden uebersprungen)."""
    def flt(ti):
        return ti if (ti.isreg() or ti.isdir()) else None
    with tarfile.open(out, "w:gz") as tf:
        if src is not None and Path(src).is_dir():
            for c in sorted(Path(src).iterdir()):
                tf.add(c, arcname=c.name, filter=flt)


def _members_ok(tf):
    for m in tf.getmembers():
        n = m.name.replace("\\", "/")
        if not (m.isreg() or m.isdir()):
            raise ValueError(_("Unzulaessiger Eintrag im Archiv: {name}").format(name=m.name))
        if n.startswith("/") or re.match(r"^[A-Za-z]:", n) or ".." in n.split("/"):
            raise ValueError(_("Unzulaessiger Pfad im Archiv: {name}").format(name=m.name))


def _extract(archive, dest):
    with tarfile.open(archive, "r:gz") as tf:
        _members_ok(tf)
        try:
            tf.extractall(dest, filter="data")
        except TypeError:       # aeltere Python-Version ohne filter
            tf.extractall(dest)


def _meta(d):
    m = json.loads((d / _META).read_text(encoding="utf-8"))
    return Snapshot(str(m["id"]), d, str(m["created"]), str(m.get("label", "")), int(m.get("size", 0)),
                    [str(a) for a in m.get("addons", [])], str(m.get("client", "")), str(m.get("manager_version", "")))


def list_snapshots(snap_root) -> list[Snapshot]:
    """Neueste zuerst; kaputte Saetze werden uebersprungen."""
    out = []
    try:
        dirs = [d for d in Path(snap_root).iterdir() if d.is_dir() and _ID.match(d.name)]
    except OSError:
        return out
    for d in dirs:
        try:
            if (d / _ADDONS).is_file():
                out.append(_meta(d))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    out.sort(key=lambda s: s.id, reverse=True)
    return out


def _rotate(snap_root, keep, protect=()):
    for s in list_snapshots(snap_root)[max(keep, 1):]:
        if s.id not in protect:
            shutil.rmtree(s.path, ignore_errors=True)


def create(addons_dir, wtf, snap_root, label="", client="", keep=3, protect=()) -> Snapshot:
    snap_root = Path(snap_root)
    try:
        snap_root.mkdir(parents=True, exist_ok=True)
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        sid, n = base, 1
        used = [c.name for c in snap_root.iterdir() if c.name == base or c.name.startswith(base + "-")]
        if used:     # Suffix hoeher als alle vorhandenen, damit die Sortierung nach Zeit stimmt
            n = max([int(u.rsplit("-", 1)[1]) if u != base else 1 for u in used if u.rsplit("-", 1)[-1].isdigit() or u == base] + [1]) + 1
            sid = "{}-{}".format(base, n)
        tmp = snap_root / ".tmp-{}".format(sid)
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            _pack(Path(addons_dir), tmp / _ADDONS)
            acc = _account_dir(wtf) if wtf else None
            if acc is not None and acc.is_dir():
                _pack(acc, tmp / _WTF)
            names = sorted(c.name for c in Path(addons_dir).iterdir() if c.is_dir()) if Path(addons_dir).is_dir() else []
            size = sum(f.stat().st_size for f in tmp.iterdir())
            meta = {"id": sid, "created": datetime.now().isoformat(timespec="seconds"), "label": label, "size": size,
                    "addons": names, "client": client, "manager_version": wfa_core.__version__}
            (tmp / _META).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            os.rename(tmp, snap_root / sid)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    except (OSError, tarfile.TarError) as e:
        raise OSError(_("Der Schnappschuss konnte nicht angelegt werden: {error}").format(error=e)) from e
    snap = _meta(snap_root / sid)
    _rotate(snap_root, keep, set(protect) | {sid})
    return snap


def _swap_in(archive, target):
    """Entpackt neben target und tauscht. Gibt (target, old-oder-None) zurueck; Aufrufer entscheidet ueber Aufraeumen."""
    new = target.parent / (target.name + ".wfa-new")
    old = target.parent / (target.name + ".wfa-old")
    shutil.rmtree(new, ignore_errors=True)
    if old.exists():
        raise OSError(_("Reste einer frueheren Wiederherstellung ({name}) im Weg; bitte pruefen und entfernen").format(name=old.name))
    target.parent.mkdir(parents=True, exist_ok=True)
    new.mkdir()
    try:
        _extract(archive, new)
        had = target.exists()
        if had:
            os.rename(target, old)
        try:
            os.rename(new, target)
        except BaseException:
            if had:
                os.rename(old, target)
            raise
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    return target, (old if had else None)


def restore(snap, addons_dir, wtf, snap_root, keep=3) -> Snapshot:
    """Stellt snap wieder her; legt vorher einen Sicherheits-Satz an und gibt ihn zurueck."""
    sp = Path(snap.path)
    if not (sp / _ADDONS).is_file():
        raise ValueError(_("Der Schnappschuss ist unvollstaendig (addons.tar.gz fehlt)"))
    parts = [(sp / _ADDONS, Path(addons_dir))]
    if (sp / _WTF).is_file():
        parts.append((sp / _WTF, _account_dir(wtf)))
    for arc, _t in parts:     # vorab pruefen, bevor irgendetwas angefasst wird
        try:
            with tarfile.open(arc, "r:gz") as tf:
                _members_ok(tf)
        except tarfile.TarError as e:
            raise ValueError(_("Das Archiv {name} ist beschaedigt: {error}").format(name=arc.name, error=e)) from e
    safety = create(addons_dir, wtf, snap_root, label=N_("Vor Wiederherstellung"), keep=keep, protect={sp.name})
    done = []
    try:
        for arc, tgt in parts:
            done.append(_swap_in(arc, tgt))
    except (OSError, tarfile.TarError, ValueError) as e:
        for tgt, old in reversed(done):      # zurueck tauschen
            try:
                shutil.rmtree(tgt, ignore_errors=True)
                if old is not None:
                    os.rename(old, tgt)
            except OSError:
                pass
        raise OSError(_("Die Wiederherstellung ist fehlgeschlagen, der alte Stand bleibt erhalten: {error}").format(error=e)) from e
    for _tgt, old in done:
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    return safety


def delete(snap):
    try:
        shutil.rmtree(Path(snap.path))
    except OSError as e:
        raise OSError(_("Der Schnappschuss konnte nicht geloescht werden: {error}").format(error=e)) from e
