"""Kernlogik des Addon-Managers fuer WoW: Forever (nur Standardbibliothek).

Keine Ein-/Ausgabe fuer Interaktion: Meldungen laufen ueber den log-Callback des Managers.
"""
from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

__version__ = "0.1.0"

APP_NAME = "wow-forever-addon-manager"
UA = f"{APP_NAME}/{__version__}"
DEFAULT_CLIENT = 16001
FOREVER_TYPE_FALLBACK = 88568
MAX_DOWNLOAD = 300 * 1024 * 1024
MAX_UNPACKED = 1024 * 1024 * 1024
KEEP_BACKUPS = 5
FOREVER_RE = re.compile(r"^1\.6\d\.")
CF_API = "https://api.curseforge.com"
CF_KEY_URL = "https://console.curseforge.com"

# Status-Konstanten
UPDATE = "UPDATE"
CURRENT = "aktuell"
NEWER = "lokal neuer"
UNKNOWN = "?"
NOKEY = "kein Key"
UNASSIGNED = "nicht zugeordnet"
ERROR = "Fehler"
NO_FOREVER = "keine Forever-Datei"
UNCHECKED = "nicht geprüft"

CATALOG = [
    dict(key="dbm-core", name="Deadly Boss Mods", cf=3358, gh="DeadlyBossMods/DeadlyBossMods",
         folders=["DBM-Core", "DBM-GUI", "DBM-StatusBarTimers", "DBM-VPVEM", "DBM-Brawlers", "DBM-Midnight",
                  "DBM-Raids-Midnight", "DBM-Lairs-Midnight"], vfolder="DBM-Core"),
    dict(key="dbm-dungeons", name="DBM Dungeons", cf=314994, gh="DeadlyBossMods/DBM-Dungeons",
         folders=["DBM-Party-*", "DBM-Challenges", "DBM-Delves-*", "DBM-WorldEvents"], vfolder="DBM-Party-Forever"),
    dict(key="questie", name="Questie (+QuestieDB)", cf=334372, gh="Questie/Questie",
         folders=["Questie", "QuestieDB", "QuestieTrace"], vfolder="Questie"),
    dict(key="rxpguides", name="RestedXP Guides", cf=486246, gh="RestedXP/RXPGuides",
         folders=["RXPGuides"], vfolder="RXPGuides"),
    dict(key="tomtom", name="TomTom", cf=18808, gh=None, folders=["TomTom"], vfolder="TomTom"),
    dict(key="whatstraining", name="WhatsTraining", cf=324944, gh="fusionpit/WhatsTraining",
         folders=["WhatsTraining"], vfolder="WhatsTraining"),
    dict(key="skillupforever", name="SkillUp Forever", cf=1705762, gh="cjber/skillup-forever",
         folders=["SkillUpForever"], vfolder="SkillUpForever"),
    dict(key="glowingbars", name="GlowingBars", cf=1754997, gh="vattiss/wowkit", tag_prefix="glowing-bars-v",
         folders=["GlowingBars"], vfolder="GlowingBars"),
    dict(key="atlasloot", name="AtlasLoot Forever", cf=1422985, gh=None,
         folders=["AtlasLootClassic", "AtlasLootClassic_*", "AtlasBIStooltips"], vfolder="AtlasLootClassic"),
    dict(key="pawn", name="Pawn", cf=4646, gh="VgerMods/Pawn", asset_regex=r"-Forever\.zip$",
         folders=["Pawn"], vfolder="Pawn"),
    dict(key="auctionator", name="Auctionator", cf=6124, gh=None, folders=["Auctionator"], vfolder="Auctionator"),
    dict(key="rarescanner", name="RareScanner", cf=84208, gh=None, folders=["RareScanner"], vfolder="RareScanner"),
]


class ApiError(Exception):
    """kind: key | forbidden | rate | http | net | nokey | nofile | download | setup | other"""

    def __init__(self, msg, kind="other"):
        super().__init__(msg)
        self.kind = kind


@dataclass
class Remote:
    version: str
    display: str
    source: str  # "CF" | "GH"
    url: str | None
    ident: object  # file_id (CF) oder tag (GH)
    filename: str
    page_url: str | None = None
    modules: list = field(default_factory=list)
    cf_id: int | None = None
    file_date: str = ""


@dataclass
class Package:
    key: str
    name: str
    folders: list
    local_version: str | None = None
    forever: str = "nein"
    source: str = "–"
    remote: Remote | None = None
    status: str = UNCHECKED
    cf_mod_id: int | None = None
    installed_file_id: int | None = None
    page_url: str | None = None
    note: str = ""
    meta: dict = field(default_factory=dict)  # gh, tag_prefix, asset_regex, vfolder, unassigned


@dataclass
class Candidate:
    source: str  # "CF" | "GH"
    ident: object  # CF-Projekt-ID bzw. "owner/repo"
    name: str
    author: str = ""
    summary: str = ""
    downloads: int = 0
    has_forever: bool | None = None
    installed: bool = False
    page_url: str | None = None


@dataclass
class InstallPlan:
    key: str
    name: str
    source: str
    old_version: str | None
    new_version: str | None
    install_folders: list
    skipped_folders: list
    warnings: list
    needs_strong_confirm: bool
    staging: Path | None
    extra: dict = field(default_factory=dict)


@dataclass
class Result:
    key: str
    name: str
    ok: bool
    message: str
    backup_set: str | None = None


@dataclass
class UninstallPlan:
    key: str
    name: str
    folders: list
    dependents: dict = field(default_factory=dict)  # fremder Ordner -> benoetigte Ordner
    warnings: list = field(default_factory=list)


@dataclass
class BackupSet:
    name: str
    path: Path
    created: float
    folders: list


# ---------------------------------------------------------------- Pfade / Config

class Paths:
    def __init__(self, home=None):
        env = os.environ.get("WOW_FA_HOME")
        if home or env:
            base = Path(home or env).expanduser()
            self.config_dir, self.data_dir, self.cache = base, base, base / "cache"
        elif getattr(sys, "frozen", False):
            h = Path.home()
            self.config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or h / ".config") / APP_NAME
            self.data_dir = Path(os.environ.get("XDG_DATA_HOME") or h / ".local" / "share") / APP_NAME
            self.cache = Path(os.environ.get("XDG_CACHE_HOME") or h / ".cache") / APP_NAME
        else:
            base = Path(__file__).resolve().parent
            self.config_dir, self.data_dir, self.cache = base, base, base / "cache"
        self.config_file = self.config_dir / "config.json"
        self.backups = self.data_dir / "backups"


def tilde(p):
    s = str(p)
    h = str(Path.home())
    return "~" + s[len(h):] if s == h or s.startswith(h + "/") else s


def xdg_user_dir(name, home=None):
    """XDG-Ordner (DOWNLOAD, DESKTOP) aus user-dirs.dirs bzw. xdg-user-dir; sonst ~/Downloads bzw. ~/Desktop."""
    h = Path(home) if home else Path.home()
    fallback = h / {"DOWNLOAD": "Downloads", "DESKTOP": "Desktop"}.get(name, name.title())
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or h / ".config") if home is None else h / ".config"
    try:
        for line in (cfg / "user-dirs.dirs").read_text("utf-8", "replace").splitlines():
            m = re.match(rf'\s*XDG_{name}_DIR\s*=\s*"(.*)"\s*$', line)
            if m:
                v = m.group(1).replace("$HOME", str(h))
                if v and Path(v) != h:
                    return Path(v)
    except OSError:
        pass
    if home is None:
        try:
            out = subprocess.run(["xdg-user-dir", name], capture_output=True, text=True, timeout=5).stdout.strip()
            if out and Path(out) != h:
                return Path(out)
        except Exception:  # noqa: BLE001
            pass
    return fallback


# (Anzeigename, Familie, Wurzeln relativ zum Home, Schluesselwoerter der .desktop-Datei)
BROWSERS = (
    ("Google Chrome", "chromium", (".config/google-chrome", ".var/app/com.google.Chrome/config/google-chrome"), ("google-chrome",)),
    ("Google Chrome Beta", "chromium", (".config/google-chrome-beta",), ("google-chrome-beta",)),
    ("Chromium", "chromium", (".config/chromium", ".var/app/org.chromium.Chromium/config/chromium",
                              "snap/chromium/common/chromium"), ("chromium",)),
    ("Brave", "chromium", (".config/BraveSoftware/Brave-Browser",
                           ".var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser"), ("brave",)),
    ("Microsoft Edge", "chromium", (".config/microsoft-edge", ".var/app/com.microsoft.Edge/config/microsoft-edge"),
     ("microsoft-edge",)),
    ("Vivaldi", "chromium", (".config/vivaldi", ".var/app/com.vivaldi.Vivaldi/config/vivaldi"), ("vivaldi",)),
    ("Opera", "chromium", (".config/opera", ".var/app/com.opera.Opera/config/opera"), ("opera",)),
    ("Firefox", "firefox", (".mozilla/firefox", "snap/firefox/common/.mozilla/firefox",
                            ".var/app/org.mozilla.firefox/.mozilla/firefox"), ("firefox",)),
    ("LibreWolf", "firefox", (".librewolf", ".var/app/io.gitlab.librewolf-community/.librewolf"), ("librewolf",)),
    ("Zen", "firefox", (".zen", ".var/app/app.zen_browser.zen/.zen"), ("zen",)),
    ("Floorp", "firefox", (".floorp",), ("floorp",)),
)


def default_browser_desktop():
    for cmd in (["xdg-settings", "get", "default-web-browser"],
                ["xdg-mime", "query", "default", "x-scheme-handler/https"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:  # noqa: BLE001
            continue
        if out:
            return out
    return ""


def _match_default(desktop):
    d = desktop.lower()
    best, blen = None, 0
    for name, _fam, _roots, keys in BROWSERS:
        for k in keys:
            if k in d and len(k) > blen:
                best, blen = name, len(k)
    return best


def _chromium_dir(root, xdg):
    prof = "Default"
    try:
        prof = json.loads((root / "Local State").read_text("utf-8"))["profile"]["last_used"] or "Default"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if "/" in prof or prof.startswith("."):
        prof = "Default"
    try:
        dl = json.loads((root / prof / "Preferences").read_text("utf-8")).get("download") or {}
    except (OSError, ValueError, AttributeError):
        dl = {}
    path = dl.get("default_directory") if isinstance(dl, dict) else None
    ask = bool(dl.get("prompt_for_download")) if isinstance(dl, dict) else False
    return (Path(path) if isinstance(path, str) and path else xdg), ask


def _firefox_profile(root):
    import configparser
    ini = configparser.RawConfigParser(strict=False)
    try:
        ini.read(root / "profiles.ini", "utf-8")
    except (OSError, configparser.Error):
        return None
    secs = ini.sections()
    for sec in secs:
        if sec.lower().startswith("install") and ini.get(sec, "Default", fallback=""):
            return root / ini.get(sec, "Default")
    for sec in secs:
        if sec.lower().startswith("profile") and ini.get(sec, "Default", fallback="") == "1":
            pth = ini.get(sec, "Path", fallback="")
            if pth:
                return root / pth if ini.get(sec, "IsRelative", fallback="1") != "0" else Path(pth)
    return None


def _firefox_dir(root, xdg, home):
    prof = _firefox_profile(root)
    if prof is None:
        return xdg, False
    try:
        txt = (prof / "prefs.js").read_text("utf-8", "replace")
    except OSError:
        return xdg, False

    def pref(key):
        m = re.search(r'user_pref\(\s*"' + re.escape(key) + r'"\s*,\s*(.+?)\s*\)\s*;', txt)
        return m.group(1) if m else None
    ask = pref("browser.download.useDownloadDir") == "false"
    fl = pref("browser.download.folderList")
    path = xdg
    if fl == "0":
        path = xdg_user_dir("DESKTOP", home)
    elif fl == "2":
        m = re.fullmatch(r'"((?:[^"\\]|\\.)*)"', pref("browser.download.dir") or "")
        if m:
            with contextlib.suppress(ValueError):
                path = Path(json.loads('"' + m.group(1) + '"'))
    return path, ask


def browser_download_dirs(home=None, default_browser=None):
    """-> [dict(browser, path, ask, default)]; Standardbrowser zuerst. `home`/`default_browser` fuer Tests
    (default_browser="" ueberspringt die Abfrage)."""
    h = Path(home) if home else Path.home()
    xdg = xdg_user_dir("DOWNLOAD", home)
    default = _match_default(default_browser if default_browser is not None else default_browser_desktop())
    out = []
    for name, fam, roots, _k in BROWSERS:
        for rel in roots:
            root = h / rel
            if not root.is_dir():
                continue
            path, ask = _chromium_dir(root, xdg) if fam == "chromium" else _firefox_dir(root, xdg, home)
            out.append(dict(browser=name, path=str(path), ask=ask, default=name == default))
    out.sort(key=lambda e: not e["default"])
    return out


_NONE = type(None)
SCHEMA = {
    "curseforge_api_key": (str, ""), "addons_dir": ((str, _NONE), None), "download_dir": ((str, _NONE), None),
    "include_beta": (bool, False), "classic_theme": (bool, True), "cf_forever_type_id": ((int, _NONE), None), "packages": (dict, {}),
    "installed": (dict, {}), "cf_ids": (dict, {}), "cf_fp_cache": (dict, {}), "cf_mods": (dict, {}),
}


class Config:
    def __init__(self, paths, log=None):
        self.paths = paths
        self.lock = threading.RLock()
        self.d = {}
        loaded = {}
        try:
            loaded = json.loads(paths.config_file.read_text("utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("kein JSON-Objekt")
        except FileNotFoundError:
            loaded = {}
        except (OSError, ValueError) as e:
            loaded = {}
            bad = paths.config_file.with_name(paths.config_file.name + ".bad")
            with contextlib.suppress(OSError):
                shutil.copy2(paths.config_file, bad)
                os.chmod(bad, 0o600)
            if log:
                log(f"Config nicht lesbar ({e}); Kopie in {bad.name}, starte mit Standardwerten.")
        for k, (types, default) in SCHEMA.items():
            v = loaded.get(k, default)
            tt = types if isinstance(types, tuple) else (types,)
            if not isinstance(v, tt) or (isinstance(v, bool) and bool not in tt):
                v = default
            self.d[k] = json.loads(json.dumps(v))
        for k, v in loaded.items():  # unbekannte Felder (z. B. aus aelteren Versionen) erhalten
            self.d.setdefault(k, v)
        if not self.d.get("download_dir"):
            self.d["download_dir"] = None

    def __getitem__(self, k):
        return self.d[k]

    def __setitem__(self, k, v):
        self.d[k] = v

    def save(self):
        with self.lock:
            p = self.paths.config_file
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.d, f, indent=2, ensure_ascii=False)
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)

    @property
    def api_key(self):
        return (os.environ.get("CF_API_KEY") or self.d.get("curseforge_api_key") or "").strip()


def mask(key):
    return "(leer)" if not key else ("*" * max(len(key) - 4, 0) + key[-4:])


# ---------------------------------------------------------------- HTTP

class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            for h in ("Authorization", "X-api-key"):
                new.headers.pop(h, None)
                new.unredirected_hdrs.pop(h, None)
        return new


_opener = urllib.request.build_opener(_Redirect)
_gh_token = {"done": False, "value": None}


def github_token():
    if not _gh_token["done"]:
        _gh_token["done"] = True
        tok = os.environ.get("GITHUB_TOKEN")
        if not tok and shutil.which("gh"):
            try:
                tok = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10).stdout.strip()
            except Exception:
                tok = None
        _gh_token["value"] = tok or None
    return _gh_token["value"]


def _open(url, headers=None, timeout=25, data=None):
    host = urllib.parse.urlparse(url).netloc
    h = {"User-Agent": UA}
    if host == "api.github.com":
        h["Accept"] = "application/vnd.github+json"
        if github_token():
            h["Authorization"] = f"Bearer {github_token()}"
    h.update(headers or {})
    try:
        return _opener.open(urllib.request.Request(url, headers=h, data=data), timeout=timeout)
    except urllib.error.HTTPError as e:
        if host == "api.curseforge.com":
            if e.code == 401:
                raise ApiError("CurseForge: nicht autorisiert (HTTP 401)", "key")
            if e.code == 403:
                raise ApiError("CurseForge: Zugriff verweigert (HTTP 403)", "forbidden")
        if e.code == 429 or (e.code == 403 and host == "api.github.com"):
            raise ApiError("Rate-Limit erreicht (%s)" % host, "rate")
        raise ApiError(f"HTTP {e.code} für {host}", "http")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ApiError(f"Netzwerkfehler ({getattr(e, 'reason', e)})", "net")


def http_json(url, headers=None, body=None):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    with _open(url, h, data=data) as r:
        try:
            return json.loads(r.read().decode("utf-8"))
        except ValueError:
            raise ApiError("Ungültige Antwort (kein JSON)", "other")


def download_file(url, dest, limit=MAX_DOWNLOAD, cancel=None):
    if urllib.parse.urlparse(url).scheme != "https":
        raise ApiError("Download nur über https erlaubt", "download")
    with _open(url, timeout=60) as r:
        size = r.headers.get("Content-Length")
        if size and size.isdigit() and int(size) > limit:
            raise ApiError("Download zu groß (>300 MB)", "other")
        total = 0
        with open(dest, "wb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise ApiError("Abgebrochen", "other")
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ApiError("Download zu groß (>300 MB)", "other")
                f.write(chunk)
    return total


# ---------------------------------------------------------------- TOC / Versionen

def parse_toc(path):
    meta = {}
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 120:
                    break
                m = re.match(r"##\s*([^:]+?)\s*:\s*(.*?)\s*$", line)
                if m:
                    meta.setdefault(m.group(1).lower(), m.group(2))
    except OSError:
        pass
    return meta


def clean_title(s):
    s = re.sub(r"\|c[0-9a-fA-F]{8}", "", s or "")
    s = re.sub(r"\|T.*?\|t", "", s)
    return s.replace("|r", "").strip()


def interfaces(meta):
    return [int(x) for x in re.findall(r"\d+", meta.get("interface", ""))]


def toc_files(folder):
    try:
        return {n.lower(): n for n in os.listdir(folder)}
    except OSError:
        return {}


def forever_toc(folder, client=DEFAULT_CLIENT):
    """-> (status ok|veraltet|nein, version|None, tocpfad|None)"""
    folder = Path(folder)
    n = folder.name
    files = toc_files(folder)
    chosen = None
    for cand in (f"{n}_Forever.toc", f"{n}-Forever.toc", f"{n}.toc"):
        if cand.lower() in files:
            chosen = folder / files[cand.lower()]
            break
    if not chosen:
        return "nein", None, None
    meta = parse_toc(chosen)
    f16 = [i for i in interfaces(meta) if 16000 <= i < 17000]
    status = "nein" if not f16 else ("ok" if max(f16) >= client else "veraltet")
    ver = meta.get("version")
    if not ver or "@" in ver:
        base = files.get(f"{n}.toc".lower())
        ver = parse_toc(folder / base).get("version") if base else None
        if ver and "@" in ver:
            ver = None
    return status, ver, chosen


def toc_dependencies(folder, client=DEFAULT_CLIENT):
    """Ordnernamen (klein geschrieben), die der Forever-TOC als Abhaengigkeit verlangt."""
    toc = forever_toc(folder, client)[2]
    if not toc:
        return set()
    out = set()
    for k, v in parse_toc(toc).items():
        if k.startswith("dep") or k == "requireddeps":
            out |= {x.strip().lower() for x in v.split(",") if x.strip()}
    return out


def client_interface(addons):
    best = 0
    try:
        for d in os.listdir(addons):
            for f in toc_files(Path(addons) / d).values():
                if f.lower().endswith(".toc"):
                    for i in interfaces(parse_toc(Path(addons) / d / f)):
                        if 16000 <= i < 17000:
                            best = max(best, i)
    except OSError:
        pass
    return best or DEFAULT_CLIENT


# Tokens: rNNN(.N)*, a.b.c, NNN. Interface-Zahlen (1xxxx) und Spielversionen (1.6x.y) sind keine Addon-Versionen.
VER_RE = re.compile(r"(?<![A-Za-z0-9])r\d+(?:\.\d+)*|\d+(?:\.\d+)+|\d+")
_SKIP_TOKEN = re.compile(r"1[0-9]{4}|1\.6\d(?:\.\d+)*")


def _version_token(s):
    for m in VER_RE.finditer(s or ""):
        if not _SKIP_TOKEN.fullmatch(m.group(0)):
            return m.group(0)
    return None


def short_version(s):
    return _version_token(s) or (s or "").strip()


def display_version(s):
    """Kurzform fuer Anzeigen: Dateinamen-Praefixe wie 'Name_FOREVER_' entfernen."""
    s = (s or "").strip()
    m = re.search(r"(?<![A-Za-z0-9])[vr]?\d+(?:\.\d+)+\S*$", s)
    return m.group(0) if m and m.start() > 0 else s


def norm(s):
    t = _version_token(s)
    if not t:
        return None
    if t.startswith("r"):
        return ("r", tuple(int(x) for x in t[1:].split(".")))
    nums = [int(x) for x in t.split(".")]
    while len(nums) > 1 and nums[-1] == 0:
        nums.pop()
    return ("d", tuple(nums))


def compare(local, remote):
    """-> UPDATE | aktuell | lokal neuer | ?"""
    a, b = norm(local), norm(remote)
    if a and b and a[0] == b[0]:
        return UPDATE if b[1] > a[1] else (CURRENT if b[1] == a[1] else NEWER)
    if local and remote and local.strip() == remote.strip():
        return CURRENT
    return UNKNOWN


# ---------------------------------------------------------------- CurseForge-Fingerprint

def murmur2(data, seed=1):
    m, r = 0x5bd1e995, 24
    n = len(data)
    h = (seed ^ n) & 0xffffffff
    full = n // 4
    for k in [(((a := (w * m) & 0xffffffff) ^ (a >> r)) * m) & 0xffffffff
              for w in struct.unpack("<%dI" % full, data[:full * 4])]:
        h = ((h * m) & 0xffffffff) ^ k
    i, rest = full * 4, n & 3
    if rest == 3:
        h ^= data[i + 2] << 16
    if rest >= 2:
        h ^= data[i + 1] << 8
    if rest >= 1:
        h ^= data[i]
        h = (h * m) & 0xffffffff
    h ^= h >> 13
    h = (h * m) & 0xffffffff
    h ^= h >> 15
    return h


def _file_hash(path):
    with open(path, "rb") as f:
        return murmur2(f.read().translate(None, b"\t\n\r "))


def _resolve_ci(base, rel):
    cur = base
    for part in re.split(r"[\\/]", rel):
        if part in ("", "."):
            continue
        cand = os.path.join(cur, part)
        if not os.path.exists(cand):
            try:
                low = {e.lower(): e for e in os.listdir(cur)}
            except OSError:
                return None
            if part.lower() not in low:
                return None
            cand = os.path.join(cur, low[part.lower()])
        cur = cand
    return cur if os.path.isfile(cur) else None


_XML_INC = re.compile(r'<(?:Include|Script)\s+file=["\']((?:(?<!\.\.).)+)["\']\s*/>', re.I)
_TOC_INC = re.compile(r'^\s*((?:(?<!\.\.).)+\.(?:xml|lua))\s*$', re.I | re.M)


def _collect(path, out):
    if path is None or path in out:
        return
    out.append(path)
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return
    if path.lower().endswith(".xml"):
        incs = _XML_INC.findall(re.sub(r"<!--.*?-->", "", txt, flags=re.S))
    elif path.lower().endswith(".toc"):
        incs = _TOC_INC.findall(re.sub(r"\s*#.*$", "", txt, flags=re.M))
    else:
        return
    for inc in incs:
        _collect(_resolve_ci(os.path.dirname(path), inc.strip()), out)


def fingerprint(folder, hasher=_file_hash):
    """CurseForge-Ordner-Fingerprint (alle <Name>*.toc + Bindings.xml + Includes)."""
    folder = str(folder)
    name = os.path.basename(folder).lower()
    files, tocs = [], []
    for e in sorted(os.listdir(folder)):
        el = e.lower()
        if el.endswith(".toc") and el.startswith(name):
            tocs.append(e)
        if el == "bindings.xml":
            files.append(os.path.join(folder, e))
    for t in tocs:
        _collect(os.path.join(folder, t), files)
    hs = sorted(hasher(f) for f in files)
    return murmur2("".join(str(h) for h in hs).encode())


# ---------------------------------------------------------------- CurseForge-API

class CurseForge:
    def __init__(self, key):
        self.key = key

    def _h(self):
        return {"x-api-key": self.key, "Accept": "application/json"}

    def get(self, path, **params):
        url = CF_API + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        return http_json(url, self._h())

    def post(self, path, body):
        return http_json(CF_API + path, self._h(), body)

    def forever_type(self):
        """Typ-ID oder None; wirft ApiError (key/forbidden bei ungueltigem Key)."""
        for t in self.get("/v1/games/1/version-types").get("data", []):
            if "forever" in (str(t.get("name", "")) + " " + str(t.get("slug", ""))).lower():
                return t["id"]
        return None

    def mods(self, ids):
        return self.post("/v1/mods", {"modIds": list(ids)}).get("data", [])

    def fingerprints(self, fps):
        return self.post("/v1/fingerprints/1", {"fingerprints": list(fps)}).get("data", {})

    def latest(self, mid, tid, include_beta):
        params = {"pageSize": 50, "index": 0}
        if tid:
            params["gameVersionTypeId"] = tid
        allowed = {1, 2} if include_beta else {1}
        hits = []
        for f in self.get(f"/v1/mods/{mid}/files", **params).get("data", []):
            if f.get("isAvailable") is False or f.get("releaseType") not in allowed:
                continue
            by_type = tid and any(s.get("gameVersionTypeId") == tid for s in f.get("sortableGameVersions") or [])
            by_str = any(FOREVER_RE.match(str(g)) for g in f.get("gameVersions") or [])
            if by_type or by_str:
                hits.append(f)
        if not hits:
            return None
        f = max(hits, key=lambda x: x.get("fileDate", ""))
        name = f.get("displayName") or f.get("fileName") or ""
        ver = _version_token(name) or _version_token(f.get("fileName", "")) or re.sub(r"\.zip$", "", name)
        return Remote(ver, name, "CF", f.get("downloadUrl"), f["id"], f.get("fileName") or "", None,
                      [m.get("name") for m in f.get("modules") or []], mid, f.get("fileDate", ""))

    def download_urls(self, rem):
        urls = [rem.url] if rem.url else []
        if not urls:
            with contextlib.suppress(ApiError):
                u = self.get(f"/v1/mods/{rem.cf_id}/files/{rem.ident}/download-url").get("data")
                if u:
                    urls.append(u)
        return urls

    def search(self, q, tid):
        params = dict(gameId=1, classId=1, searchFilter=q, sortField=2, sortOrder="desc", pageSize=15)
        if tid:
            params["gameVersionTypeId"] = tid
        return self.get("/v1/mods/search", **params).get("data", [])

    def featured(self, tid):
        d = self.post("/v1/mods/featured", {"gameId": 1, "excludedModIds": [], "gameVersionTypeId": tid}).get("data", {})
        return [m for k in ("featured", "popular", "recentlyUpdated") for m in d.get(k) or []]


# ---------------------------------------------------------------- GitHub

def gh_pick_asset(rel, meta):
    assets = rel.get("assets") or []
    zips = [a for a in assets if a["name"].lower().endswith(".zip")]
    byname = {a["name"]: a for a in zips}
    rj = next((a for a in assets if a["name"] == "release.json"), None)
    if rj:
        try:
            for r in http_json(rj["browser_download_url"]).get("releases", []):
                if any(str(m.get("flavor")).lower() == "forever" for m in r.get("metadata") or []):
                    if r.get("filename") in byname:
                        return byname[r["filename"]]
        except (ApiError, AttributeError, TypeError):
            pass
    rx = meta.get("asset_regex")
    if rx:
        for a in zips:
            if re.search(rx, a["name"]):
                return a
    for a in zips:
        if "forever" in a["name"].lower():
            return a
    if rj:
        return None
    plain = [a for a in zips if "nolib" not in a["name"].lower()]
    return plain[0] if len(plain) == 1 else None


def gh_latest(repo, meta, include_beta):
    rels = http_json(f"https://api.github.com/repos/{repo}/releases?per_page=15")
    prefix = meta.get("tag_prefix") or ""
    for rel in rels if isinstance(rels, list) else []:
        tag = rel.get("tag_name") or ""
        if rel.get("draft") or (rel.get("prerelease") and not include_beta) or not tag.startswith(prefix):
            continue
        a = gh_pick_asset(rel, meta)
        if a:
            return Remote(short_version(tag[len(prefix):]), tag, "GH", a["browser_download_url"], tag,
                          a["name"], rel.get("html_url"))
    return None


def parse_github(s):
    m = re.match(r"^(?:gh:|https?://github\.com/)([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?].*)?$", s.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def is_zip_url(s):
    u = urllib.parse.urlparse(s.strip())
    return u.scheme in ("http", "https") and u.path.lower().endswith(".zip")


# ---------------------------------------------------------------- Zip

def safe_extract(zpath, dest):
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zpath) as zf:
        infos = zf.infolist()
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise ValueError("Zip entpackt zu groß")
        for i in infos:
            name = i.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if name.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", name):
                raise ValueError(f"Unsicherer Pfad im Zip: {i.filename}")
            if stat.S_IFMT(i.external_attr >> 16) == stat.S_IFLNK:
                raise ValueError(f"Symlink im Zip abgelehnt: {i.filename}")
            if parts and parts[0] == "__MACOSX":
                continue
            target = dest.joinpath(*parts)
            if dest not in target.resolve().parents and target.resolve() != dest:
                raise ValueError(f"Unsicherer Pfad im Zip: {i.filename}")
            for anc in target.parents:
                if dest in anc.parents and anc.is_file() and anc.stat().st_size == 0:
                    anc.unlink()  # leere Datei an Stelle eines Ordners
            if name.endswith("/") or i.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(i) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)


def is_addon_dir(d):
    n = d.name.lower()
    for f in os.listdir(d):
        fl = f.lower()
        if fl.endswith(".toc") and (fl == n + ".toc" or fl.startswith(n + "_") or fl.startswith(n + "-")):
            if (d / f).is_file():
                return True
    return False


def find_addon_dirs(root):
    """Alle Addon-Ordner (flachste Ebene je Zweig) -> Liste von (Pfad, Tiefe)."""
    found = []

    def walk(d, depth):
        for sub in sorted(d.iterdir()):
            if sub.is_dir() and not sub.is_symlink() and sub.name != "__MACOSX":
                if is_addon_dir(sub):
                    found.append((sub, depth))
                else:
                    walk(sub, depth + 1)
    walk(Path(root), 0)
    return found


def _remove(p):
    p = Path(p)
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.exists():
        shutil.rmtree(p)


# ---------------------------------------------------------------- Pfadsuche

def _expand(p):
    return Path(os.path.expanduser(p))


def _drive_c_dirs(base, depth=0, pfx=True):
    """drive_c-Ordner unter base (optional unter base/pfx), bis zu `depth` Ebenen tiefer (nur gezielte Listings)."""
    base = Path(base)
    out = []
    for cand in ([base / "drive_c", base / "pfx" / "drive_c"] if pfx else [base / "drive_c"]):
        if cand.is_dir():
            out.append(cand)
    if depth > 0:
        try:
            subs = sorted(s for s in base.iterdir() if s.is_dir() and s.name != "drive_c")
        except OSError:
            subs = []
        for s in subs:
            out += _drive_c_dirs(s, depth - 1, pfx)
    return out


def _forever_in_drive_c(dc):
    for pf in ("Program Files (x86)", "Program Files"):
        yield Path(dc) / pf / "World of Warcraft" / "_forever_"


def _steam_libraries():
    roots = [_expand("~/.steam/steam"), _expand("~/.local/share/Steam"),
             _expand("~/.var/app/com.valvesoftware.Steam/.local/share/Steam")]
    libs = []
    for root in roots:
        if root.is_dir():
            libs.append(root)
        try:
            txt = (root / "steamapps" / "libraryfolders.vdf").read_text("utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
            libs.append(Path(m.group(1).replace("\\\\", "\\")))
    return libs


def _is_forever_root(fr):
    if not fr.is_dir():
        return False
    try:
        if "wowf" in (fr / ".flavor.info").read_text("utf-8", errors="replace"):
            return True
    except OSError:
        pass
    return (fr / "Interface" / "AddOns").is_dir()


def find_forever_installs():
    """Kandidaten (AddOns-Ordner) an bekannten Orten; kein rekursives Durchsuchen."""
    drive_cs = []
    for lib in _steam_libraries():
        cd = lib / "steamapps" / "compatdata"
        try:
            for pre in sorted(cd.iterdir()):
                drive_cs += _drive_c_dirs(pre, 0)
        except OSError:
            pass
    drive_cs += _drive_c_dirs(_expand("~/.wine"), 0, pfx=False)
    drive_cs += _drive_c_dirs(_expand("~/Games"), 2)
    drive_cs += _drive_c_dirs(_expand("~/.local/share/lutris"), 1)
    drive_cs += _drive_c_dirs(_expand("~/.local/share/bottles/bottles"), 1, pfx=False)
    drive_cs += _drive_c_dirs(_expand("~/.var/app/com.usebottles.bottles/data/bottles/bottles"), 1, pfx=False)
    drive_cs += _drive_c_dirs(_expand("~/Games/Heroic/Prefixes"), 1)
    drive_cs += _drive_c_dirs(_expand("~/.local/share/umu"), 1)
    drive_cs += _drive_c_dirs(_expand("~/Faugus"), 1)
    out, seen = [], set()
    for dc in drive_cs:
        for fr in _forever_in_drive_c(dc):
            if _is_forever_root(fr):
                addons = fr / "Interface" / "AddOns"
                try:
                    k = addons.resolve()
                except OSError:
                    k = addons
                if k not in seen:
                    seen.add(k)
                    out.append(addons)
    return out


def normalize_addons_dir(p):
    p = _expand(str(p))
    if p.name.lower() == "_forever_":
        return p / "Interface" / "AddOns"
    if p.name.lower() == "interface":
        return p / "AddOns"
    return p


def validate_addons_dir(p):
    """-> (ok, Hinweis). ok=True kann trotzdem einen Warnhinweis tragen."""
    raw = _expand(str(p))
    q = normalize_addons_dir(raw)
    if q.is_dir():
        if q.name.lower() != "addons":
            return False, "Das ist kein AddOns-Ordner."
        if "_forever_" not in [x.lower() for x in q.parts]:
            return True, "Warnung: Im Pfad kommt kein Ordner „_forever_“ vor – ist das wirklich WoW: Forever?"
        return True, ""
    if raw.is_dir() and raw.name.lower() in ("_forever_", "interface"):
        return True, "Der Ordner Interface/AddOns wird angelegt."
    return False, "Ordner existiert nicht."


# ---------------------------------------------------------------- Startmenue

def asset_path(name):
    base = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent)
    return base / "assets" / name


def _desktop_quote(s):
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    return f'"{s}"'


def install_desktop_entry():
    """Legt den Startmenue-Eintrag (benutzerlokal, $XDG_DATA_HOME) an. -> Pfad der .desktop-Datei."""
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    icon_dir = data / APP_NAME
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon = icon_dir / "icon.svg"
    src = asset_path("icon.svg")
    if src.is_file():
        shutil.copyfile(src, icon)
    if getattr(sys, "frozen", False):
        exe = _desktop_quote(sys.executable)
    else:
        exe = "python3 " + _desktop_quote(str(Path(__file__).resolve().parent / "wow-forever-addon-manager.py"))
    apps = data / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    target = apps / f"{APP_NAME}.desktop"
    target.write_text(
        "[Desktop Entry]\nType=Application\nName=WoW: Forever Addon-Manager\n"
        "Comment=Addons für WoW: Forever verwalten\n"
        f"Exec={exe}\nIcon={icon}\nTerminal=false\nCategories=Game;Utility;\n"
        f"StartupWMClass={APP_NAME}\n", "utf-8")
    return target


# ---------------------------------------------------------------- Manager

class Manager:
    def __init__(self, home=None, addons_dir=None, log=None):
        self.log = log or (lambda s: None)
        self.paths = Paths(home)
        self.cfg = Config(self.paths, self.log)
        self.notes = []
        self.client_interface = DEFAULT_CLIENT
        self.addons_dir = None
        self._key_invalid = False
        self._folders = []
        self._fps = {}
        self._installed_ids = set()
        self._meta = {}
        self._hash_lock = threading.Lock()
        self._hash_cache = None
        self._hash_seen = set()
        self._apply_lock = threading.RLock()
        if addons_dir:  # Override gilt nur fuer diese Sitzung
            self.addons_dir = normalize_addons_dir(addons_dir)
        else:
            cfgd = self.cfg["addons_dir"]
            if cfgd and normalize_addons_dir(cfgd).is_dir():
                self.addons_dir = normalize_addons_dir(cfgd)
        if self.addons_dir and self.addons_dir.is_dir():
            self.client_interface = client_interface(self.addons_dir)

    # -- Einrichtung
    def needs_setup(self):
        return not (self.addons_dir and self.addons_dir.is_dir())

    def find_installs(self):
        return find_forever_installs()

    def validate_addons_dir(self, p):
        return validate_addons_dir(p)

    def set_addons_dir(self, p):
        ok, hint = validate_addons_dir(p)
        if not ok:
            raise ValueError(hint)
        q = normalize_addons_dir(p)
        q.mkdir(parents=True, exist_ok=True)
        with self.cfg.lock:
            self.cfg["addons_dir"] = str(q)
            self.cfg.save()
        self.addons_dir = q
        self.client_interface = client_interface(q)

    @property
    def api_key(self):
        return self.cfg.api_key

    def cf_key_state(self):
        if self._key_invalid and self.api_key:
            return "ungültig"
        if os.environ.get("CF_API_KEY", "").strip():
            return "aus Umgebung"
        return "gesetzt" if self.cfg["curseforge_api_key"] else "fehlt"

    def set_cf_key(self, key):
        with self.cfg.lock:
            self.cfg["curseforge_api_key"] = (key or "").strip()
            self.cfg.save()
        self._key_invalid = False

    def set_include_beta(self, on):
        with self.cfg.lock:
            self.cfg["include_beta"] = bool(on)
            self.cfg.save()

    def _cf(self):
        if not self.api_key:
            raise ApiError("Kein CurseForge-API-Key gesetzt.", "nokey")
        return CurseForge(self.api_key)

    def _tid(self):
        return self.cfg["cf_forever_type_id"] or FOREVER_TYPE_FALLBACK

    # -- Katalog / Gruppierung
    def _specs(self):
        specs = [dict(p) for p in CATALOG]
        keys = {p["key"] for p in specs}
        for k, p in self.cfg["packages"].items():
            if k not in keys and isinstance(p, dict):
                specs.append(dict(p, key=k))
        return specs

    def _spec_cf_id(self, spec):
        c = spec.get("cf")
        if isinstance(c, int):
            return c
        if isinstance(c, str):
            if c.isdigit():
                return int(c)
            if c in self.cfg["cf_ids"]:
                return self.cfg["cf_ids"][c]
            for mid, info in self.cfg["cf_mods"].items():
                if isinstance(info, dict) and info.get("slug") == c and str(mid).isdigit():
                    return int(mid)
        return None

    def _addon_folders(self):
        d = self.addons_dir
        out = []
        for n in sorted(os.listdir(d)):
            p = d / n
            if p.is_dir() and any(f.lower().endswith(".toc") for f in toc_files(p)):
                out.append(n)
        return out

    def _mod_name(self, mid):
        info = self.cfg["cf_mods"].get(str(mid))
        return info.get("name") if isinstance(info, dict) else None

    def _mod_url(self, mid):
        info = self.cfg["cf_mods"].get(str(mid))
        url = info.get("url") if isinstance(info, dict) else None
        return url or f"https://www.curseforge.com/projects/{mid}"

    def _cached(self, folder, fp):
        e = self.cfg["cf_fp_cache"].get(folder)
        return e if isinstance(e, dict) and e.get("fp") == fp else None

    def _group(self, folders, fps):
        groups = []  # dict(key,name,cf,meta,folders,adopted)
        by_mod = {}
        for f in folders:
            e = self._cached(f, fps.get(f))
            if e and e.get("mod_id"):
                mid = int(e["mod_id"])
                if mid not in by_mod:
                    g = dict(key=f"cf-{mid}", name=self._mod_name(mid) or f"CurseForge {mid}", cf=mid, meta={},
                             folders=[], adopted=False)
                    by_mod[mid] = g
                    groups.append(g)
                by_mod[mid]["folders"].append(f)
        claimed = {f for g in groups for f in g["folders"]}
        for spec in self._specs():
            sid = self._spec_cf_id(spec)
            pats = spec.get("folders") or []
            hit = [f for f in folders if f not in claimed and any(fnmatch.fnmatchcase(f, pt) for pt in pats)]
            meta = {k: spec.get(k) for k in ("gh", "tag_prefix", "asset_regex", "vfolder") if spec.get(k)}
            g = by_mod.get(sid) if sid else None
            if g is not None and not g["adopted"]:
                g.update(key=spec["key"], adopted=True, name=self._mod_name(sid) or spec.get("name") or g["name"])
                g["meta"] = meta
                g["folders"] += hit
            elif hit:
                g = dict(key=spec["key"], name=spec.get("name") or spec["key"], cf=sid, meta=meta, folders=hit,
                         adopted=True)
                groups.append(g)
                if sid and sid not in by_mod:
                    by_mod[sid] = g
            claimed |= set(hit)
        unassigned = []
        for f in folders:
            if f in claimed:
                continue
            meta = {}
            for fn in toc_files(self.addons_dir / f).values():
                if fn.lower().endswith(".toc"):
                    meta = parse_toc(self.addons_dir / f / fn)
                    break
            st, ver, toc = forever_toc(self.addons_dir / f)
            if toc:
                meta = parse_toc(toc) or meta
            cid = (meta.get("x-curse-project-id") or "").strip()
            site = meta.get("x-website", "")
            repo = parse_github(site) if "github.com/" in site else None
            title = clean_title(meta.get("title")) or f
            if cid.isdigit() and int(cid) in by_mod:
                by_mod[int(cid)]["folders"].append(f)
            elif cid.isdigit():
                g = dict(key=f"cf-{cid}", name=title, cf=int(cid), meta={"gh": repo} if repo else {}, folders=[f],
                         adopted=True)
                groups.append(g)
                by_mod[int(cid)] = g
            elif repo:
                key = "gh-" + repo.replace("/", "-")
                g = next((x for x in groups if x["key"] == key), None)
                if g is None:
                    g = dict(key=key, name=title, cf=None, meta={"gh": repo}, folders=[], adopted=True)
                    groups.append(g)
                g["folders"].append(f)
            else:
                unassigned.append((f, title))
        pkgs = [self._make_package(g) for g in groups]
        pkgs.sort(key=lambda p: p.name.lower())
        for f, title in unassigned:
            st, ver, _ = forever_toc(self.addons_dir / f, self.client_interface)
            e = self.cfg["cf_fp_cache"].get(f)
            note = "lokal verändert (von CurseForge nicht erkannt)" if isinstance(e, dict) and e.get("partial") else \
                (title if title != f else "")
            pkgs.append(Package(f"folder:{f}", f, [f], ver, st, "–", None, UNASSIGNED, None, None, None, note,
                                {"unassigned": True, "vfolder": f}))
        return pkgs

    def _make_package(self, g):
        folders = sorted(g["folders"], key=str.lower)
        vf = g["meta"].get("vfolder")
        if vf not in folders:
            vf = min(folders, key=len)
        st, ver, _ = forever_toc(self.addons_dir / vf, self.client_interface)
        meta = dict(g["meta"], vfolder=vf)
        best = None
        for f in folders:
            e = self.cfg["cf_fp_cache"].get(f)
            if isinstance(e, dict) and e.get("file_id") and e.get("mod_id") == g["cf"]:
                if best is None or (e.get("file_date") or "") > (best.get("file_date") or ""):
                    best = e
        mid = g["cf"]
        page = self._mod_url(mid) if mid else (f"https://github.com/{meta['gh']}/releases" if meta.get("gh") else None)
        return Package(g["key"], g["name"], folders, ver, st, "–", None, UNCHECKED, mid,
                       best.get("file_id") if best else None, page, "", meta)

    # -- Fingerprints (Dateihashes werden auf der Platte zwischengespeichert; reines Python ist langsam)
    def _hash_file(self, path):
        st = os.stat(path)
        sig = [st.st_mtime_ns, st.st_size]
        with self._hash_lock:
            if self._hash_cache is None:
                try:
                    self._hash_cache = json.loads((self.paths.cache / "filehash.json").read_text("utf-8"))
                except (OSError, ValueError):
                    self._hash_cache = {}
            self._hash_seen.add(path)
            e = self._hash_cache.get(path)
            if e and e[:2] == sig:
                return e[2]
        h = _file_hash(path)
        with self._hash_lock:
            self._hash_cache[path] = sig + [h]
        return h

    def _save_hash_cache(self):
        with self._hash_lock:
            if self._hash_cache is None:
                return
            cache = {k: v for k, v in self._hash_cache.items() if k in self._hash_seen}
            self._hash_cache = cache
        try:
            self.paths.cache.mkdir(parents=True, exist_ok=True)
            tmp = self.paths.cache / "filehash.json.tmp"
            tmp.write_text(json.dumps(cache), "utf-8")
            os.replace(tmp, self.paths.cache / "filehash.json")
        except OSError:
            pass

    def _fingerprint(self, folder):
        return fingerprint(folder, self._hash_file)

    # -- Scan / Check
    def scan(self):
        """Nur lokal: Ordner lesen, fingerprinten, anhand Cache/Katalog gruppieren."""
        if self.needs_setup():
            raise ApiError("Kein AddOns-Ordner eingerichtet.", "setup")
        self.client_interface = client_interface(self.addons_dir)
        self._folders = self._addon_folders()
        self._fps = {}
        self._hash_seen = set()
        for f in self._folders:
            with contextlib.suppress(OSError):
                self._fps[f] = self._fingerprint(self.addons_dir / f)
        self._save_hash_cache()
        pkgs = self._group(self._folders, self._fps)
        self._installed_ids = {p.cf_mod_id for p in pkgs if p.cf_mod_id}
        self._meta = {p.key: p.meta for p in pkgs}
        return pkgs

    def _query_fingerprints(self, cf, folders):
        """Fragt unbekannte Ordner-Fingerprints ab und schreibt das Ergebnis in den Cache. -> True bei Aenderung."""
        todo = [f for f in folders if f in self._fps and self._cached(f, self._fps[f]) is None]
        if not todo:
            return False
        data = cf.fingerprints(sorted({self._fps[f] for f in todo}))
        by_fp = {}
        for m in data.get("exactMatches") or []:
            fl = m.get("file") or {}
            for mod in fl.get("modules") or []:
                by_fp.setdefault(mod.get("fingerprint"), (m.get("id"), fl))
        partial = {mod.get("name") for m in data.get("partialMatches") or []
                   for mod in (m.get("file") or {}).get("modules") or []}
        with self.cfg.lock:
            for f in todo:
                fp = self._fps[f]
                hit = by_fp.get(fp)
                if hit:
                    mid, fl = hit
                    self.cfg["cf_fp_cache"][f] = dict(fp=fp, mod_id=mid, file_id=fl.get("id"),
                                                      display=fl.get("displayName") or fl.get("fileName") or "",
                                                      file_date=fl.get("fileDate") or "")
                else:
                    self.cfg["cf_fp_cache"][f] = dict(fp=fp, mod_id=None, partial=f in partial)
            self.cfg.save()
        return True

    def _fill_mod_info(self, cf, ids):
        missing = [i for i in ids if str(i) not in self.cfg["cf_mods"]]
        if not missing:
            return
        for m in cf.mods(missing):
            with self.cfg.lock:
                self.cfg["cf_mods"][str(m["id"])] = dict(name=m.get("name") or "", slug=m.get("slug") or "",
                                                         url=(m.get("links") or {}).get("websiteUrl") or "")
        with self.cfg.lock:
            self.cfg.save()

    def check(self, packages, progress=None, cancel=None):
        """Netzabfrage; fuellt pkg.remote/source/status/note. Regruppiert `packages` bei neuen CF-Erkennungen
        in place (packages[:] = ...). progress(done, total, text)."""
        self.notes = []
        beta = self.cfg["include_beta"]
        cf = None
        if self.api_key:
            cf = CurseForge(self.api_key)
            try:
                tid = cf.forever_type()
                self._key_invalid = False
                if tid and tid != self.cfg["cf_forever_type_id"]:
                    with self.cfg.lock:
                        self.cfg["cf_forever_type_id"] = tid
                        self.cfg.save()
            except ApiError as e:
                if e.kind in ("key", "forbidden"):
                    self._key_invalid = True
                    self.notes.append("CurseForge-API-Key ungültig oder abgelehnt.")
                else:
                    self.notes.append(f"CurseForge: {e}")
                if e.kind in ("key", "forbidden"):
                    cf = None
        tid = self._tid()
        if cf:
            try:
                if self._query_fingerprints(cf, self._folders):
                    ids = {p.cf_mod_id for p in self._group(self._folders, self._fps) if p.cf_mod_id}
                    self._fill_mod_info(cf, sorted(ids))
                    packages[:] = self._group(self._folders, self._fps)
                else:
                    self._fill_mod_info(cf, sorted({p.cf_mod_id for p in packages if p.cf_mod_id}))
            except ApiError as e:
                self.notes.append(f"CurseForge-Erkennung: {e}")
            for p in packages:  # Namen/Links nachziehen
                if p.cf_mod_id:
                    p.page_url = self._mod_url(p.cf_mod_id)
                    if not p.meta.get("unassigned"):
                        p.name = self._mod_name(p.cf_mod_id) or p.name
        self._installed_ids = {p.cf_mod_id for p in packages if p.cf_mod_id}
        if any(p.meta.get("gh") for p in packages):
            github_token()
        total = len(packages)
        done = [0]

        def work(p):
            if cancel is not None and cancel.is_set():
                return
            try:
                self._check_one(p, cf, tid, beta)
            except Exception as e:  # ein Paket darf die Pruefung nicht abbrechen
                p.status, p.note = ERROR, f"{type(e).__name__}: {e}"
            done[0] += 1
            if progress:
                progress(done[0], total, p.name)

        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(work, packages))
        if not self.api_key and any(p.cf_mod_id and not p.meta.get("gh") for p in packages):
            self.notes.append("Ohne CurseForge-Key sind reine CF-Pakete nicht prüfbar.")
        for p in packages:
            if p.status == ERROR and p.note:
                self.notes.append(f"{p.name}: {p.note}")

    def _check_one(self, p, cf, tid, beta):
        if p.meta.get("unassigned"):
            return
        rem, errs = None, []
        if cf and p.cf_mod_id:
            try:
                rem = cf.latest(p.cf_mod_id, tid, beta)
                if rem:
                    rem.page_url = p.page_url
                else:
                    errs.append("CF: keine Forever-Datei")
            except ApiError as e:
                errs.append(f"CF: {e}")
        if rem is None and p.meta.get("gh"):
            try:
                rem = gh_latest(p.meta["gh"], p.meta, beta)
                if rem is None:
                    errs.append("GH: kein Forever-Release")
            except ApiError as e:
                errs.append(f"GH: {e}")
        p.remote = rem
        p.source = rem.source if rem else "–"
        p.note = "; ".join(errs)
        if rem is None:
            if p.cf_mod_id and not cf:
                p.status = NOKEY
            elif errs and all("keine Forever" in e or "kein Forever" in e for e in errs):
                p.status = NO_FOREVER
            elif errs:
                p.status = ERROR
            else:
                p.status = UNASSIGNED
            return
        p.status = self._status(p, rem)

    def _status(self, p, rem):
        rec = self.cfg["installed"].get(p.key) or {}
        if rem.source == "CF":
            fid = p.installed_file_id or rec.get("file_id")
            if fid:
                if fid == rem.ident:
                    return CURRENT
                date = ""
                for f in p.folders:
                    e = self.cfg["cf_fp_cache"].get(f)
                    if isinstance(e, dict) and e.get("file_id") == fid:
                        date = e.get("file_date") or ""
                if date and rem.file_date:
                    return UPDATE if rem.file_date > date else NEWER
        elif rec.get("tag") == rem.ident:
            return CURRENT
        return compare(p.local_version, rem.version)

    # -- Neue Addons
    def _candidate(self, m):
        tid = self._tid()
        idx = m.get("latestFilesIndexes")
        hf = None if idx is None else any(x.get("gameVersionTypeId") == tid for x in idx)
        return Candidate("CF", m["id"], m.get("name") or str(m["id"]), (m.get("authors") or [{}])[0].get("name", ""),
                         m.get("summary") or "", m.get("downloadCount") or 0, hf, m["id"] in self._installed_ids,
                         (m.get("links") or {}).get("websiteUrl"))

    def featured(self):
        return [self._candidate(m) for m in {m["id"]: m for m in self._cf().featured(self._tid())}.values()]

    def search(self, q):
        try:
            res = self._cf().search(q, self._tid())
        except ApiError as e:
            if e.kind == "forbidden":
                raise ApiError("Suche ist für diesen API-Key nicht freigeschaltet", "forbidden")
            raise
        return [self._candidate(m) for m in res]

    def resolve_input(self, text):
        t = (text or "").strip()
        if not t:
            return []
        if is_zip_url(t):
            return self._plan_zip_url(t)
        repo = parse_github(t)
        if repo:
            return [Candidate("GH", repo, repo.split("/")[1], repo.split("/")[0], "", 0, None,
                              False, f"https://github.com/{repo}")]
        if t.isdigit():
            return [self._candidate(self._cf().get(f"/v1/mods/{int(t)}")["data"])]
        if re.match(r"^https?://", t):
            raise ApiError("Nur direkte .zip-Links, GitHub-Repos oder CurseForge-Projekt-IDs werden unterstützt.")
        p = _expand(t)
        if t.lower().endswith(".zip") or p.is_file():
            if not p.is_file():
                raise ApiError("Datei nicht gefunden.")
            return self.plan_zip(p)
        return self.search(t)

    # -- Planen
    def _new_staging(self):
        self.paths.cache.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="stage-", dir=self.paths.cache))

    def discard(self, plan):
        if plan and plan.staging:
            shutil.rmtree(plan.staging, ignore_errors=True)
            plan.staging = None

    def _plan_zip_url(self, url):
        st = self._new_staging()
        try:
            download_file(url, st / "download.zip")
        except BaseException:
            shutil.rmtree(st, ignore_errors=True)
            raise
        name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).stem
        return self._build_plan(st / "download.zip", st, f"zip-{name}", name, "ZIP", {}, {})

    def plan_zip(self, path, hint_key=None):
        path = Path(path)
        if not path.is_file():
            raise ApiError("Datei nicht gefunden.")
        key, name, meta = hint_key or f"zip-{path.stem}", path.stem, dict(self._meta.get(hint_key) or {})
        for spec in self._specs():
            if spec["key"] == hint_key:
                name = spec.get("name") or path.stem
                meta = {k: spec.get(k) for k in ("vfolder", "gh") if spec.get(k)}
        return self._build_plan(path, self._new_staging(), key, name, "ZIP", meta, {})

    def plan_update(self, pkg):
        if not pkg.remote:
            raise ApiError("Keine Update-Quelle bekannt.", "nofile")
        return self._plan_remote(pkg.remote, pkg.key, pkg.name, pkg.meta, pkg.cf_mod_id)

    def plan_candidate(self, cand):
        beta = self.cfg["include_beta"]
        if cand.source == "CF":
            rem = self._cf().latest(int(cand.ident), self._tid(), beta)
            if not rem:
                raise ApiError("Keine Forever-Datei bei CurseForge.", "nofile")
            meta, key = {}, f"cf-{cand.ident}"
            for spec in self._specs():
                if self._spec_cf_id(spec) == cand.ident:
                    key, meta = spec["key"], {k: spec.get(k) for k in ("vfolder", "gh") if spec.get(k)}
            return self._plan_remote(rem, key, cand.name, meta, int(cand.ident))
        repo = str(cand.ident)
        meta = {}
        key = "gh-" + repo.replace("/", "-")
        for spec in self._specs():
            if spec.get("gh") == repo:
                key, meta = spec["key"], {k: spec.get(k) for k in ("vfolder", "gh", "tag_prefix", "asset_regex") if spec.get(k)}
        rem = gh_latest(repo, dict(meta), beta)
        if not rem:
            raise ApiError("Kein GitHub-Release mit Forever-Zip gefunden.", "nofile")
        meta.setdefault("gh", repo)
        return self._plan_remote(rem, key, cand.name, meta, None, save_package=key.startswith("gh-"))

    def _plan_remote(self, rem, key, name, meta, mod_id, save_package=False):
        if rem.source == "GH":
            urls = [rem.url] if rem.url else []
        else:
            urls = self._cf().download_urls(rem)
        if not urls:
            raise ApiError("Kein Download-Link verfügbar (Browser-Download nötig).", "download")
        st = self._new_staging()
        try:
            last = None
            for u in urls:
                try:
                    self.log(f"Lade {rem.filename or rem.display} ...")
                    download_file(u, st / "download.zip")
                    last = None
                    break
                except ApiError as e:
                    last = e
            if last:
                raise ApiError(f"Download fehlgeschlagen: {last}", "download")
            info = dict(source=rem.source, ident_key="file_id" if rem.source == "CF" else "tag", ident=rem.ident,
                        version=rem.version, cf_mod_id=mod_id, file_date=rem.file_date, display=rem.display,
                        save_package=save_package)
            return self._build_plan(st / "download.zip", st, key, name, rem.source, meta, info)
        except BaseException:
            shutil.rmtree(st, ignore_errors=True)
            raise

    def _build_plan(self, zpath, st, key, name, source, meta, info):
        x = st / "x"
        try:
            try:
                safe_extract(zpath, x)
            except (zipfile.BadZipFile, ValueError, OSError) as e:
                raise ApiError(f"Zip nicht installierbar: {e}")
            found = find_addon_dirs(x)
            if not found:
                raise ApiError("Im Zip wurde kein Addon-Ordner (Ordner mit passender .toc) gefunden.")
            warnings, dirs = [], {}
            for d, depth in sorted(found, key=lambda t: t[1]):
                if d.name in dirs:
                    warnings.append(f"Ordner „{d.name}“ kommt mehrfach im Zip vor; der flachste wird verwendet.")
                else:
                    dirs[d.name] = d
            comp = {n: forever_toc(d, self.client_interface)[0] for n, d in dirs.items()}
            chosen = [n for n in dirs if comp[n] != "nein" or (self.addons_dir / n).exists()]
            vf = meta.get("vfolder")
            strong = (comp[vf] == "nein") if vf in dirs else not any(c != "nein" for c in comp.values())
            if strong:
                chosen = list(dirs)
                warnings.append("Dieses Paket enthält keine für WoW: Forever (Interface 16xxx) markierte Hauptdatei – "
                                "es wird vermutlich nicht geladen.")
            skipped = [n for n in dirs if n not in chosen]
            if skipped:
                warnings.append("Übersprungen (werden von WoW: Forever nicht geladen): " + ", ".join(skipped))
            vfold = vf if vf in chosen else min(chosen, key=len)
            old = forever_toc(self.addons_dir / vfold, self.client_interface)[1] if (self.addons_dir / vfold).exists() else None
            new = forever_toc(dirs[vfold], self.client_interface)[1] or info.get("version")
            info = dict(info, vfolder=vfold, dirs={n: str(dirs[n]) for n in chosen}, meta=meta)
            return InstallPlan(key, name, source, old, new, chosen, skipped, warnings, strong, st, info)
        except BaseException:
            shutil.rmtree(st, ignore_errors=True)
            raise

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
            return f"manuell ({tilde(self.cfg['download_dir'])})"
        return f"automatisch (aus Browser: {w['source']})" if w["entries"] and w["entries"][0]["default"] \
            else f"automatisch ({w['source']})"

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
        try:
            return subprocess.run(["pgrep", "-f", "-i", r"wow\.exe"], capture_output=True, timeout=5).returncode == 0
        except Exception:
            return False

    def _new_backup_dir(self):
        self.paths.backups.mkdir(parents=True, exist_ok=True)
        base = time.strftime("%Y%m%d-%H%M%S")
        d, n = self.paths.backups / base, 0
        while d.exists():
            n += 1
            d = self.paths.backups / f"{base}-{n}"
        d.mkdir()
        return d

    def _prune_backups(self):
        sets = sorted(p for p in self.paths.backups.iterdir() if p.is_dir()) if self.paths.backups.exists() else []
        for p in sets[:-KEEP_BACKUPS]:
            shutil.rmtree(p, ignore_errors=True)

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

    def apply(self, plans):
        """Installiert alle Plaene in einem gemeinsamen Backup-Satz. Fehler je Plan -> Rollback dieses Plans."""
        results = []
        with self._apply_lock:
            bdir = self._new_backup_dir()
            try:
                for plan in plans:
                    dirs = {n: Path(p) for n, p in (plan.extra.get("dirs") or {}).items() if n in plan.install_folders}
                    try:
                        moved = self._swap(dirs, bdir)
                    except Exception as e:
                        results.append(Result(plan.key, plan.name, False, f"Fehler bei der Installation: {e} "
                                              "(Zustand wiederhergestellt)", None))
                        self.discard(plan)
                        continue
                    try:
                        self._record(plan, list(dirs))
                    except Exception as e:
                        self.log(f"Konfiguration konnte nicht gespeichert werden: {e}")
                    results.append(Result(plan.key, plan.name, True, f"{len(dirs)} Ordner installiert",
                                          bdir.name if moved else None))
                    self.discard(plan)
            finally:
                for plan in plans:
                    self.discard(plan)
                with contextlib.suppress(OSError):
                    bdir.rmdir()  # leerer Satz
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
                self.log(f"Erkennung nach Installation nicht möglich: {e}")

    def plan_uninstall(self, pkg):
        names = [n for n in pkg.folders if (self.addons_dir / n).exists() or (self.addons_dir / n).is_symlink()]
        gone = {n.lower() for n in names}
        warnings = []
        if len(names) < len(pkg.folders):
            warnings.append("Nicht vorhanden: " + ", ".join(n for n in pkg.folders if n not in names))
        dependents = {}
        for f in self._addon_folders():
            if f.lower() in gone:
                continue
            deps = toc_dependencies(self.addons_dir / f, self.client_interface)
            need = sorted(n for n in names if n.lower() in deps)
            if need:
                dependents[f] = need
        for f, need in dependents.items():
            warnings.append(f"{f} benötigt {', '.join(need)}")
        return UninstallPlan(pkg.key, pkg.name, names, dependents, warnings)

    def uninstall(self, plans):
        """Verschiebt die Ordner in einen neuen Backup-Satz (per restore rueckgaengig machbar)."""
        results = []
        with self._apply_lock:
            bdir = self._new_backup_dir()
            try:
                for plan in plans:
                    if not plan.folders:
                        results.append(Result(plan.key, plan.name, False, "Keine Ordner vorhanden."))
                        continue
                    try:
                        self._move_out(plan.folders, bdir)
                    except Exception as e:
                        results.append(Result(plan.key, plan.name, False, f"Fehler: {e} (Zustand wiederhergestellt)"))
                        continue
                    try:
                        self._forget(plan.folders)
                    except Exception as e:
                        self.log(f"Konfiguration konnte nicht gespeichert werden: {e}")
                    results.append(Result(plan.key, plan.name, True, f"{len(plan.folders)} Ordner entfernt", bdir.name))
            finally:
                with contextlib.suppress(OSError):
                    bdir.rmdir()
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
            try:
                created = datetime.strptime(p.name[:15], "%Y%m%d-%H%M%S").timestamp()
            except ValueError:
                created = p.stat().st_mtime
            out.append(BackupSet(p.name, p, created, sorted(x.name for x in p.iterdir())))
        return out

    def restore(self, bset):
        names = sorted(x.name for x in Path(bset.path).iterdir()) if Path(bset.path).is_dir() else []
        if not names:
            return Result(bset.name, bset.name, False, "Sicherung ist leer oder fehlt.")
        with self._apply_lock:
            bdir = self._new_backup_dir()
            try:
                self._swap({n: Path(bset.path) / n for n in names}, bdir)
            except Exception as e:
                return Result(bset.name, bset.name, False, f"Fehler: {e} (Zustand wiederhergestellt)")
            finally:
                with contextlib.suppress(OSError):
                    bdir.rmdir()
            with contextlib.suppress(OSError):
                Path(bset.path).rmdir()
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
        return Result(bset.name, bset.name, True, f"Wiederhergestellt: {', '.join(names)}", bdir.name)

    # -- Zuordnung unbekannter Ordner
    def assign_folders(self, folders, name=None, cf_id=None, gh=None):
        """Ordner manuell einem CF-Projekt (ID) oder GitHub-Repo zuordnen. -> Paket-Key."""
        if not cf_id and not gh:
            raise ValueError("CF-ID oder GitHub-Repo nötig")
        key = f"cf-{cf_id}" if cf_id else "gh-" + gh.replace("/", "-")
        folders = list(folders)
        with self.cfg.lock:
            old = self.cfg["packages"].get(key) or {}
            allf = sorted(set(old.get("folders", [])) | set(folders))
            self.cfg["packages"][key] = dict(key=key, name=name or old.get("name") or folders[0], folders=allf,
                                             vfolder=min(allf, key=len), cf=int(cf_id) if cf_id else None, gh=gh)
            self.cfg.save()
        return key
