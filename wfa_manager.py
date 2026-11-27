"""Manager: Einrichtung, Katalog, Scan und Pruefung; fuegt die Mixins zusammen."""
from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from wfa_apply import ApplyMixin
from wfa_assign import AssignMixin
from wfa_base import ApiError, CATALOG, CURRENT, DEFAULT_CLIENT, ERROR, FOREVER_TYPE_FALLBACK, HELD, NEWER, NOKEY, NO_FOREVER, Package, SKIPPED, UNASSIGNED, UNCHECKED, UPDATE
from wfa_files import find_forever_installs, normalize_addons_dir, validate_addons_dir
from wfa_http import github_token
from wfa_paths import Config, Paths
from wfa_pins import _pin_record, _remote_newer
from wfa_plan import PlanMixin
from wfa_savedvars import SavedVarsMixin
from wfa_sources import CurseForge, channel_types, gh_latest, parse_github
from wfa_toc import _file_hash, clean_title, client_interface, client_version, compare, fingerprint, forever_toc, parse_toc, toc_dependency_names, toc_files

class Manager(PlanMixin, ApplyMixin, SavedVarsMixin, AssignMixin):
    def __init__(self, home=None, addons_dir=None, log=None, progress=None):
        self.log = log or (lambda s: None)
        # progress(**ereignis) aus dem Worker-Thread, siehe _fetch
        self.progress = progress or (lambda **_kw: None)
        self.dl_cancel = threading.Event()   # setzen bricht laufende Downloads ab
        self.paths = Paths(home)
        self.cfg = Config(self.paths, self.log)
        self.notes = []
        self.client_interface = DEFAULT_CLIENT
        self.client_version = None   # z. B. "1.60.1" aus .build.info
        self.addons_dir = None
        self._key_invalid = False
        self._folders = []
        self._fps = {}
        self._installed_ids = set()
        self._installed_gh = set()
        self._assign_tried = set()
        self._meta = {}
        self._hash_lock = threading.Lock()
        self._hash_cache = None
        self._hash_seen = set()
        self._apply_lock = threading.RLock()
        self._hist_lock = threading.Lock()
        self._ver_cursor = {}   # Index der naechsten CF-Dateiseite je Paket (Seiten koennen nach dem Filtern leer sein)
        if addons_dir:  # Override gilt nur fuer diese Sitzung
            self.addons_dir = normalize_addons_dir(addons_dir)
        else:
            cfgd = self.cfg["addons_dir"]
            if cfgd and normalize_addons_dir(cfgd).is_dir():
                self.addons_dir = normalize_addons_dir(cfgd)
        if self.addons_dir and self.addons_dir.is_dir():
            self._read_client()

    def _read_client(self):
        self.client_version = client_version(self.addons_dir)
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
        self._read_client()

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

    def is_ignored(self, key):
        return key in self.cfg["ignored"]

    def set_ignored(self, key, on):
        with self.cfg.lock:
            lst = [k for k in self.cfg["ignored"] if k != key]
            if on:
                lst.append(key)
            self.cfg["ignored"] = lst
            self.cfg.save()

    def channel(self, key):
        ch = self.cfg["channels"].get(key)
        return ch if ch in ("release", "beta", "alpha") else None

    def allowed_types(self, key):
        return channel_types(self.channel(key) or self.cfg["include_beta"])

    def set_channel(self, key, ch):
        with self.cfg.lock:
            if ch in ("release", "beta", "alpha"):
                self.cfg["channels"][key] = ch
            else:
                self.cfg["channels"].pop(key, None)
            self.cfg.save()

    def pin(self, key):
        pin = self.cfg["pins"].get(key)
        return pin if isinstance(pin, dict) and pin.get("mode") in ("hold", "skip") else None

    def clear_pin(self, key):
        with self.cfg.lock:
            if self.cfg["pins"].pop(key, None) is not None:
                self.cfg.save()

    def hold(self, key, rem):
        """Version festhalten: keine Update-Angebote, bis der Pin aufgehoben wird."""
        self._set_pin(key, "hold", rem)

    def skip_newer(self, key, rem):
        """Updates erst wieder anbieten, wenn etwas neuer als `rem` (die bisher neueste Version) erscheint."""
        self._set_pin(key, "skip", rem)

    def _set_pin(self, key, mode, rem):
        with self.cfg.lock:
            self.cfg["pins"][key] = _pin_record(mode, rem)
            self.cfg.save()

    def _mark_ignored(self, pkgs):
        ign = set(self.cfg["ignored"])
        for p in pkgs:
            p.ignored = p.key in ign

    def updatable(self, pkgs):
        return [p for p in pkgs if p.status == UPDATE and not p.ignored]

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
                       best.get("file_id") if best else None, page, "", meta,
                       pin=self.pin(g["key"]), channel=self.channel(g["key"]))

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
        self._read_client()
        self._folders = self._addon_folders()
        self._fps = {}
        self._hash_seen = set()
        for f in self._folders:
            with contextlib.suppress(OSError):
                self._fps[f] = self._fingerprint(self.addons_dir / f)
        self._save_hash_cache()
        pkgs = self._group(self._folders, self._fps)
        self._installed_ids = {p.cf_mod_id for p in pkgs if p.cf_mod_id}
        self._installed_gh = {p.meta["gh"].lower() for p in pkgs if p.meta.get("gh")}
        self._meta = {p.key: p.meta for p in pkgs}
        self._mark_ignored(pkgs)
        self._mark_missing(pkgs)
        return pkgs

    def _mark_missing(self, pkgs):
        have = {f.lower() for f in self._folders}
        for p in pkgs:
            p.missing = sorted({n for f in p.folders for n in toc_dependency_names(self.addons_dir / f, self.client_interface)
                                if n.lower() not in have and not n.lower().startswith("blizzard_")}, key=str.lower)

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
                if self._auto_assign(packages):
                    packages[:] = self._group(self._folders, self._fps)
                    self._fill_mod_info(cf, sorted({p.cf_mod_id for p in packages if p.cf_mod_id}))
                    self._mark_missing(packages)
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
                self._check_one(p, cf, tid)
            except Exception as e:  # ein Paket darf die Pruefung nicht abbrechen
                p.status, p.note = ERROR, f"{type(e).__name__}: {e}"
            done[0] += 1
            if progress:
                progress(done[0], total, p.name)

        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(work, packages))
        if not self.api_key and any(p.cf_mod_id and not p.meta.get("gh") for p in packages):
            self.notes.append("Ohne CurseForge-Key sind reine CF-Pakete nicht prüfbar.")
        self._mark_ignored(packages)
        self._mark_missing(packages)
        for p in packages:
            if p.status == ERROR and p.note:
                self.notes.append(f"{p.name}: {p.note}")

    def recheck(self, p):
        """Nur dieses Paket neu pruefen (z. B. nach Kanal- oder Pin-Wechsel)."""
        cf = CurseForge(self.api_key) if self.api_key and not self._key_invalid else None
        self._check_one(p, cf, self._tid())
        self._mark_ignored([p])

    def _check_one(self, p, cf, tid):
        p.pin, p.channel = self.pin(p.key), self.channel(p.key)
        if p.meta.get("unassigned"):
            return
        allowed = self.allowed_types(p.key)
        rem, errs = None, []
        if cf and p.cf_mod_id:
            try:
                rem = cf.latest(p.cf_mod_id, tid, allowed)
                if rem:
                    rem.page_url = p.page_url
                else:
                    errs.append("CF: keine Forever-Datei")
            except ApiError as e:
                errs.append(f"CF: {e}")
        if rem is None and p.meta.get("gh"):
            try:
                rem = gh_latest(p.meta["gh"], p.meta, allowed)
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
        p.status = self._pinned(p, rem, self._status(p, rem))

    @staticmethod
    def _pinned(p, rem, st):
        if st != UPDATE or not p.pin:
            return st
        if p.pin["mode"] == "hold":
            return HELD
        return UPDATE if _remote_newer(rem, p.pin.get("ref")) else SKIPPED

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
