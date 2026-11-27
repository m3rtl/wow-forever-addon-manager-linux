"""Addon-Sets: benannte Ordnerlisten, die sich ueber AddOns.txt aller Charaktere anwenden lassen."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import wfa_chars
from wfa_toc import toc_dependency_names, toc_files


@dataclass
class SetPlan:
    changes: dict = field(default_factory=dict)       # Ordner -> an/aus
    missing: list = field(default_factory=list)       # Set-Ordner, die nicht installiert sind
    deps_added: list = field(default_factory=list)    # Pflichtabhaengigkeiten, die zusaetzlich an bleiben


def _sets(cfg):
    d = cfg["addon_sets"]
    if not isinstance(d, dict):
        d = cfg["addon_sets"] = {}
    return d


def list_sets(cfg) -> list[str]:
    return sorted(_sets(cfg), key=str.lower)


def get_set(cfg, name) -> list[str] | None:
    e = _sets(cfg).get(name)
    f = e.get("folders") if isinstance(e, dict) else None
    return list(f) if isinstance(f, list) else None


def save_set(cfg, name, folders):
    old = _sets(cfg).get(name)
    created = old.get("created") if isinstance(old, dict) and old.get("created") else datetime.now().isoformat(timespec="seconds")
    _sets(cfg)[name] = {"folders": sorted(set(folders), key=str.lower), "created": created}
    cfg.save()


def delete_set(cfg, name):
    if _sets(cfg).pop(name, None) is not None:
        cfg.save()


def rename_set(cfg, old, new) -> bool:
    sets = _sets(cfg)
    new = (new or "").strip()
    if old not in sets or not new or (new in sets and new != old):
        return False
    if new != old:
        sets[new] = sets.pop(old)
        cfg.save()
    return True


def set_from_states(states, installed_folders) -> list[str]:
    """Aktivierte unter den installierten Ordnern (Eintrag fehlt = aktiviert), sortiert."""
    return sorted((f for f in installed_folders if wfa_chars.is_enabled(states, f)), key=str.lower)


def _installed(addons_dir):
    out = []
    try:
        names = sorted(os.listdir(addons_dir))
    except OSError:
        return out
    for n in names:
        p = Path(addons_dir) / n
        if p.is_dir() and any(f.lower().endswith(".toc") for f in toc_files(p)):
            out.append(n)
    return out


def plan_set(folders, addons_dir, client_interface) -> SetPlan:
    installed = {n.lower(): n for n in _installed(addons_dir)}
    want = {}
    missing = []
    for f in folders:
        if f.lower() in installed:
            want[f.lower()] = True
        elif f not in missing:
            missing.append(f)
    todo = list(want)
    deps = set()
    while todo:   # Pflichtabhaengigkeiten rekursiv (Zyklen sicher durch want)
        cur = todo.pop()
        for d in toc_dependency_names(Path(addons_dir) / installed[cur], client_interface):
            k = d.lower()
            if k in installed and k not in want:
                want[k] = True
                deps.add(installed[k])
                todo.append(k)
    return SetPlan({n: k in want for k, n in installed.items()}, missing, sorted(deps, key=str.lower))


def apply_set(plan, chars, backup_dir, install=None) -> None:
    """Schreibt den Plan in alle Charaktere; der Aufrufer prueft vorher, dass WoW nicht laeuft.
    install: Kennung der aktiven Installation fuer die AddOns.txt-Backups."""
    wfa_chars.write_states_all(chars, plan.changes, backup_dir, install=install)
