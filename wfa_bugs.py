"""Fehleranalyse aus !BugGrabber: sicherer Lua-Literal-Parser, Fehlerliste, Gruppierung je Addon.

Es wird nichts ausgefuehrt: die SavedVariables-Datei wird nur als Datenliteral gelesen.
Defekte oder abgeschnittene Dateien liefern, was bis zur Bruchstelle lesbar war.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wfa_i18n import _

TIME_FMT = "%Y/%m/%d %H:%M:%S"
MAX_DEPTH = 80
SAMPLE_MAX = 3
SAMPLE_LEN = 300


# ---------------------------------------------------------------- Lua-Literal-Parser

class _Stop(Exception):
    """Ende der lesbaren Daten (Dateiende oder Syntaxfehler)."""


_WS = re.compile(r"[ \t\r\n\f\v\ufeff]+")
_LONG_OPEN = re.compile(r"\[(=*)\[")
_NUM = re.compile(r"[+-]?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QSTR = {'"': re.compile(r'"((?:[^"\\\n]|\\z\s*|\\[\s\S])*)"'), "'": re.compile(r"'((?:[^'\\\n]|\\z\s*|\\[\s\S])*)'")}
_ESC = re.compile(r"\\(?:(\d{1,3})|x([0-9a-fA-F]{2})|u\{([0-9a-fA-F]+)\}|z\s*|(\r\n|\n\r|\n|\r)|([\s\S]))")
_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
_KEYWORDS = {"true": True, "false": False, "nil": None}


def _unescape(s: str) -> str:
    if "\\" not in s:
        return s

    def rep(m):
        dec, hx, uni, nl, ch = m.groups()
        if dec is not None:
            return chr(min(int(dec), 255))
        if hx is not None:
            return chr(int(hx, 16))
        if uni is not None:
            try:
                return chr(int(uni, 16))
            except (ValueError, OverflowError):
                return "?"
        if nl is not None:
            return "\n"
        if ch is not None:
            return _SIMPLE.get(ch, ch)
        return ""   # \z
    s = _ESC.sub(rep, s)
    # Lua-Bytes (UTF-8, als chr(<256) gelesen) zurueck in Text wandeln, wenn gueltig
    if any(0x80 <= ord(c) < 0x100 for c in s) and all(ord(c) < 0x100 for c in s):
        try:
            return s.encode("latin-1").decode("utf-8")
        except UnicodeError:
            pass
    return s


class _Parser:
    def __init__(self, text: str):
        self.s = text
        self.n = len(text)
        self.i = 0
        self.broken = False

    def skip(self):
        s, n = self.s, self.n
        while self.i < n:
            m = _WS.match(s, self.i)
            if m:
                self.i = m.end()
                continue
            if s.startswith("--", self.i):
                m = _LONG_OPEN.match(s, self.i + 2)
                if m:
                    end = s.find("]" + m.group(1) + "]", m.end())
                    self.i = n if end < 0 else end + len(m.group(1)) + 2
                else:
                    nl = s.find("\n", self.i)
                    self.i = n if nl < 0 else nl + 1
                continue
            break

    def peek(self) -> str:
        self.skip()
        return self.s[self.i] if self.i < self.n else ""

    def expect(self, ch: str):
        if self.peek() != ch:
            raise _Stop
        self.i += 1

    def long_string(self, m):
        end = self.s.find("]" + m.group(1) + "]", m.end())
        if end < 0:
            self.i = self.n
            raise _Stop
        body = self.s[m.end():end]
        self.i = end + len(m.group(1)) + 2
        if body.startswith("\r\n"):
            return body[2:]
        return body[1:] if body.startswith("\n") else body

    def value(self, depth=0):
        c = self.peek()
        if not c:
            raise _Stop
        if c == "{":
            return self.table(depth + 1)
        if c in _QSTR:
            m = _QSTR[c].match(self.s, self.i)
            if not m:
                self.i = self.n   # unbeendeter String: Rest der Datei ist unbrauchbar
                raise _Stop
            self.i = m.end()
            return _unescape(m.group(1))
        if c == "[":
            m = _LONG_OPEN.match(self.s, self.i)
            if not m:
                raise _Stop
            return self.long_string(m)
        m = _NUM.match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            try:
                return int(t, 16) if "x" in t.lower() else int(t) if re.fullmatch(r"[+-]?\d+", t) else float(t)
            except (ValueError, OverflowError):
                return 0
        m = _NAME.match(self.s, self.i)
        if m and m.group(0) in _KEYWORDS:
            self.i = m.end()
            return _KEYWORDS[m.group(0)]
        raise _Stop

    def table(self, depth=0):
        """Liest { ... }. Bei Abbruch bleibt das bisher Gelesene erhalten (self.broken)."""
        if depth > MAX_DEPTH:
            self.i = self.n
            raise _Stop
        self.i += 1   # {
        out: dict = {}
        idx = 1
        try:
            while True:
                c = self.peek()
                if not c:
                    raise _Stop
                if c == "}":
                    self.i += 1
                    return out
                if c in ",;":
                    self.i += 1
                    continue
                key = None
                if c == "[" and not _LONG_OPEN.match(self.s, self.i):
                    self.i += 1
                    key = self.value(depth)
                    self.expect("]")
                    self.expect("=")
                else:
                    m = _NAME.match(self.s, self.i)
                    if m and m.group(0) not in _KEYWORDS:
                        j = m.end()
                        save = self.i
                        self.i = j
                        if self.peek() == "=" and self.s[self.i:self.i + 2] != "==":
                            self.i += 1
                            key = m.group(0)
                        else:
                            self.i = save
                v = self.value(depth)
                if key is None:
                    key, idx = idx, idx + 1
                if v is not None:
                    out[key] = v
        except _Stop:
            self.broken = True
            return out

    def assignments(self) -> dict:
        """Top-Level-Zuweisungen `Name = Wert`."""
        out = {}
        while True:
            self.skip()
            if self.i >= self.n:
                break
            m = _NAME.match(self.s, self.i)
            if not m:
                self.broken = True
                break
            self.i = m.end()
            try:
                self.expect("=")
                out[m.group(0)] = self.value()
            except _Stop:
                self.broken = True
                break
            if self.broken:
                break
        return out


def parse_lua_assignments(text: str) -> tuple[dict, bool]:
    """Liest `Name = <Literal>`-Zuweisungen. Gibt (Werte, vollstaendig) zurueck."""
    p = _Parser(text)
    res = p.assignments()
    return res, not p.broken


def _as_list(v) -> list:
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        ints = sorted(k for k in v if isinstance(k, int))
        return [v[k] for k in ints]
    return []


# ---------------------------------------------------------------- Fehler lesen

@dataclass
class BugError:
    message: str
    stack: str = ""
    time: datetime | None = None
    count: int = 1
    session: int | None = None
    folders: list[str] = field(default_factory=list)


_ADDON_PATH = re.compile(r"AddOns[/\\]+([^/\\:\"'\]\r\n]+?)[/\\]", re.I)  # nur Ordner, auch mit Leerzeichen


def folders_in(text: str) -> list[str]:
    """Addon-Ordner aus Pfaden `Interface/AddOns/<Ordner>/` (auch Backslash, auch in [string "@..."])."""
    seen = []
    for m in _ADDON_PATH.finditer(text or ""):
        f = m.group(1)
        if f not in seen:
            seen.append(f)
    return seen


def _str(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, bool) or v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    return ""


def _int(v, default=None):
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        try:
            return int(v)
        except (ValueError, OverflowError):
            return default
    if isinstance(v, str) and re.fullmatch(r"\s*-?\d+\s*", v):
        return int(v)
    return default


def _time(v) -> datetime | None:
    if isinstance(v, str):
        try:
            return datetime.strptime(v.strip(), TIME_FMT)
        except ValueError:
            return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return datetime.fromtimestamp(v)
        except (ValueError, OverflowError, OSError):
            return None
    return None


def _entry(raw) -> tuple[BugError, str] | None:
    if not isinstance(raw, dict):
        return None
    msg = _str(raw.get("message"))
    stack = _str(raw.get("stack"))
    if not msg and not stack:
        return None
    first = folders_in(msg) or folders_in(stack)
    t = _time(raw.get("time"))
    cnt = _int(raw.get("counter"), 1)
    err = BugError(msg, stack, t, cnt if cnt and cnt > 0 else 1, _int(raw.get("session")), first[:1])
    raw_time = raw.get("time")
    return err, _str(raw_time)


def parse_bug_grabber(text: str) -> list[tuple[BugError, str]]:
    """Fehler aus dem Text einer !BugGrabber.lua (mit der Roh-Zeitangabe fuer die Duplikatpruefung)."""
    vals, _ok = parse_lua_assignments(text)
    db = vals.get("BugGrabberDB")
    errs = _as_list(db.get("errors")) if isinstance(db, dict) else []
    out = []
    for raw in errs:
        e = _entry(raw)
        if e:
            out.append(e)
    return out


def _ci_child(parent: Path, name: str, want_dir=None):
    try:
        for c in parent.iterdir():
            if c.name.lower() == name.lower() and (want_dir is None or c.is_dir() == want_dir):
                return c
    except OSError:
        pass
    return None


def bug_grabber_installed(addons_dir) -> bool:
    """Ist !BugGrabber oder BugSack installiert (Ordnername ohne Beachtung der Schreibweise)?"""
    if not addons_dir:
        return False
    d = Path(addons_dir)
    return any(_ci_child(d, n, True) for n in ("!BugGrabber", "BugSack"))


def bug_files(wtf) -> list[Path]:
    """Alle !BugGrabber.lua unter WTF/Account/*/SavedVariables."""
    out = []
    if not wtf:
        return out
    acc_root = _ci_child(Path(wtf), "Account", True)
    if not acc_root:
        return out
    try:
        accounts = sorted(p for p in acc_root.iterdir() if p.is_dir())
    except OSError:
        return out
    for acc in accounts:
        sv = _ci_child(acc, "SavedVariables", True)
        f = _ci_child(sv, "!BugGrabber.lua", False) if sv else None
        if f:
            out.append(f)
    return out


def load_errors(wtf) -> list[BugError]:
    """Fehler aller Konten, neueste zuletzt (Fehler ohne Zeit zuerst). Identische (message+time) zaehlen einmal."""
    seen = set()
    out: list[BugError] = []
    for f in bug_files(wtf):
        try:
            text = f.read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        for err, raw_time in parse_bug_grabber(text):
            k = (err.message, raw_time)
            if k in seen:
                continue
            seen.add(k)
            out.append(err)
    out.sort(key=lambda e: e.time or datetime.min)
    return out


# ---------------------------------------------------------------- Gruppierung

@dataclass
class ErrorGroup:
    key: str
    name: str
    folders: list[str]
    count: int
    first: datetime | None
    last: datetime | None
    last_update: dict | None
    since_update: int
    before_update: int
    samples: list[str]


def _ts(e: dict) -> datetime | None:
    try:
        return datetime.strptime(str(e.get("ts", "")), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _is_update(e: dict) -> bool:
    """Installation/Update/Versionswechsel/Automatisch: Eintrag mit Paket und neuer Version."""
    return bool(isinstance(e, dict) and e.get("key") and e.get("new"))


def _short(msg: str) -> str:
    line = (msg or "").strip().splitlines()[0] if (msg or "").strip() else ""
    return line if len(line) <= SAMPLE_LEN else line[:SAMPLE_LEN - 1] + "…"


def group_errors(errors, folder_to_addon: dict, history: list) -> list[ErrorGroup]:
    """Fehler je Addon buendeln. folder_to_addon: Ordner -> (Schluessel, Name); history: Eintraege wie read_history()."""
    lower = {str(f).lower(): (str(f), v) for f, v in (folder_to_addon or {}).items()}
    groups: dict[str, dict] = {}
    for e in errors:
        folder = e.folders[0] if e.folders else ""
        hit = lower.get(folder.lower()) if folder else None
        if hit:
            folder, (key, name) = hit[0], hit[1][:2]
        elif folder:
            key, name = f"folder:{folder}", folder
        else:
            key, name = "folder:", _("Unbekannt")
        g = groups.setdefault(key, {"name": name, "folders": [], "errs": []})
        if folder and folder not in g["folders"]:
            g["folders"].append(folder)
        g["errs"].append(e)

    upd = [(h, _ts(h)) for h in (history or []) if _is_update(h)]
    upd = [(h, t) for h, t in upd if t]
    out = []
    for key, g in groups.items():
        fl = {f.lower() for f in g["folders"]}
        best = None
        for h, t in upd:
            hf = {str(x).lower() for x in (h.get("folders") or [])}
            if h.get("key") == key or (fl & hf):
                if best is None or t > best[1]:
                    best = (h, t)
        errs = sorted(g["errs"], key=lambda e: e.time or datetime.min, reverse=True)
        timed = [e.time for e in errs if e.time]
        since = before = 0
        if best:
            for e in errs:
                if e.time:
                    if e.time >= best[1]:
                        since += e.count
                    else:
                        before += e.count
        samples = []
        for e in errs:
            s = _short(e.message)
            if s and s not in samples:
                samples.append(s)
                if len(samples) >= SAMPLE_MAX:
                    break
        out.append(ErrorGroup(key, g["name"], sorted(g["folders"], key=str.lower), sum(e.count for e in errs),
                              min(timed) if timed else None, max(timed) if timed else None,
                              best[0] if best else None, since, before, samples))
    out.sort(key=lambda g: (-g.since_update, -g.count, g.name.lower()))
    return out
