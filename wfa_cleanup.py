"""Aufraeumen: verwaiste SavedVariables, verschachtelte und Nicht-Addon-Ordner; Speicherbedarf. GUI-frei."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wfa_i18n import _

_SET = re.compile(r"^\d{8}-\d{6}(-\d+)?$")


@dataclass
class Finding:
    kind: str       # "orphan_sv" | "nested" | "no_toc"
    path: Path
    size: int
    detail: str


def _ci_child(parent, name):
    try:
        for c in parent.iterdir():
            if c.name.lower() == name.lower() and c.is_dir():
                return c
    except OSError:
        pass
    return None


def _subdirs(d):
    try:
        return [c for c in d.iterdir() if c.is_dir()]
    except OSError:
        return []


def _has_toc(d):
    try:
        return any(c.is_file() and c.name.lower().endswith(".toc") for c in d.iterdir())
    except OSError:
        return False


def _size(p):
    p = Path(p)
    try:
        if p.is_symlink() or not p.is_dir():
            return p.lstat().st_size
    except OSError:
        return 0
    total = 0
    for root, _dirs, files in os.walk(p, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def disk_usage(paths: dict[str, Path]) -> dict[str, int]:
    """Bytes je Eintrag; fehlende Pfade = 0, Symlinks werden nicht verfolgt."""
    return {k: _size(v) for k, v in paths.items()}


def _inner(d):
    """Gleichnamiger Unterordner mit .toc (oder None)."""
    for c in _subdirs(d):
        if c.name.lower() == d.name.lower() and _has_toc(c):
            return c
    return None


def _sv_dirs(wtf):
    acc_root = _ci_child(Path(wtf), "Account")
    if not acc_root:
        return
    for acc in _subdirs(acc_root):
        sv = _ci_child(acc, "SavedVariables")
        if sv:
            yield sv
        for realm in _subdirs(acc):
            if realm.name.lower() == "savedvariables":
                continue
            for ch in _subdirs(realm):
                sv = _ci_child(ch, "SavedVariables")
                if sv:
                    yield sv


def scan(addons_dir, wtf) -> list[Finding]:
    out = []
    addons_dir = Path(addons_dir)
    if not addons_dir.is_dir():
        return out
    dirs = sorted((d for d in _subdirs(addons_dir) if not d.name.startswith(".")), key=lambda d: d.name.lower())
    known = {d.name.lower() for d in _subdirs(addons_dir)}
    for d in dirs:
        if _has_toc(d):
            continue
        inner = _inner(d)
        if inner:
            out.append(Finding("nested", d, _size(d), d.name))
        else:
            out.append(Finding("no_toc", d, _size(d), d.name))
    if wtf and Path(wtf).is_dir():
        for sv in _sv_dirs(wtf):
            for f in sorted(sv.iterdir(), key=lambda x: x.name.lower()):
                n = f.name
                low = n.lower()
                base = n[:-4] if low.endswith(".lua") else n[:-8] if low.endswith(".lua.bak") else None
                if not base or not f.is_file() or base.lower().startswith("blizzard_"):
                    continue
                if base.lower() not in known:
                    out.append(Finding("orphan_sv", f, _size(f), base))
    return out


def _write_manifest(set_dir, items):
    fd, tmp = tempfile.mkstemp(dir=set_dir, prefix=".manifest.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, set_dir / "manifest.json")


def _new_set(trash_root):
    trash_root.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    name, n = base, 1
    while True:
        try:
            (trash_root / name).mkdir()
            return trash_root / name
        except FileExistsError:
            n += 1
            name = "{}-{}".format(base, n)


def _rotate(trash_root, keep, protect=None):
    sets = sorted((d for d in _subdirs(trash_root) if _SET.match(d.name)), key=lambda d: d.name, reverse=True)
    for d in sets[max(keep, 1):]:
        if d != protect:
            shutil.rmtree(d, ignore_errors=True)


def _apply_one(f, addons_dir, set_dir, idx):
    p = Path(f.path)
    if f.kind not in ("orphan_sv", "nested", "no_toc"):
        raise ValueError(_("Unbekannte Art: {kind}").format(kind=f.kind))
    if not (p.exists() or p.is_symlink()):
        raise OSError(_("{name} existiert nicht mehr").format(name=p.name))
    if f.kind != "orphan_sv" and p.parent.resolve() != Path(addons_dir).resolve():
        raise ValueError(_("{name} liegt nicht direkt im AddOns-Ordner").format(name=p.name))
    dest = set_dir / "items" / "{}-{}".format(idx, p.name)
    dest.parent.mkdir(exist_ok=True)
    if f.kind == "nested":
        inner = _inner(p)
        if not inner:
            raise OSError(_("Kein gueltiger innerer Ordner in {name}").format(name=p.name))
        tmp = p.parent / ".wfa-fix-{}".format(p.name)
        if tmp.exists():
            raise OSError(_("Temporaerer Ordner {name} existiert bereits").format(name=tmp.name))
        shutil.copytree(inner, tmp, symlinks=True)
        try:
            shutil.move(str(p), str(dest))
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        try:
            os.rename(tmp, p)
        except BaseException:
            shutil.move(str(dest), str(p))   # Original zurueck
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    else:
        shutil.move(str(p), str(dest))
    return {"kind": f.kind, "original": str(p), "stored": str(dest.relative_to(set_dir))}


def apply(findings, addons_dir, trash_root, keep=5) -> list[tuple[Finding, bool, str]]:
    """Verschiebt die Funde in einen neuen Satz im Papierkorb (mit manifest.json); rotiert auf keep Saetze."""
    trash_root = Path(trash_root)
    res = []
    if not findings:
        return res
    set_dir = _new_set(trash_root)
    items = []
    for i, f in enumerate(findings):
        try:
            items.append(_apply_one(f, addons_dir, set_dir, i))
            _write_manifest(set_dir, items)
            res.append((f, True, _("Verschoben: {name}").format(name=Path(f.path).name)))
        except (OSError, ValueError, shutil.Error) as e:
            res.append((f, False, _("{name} konnte nicht verarbeitet werden: {error}").format(name=Path(f.path).name, error=e)))
    if not items:
        shutil.rmtree(set_dir, ignore_errors=True)
    _rotate(trash_root, keep, set_dir if items else None)
    return res


def _manifest(set_dir):
    try:
        data = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
        return [i for i in data["items"] if isinstance(i, dict)]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def list_sets(trash_root) -> list[tuple[Path, datetime, int]]:
    """(Pfad, Zeitpunkt, Anzahl Eintraege), neueste zuerst."""
    out = []
    for d in _subdirs(Path(trash_root)):
        if not _SET.match(d.name):
            continue
        try:
            created = datetime.strptime(d.name[:15], "%Y%m%d-%H%M%S")
        except ValueError:
            created = datetime.fromtimestamp(d.stat().st_mtime)
        items = _manifest(d)
        out.append((d, created, len(items or [])))
    out.sort(key=lambda t: t[0].name, reverse=True)
    return out


def restore_set(set_dir) -> list[str]:
    """Legt alles laut Manifest zurueck; Konflikte werden gemeldet, nichts wird ueberschrieben."""
    set_dir = Path(set_dir)
    items = _manifest(set_dir)
    if items is None:
        raise ValueError(_("Der Satz {name} hat kein lesbares Manifest").format(name=set_dir.name))
    errors, left = [], []
    for it in items:
        src, dst = set_dir / it.get("stored", ""), Path(it.get("original", ""))
        if not (src.exists() or src.is_symlink()):
            errors.append(_("{name}: Sicherung fehlt").format(name=dst.name))
            continue
        if dst.exists() or dst.is_symlink():
            errors.append(_("{name}: Ziel existiert bereits").format(name=dst.name))
            left.append(it)
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except (OSError, shutil.Error) as e:
            errors.append("{}: {}".format(dst.name, e))
            left.append(it)
    if left:
        _write_manifest(set_dir, left)
    else:
        shutil.rmtree(set_dir, ignore_errors=True)   # alles zurueckgelegt, nur leere Huelle
    return errors
