"""Gemeinsame Hilfen: Netzsperre, Temp-Umgebung und Bauer fuer Fake-Ordner."""
import contextlib
import os
import socket
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _blocked(*_a, **_kw):
    raise RuntimeError("Netzzugriff im Test gesperrt")


class OfflineCase(unittest.TestCase):
    """Basis: sperrt das Netz und biegt HOME/XDG/WOW_FA_HOME auf einen Temp-Ordner um."""

    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(socket.socket, "connect", _blocked))
        stack.enter_context(mock.patch.object(socket, "create_connection", _blocked))
        tmp = stack.enter_context(tempfile.TemporaryDirectory())
        self.tmp = Path(tmp).resolve()
        self.wfa_home = self.tmp / "wfa-home"
        env = {"HOME": str(self.tmp / "home"), "WOW_FA_HOME": str(self.wfa_home),
               "XDG_CONFIG_HOME": str(self.tmp / "xdg-config"), "XDG_DATA_HOME": str(self.tmp / "xdg-data"),
               "XDG_CACHE_HOME": str(self.tmp / "xdg-cache")}
        stack.enter_context(mock.patch.dict(os.environ, env))
        os.environ.pop("CF_API_KEY", None)


def write(path, text="", mode="w"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        mode = "wb"
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        f.write(text)
    return path


def make_addon(addons, name, interface=16001, version="1.0", extra_toc="", files=None):
    """Legt <addons>/<name>/<name>.toc samt Lua-Datei an."""
    d = Path(addons) / name
    toc = f"## Interface: {interface}\n## Title: {name}\n## Version: {version}\n{extra_toc}\n{name}.lua\n"
    write(d / f"{name}.toc", toc)
    write(d / f"{name}.lua", "-- " + name)
    for rel, text in (files or {}).items():
        write(d / rel, text)
    return d


def make_wow(root, build_info=None, flavor=None):
    """Fake-Installation: <root>/World of Warcraft/_forever_/Interface/AddOns -> AddOns-Pfad."""
    wow = Path(root) / "World of Warcraft"
    addons = wow / "_forever_" / "Interface" / "AddOns"
    addons.mkdir(parents=True)
    if build_info is not None:
        write(wow / ".build.info", build_info)
    if flavor is not None:
        write(wow / "_forever_" / ".flavor.info", flavor)
    return addons


def build_info(*rows):
    """rows: (product, version) -> Inhalt einer .build.info."""
    out = ["Branch!STRING:0|Product!STRING:0|Version!STRING:0"]
    out += [f"eu|{p}|{v}" for p, v in rows]
    return "\n".join(out) + "\n"


def make_zip(path, entries):
    """entries: Name -> Inhalt (str/bytes). Namen werden unveraendert gespeichert."""
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return Path(path)
