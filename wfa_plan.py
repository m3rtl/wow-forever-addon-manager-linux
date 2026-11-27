"""Manager-Teil: neue Addons, Planen, Versionswahl, Download."""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from wfa_i18n import _
from wfa_base import ApiError, BROWSER_UA, CF_CDNS, CF_SITE, Candidate, DL_ATTEMPTS, DL_BACKOFF, IMAGE_HOSTS, InstallPlan, MAX_IMAGE
from wfa_files import _expand, find_addon_dirs, safe_extract
from wfa_http import _Redirect, _open, check_zip, download_file, fmt_size
from wfa_pins import _pin_record
from wfa_sources import CurseForge, _html_to_text, channel_types, gh_latest, gh_releases, is_zip_url, parse_github
from wfa_toc import forever_toc

class PlanMixin:
    # -- Neue Addons
    def _candidate(self, m):
        tid = self._tid()
        idx = m.get("latestFilesIndexes")
        hf = None if idx is None else any(x.get("gameVersionTypeId") == tid for x in idx)
        return Candidate("CF", m["id"], m.get("name") or str(m["id"]), (m.get("authors") or [{}])[0].get("name", ""),
                         m.get("summary") or "", m.get("downloadCount") or 0, hf, m["id"] in self._installed_ids,
                         (m.get("links") or {}).get("websiteUrl"),
                         (m.get("logo") or {}).get("thumbnailUrl") or None,
                         [dict(thumb=x.get("thumbnailUrl") or "", url=x.get("url") or "", title=x.get("title") or "")
                          for x in (m.get("screenshots") or [])[:4]],
                         m.get("dateModified") or "",
                         [c.get("name") for c in m.get("categories") or [] if c.get("name")])

    def browse(self, query="", sort="downloads", page=0, page_size=20):
        """Eine Seite Forever-Addons; -> (Kandidaten, has_more)."""
        page_size = max(1, min(int(page_size), 49))
        try:
            res = self._cf().browse((query or "").strip(), self._tid(), sort, max(0, int(page)), page_size)
        except ApiError as e:
            if e.kind == "forbidden":
                raise ApiError(_("Suche ist für diesen API-Key nicht freigeschaltet"), "forbidden")
            raise
        return [self._candidate(m) for m in res[:page_size]], len(res) > page_size

    def fetch_image(self, url):
        """Laedt ein Bild in den Cache (blockierend). -> Pfad oder None."""
        def allowed(u):
            pu = urllib.parse.urlparse(u)
            h = (pu.hostname or "").lower()
            return pu.scheme == "https" and any(h == d or h.endswith("." + d) for d in IMAGE_HOSTS)
        class _Guard(_Redirect):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if not allowed(newurl):
                    raise ApiError(_("Bild-Redirect auf nicht erlaubten Host"), "http")
                return super().redirect_request(req, fp, code, msg, headers, newurl)
        try:
            if not url or not allowed(url):
                return None
            ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                ext = ".img"
            d = self.paths.cache / "img"
            dest = d / (hashlib.sha1(url.encode()).hexdigest() + ext)
            if dest.is_file():
                return dest
            d.mkdir(parents=True, exist_ok=True)
            with _open(url, timeout=20, opener=urllib.request.build_opener(_Guard)) as r:
                if not allowed(r.geturl()):
                    return None
                data = r.read(MAX_IMAGE + 1)
            if not data or len(data) > MAX_IMAGE:
                return None
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            return dest
        except (ApiError, OSError, ValueError):
            return None

    def changelog(self, pkg):
        """Klartext-Changelog der verfuegbaren Version (pkg.remote); "" ohne Daten."""
        rem = pkg.remote
        if not rem:
            return ""
        ck = (rem.source, str(rem.ident))
        cache = self.__dict__.setdefault("_changelogs", {})
        if ck in cache:
            return cache[ck]
        text = ""
        try:
            if rem.source == "CF" and rem.cf_id:
                text = _html_to_text(self._cf().changelog(rem.cf_id, rem.ident))
            elif rem.source == "GH":
                text = (rem.notes or "").strip()
        except ApiError:
            return ""  # nicht cachen, naechster Versuch moeglich
        cache[ck] = text
        return text

    def featured(self):
        return [self._candidate(m) for m in {m["id"]: m for m in self._cf().featured(self._tid())}.values()]

    def search(self, q):
        try:
            res = self._cf().search(q, self._tid())
        except ApiError as e:
            if e.kind == "forbidden":
                raise ApiError(_("Suche ist für diesen API-Key nicht freigeschaltet"), "forbidden")
            raise
        return [self._candidate(m) for m in res]

    def resolve_input(self, text):
        t = (text or "").strip()
        if not t:
            return []
        if is_zip_url(t):
            return self._plan_zip_url(t)
        repo = parse_github(t)
        if repo:
            return [Candidate("GH", repo, repo.split("/")[1], repo.split("/")[0], "", 0, None,
                              False, f"https://github.com/{repo}")]
        if t.isdigit():
            return [self._candidate(self._cf().get(f"/v1/mods/{int(t)}")["data"])]
        if re.match(r"^https?://", t):
            raise ApiError(_("Nur direkte .zip-Links, GitHub-Repos oder CurseForge-Projekt-IDs werden unterstützt."))
        p = _expand(t)
        if t.lower().endswith(".zip") or p.is_file():
            if not p.is_file():
                raise ApiError(_("Datei nicht gefunden."))
            return self.plan_zip(p)
        return self.search(t)

    # -- Planen
    def _new_staging(self):
        self.paths.cache.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="stage-", dir=self.paths.cache))

    def discard(self, plan):
        if plan and plan.staging:
            shutil.rmtree(plan.staging, ignore_errors=True)
            plan.staging = None

    def _plan_zip_url(self, url):
        name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).stem
        st = self._new_staging()
        try:
            self.log(_("Lade {name} ...").format(name=name))
            self._fetch([("Zip-URL", url, None, False)], st / "download.zip", name)
        except BaseException:
            shutil.rmtree(st, ignore_errors=True)
            raise
        return self._build_plan(st / "download.zip", st, f"zip-{name}", name, "ZIP", {}, {})

    def plan_zip(self, path, hint_key=None):
        path = Path(path)
        if not path.is_file():
            raise ApiError(_("Datei nicht gefunden."))
        key, name, meta = hint_key or f"zip-{path.stem}", path.stem, dict(self._meta.get(hint_key) or {})
        for spec in self._specs():
            if spec["key"] == hint_key:
                name = spec.get("name") or path.stem
                meta = {k: spec.get(k) for k in ("vfolder", "gh") if spec.get(k)}
        return self._build_plan(path, self._new_staging(), key, name, "ZIP", meta, {})

    def plan_update(self, pkg):
        if not pkg.remote:
            raise ApiError(_("Keine Update-Quelle bekannt."), "nofile")
        return self._plan_remote(pkg.remote, pkg.key, pkg.name, pkg.meta, pkg.cf_mod_id)

    def plan_candidate(self, cand, channel=None):
        """channel: Kanal fuer diese Installation (wird nach dem Installieren als Kanal des Addons gemerkt)."""
        if cand.source == "CF":
            meta, key = {}, f"cf-{cand.ident}"
            for spec in self._specs():
                if self._spec_cf_id(spec) == cand.ident:
                    key, meta = spec["key"], {k: spec.get(k) for k in ("vfolder", "gh") if spec.get(k)}
            rem = self._cf().latest(int(cand.ident), self._tid(), channel or self.allowed_types(key))
            if not rem:
                raise ApiError(_("Keine Forever-Datei bei CurseForge."), "nofile")
            return self._plan_remote(rem, key, cand.name, meta, int(cand.ident), channel=channel)
        repo = str(cand.ident)
        meta = {}
        key = "gh-" + repo.replace("/", "-")
        for spec in self._specs():
            if spec.get("gh") == repo:
                key, meta = spec["key"], {k: spec.get(k) for k in ("vfolder", "gh", "tag_prefix", "asset_regex") if spec.get(k)}
        rem = gh_latest(repo, dict(meta), channel_types(channel) if channel else self.allowed_types(key))
        if not rem:
            raise ApiError(_("Kein GitHub-Release mit Forever-Zip gefunden."), "nofile")
        meta.setdefault("gh", repo)
        return self._plan_remote(rem, key, cand.name, meta, None, save_package=key.startswith("gh-"), channel=channel)

    # -- Versionswahl
    def versions(self, pkg, page=0):
        """Verfuegbare Forever-Versionen (neueste zuerst) -> (Remotes, gibt_es_mehr)."""
        rem = pkg.remote
        if (rem and rem.source == "CF") or (not rem and pkg.cf_mod_id and self.api_key):
            if not pkg.cf_mod_id:
                raise ApiError(_("Keine Versionsquelle bekannt."), "nofile")
            cf = self._cf()
            cur = self._ver_cursor.get(pkg.key) if page else None
            files, more = cf.files(pkg.cf_mod_id, self._tid(), cur if cur is not None else page * 50)
            self._ver_cursor[pkg.key] = cf.next_index
            out = sorted((CurseForge.remote_of(f, pkg.cf_mod_id) for f in files), key=lambda r: r.file_date, reverse=True)
            for r in out:
                r.page_url = pkg.page_url
            return out, more
        if pkg.meta.get("gh"):
            return gh_releases(pkg.meta["gh"], pkg.meta, page + 1)
        raise ApiError(_("Keine Versionsquelle bekannt."), "nofile")

    def installed_ident(self, pkg):
        rec = self.cfg["installed"].get(pkg.key) or {}
        src = pkg.remote.source if pkg.remote else pkg.source
        return rec.get("tag") if src == "GH" else (pkg.installed_file_id or rec.get("file_id"))

    def newest_allowed(self, pkg, remotes):
        """Neueste der Versionen, die der Kanal des Pakets erlaubt (Grundlage fuer „Auslassen“)."""
        allowed = self.allowed_types(pkg.key)
        return next((r for r in remotes if r.rtype in allowed), remotes[0] if remotes else None)

    def plan_version(self, pkg, rem, pin_mode=None, newest=None):
        """Eine bestimmte Version installieren; pin_mode "hold" haelt sie fest, "skip" laesst alles bis `newest` aus."""
        pin = _pin_record(pin_mode, rem if pin_mode == "hold" else newest) if pin_mode else None
        return self._plan_remote(rem, pkg.key, pkg.name, pkg.meta, pkg.cf_mod_id, pin=pin)

    def _download_ways(self, rem):
        """Reihenfolge der Download-Wege -> Liste (Label, URL, Header, ist_direkt)."""
        if rem.source == "GH":
            return [("GitHub", rem.url, None, False)] if rem.url else []
        ways = [("CurseForge-API", u, None, False) for u in self._cf().download_urls(rem)]
        if self.cfg["direct_download"] and rem.cf_id:
            hdr = {"User-Agent": BROWSER_UA}
            ways.append(("CurseForge-Website", f"{CF_SITE}/api/v1/mods/{rem.cf_id}/files/{rem.ident}/download", hdr, True))
            if rem.filename and isinstance(rem.ident, int):
                path = f"/files/{rem.ident // 1000}/{rem.ident % 1000}/{urllib.parse.quote(rem.filename)}"
                ways += [("CDN", cdn + path, hdr, True) for cdn in CF_CDNS]
        seen, out = set(), []
        for w in ways:
            if w[1] not in seen:
                seen.add(w[1])
                out.append(w)
        return out

    def _plan_remote(self, rem, key, name, meta, mod_id, save_package=False, pin=None, channel=None):
        ways = self._download_ways(rem)
        if not ways:
            raise ApiError(_("Kein Download-Link verfügbar (Browser-Download nötig)."), "download")
        st = self._new_staging()
        try:
            self.log(_("Lade {name} ...").format(name=rem.filename or rem.display))
            self._fetch(ways, st / "download.zip", name)
            info = dict(source=rem.source, ident_key="file_id" if rem.source == "CF" else "tag", ident=rem.ident,
                        version=rem.version, cf_mod_id=mod_id, file_date=rem.file_date, display=rem.display,
                        save_package=save_package, pin=pin, cf_deps=list(rem.deps), channel=channel)
            return self._build_plan(st / "download.zip", st, key, name, rem.source, meta, info)
        except BaseException:
            shutil.rmtree(st, ignore_errors=True)
            raise

    def _fetch(self, ways, dest, name):
        """ways: [(Label, URL, Header, ist_direkt)]. Jeder Weg bekommt bei voruebergehenden Fehlern (Netz, haengende
        Verbindung, HTTP 5xx/429, kaputte Zip) bis zu DL_ATTEMPTS Versuche, sonst geht es mit dem naechsten Weg weiter.
        Meldet den Verlauf an self.progress(name, way, state=download|verify|retry|fallback, ...).
        -> Label des erfolgreichen Wegs. Fehler: kind=download (alle Wege gescheitert, mit Liste) oder kind=cancel."""
        cancel = self.dl_cancel
        tried = []
        for wi, (label, url, hdr, _direct) in enumerate(ways):
            nxt = ways[wi + 1][0] if wi + 1 < len(ways) else None
            for attempt in range(1, DL_ATTEMPTS + 1):
                def prog(done, total, label=label, attempt=attempt):
                    self.progress(name=name, way=label, state="download", done=done, total=total, attempt=attempt)
                try:
                    n = download_file(url, dest, cancel=cancel, headers=hdr, progress=prog)
                    self.progress(name=name, way=label, state="verify", done=n, total=n, attempt=attempt)
                    check_zip(dest)
                    self.log(_("{name}: {size} geladen über {way}").format(name=name, size=fmt_size(n), way=label))
                    return label
                except ApiError as e:
                    with contextlib.suppress(OSError):
                        dest.unlink()
                    if e.kind == "cancel" or cancel.is_set():
                        self.log(_("{name}: Download abgebrochen").format(name=name))
                        raise ApiError(_("Download abgebrochen"), "cancel") from e
                    if e.transient and attempt < DL_ATTEMPTS:
                        wait = DL_BACKOFF[min(attempt, len(DL_BACKOFF)) - 1]
                        self.log(_("{name} – {way}: {error} – neuer Versuch {attempt}/{total} in {seconds} s").format(
                            name=name, way=label, error=e, attempt=attempt + 1, total=DL_ATTEMPTS, seconds=wait))
                        self.progress(name=name, way=label, state="retry", error=str(e), attempt=attempt + 1,
                                      wait=wait)
                        if cancel.wait(wait):
                            self.log(_("{name}: Download abgebrochen").format(name=name))
                            raise ApiError(_("Download abgebrochen"), "cancel") from e
                        continue
                    tried.append(f"{label}: {e}" + (_(" ({attempts} Versuche)").format(attempts=attempt) if attempt > 1 else ""))
                    self.log(f"{name} – {label}: {e}" + (_(" – weiter mit {way}").format(way=nxt) if nxt else ""))
                    if nxt:
                        self.progress(name=name, way=label, state="fallback", error=str(e), next=nxt)
                    break
        raise ApiError(_("Download fehlgeschlagen, alle Wege versucht:") + "\n  " + "\n  ".join(tried), "download")

    def _build_plan(self, zpath, st, key, name, source, meta, info):
        x = st / "x"
        try:
            try:
                safe_extract(zpath, x)
            except (zipfile.BadZipFile, ValueError, OSError) as e:
                raise ApiError(_("Zip nicht installierbar: {error}").format(error=e))
            found = find_addon_dirs(x)
            if not found:
                raise ApiError(_("Im Zip wurde kein Addon-Ordner (Ordner mit passender .toc) gefunden."))
            warnings, dirs = [], {}
            for d, depth in sorted(found, key=lambda t: t[1]):
                if d.name in dirs:
                    warnings.append(_("Ordner „{name}“ kommt mehrfach im Zip vor; der flachste wird verwendet.").format(name=d.name))
                else:
                    dirs[d.name] = d
            comp = {n: forever_toc(d, self.client_interface)[0] for n, d in dirs.items()}
            chosen = [n for n in dirs if comp[n] != "nein" or (self.addons_dir / n).exists()]
            vf = meta.get("vfolder")
            strong = (comp[vf] == "nein") if vf in dirs else not any(c != "nein" for c in comp.values())
            if strong:
                chosen = list(dirs)
                warnings.append(_("Dieses Paket enthält keine für WoW: Forever (Interface 16xxx) markierte Hauptdatei – "
                                  "es wird vermutlich nicht geladen."))
            skipped = [n for n in dirs if n not in chosen]
            if skipped:
                warnings.append(_("Übersprungen (werden von WoW: Forever nicht geladen): ") + ", ".join(skipped))
            vfold = vf if vf in chosen else min(chosen, key=len)
            old = forever_toc(self.addons_dir / vfold, self.client_interface)[1] if (self.addons_dir / vfold).exists() else None
            new = forever_toc(dirs[vfold], self.client_interface)[1] or info.get("version")
            info = dict(info, vfolder=vfold, dirs={n: str(dirs[n]) for n in chosen}, meta=meta)
            return InstallPlan(key, name, source, old, new, chosen, skipped, warnings, strong, st, info)
        except BaseException:
            shutil.rmtree(st, ignore_errors=True)
            raise
