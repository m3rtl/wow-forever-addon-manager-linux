"""Self-Updater des Addon-Managers ueber GitHub Releases (SHA256 Pflicht)."""
import hashlib
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import wfa_core as core
from wfa_core import ApiError

REPO = "m3rtl/wow-forever-addon-manager-linux"
ASSET_NAME = "wow-forever-addon-manager-x86_64-linux"
SUMS_NAME = "SHA256SUMS"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"

_lock = threading.Lock()
_state = {"installed": None}    # installierte, auf Neustart wartende Version


def installed_pending():
    return _state["installed"]


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page_url: str
    asset_url: str | None
    sums_url: str | None
    published: str


def _vtuple(v):
    parts = re.findall(r"\d+", str(v).split("-")[0].split("+")[0])
    return tuple(int(x) for x in parts) or (0,)


def _newer(a, b):
    x, y = _vtuple(a), _vtuple(b)
    n = max(len(x), len(y))
    return x + (0,) * (n - len(x)) > y + (0,) * (n - len(y))


def check(current=None):
    """Neuestes Release, falls neuer als current; sonst None. Fehler -> ApiError."""
    current = current or core.__version__
    data = core.http_json(f"https://api.github.com/repos/{REPO}/releases/latest")
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    ver = tag.lstrip("vV")
    if not ver or not _newer(ver, current):
        return None
    if _state["installed"] and not _newer(ver, _state["installed"]):
        return None
    asset = sums = None
    for a in data.get("assets") or []:
        if a.get("name") == ASSET_NAME:
            asset = a.get("browser_download_url")
        elif a.get("name") == SUMS_NAME:
            sums = a.get("browser_download_url")
    return Release(ver, tag, data.get("body") or "", data.get("html_url") or RELEASES_PAGE,
                   asset, sums, data.get("published_at") or "")


def can_self_update():
    """Nur das PyInstaller-Onefile-Binary kann sich selbst ersetzen."""
    if not getattr(sys, "frozen", False):
        return False
    exe = Path(sys.executable)
    return exe.is_file() and not exe.is_symlink() and os.access(exe.parent, os.W_OK)


def _parse_sums(text, name):
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m and Path(m.group(2)).name == name:
            return m.group(1).lower()
    return None


def install(rel, progress=None, cancel=None):
    """Laedt und ersetzt sys.executable; -> Pfad der neuen Datei. Ohne gueltige Pruefsumme wird nichts ersetzt."""
    if not rel.asset_url or not rel.sums_url:
        raise ApiError("Release enthält kein Programm-Paket oder keine Prüfsumme.", "download")
    if not _lock.acquire(blocking=False):
        raise ApiError("Ein Programm-Update läuft bereits.", "busy")
    try:
        return _install(rel, progress, cancel)
    finally:
        _lock.release()


def _install(rel, progress, cancel):
    exe = Path(sys.executable)
    tmp_sums = tmp_bin = None
    try:
        fd, tmp_sums = tempfile.mkstemp(prefix=".wfa-sums-", dir=exe.parent)
        os.close(fd)
        core.download_file(rel.sums_url, tmp_sums, limit=1 << 20, cancel=cancel)
        want = _parse_sums(Path(tmp_sums).read_text("utf-8", "replace"), ASSET_NAME)
        if not want:
            raise ApiError("Prüfsumme für das Programm-Paket fehlt in SHA256SUMS.", "download")
        fd, tmp_bin = tempfile.mkstemp(prefix=".wfa-new-", dir=exe.parent)
        os.close(fd)
        if progress:
            progress(0.0)
        core.download_file(rel.asset_url, tmp_bin, cancel=cancel)
        h = hashlib.sha256()
        with open(tmp_bin, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            raise ApiError("Prüfsumme stimmt nicht überein – Update abgebrochen.", "download")
        os.chmod(tmp_bin, 0o755)
        old = exe.with_name(exe.name + ".old")
        keep_old = _state["installed"] is not None    # laufende Datei wurde schon ersetzt
        if exe.exists() and not keep_old:
            os.replace(exe, old)
        try:
            os.replace(tmp_bin, exe)
        except OSError:
            if not keep_old:
                os.replace(old, exe)
            raise
        _state["installed"] = rel.version
        tmp_bin = None
        if progress:
            progress(1.0)
        return exe
    finally:
        for p in (tmp_sums, tmp_bin):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def restart_command():
    drop = ("--screenshot", "--screenshot-delay", "--screenshot-dialog")
    args, skip = [], False
    for a in sys.argv[1:]:
        if skip:
            skip = False
        elif a in drop:
            skip = True
        elif a.split("=", 1)[0] in drop:
            pass
        else:
            args.append(a)
    if getattr(sys, "frozen", False):
        return [sys.executable] + args
    return [sys.executable] + [sys.argv[0]] + args


def due(cfg, hours=12):
    try:
        last = float((cfg["tray_notified"] or {}).get("self_checked", 0))
    except (TypeError, ValueError):
        last = 0.0
    return time.time() - last >= hours * 3600


def mark_checked(cfg):
    with cfg.lock:
        d = dict(cfg["tray_notified"] or {})
        d["self_checked"] = time.time()
        cfg["tray_notified"] = d
        cfg.save()
