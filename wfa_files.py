"""Zip, Pfadsuche und Startmenue."""
from __future__ import annotations

import contextlib
import os
import re
import shlex
import shutil
import stat
import sys
import zipfile
from pathlib import Path

from wfa_i18n import _
from wfa_base import APP_ID, APP_NAME, MAX_UNPACKED, in_flatpak, install_kind, managed_install, package_channel
from wfa_savedvars import SavedVarsMixin

# ---------------------------------------------------------------- Zip

def safe_extract(zpath, dest):
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zpath) as zf:
        infos = zf.infolist()
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise ValueError(_("Zip entpackt zu groß"))
        for i in infos:
            name = i.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if name.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", name):
                raise ValueError(_("Unsicherer Pfad im Zip: {name}").format(name=i.filename))
            if stat.S_IFMT(i.external_attr >> 16) == stat.S_IFLNK:
                raise ValueError(_("Symlink im Zip abgelehnt: {name}").format(name=i.filename))
            if parts and parts[0] == "__MACOSX":
                continue
            target = dest.joinpath(*parts)
            if dest not in target.resolve().parents and target.resolve() != dest:
                raise ValueError(_("Unsicherer Pfad im Zip: {name}").format(name=i.filename))
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
    if p.name.lower() not in ("_forever_", "interface", "addons"):
        # z. B. "World of Warcraft" gewaehlt; ein zusaetzliches Interface daneben (alter Client) aendert nichts
        sub = SavedVarsMixin._ci_child(p, "_forever_")
        if sub is not None:
            return sub / "Interface" / "AddOns"
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
            return False, _("Das ist kein AddOns-Ordner.")
        if "_forever_" not in [x.lower() for x in q.parts]:
            return True, _("Warnung: Im Pfad kommt kein Ordner „_forever_“ vor – ist das wirklich WoW: Forever?")
        return True, ""
    # AddOns (bzw. Interface/AddOns) fehlt noch: ok, wenn Interface oder _forever_ existiert. Gilt auch fuer den
    # schon normalisierten Pfad, den der Dialog beim Uebernehmen erneut prueft.
    iface = q.parent
    if q.name.lower() == "addons" and iface.name.lower() == "interface" and (
            iface.is_dir() or (iface.parent.is_dir() and iface.parent.name.lower() == "_forever_")):
        return True, _("Der Ordner Interface/AddOns wird angelegt.")
    return False, _("Ordner existiert nicht.")


def portal_path(p):
    """True, wenn p ueber das Dokument-Portal freigegeben wurde (/run/user/<uid>/doc/...)."""
    parts = Path(p).parts
    return len(parts) > 4 and parts[1] == "run" and parts[2] == "user" and parts[4] == "doc"


def sandbox_hint(addons):
    """Hinweis, wenn im Flatpak nur der AddOns-Ordner selbst freigegeben ist: dann fehlen .build.info
    (Client-Version, im WoW-Ordner) und WTF (SavedVariables, im _forever_-Ordner). Sonst ""."""
    if not in_flatpak() or not addons:
        return ""
    a = Path(addons)
    if (a.parent.parent.parent / ".build.info").is_file():
        return ""
    if portal_path(a) or not a.parent.parent.is_dir():
        return _("Im Flatpak sieht der Manager nur den gewählten Ordner. Wähle besser den Ordner "
                 "„World of Warcraft“ (oberhalb von _forever_), damit Client-Version und SavedVariables "
                 "erreichbar sind.")
    return ""


def sandbox_blocked_libraries():
    """Steam-Bibliotheken aus libraryfolders.vdf, die im Flatpak nicht freigegeben sind (z. B. auf einer zweiten
    Platte). -> [Path]; ausserhalb des Flatpaks immer leer."""
    if not in_flatpak():
        return []
    out = []
    for lib in _steam_libraries():
        if not lib.is_dir() and lib not in out:
            out.append(lib)
    return out


def flatpak_override_cmd(path):
    return f"flatpak override --user --filesystem={shlex.quote(str(path))} {APP_ID}"


# ---------------------------------------------------------------- Startmenue

def asset_path(name):
    base = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent)
    return base / "assets" / name


def _desktop_quote(s):
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    return f'"{s}"'


def _desktop_exec():
    if install_kind() == "package":
        return APP_NAME          # Starter liegt im PATH (/usr/bin)
    if getattr(sys, "frozen", False):
        return _desktop_quote(sys.executable)
    return "python3 " + _desktop_quote(str(Path(__file__).resolve().parent / "wow-forever-addon-manager.py"))


def autostart_path():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / f"{APP_NAME}.desktop"


def autostart_enabled():
    return autostart_path().is_file()


def set_autostart(on):
    """Schreibt bzw. entfernt den Autostart-Eintrag (Start im Tray). -> Pfad oder None (entfernt).
    Im Flatpak nicht nutzbar (der Ordner liegt in der Sandbox); dort setzt wfa_portal den Autostart."""
    if in_flatpak():
        raise OSError(_("Im Flatpak wird der Autostart über das Hintergrund-Portal gesetzt."))
    target = autostart_path()
    if not on:
        with contextlib.suppress(FileNotFoundError):
            target.unlink()
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    icon = (Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME / "icon.svg")
    if install_kind() == "package":
        src = f"Icon={APP_ID}\n"     # vom Paket ins hicolor-Theme installiert
    else:
        src = f"Icon={icon}\n" if icon.is_file() else f"Icon={APP_NAME}\n"
    target.write_text(
        "[Desktop Entry]\nType=Application\nName=WoW: Forever Addon-Manager\n"
        "Comment=Addons für WoW: Forever verwalten\n"
        f"Exec={_desktop_exec()} --tray\n{src}Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=20\n", "utf-8")
    return target


def install_desktop_entry():
    """Legt den Startmenue-Eintrag (benutzerlokal, $XDG_DATA_HOME) an. -> Pfad der .desktop-Datei.
    Pakete und Flatpak bringen den Eintrag selbst mit."""
    if managed_install():
        raise OSError(_("Der Startmenü-Eintrag wird mit dem Paket ({package}) installiert.").format(package=package_channel()))
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    icon_dir = data / APP_NAME
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon = icon_dir / "icon.svg"
    src = asset_path("icon.svg")
    if src.is_file():
        shutil.copyfile(src, icon)
    exe = _desktop_exec()
    apps = data / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    target = apps / f"{APP_NAME}.desktop"
    target.write_text(
        "[Desktop Entry]\nType=Application\nName=WoW: Forever Addon-Manager\n"
        "Comment=Addons für WoW: Forever verwalten\n"
        f"Exec={exe}\nIcon={icon}\nTerminal=false\nCategories=Game;Utility;\n"
        f"StartupWMClass={APP_NAME}\n", "utf-8")
    return target
