"""Konstanten, Dataclasses und Installationsart."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "0.3.0"

APP_NAME = "wow-forever-addon-manager"
APP_ID = "io.github.m3rtl.WowForeverAddonManager"   # Gtk-Application-ID, Flatpak-ID, Name von .desktop/Icon/Metainfo
UA = f"{APP_NAME}/{__version__}"
DEFAULT_CLIENT = 16001
FOREVER_TYPE_FALLBACK = 88568
MAX_DOWNLOAD = 300 * 1024 * 1024
MAX_UNPACKED = 1024 * 1024 * 1024
DL_TIMEOUT = 30           # Sekunden ohne Daten, bis ein Download als haengend gilt
DL_ATTEMPTS = 3           # Versuche je Download-Weg bei voruebergehenden Fehlern
DL_BACKOFF = (2, 5)       # Wartezeit vor dem 2. und 3. Versuch
KEEP_BACKUPS = 5
HISTORY_MAX = 500
FOREVER_RE = re.compile(r"^1\.6\d\.")
CF_API = "https://api.curseforge.com"
CF_KEY_URL = "https://console.curseforge.com"
CF_SITE = "https://www.curseforge.com"
CF_CDNS = ("https://mediafilez.forgecdn.net", "https://edge.forgecdn.net")
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"  # nur fuer Website/CDN-Downloads
MAX_IMAGE = 2 * 1024 * 1024
IMAGE_HOSTS = ("forgecdn.net", "githubusercontent.com", "github.com")
TYPE_NAMES = {1: "Release", 2: "Beta", 3: "Alpha"}
SORT_FIELDS = {"downloads": 6, "popularity": 2, "updated": 3, "name": 4}

# Status-Konstanten
UPDATE = "UPDATE"
CURRENT = "aktuell"
NEWER = "lokal neuer"
UNKNOWN = "?"
NOKEY = "kein Key"
UNASSIGNED = "nicht zugeordnet"
ERROR = "Fehler"
NO_FOREVER = "keine Forever-Datei"
HELD = "festgehalten"
SKIPPED = "ausgelassen"
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
    """kind: key | forbidden | rate | http | net | stall | corrupt | cancel | nokey | nofile | download | setup | other
    code: HTTP-Status bei kind=http."""

    def __init__(self, msg, kind="other", code=None):
        super().__init__(msg)
        self.kind = kind
        self.code = code

    @property
    def transient(self):
        """Lohnt ein neuer Versuch (Netz, haengende Verbindung, Rate-Limit, Serverfehler, kaputte Datei)?"""
        if self.kind == "http":
            return (self.code or 0) in (408, 425) or (self.code or 0) >= 500
        return self.kind in ("net", "stall", "rate", "corrupt")


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
    notes: str = ""  # GitHub-Release-Body
    rtype: int = 1  # 1 Release, 2 Beta, 3 Alpha (GitHub: Prerelease = Beta)
    deps: list = field(default_factory=list)  # CF-Projekt-IDs der Pflicht-Abhaengigkeiten (relationType 3)


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
    ignored: bool = False
    pin: dict | None = None  # dict(mode="hold"|"skip", since, ref)
    channel: str | None = None  # None = globale Einstellung
    missing: list = field(default_factory=list)  # Ordner, die der TOC verlangt, die aber fehlen


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
    thumbnail_url: str | None = None
    screenshots: list = field(default_factory=list)  # dict(thumb, url, title), max. 4
    updated: str = ""
    categories: list = field(default_factory=list)


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
class DepNeed:
    name: str
    reason: str  # z. B. „benötigt von DBM-Dungeons“
    cand: Candidate | None = None  # None: nur Hinweis, nicht automatisch installierbar
    note: str = ""
    via: str = "cf"  # "cf" (CF-Abhaengigkeit) | "toc" (nur im TOC genannt)


@dataclass
class Suggestion:
    cand: Candidate
    reason: str
    strong: bool = False  # eindeutig und geprueft: darf automatisch zugeordnet werden


@dataclass
class Result:
    key: str
    name: str
    ok: bool
    message: str
    backup_set: str | None = None
    sv_set: str | None = None


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


@dataclass
class SvSet:
    name: str
    path: Path
    created: float
    addons: list  # Namen der gesicherten SavedVariables-Dateien (ohne .lua)
    files: int = 0


def _read_text(path):
    try:
        return Path(path).read_text("utf-8", "replace")
    except OSError:
        return ""


# ---------------------------------------------------------------- Installationsart

_KIND = None


def install_kind():
    """-> "flatpak", "package" (Paketverwaltung, z. B. AUR), "binary" (PyInstaller-Release-Datei) oder "source".
    Pakete legen neben die Module eine Datei PACKAGED (Inhalt: Kanal, z. B. "aur")."""
    global _KIND
    if _KIND is None:
        if os.environ.get("FLATPAK_ID") or os.path.exists("/.flatpak-info"):
            _KIND = "flatpak"
        elif getattr(sys, "frozen", False):
            _KIND = "binary"
        elif (Path(__file__).resolve().parent / "PACKAGED").is_file():
            _KIND = "package"
        else:
            _KIND = "source"
    return _KIND


def package_channel():
    """Name des Pakets fuer Hinweise, z. B. "AUR" oder "Flatpak"; leer fuer Quellcode/Release-Datei."""
    k = install_kind()
    if k == "flatpak":
        return "Flatpak"
    if k == "package":
        txt = _read_text(Path(__file__).resolve().parent / "PACKAGED").strip()
        return txt.upper() if txt.lower() == "aur" else (txt or "Paketverwaltung")
    return ""


def managed_install():
    """Updates, Startmenue-Eintrag und Icon kommen von der Paketverwaltung bzw. Flatpak."""
    return install_kind() in ("flatpak", "package")


def in_flatpak():
    return install_kind() == "flatpak"


_HOST_SPAWN = None


def host_spawn_available():
    """Flatpak: darf das Programm Befehle auf dem Host starten (Freigabe org.freedesktop.Flatpak)?
    Standardmaessig nicht; nur dann laesst sich sehen, ob WoW laeuft. Ergebnis gilt fuer die Laufzeit des Prozesses."""
    global _HOST_SPAWN
    if _HOST_SPAWN is None:
        try:
            _HOST_SPAWN = subprocess.run(["flatpak-spawn", "--host", "true"], capture_output=True,
                                         timeout=5).returncode == 0
        except Exception:  # noqa: BLE001
            _HOST_SPAWN = False
    return _HOST_SPAWN


WOW_DETECT_OVERRIDE = f"flatpak override --user --talk-name=org.freedesktop.Flatpak {APP_ID}"
