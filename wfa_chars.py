"""Addons je Charakter an- und ausschalten (WTF/Account/<KONTO>/<REALM>/<CHAR>/AddOns.txt). GUI-frei, ohne globalen Zustand."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from wfa_i18n import _

_LINE = re.compile(r"^\s*([^:]+?)\s*:\s*(enabled|disabled)\s*$", re.I)


@dataclass
class Character:
    account: str
    realm: str
    name: str
    path: Path


def _ci_child(parent, name, want_dir=None):
    """Kind ohne Beachtung der Gross-/Kleinschreibung (None, wenn nicht vorhanden)."""
    try:
        for c in parent.iterdir():
            if c.name.lower() == name.lower() and (want_dir is None or c.is_dir() == want_dir):
                return c
    except OSError:
        pass
    return None


def _subdirs(d):
    try:
        return sorted((c for c in d.iterdir() if c.is_dir()), key=lambda c: c.name.lower())
    except OSError:
        return []


def _is_char_dir(d):
    if _ci_child(d, "AddOns.txt", False) or _ci_child(d, "SavedVariables", True):
        return True
    try:
        return any(c.is_file() and c.name.lower().endswith(".wtf") for c in d.iterdir())
    except OSError:
        return False


def list_characters(wtf) -> list[Character]:
    """Alle Charaktere unter WTF/Account, sortiert nach Konto, Realm, Name."""
    out = []
    acc_root = _ci_child(Path(wtf), "Account", True) if wtf else None
    if not acc_root:
        return out
    for acc in _subdirs(acc_root):
        for realm in _subdirs(acc):
            if realm.name.lower() == "savedvariables":
                continue
            for ch in _subdirs(realm):
                if _is_char_dir(ch):
                    out.append(Character(acc.name, realm.name, ch.name, ch))
    out.sort(key=lambda c: (c.account.lower(), c.realm.lower(), c.name.lower()))
    return out


def _file(char):
    return _ci_child(char.path, "AddOns.txt", False) or char.path / "AddOns.txt"


def _read_text(p):
    return p.read_bytes().decode("utf-8", errors="surrogateescape")


def read_states(char) -> dict[str, bool]:
    """Ordnername -> aktiviert. Fehlende Datei ergibt {}."""
    p = _file(char)
    if not p.is_file():
        return {}
    try:
        text = _read_text(p)
    except OSError as e:
        raise OSError(_("AddOns.txt von {name} konnte nicht gelesen werden: {error}").format(name=char.name, error=e)) from e
    out = {}
    for ln in text.splitlines():
        m = _LINE.match(ln)
        if m:
            out[m.group(1)] = m.group(2).lower() == "enabled"
    return out


def is_enabled(states, folder) -> bool:
    """Ohne Eintrag gilt ein Addon als aktiviert (Namen case-insensitive)."""
    f = folder.lower()
    for k, v in states.items():
        if k.lower() == f:
            return bool(v)
    return True


def disabled_folders(chars) -> set[str]:
    """Ordnernamen (klein), die bei allen Charakteren deaktiviert sind; ohne Charaktere leer.
    Unlesbare AddOns.txt zaehlen als „aktiviert“ (nichts wird faelschlich als deaktiviert gemeldet)."""
    out = None
    for c in chars:
        try:
            off = {k.lower() for k, v in read_states(c).items() if not v}
        except OSError:
            return set()
        out = off if out is None else out & off
        if not out:
            return set()
    return out or set()


def backup_root(backup_dir, install=None) -> Path:
    """Wurzel fuer AddOns.txt-Backups; mit install (AddOns-Pfad) je Installation ein eigener Unterordner."""
    if not install:
        return Path(backup_dir)
    root = Path(backup_dir) / ("inst-" + hashlib.sha1(str(install).encode("utf-8")).hexdigest()[:8])
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / ".wfa-install").write_text(str(install), "utf-8")
    except OSError:
        pass
    return root


def write_states(char, changes: dict[str, bool], backup_dir: Path | None = None, install: str | None = None):
    """Aenderungen in AddOns.txt einfuegen; Reihenfolge, fremde Zeilen und Zeilenende bleiben erhalten.
    install: AddOns-Pfad der Installation, zu der das Backup gehoert (ohne: alte Ablage)."""
    p = _file(char)
    exists = p.is_file()
    try:
        text = _read_text(p) if exists else ""
        if exists and backup_dir is not None:
            dst = backup_root(backup_dir, install) / char.account / char.realm / char.name / "AddOns.txt"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
        eol = "\r\n" if ("\r\n" in text or not text) else "\n"
        todo = {k.lower(): (k, bool(v)) for k, v in changes.items()}
        seen = set()
        lines = text.splitlines(keepends=True)
        for i, ln in enumerate(lines):
            body = ln.rstrip("\r\n")
            m = _LINE.match(body)
            if m and m.group(1).lower() in todo:
                low = m.group(1).lower()
                lines[i] = "{}: {}{}".format(m.group(1), "enabled" if todo[low][1] else "disabled", ln[len(body):])
                seen.add(low)
        new = [v for k, v in todo.items() if k not in seen]
        if new and lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += eol
        for key, val in new:
            lines.append("{}: {}{}".format(key, "enabled" if val else "disabled", eol))
        data = "".join(lines).encode("utf-8", errors="surrogateescape")
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".AddOns.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        raise OSError(_("AddOns.txt von {name} konnte nicht geschrieben werden: {error}").format(name=char.name, error=e)) from e


def write_states_all(chars, changes: dict[str, bool], backup_dir: Path | None = None, install: str | None = None):
    for c in chars:
        write_states(c, changes, backup_dir, install)
