"""Pfade, Config und Browser-Download-Ordner."""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from wfa_i18n import _
from wfa_base import APP_NAME, install_kind

# ---------------------------------------------------------------- Pfade / Config

class Paths:
    def __init__(self, home=None):
        env = os.environ.get("WOW_FA_HOME")
        if home or env:
            base = Path(home or env).expanduser()
            self.config_dir, self.data_dir, self.cache = base, base, base / "cache"
        elif install_kind() != "source":
            # Release-Datei, Paket und Flatpak: Programmordner ist nicht (sinnvoll) beschreibbar -> XDG.
            # Im Flatpak zeigen die XDG-Variablen nach ~/.var/app/<ID>/; das Manifest gibt dort die Host-Ordner
            # xdg-config/xdg-data/<APP_NAME> frei, so teilen sich alle Installationsarten dieselben Daten.
            h = Path.home()
            self.config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or h / ".config") / APP_NAME
            self.data_dir = Path(os.environ.get("XDG_DATA_HOME") or h / ".local" / "share") / APP_NAME
            self.cache = Path(os.environ.get("XDG_CACHE_HOME") or h / ".cache") / APP_NAME
        else:
            base = Path(__file__).resolve().parent
            self.config_dir, self.data_dir, self.cache = base, base, base / "cache"
        self.config_file = self.config_dir / "config.json"
        self.backups = self.data_dir / "backups"
        self.sv_backups = self.data_dir / "sv_backups"
        self.history = self.data_dir / "history.jsonl"


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
    "direct_download": (bool, True), "close_to_tray": (bool, True), "check_interval_min": (int, 60),
    "auto_update": (bool, False), "ignored": (list, []), "tray_notified": (dict, {}),
    "self_update_check": (bool, True), "self_auto_update": (bool, False), "self_update_skipped": (str, ""),
    "pins": (dict, {}), "channels": (dict, {}), "sv_backup": (bool, True), "assign_failed": (dict, {}),
    "autostart_portal": (bool, False),   # Flatpak: Autostart ueber das Hintergrund-Portal eingerichtet
    "expert": (bool, False),             # Erweiterte Funktionen im Menue zeigen
    "language": (str, "auto"),           # auto, de oder en (wfa_i18n)
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
                raise ValueError(_("kein JSON-Objekt"))
        except FileNotFoundError:
            loaded = {}
        except (OSError, ValueError) as e:
            loaded = {}
            bad = paths.config_file.with_name(paths.config_file.name + ".bad")
            with contextlib.suppress(OSError):
                shutil.copy2(paths.config_file, bad)
                os.chmod(bad, 0o600)
            if log:
                log(_("Config nicht lesbar ({error}); Kopie in {name}, starte mit Standardwerten.").format(error=e, name=bad.name))
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
        if not 15 <= self.d["check_interval_min"] <= 1440:
            self.d["check_interval_min"] = 60

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
    return _("(leer)") if not key else ("*" * max(len(key) - 4, 0) + key[-4:])
