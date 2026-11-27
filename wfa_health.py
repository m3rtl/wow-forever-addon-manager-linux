"""Verwaiste Addons (aufgegeben/veraltet) und Konflikte (gemeinsame oder doppelte Ordner)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from wfa_i18n import N_, _
from wfa_toc import clean_title, toc_meta

# CurseForge ModStatus laut CurseForge-API-Doku (UNVERIFIZIERT, im Projekt nicht belegt):
# 7 = Inactive, 8 = Abandoned, 9 = Deleted
CF_ABANDONED = {7: N_("inaktiv"), 8: N_("aufgegeben"), 9: N_("gelöscht")}
FOREVER_OUTDATED = "veraltet"   # Package.forever: TOC-Interface unter dem des Clients


@dataclass
class Health:
    status: str = "ok"                       # "ok" | "stale" | "abandoned"
    reasons: list = field(default_factory=list)
    last_file: datetime | None = None


@dataclass
class Conflict:
    kind: str                                # "shared_folder" | "duplicate"
    folders: list = field(default_factory=list)
    keys: list = field(default_factory=list)


def _date(s):
    """ISO-Zeit (auch mit Z) -> naive UTC-Zeit, sonst None."""
    if not isinstance(s, str) or not s:
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def _info(pkg, cfg):
    """Gecachte Projektdaten (cf_mods) des Pakets; alte Eintraege ohne neue Felder sind ok."""
    mods = cfg["cf_mods"] if isinstance(cfg["cf_mods"], dict) else {}
    keys = []
    if pkg.cf_mod_id:
        keys.append(str(pkg.cf_mod_id))
    gh = (pkg.meta or {}).get("gh")
    if gh:
        keys.append("gh:" + str(gh))
    for k in keys:
        e = mods.get(k)
        if isinstance(e, dict):
            return e
    return {}


def assess(pkgs, cfg, client_interface, now=None) -> dict[str, Health]:
    """pkgs: Liste von wfa_base.Package. Verwaist = Projekt aufgegeben/nicht verfuegbar/archiviert;
    stale = lange keine Forever-Datei UND TOC-Interface (pkg.forever == "veraltet") unter dem Client."""
    now = now or datetime.now()
    if now.tzinfo:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    days = cfg["stale_days"] if isinstance(cfg["stale_days"], int) and cfg["stale_days"] >= 0 else 180   # 0 = aus
    out = {}
    for p in pkgs:
        info = _info(p, cfg)
        h = Health()
        h.last_file = _date(info.get("last_file")) or _date(getattr(p.remote, "file_date", ""))
        if info.get("status") in CF_ABANDONED:
            h.reasons.append(_("Projekt auf CurseForge als {state} markiert").format(state=_(CF_ABANDONED[info["status"]])))
        if info.get("available") is False:
            h.reasons.append(_("Projekt auf CurseForge nicht mehr verfügbar"))
        if info.get("archived") is True:
            h.reasons.append(_("GitHub-Repository ist archiviert"))
        if h.reasons:
            h.status = "abandoned"
        elif days and h.last_file and (now - h.last_file).days >= days and p.forever == FOREVER_OUTDATED:
            h.status = "stale"
            h.reasons.append(_("Seit {days} Tagen keine neue Forever-Datei und TOC älter als der Client").format(
                days=(now - h.last_file).days))
        out[p.key] = h
    return out


def _base(s):
    """Ordner-/Titelname ohne Suffix wie -master, -main oder Versionsnummer."""
    s = re.sub(r"[-_ ]?(master|main|dev|beta)$", "", (s or "").strip(), flags=re.I)
    s = re.sub(r"[-_ ]?v?\d+(\.\d+)*$", "", s, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def conflicts(pkgs, addons_dir) -> list[Conflict]:
    out = []
    owners = {}
    for p in pkgs:
        for f in p.folders:
            owners.setdefault(f.lower(), (f, []))[1].append(p.key)
    shared = set()
    for low, (f, keys) in sorted(owners.items()):
        if len(set(keys)) > 1:
            shared.add(low)
            out.append(Conflict("shared_folder", [f], sorted(set(keys))))
    # Duplikate: gleicher TOC-Titel und (gleiche Projekt-ID/Quelle in verschiedenen Paketen oder gleicher Name ohne Suffix)
    rows = []   # (Ordner, Titel, Paket)
    for p in pkgs:
        for f in p.folders:
            t = clean_title(toc_meta(Path(addons_dir) / f).get("title", "")).lower()
            if t and f.lower() not in shared:
                rows.append((f, t, p))
    seen = set()
    for i, (fa, ta, pa) in enumerate(rows):
        for fb, tb, pb in rows[i + 1:]:
            if ta != tb or fa.lower() == fb.lower() or (fa, fb) in seen:
                continue
            same_src = pa.key != pb.key and bool(
                (pa.cf_mod_id and pa.cf_mod_id == pb.cf_mod_id)
                or ((pa.meta or {}).get("gh") and (pa.meta or {}).get("gh") == (pb.meta or {}).get("gh")))
            if same_src or _base(fa) == _base(fb):
                seen.add((fa, fb))
                # zu behaltender Ordner zuerst: Name ohne Suffix, sonst der kuerzere
                keep = sorted([fa, fb], key=lambda f: (re.sub(r"[^a-z0-9]", "", f.lower()) != _base(f), len(f), f.lower()))
                out.append(Conflict("duplicate", keep, sorted({pa.key, pb.key})))
    return out
