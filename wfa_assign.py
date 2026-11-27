"""Manager-Teil: Zuordnung, Abhaengigkeiten, Export/Import."""
from __future__ import annotations

import contextlib
import json
import os
import re
import time

from wfa_i18n import _
from wfa_base import ApiError, Candidate, DepNeed, Suggestion, __version__
from wfa_sources import CurseForge, parse_github
from wfa_toc import _slug, clean_title, display_version, toc_dependency_names, toc_meta

class AssignMixin:
    # -- Zuordnung unbekannter Ordner
    def assign_folders(self, folders, name=None, cf_id=None, gh=None):
        """Ordner manuell einem CF-Projekt (ID) oder GitHub-Repo zuordnen. -> Paket-Key."""
        if not cf_id and not gh:
            raise ValueError(_("CF-ID oder GitHub-Repo nötig"))
        key = f"cf-{cf_id}" if cf_id else "gh-" + gh.replace("/", "-")
        folders = list(folders)
        with self.cfg.lock:
            old = self.cfg["packages"].get(key) or {}
            allf = sorted(set(old.get("folders", [])) | set(folders))
            self.cfg["packages"][key] = dict(key=key, name=name or old.get("name") or folders[0], folders=allf,
                                             vfolder=min(allf, key=len), cf=int(cf_id) if cf_id else None, gh=gh)
            self.cfg.save()
        return key

    # -- Abhaengigkeiten
    def _have_ids(self, plans):
        have = set(self._installed_ids)
        folders = {f.lower() for f in os.listdir(self.addons_dir)}
        for f, e in self.cfg["cf_fp_cache"].items():
            if isinstance(e, dict) and e.get("mod_id") and f.lower() in folders:
                have.add(int(e["mod_id"]))
        have |= {p.extra["cf_mod_id"] for p in plans if p.extra.get("cf_mod_id")}
        return have, folders

    def resolve_deps(self, plans, cf_only=False, max_depth=2):
        """Fehlende Pflicht-Abhaengigkeiten der geplanten Installationen -> [DepNeed]. Quellen: CF-Abhaengigkeiten
        (relationType 3, rekursiv bis max_depth Ebenen) und die TOC-Zeilen der neuen Ordner. Eintraege ohne `cand`
        sind nur Hinweise. cf_only: TOC-only-Abhaengigkeiten werden nicht per Suche aufgeloest."""
        cf = CurseForge(self.api_key) if self.api_key and not self._key_invalid else None
        tid = self._tid()
        have_ids, have_dirs = self._have_ids(plans)
        batch = {n.lower() for p in plans for n in p.install_folders}
        seen, out, provided = set(have_ids), [], set()
        queue = [(mid, p.name, 1) for p in plans for mid in p.extra.get("cf_deps") or []]
        while queue:
            mid, von, lvl = queue.pop(0)
            if mid in seen:
                continue
            seen.add(mid)
            name, rem, err = self._mod_name(mid), None, ""
            try:
                if cf:
                    if name is None:
                        self._fill_mod_info(cf, [mid])
                        name = self._mod_name(mid)
                    rem = cf.latest(mid, tid, self.allowed_types(f"cf-{mid}"))
                    if rem is None:
                        err = _("keine Forever-Datei bei CurseForge")
                else:
                    err = _("ohne CurseForge-Key nicht installierbar")
            except ApiError as e:
                err = str(e)
            name = name or f"CurseForge {mid}"
            reason = _("benötigt von {name}").format(name=von)
            if rem is None:
                out.append(DepNeed(name, reason, None, err or _("nicht gefunden")))
                continue
            mods = {m.lower() for m in rem.modules if m}
            if mods and mods <= have_dirs:   # Ordner liegen schon da (auch unzugeordnet)
                continue
            provided |= mods
            cand = Candidate("CF", mid, name, page_url=self._mod_url(mid), has_forever=True)
            out.append(DepNeed(name, reason, cand))
            if lvl < max_depth:
                queue += [(d, name, lvl + 1) for d in rem.deps]
        toc = {}
        for p in plans:
            for n, d in (p.extra.get("dirs") or {}).items():
                if n in p.install_folders:
                    for dep in toc_dependency_names(d, self.client_interface):
                        toc.setdefault(dep, p.name)
        for dep, von in sorted(toc.items(), key=lambda t: t[0].lower()):
            low = dep.lower()
            if low in have_dirs or low in batch or low in provided or low.startswith("blizzard_"):
                continue
            need = self._find_dep_folder(cf, tid, dep, seen) if not cf_only and cf else None
            reason = _("benötigt von {name}").format(name=von)
            if need:
                seen.add(need.ident)
                out.append(DepNeed(need.name, reason, need, via="toc"))
            else:
                out.append(DepNeed(dep, reason, None, _("fehlt, nicht automatisch gefunden"), "toc"))
        return out

    def _find_dep_folder(self, cf, tid, name, seen):
        """Eindeutiger CF-Treffer fuer einen Ordnernamen (Name oder Slug stimmt genau) -> Candidate | None."""
        try:
            res = cf.search(name, tid)
        except ApiError:
            return None
        key = _slug(name)
        hits = [m for m in res if key in (_slug(m.get("name")), _slug(m.get("slug"))) and m["id"] not in seen]
        if len(hits) != 1:
            return None
        try:
            files, _more = cf.files(hits[0]["id"], tid)
        except ApiError:
            return None
        newest = max(files, key=lambda x: x.get("fileDate", ""), default=None)
        if not newest or name.lower() not in {(x.get("name") or "").lower() for x in newest.get("modules") or []}:
            return None
        cand = self._candidate(hits[0])
        return cand if cand and cand.has_forever is not False else None

    # -- Nicht zugeordnete Ordner
    def suggest_assignments(self, pkg, verify=False, names=True):
        """Kandidaten fuer ein nicht zugeordnetes Paket -> [Suggestion]: Projekt-ID, CF-/GitHub-Adresse aus dem TOC,
        zuletzt (names) CF-Suche nach Titel/Ordnername. verify: CF-Treffer gelten nur als eindeutig (strong), wenn die
        Forever-Datei genau diesen Ordner enthaelt."""
        cf = CurseForge(self.api_key) if self.api_key and not self._key_invalid else None
        tid = self._tid()
        out, seen = [], set()

        def add(cand, reason, strong=False):
            if (cand.source, str(cand.ident).lower()) in seen:
                return
            seen.add((cand.source, str(cand.ident).lower()))
            out.append(Suggestion(cand, reason, strong))

        def from_cf(m, reason, folder, trusted):
            strong = False
            if verify and trusted and cf:
                files, _more = cf.files(m["id"], tid)
                newest = max(files, key=lambda x: x.get("fileDate", ""), default=None)
                strong = bool(newest) and folder.lower() in {(x.get("name") or "").lower() for x in newest.get("modules") or []}
            add(self._candidate(m), reason, strong)

        for folder in pkg.folders:
            meta = toc_meta(self.addons_dir / folder)
            title = clean_title(meta.get("title")) or folder
            text = " ".join(meta.values())
            for u in re.findall(r"(?:https?://)?github\.com/[\w.-]+/[\w.-]+", text):
                repo = parse_github(u if u.startswith("http") else "https://" + u)
                if repo:
                    add(Candidate("GH", repo, repo.split("/")[1], repo.split("/")[0], "", 0, None, False,
                                  f"https://github.com/{repo}"), _("GitHub-Adresse aus TOC"))
            if not cf:
                continue
            try:
                cid = (meta.get("x-curse-project-id") or "").strip()
                if cid.isdigit():
                    from_cf(cf.get(f"/v1/mods/{int(cid)}")["data"], _("Projekt-ID aus TOC"), folder, True)
                for slug in dict.fromkeys(re.findall(r"curseforge\.com/wow/addons/([\w-]+)", text, re.I)):
                    for m in cf.search(slug, tid):
                        if (m.get("slug") or "").lower() == slug.lower():
                            from_cf(m, _("CurseForge-Adresse aus TOC"), folder, True)
                if names:
                    for term in dict.fromkeys((title, folder)):
                        for m in cf.search(term, tid):
                            if _slug(term) in (_slug(m.get("name")), _slug(m.get("slug"))):
                                from_cf(m, _("Name passt (CurseForge-Suche)"), folder, False)
            except ApiError as e:
                self.notes.append(_("Zuordnung {folder}: {error}").format(folder=folder, error=e))
        return out[:6]

    def assign_target(self, text):
        """Freitext (CF-ID, CF-Adresse, gh:owner/repo, GitHub-URL) -> Candidate fuer assign_folders."""
        t = (text or "").strip()
        repo = parse_github(t if re.match(r"(?i)(https?://|gh:)", t) else re.sub(r"(?i)^(www\.)?github\.com/", "https://github.com/", t))
        if repo:
            return Candidate("GH", repo, repo.split("/")[1], repo.split("/")[0], "", 0, None, False,
                             f"https://github.com/{repo}")
        slug = re.search(r"curseforge\.com/wow/addons/([\w-]+)", t, re.I)
        if t.isdigit():
            return self._candidate(self._cf().get(f"/v1/mods/{int(t)}")["data"])
        if slug:
            for m in self._cf().search(slug.group(1), self._tid()):
                if (m.get("slug") or "").lower() == slug.group(1).lower():
                    return self._candidate(m)
            raise ApiError(_("Zu dieser CurseForge-Adresse wurde kein Projekt gefunden."))
        raise ApiError(_("Bitte eine CurseForge-Projekt-ID, eine CurseForge-/GitHub-Adresse oder gh:owner/repo angeben."))

    def _auto_assign(self, packages):
        """Ordner mit CF-Adresse im TOC, deren Forever-Datei genau diesen Ordner enthaelt, automatisch zuordnen."""
        changed, budget = False, ASSIGN_MAX_LOOKUPS
        for p in [p for p in packages if p.meta.get("unassigned")]:
            folder = p.folders[0]
            if folder in self._assign_tried:
                continue
            failed = self.cfg["assign_failed"].get(folder)
            if isinstance(failed, (int, float)) and time.time() - failed < ASSIGN_RETRY_S:
                continue
            meta = toc_meta(self.addons_dir / folder)
            if not re.search(r"curseforge\.com/wow/addons/[\w-]+", " ".join(meta.values()), re.I):
                self._assign_tried.add(folder)
                continue
            if budget <= 0:
                continue
            budget -= 1
            self._assign_tried.add(folder)
            notes = len(self.notes)
            strong = [s for s in self.suggest_assignments(p, verify=True, names=False) if s.strong and s.cand.source == "CF"]
            if len(strong) != 1 and len(self.notes) == notes:   # Netzfehler zaehlen nicht als Misserfolg
                with self.cfg.lock:
                    self.cfg["assign_failed"][folder] = int(time.time())
                    with contextlib.suppress(OSError):
                        self.cfg.save()
            if len(strong) == 1:
                c = strong[0].cand
                self.assign_folders(p.folders, c.name, cf_id=int(c.ident))
                self.log(_("Automatisch zugeordnet: {folder} → {name} (CurseForge {ident}, {reason})").format(
                    folder=folder, name=c.name, ident=c.ident, reason=strong[0].reason))
                changed = True
        return changed

    # -- Export / Import
    def export_data(self, pkgs):
        """Addon-Liste als Dict (siehe parse_import); Pakete ohne CF-/GitHub-Quelle stehen unter „untransferable“."""
        items, lost = [], []
        for p in pkgs:
            src = f"cf:{p.cf_mod_id}" if p.cf_mod_id else (f"gh:{p.meta['gh']}" if p.meta.get("gh") else None)
            if src and not p.meta.get("unassigned"):
                item = dict(source=src, name=p.name, version=display_version(p.local_version) or "")
                if p.channel:
                    item["channel"] = p.channel
                items.append(item)
            else:
                lost.append(p.name)
        return dict(format=EXPORT_FORMAT, created=time.strftime("%Y-%m-%dT%H:%M:%S"), manager=__version__,
                    packages=items, untransferable=lost)

    def import_preview(self, entries):
        """Ergaenzt Eintraege um Namen und `installed` (Netz nur fuer unbekannte CF-Namen)."""
        ids = [int(e["source"][3:]) for e in entries if e["source"].startswith("cf:")]
        if self.api_key and any(str(i) not in self.cfg["cf_mods"] for i in ids):
            with contextlib.suppress(ApiError):
                self._fill_mod_info(CurseForge(self.api_key), ids)
        out = []
        for e in entries:
            kind, ident = e["source"].split(":", 1)
            installed = int(ident) in self._installed_ids if kind == "cf" else ident.lower() in self._installed_gh
            name = e.get("name") or (self._mod_name(int(ident)) if kind == "cf" else ident.split("/")[1]) or e["source"]
            out.append(dict(e, name=name, installed=installed))
        return out

    def import_candidate(self, entry):
        kind, ident = entry["source"].split(":", 1)
        if kind == "cf":
            return Candidate("CF", int(ident), entry["name"], page_url=self._mod_url(int(ident)))
        return Candidate("GH", ident, entry["name"], ident.split("/")[0], "", 0, None, False,
                         f"https://github.com/{ident}")


EXPORT_FORMAT = 1
ASSIGN_MAX_LOOKUPS = 10            # Netzabfragen je Lauf bei der automatischen Zuordnung
ASSIGN_RETRY_S = 7 * 86400         # erfolglose Zuordnungen frühestens nach 7 Tagen wiederholen
_SRC_RE = re.compile(r"^(cf:\d+|gh:[\w.-]+/[\w.-]+)(?:@(release|beta|alpha))?$", re.I)


def export_text(data):
    """Kurzformat fuer Chats: `WFA1 cf:18808 cf:4646@beta gh:owner/repo` (Namen gehen dabei verloren)."""
    return "WFA1 " + " ".join(p["source"] + (f"@{p['channel']}" if p.get("channel") else "") for p in data["packages"])


def parse_import(text):
    """JSON-Dokument oder Kurzformat -> [dict(source, name?, channel?, version?)]. Wirft ApiError bei Unbekanntem."""
    t = re.sub(r"```[A-Za-z]*", "", text or "").strip("`\n\t \"'“”„‚‘’")
    out = []
    if "{" in t and not re.match(r"(?i)\s*WFA1\b", t):
        try:
            doc, _end = json.JSONDecoder().raw_decode(t[t.index("{"):])
        except ValueError as e:
            raise ApiError(_("Die Liste ist kein gültiges JSON: {error}").format(error=e))
        if not isinstance(doc, dict) or not isinstance(doc.get("packages"), list):
            raise ApiError(_("Das ist keine Addon-Liste dieses Programms."))
        fmt = doc.get("format", 1)
        if isinstance(fmt, int) and fmt > EXPORT_FORMAT:
            raise ApiError(_("Die Liste hat Format {found}; dieses Programm kennt nur Format {known} – bitte aktualisieren.").format(
                found=fmt, known=EXPORT_FORMAT))
        for p in doc["packages"]:
            m = _SRC_RE.match(str(p.get("source", "")).strip()) if isinstance(p, dict) else None
            if m:
                e = dict(source=m.group(1).lower() if m.group(1)[:2].lower() == "cf" else "gh:" + m.group(1)[3:],
                         name=str(p.get("name") or ""), version=str(p.get("version") or ""))
                if p.get("channel") in ("release", "beta", "alpha"):
                    e["channel"] = p["channel"]
                out.append(e)
    else:
        w = re.search(r"(?i)\bWFA(\d+)\b:?", t)
        if w:
            if int(w.group(1)) > EXPORT_FORMAT:
                raise ApiError(_("Die Liste hat Format {found}; dieses Programm kennt nur Format {known} – bitte aktualisieren.").format(
                    found=w.group(1), known=EXPORT_FORMAT))
            t = t[w.end():]
        for tok in (x.strip("\"'“”„‚‘’") for x in re.split(r"[\s,;]+", t)):
            if not tok:
                continue
            m = _SRC_RE.match(tok)
            if not m:
                raise ApiError(_("Unbekannter Eintrag in der Liste: „{entry}“").format(entry=tok[:40]))
            e = dict(source="cf:" + m.group(1)[3:] if m.group(1)[:2].lower() == "cf" else "gh:" + m.group(1)[3:])
            if m.group(2):
                e["channel"] = m.group(2).lower()
            out.append(e)
    uniq = {}
    for e in out:
        old = uniq.setdefault(e["source"].lower(), e)
        for k, v in e.items():
            if v and not old.get(k):
                old[k] = v
    out = list(uniq.values())
    if not out:
        raise ApiError(_("Keine übertragbaren Addons in der Liste gefunden."))
    return out
