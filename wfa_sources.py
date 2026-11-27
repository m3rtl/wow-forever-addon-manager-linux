"""Quellen: CurseForge-API und GitHub."""
from __future__ import annotations

import contextlib
import html
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from wfa_base import ApiError, CF_API, FOREVER_RE, Remote, SORT_FIELDS
from wfa_http import http_json
from wfa_toc import _version_token, short_version

# ---------------------------------------------------------------- CurseForge-API

def mod_info(m, tid=None):
    """Felder eines CurseForge-Projekts fuer den cf_mods-Cache (ohne zusaetzlichen Request, aus der /v1/mods-Antwort).
    Neu: status (ModStatus), available (isAvailable) und last_file (Datum der juengsten Forever-Datei aus latestFiles)."""
    last = ""
    for f in m.get("latestFiles") or []:
        if not isinstance(f, dict) or f.get("isAvailable") is False:
            continue
        by_type = tid and any(isinstance(s, dict) and s.get("gameVersionTypeId") == tid for s in f.get("sortableGameVersions") or [])
        by_str = any(FOREVER_RE.match(str(g)) for g in f.get("gameVersions") or [])
        if (by_type or by_str) and str(f.get("fileDate") or "") > last:
            last = str(f["fileDate"])
    out = dict(name=m.get("name") or "", slug=m.get("slug") or "",
               url=(m.get("links") or {}).get("websiteUrl") or "", last_file=last)
    if isinstance(m.get("status"), int):
        out["status"] = m["status"]
    if isinstance(m.get("isAvailable"), bool):
        out["available"] = m["isAvailable"]
    return out


class CurseForge:
    def __init__(self, key):
        self.key = key

    def _h(self):
        return {"x-api-key": self.key, "Accept": "application/json"}

    def get(self, path, **params):
        url = CF_API + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        return http_json(url, self._h())

    def post(self, path, body):
        return http_json(CF_API + path, self._h(), body)

    def forever_type(self):
        """Typ-ID oder None; wirft ApiError (key/forbidden bei ungueltigem Key)."""
        for t in self.get("/v1/games/1/version-types").get("data", []):
            if "forever" in (str(t.get("name", "")) + " " + str(t.get("slug", ""))).lower():
                return t["id"]
        return None

    def mods(self, ids):
        return self.post("/v1/mods", {"modIds": list(ids)}).get("data", [])

    def fingerprints(self, fps):
        return self.post("/v1/fingerprints/1", {"fingerprints": list(fps)}).get("data", {})

    def files(self, mid, tid, index=0):
        """Eine Seite Forever-Dateien (so, wie die API sie liefert) -> (Dateien, gibt_es_mehr)."""
        hits = []
        for _ in range(5):   # leere Seiten nach dem Filtern ueberspringen, aber begrenzt
            params = {"pageSize": 50, "index": index}
            if tid:
                params["gameVersionTypeId"] = tid
            data = self.get(f"/v1/mods/{mid}/files", **params).get("data", [])
            more = len(data) >= 50
            for f in data:
                if f.get("isAvailable") is False:
                    continue
                by_type = tid and any(isinstance(s, dict) and s.get("gameVersionTypeId") == tid for s in f.get("sortableGameVersions") or [])
                by_str = any(FOREVER_RE.match(str(g)) for g in f.get("gameVersions") or [])
                if by_type or by_str:
                    hits.append(f)
            index += len(data)
            if hits or not more:
                break
        self.next_index = index
        return hits, more

    @staticmethod
    def remote_of(f, mid):
        name = f.get("displayName") or f.get("fileName") or ""
        ver = _version_token(name) or _version_token(f.get("fileName", "")) or re.sub(r"\.zip$", "", name)
        return Remote(ver, name, "CF", f.get("downloadUrl"), f["id"], f.get("fileName") or "", None,
                      [m.get("name") for m in f.get("modules") or []], mid, f.get("fileDate", ""),
                      rtype=f.get("releaseType") or 1,
                      deps=[d["modId"] for d in f.get("dependencies") or [] if d.get("relationType") == 3 and d.get("modId")])

    def latest(self, mid, tid, allowed):
        """allowed: Menge erlaubter releaseTypes (bool bleibt als „Beta ja/nein“ zulaessig)."""
        allowed = channel_types(allowed)
        hits = [f for f in self.files(mid, tid)[0] if f.get("releaseType") in allowed]
        if not hits:
            return None
        return self.remote_of(max(hits, key=lambda x: x.get("fileDate", "")), mid)

    def download_urls(self, rem):
        urls = [rem.url] if rem.url else []
        if not urls:
            with contextlib.suppress(ApiError):
                u = self.get(f"/v1/mods/{rem.cf_id}/files/{rem.ident}/download-url").get("data")
                if u:
                    urls.append(u)
        return urls

    def search(self, q, tid):
        params = dict(gameId=1, classId=1, searchFilter=q, sortField=2, sortOrder="desc", pageSize=15)
        if tid:
            params["gameVersionTypeId"] = tid
        return self.get("/v1/mods/search", **params).get("data", [])

    def browse(self, q, tid, sort, page, page_size):
        """Eine Seite Suchtreffer; liefert bis zu page_size+1 Eintraege (der Ueberhang zeigt „mehr“ an)."""
        field_id = SORT_FIELDS.get(sort, 6)
        params = dict(gameId=1, classId=1, sortField=field_id, sortOrder="asc" if sort == "name" else "desc",
                      pageSize=page_size + 1, index=page * page_size)
        if q:
            params["searchFilter"] = q
        if tid:
            params["gameVersionTypeId"] = tid
        return self.get("/v1/mods/search", **params).get("data", [])

    def changelog(self, mid, fid):
        return self.get(f"/v1/mods/{mid}/files/{fid}/changelog").get("data") or ""

    def featured(self, tid):
        d = self.post("/v1/mods/featured", {"gameId": 1, "excludedModIds": [], "gameVersionTypeId": tid}).get("data", {})
        return [m for k in ("featured", "popular", "recentlyUpdated") for m in d.get(k) or []]


def _html_to_text(s):
    s = re.sub(r"(?i)<li[^>]*>", "\n• ", s)
    s = re.sub(r"(?i)<br\s*/?>|</?(?:p|h[1-6]|ul|ol|div)[^>]*>|</li>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n\s*\n+", "\n\n", "\n".join(l.rstrip() for l in s.splitlines())).strip()


def channel_types(ch):
    """Kanal ("release"|"beta"|"alpha"), Menge oder bool (Beta ja/nein) -> erlaubte releaseTypes."""
    if isinstance(ch, (set, frozenset)):
        return set(ch)
    if isinstance(ch, str):
        return {1, 2, 3} if ch == "alpha" else ({1, 2} if ch == "beta" else {1})
    return {1, 2} if ch else {1}


# ---------------------------------------------------------------- GitHub

def gh_pick_asset(rel, meta):
    assets = rel.get("assets") or []
    zips = [a for a in assets if a["name"].lower().endswith(".zip")]
    byname = {a["name"]: a for a in zips}
    rj = next((a for a in assets if a["name"] == "release.json"), None)
    if rj:
        try:
            for r in http_json(rj["browser_download_url"]).get("releases", []):
                if any(str(m.get("flavor")).lower() == "forever" for m in r.get("metadata") or []):
                    if r.get("filename") in byname:
                        return byname[r["filename"]]
        except (ApiError, AttributeError, TypeError):
            pass
    rx = meta.get("asset_regex")
    if rx:
        for a in zips:
            if re.search(rx, a["name"]):
                return a
    for a in zips:
        if "forever" in a["name"].lower():
            return a
    if rj:
        return None
    plain = [a for a in zips if "nolib" not in a["name"].lower()]
    return plain[0] if len(plain) == 1 else None


def _gh_remote(rel, meta):
    tag = rel.get("tag_name") or ""
    prefix = meta.get("tag_prefix") or ""
    if rel.get("draft") or not tag.startswith(prefix):
        return None
    a = gh_pick_asset(rel, meta)
    if not a:
        return None
    return Remote(short_version(tag[len(prefix):]), tag, "GH", a["browser_download_url"], tag, a["name"],
                  rel.get("html_url"), notes=rel.get("body") or "", file_date=rel.get("published_at") or "",
                  rtype=2 if rel.get("prerelease") else 1)


def gh_latest(repo, meta, allowed):
    rels = http_json(f"https://api.github.com/repos/{repo}/releases?per_page=15")
    allowed = channel_types(allowed)
    for rel in rels if isinstance(rels, list) else []:
        if rel.get("prerelease") and 2 not in allowed:
            continue
        rem = _gh_remote(rel, meta)
        if rem:
            return rem
    return None


def gh_releases(repo, meta, page=1, per_page=30):
    """Eine Seite Releases (inkl. Prereleases, neueste zuerst) mit Forever-Zip -> (Remotes, gibt_es_mehr)."""
    rels = http_json(f"https://api.github.com/repos/{repo}/releases?per_page={per_page}&page={page}")
    rels = [r for r in rels if isinstance(r, dict)] if isinstance(rels, list) else []
    with ThreadPoolExecutor(max_workers=6) as ex:
        out = [r for r in ex.map(lambda r: _gh_remote(r, meta), rels) if r]
    return out, len(rels) >= per_page


def parse_github(s):
    m = re.match(r"^(?:gh:|https?://github\.com/)([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?].*)?$", s.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def is_zip_url(s):
    u = urllib.parse.urlparse(s.strip())
    return u.scheme in ("http", "https") and u.path.lower().endswith(".zip")
