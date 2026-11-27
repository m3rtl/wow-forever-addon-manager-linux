"""TOC, Versionen und CurseForge-Fingerprint."""
from __future__ import annotations

import os
import re
import struct
from pathlib import Path

from wfa_base import CURRENT, DEFAULT_CLIENT, FOREVER_RE, NEWER, UNKNOWN, UPDATE, _read_text

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


def toc_dependency_names(folder, client=DEFAULT_CLIENT):
    """Ordnernamen (Schreibweise wie im TOC), die der Forever-TOC als Abhaengigkeit verlangt."""
    toc = forever_toc(folder, client)[2]
    out = []
    for k, v in (parse_toc(toc).items() if toc else ()):
        if k.startswith("dep") or k == "requireddeps":
            out += [x.strip() for x in v.split(",") if x.strip() and x.strip() not in out]
    return out


def toc_dependencies(folder, client=DEFAULT_CLIENT):
    """Ordnernamen (klein geschrieben), die der Forever-TOC als Abhaengigkeit verlangt."""
    return {x.lower() for x in toc_dependency_names(folder, client)}


def toc_meta(folder):
    """TOC-Felder eines Ordners: bevorzugt die Forever-TOC, sonst die erste .toc."""
    toc = forever_toc(folder)[2]
    if toc:
        return parse_toc(toc)
    for fn in toc_files(folder).values():
        if fn.lower().endswith(".toc"):
            return parse_toc(Path(folder) / fn)
    return {}


def _slug(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def client_version(addons):
    """Spielversion des installierten Clients (z. B. "1.60.1") aus <WoW>/.build.info, sonst None.
    addons: <WoW>/<_flavor_>/Interface/AddOns; der Flavor (z. B. wowf) steht in <_flavor_>/.flavor.info."""
    flavor_dir = Path(addons).parent.parent
    lines = [ln.strip() for ln in _read_text(flavor_dir / ".flavor.info").splitlines() if ln.strip()]
    flavor = lines[1] if len(lines) > 1 else None
    rows = [ln.split("|") for ln in _read_text(flavor_dir.parent / ".build.info").splitlines() if ln.strip()]
    if len(rows) < 2:
        return None
    head = [c.split("!")[0].strip().lower() for c in rows[0]]
    found = []
    for r in rows[1:]:
        row = dict(zip(head, (c.strip() for c in r)))
        m = re.match(r"(\d+)\.(\d+)\.(\d+)", row.get("version", ""))
        if m and (flavor is None or row.get("product") == flavor):
            found.append(m.group(0))
    forever = [v for v in found if FOREVER_RE.match(v + ".")]
    return (forever or found or [None])[0]


def version_interface(ver):
    """"1.60.1" -> 16001 (Major*10000 + Minor*100 + Patch)"""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", ver or "")
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3)) if m else None


def client_interface(addons):
    """Interface-Nummer des Clients: aus der Spielversion in .build.info; fehlt sie, die Nummer, die die meisten
    installierten Addons angeben (nicht die hoechste: ein einzelnes Addon mit einer kuenftigen Nummer wuerde sonst
    alle anderen als veraltet markieren)."""
    iface = version_interface(client_version(addons))
    if iface and 16000 <= iface < 17000:
        return iface
    votes = {}
    try:
        for d in os.listdir(addons):
            best = 0
            for f in toc_files(Path(addons) / d).values():
                if f.lower().endswith(".toc"):
                    best = max([best] + [i for i in interfaces(parse_toc(Path(addons) / d / f)) if 16000 <= i < 17000])
            if best:
                votes[best] = votes.get(best, 0) + 1
    except OSError:
        pass
    return max(votes, key=lambda i: (votes[i], i)) if votes else DEFAULT_CLIENT


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
