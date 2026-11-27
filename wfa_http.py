"""HTTP und Download."""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from wfa_i18n import _
from wfa_base import ApiError, DL_TIMEOUT, MAX_DOWNLOAD, UA

# ---------------------------------------------------------------- HTTP

class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            for h in ("Authorization", "X-api-key"):
                new.headers.pop(h, None)
                new.unredirected_hdrs.pop(h, None)
        return new


_opener = urllib.request.build_opener(_Redirect)
_gh_token = {"done": False, "value": None}


def github_token():
    if not _gh_token["done"]:
        _gh_token["done"] = True
        tok = os.environ.get("GITHUB_TOKEN")
        if not tok and shutil.which("gh"):
            try:
                tok = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10).stdout.strip()
            except Exception:
                tok = None
        _gh_token["value"] = tok or None
    return _gh_token["value"]


def _open(url, headers=None, timeout=25, data=None, opener=None):
    host = urllib.parse.urlparse(url).netloc
    h = {"User-Agent": UA}
    if host == "api.github.com":
        h["Accept"] = "application/vnd.github+json"
        if github_token():
            h["Authorization"] = f"Bearer {github_token()}"
    h.update(headers or {})
    try:
        return (opener or _opener).open(urllib.request.Request(url, headers=h, data=data), timeout=timeout)
    except urllib.error.HTTPError as e:
        if host == "api.curseforge.com":
            if e.code == 401:
                raise ApiError(_("CurseForge: nicht autorisiert (HTTP 401)"), "key")
            if e.code == 403:
                raise ApiError(_("CurseForge: Zugriff verweigert (HTTP 403)"), "forbidden")
        if e.code == 429 or (e.code == 403 and host == "api.github.com"):
            raise ApiError(_("Rate-Limit erreicht ({host})").format(host=host), "rate")
        raise ApiError(_("HTTP {code} für {host}").format(code=e.code, host=host), "http", e.code)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ApiError(_("Netzwerkfehler ({reason})").format(reason=getattr(e, "reason", e)), "net")


def http_json(url, headers=None, body=None):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    with _open(url, h, data=data) as r:
        try:
            return json.loads(r.read().decode("utf-8"))
        except ValueError:
            raise ApiError(_("Ungültige Antwort (kein JSON)"), "other")


def fmt_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return ""


def download_file(url, dest, limit=MAX_DOWNLOAD, cancel=None, headers=None, progress=None, timeout=DL_TIMEOUT):
    """Laedt url nach dest -> Bytes. progress(geladen, gesamt|None) nach jedem Block.
    Fehler als ApiError: stall (timeout s ohne Daten), net (Abbruch, unvollstaendig), cancel, http, ..."""
    if urllib.parse.urlparse(url).scheme != "https":
        raise ApiError(_("Download nur über https erlaubt"), "download")
    with _open(url, headers, timeout=timeout) as r:
        size = r.headers.get("Content-Length")
        size = int(size) if size and size.isdigit() else None
        if size and size > limit:
            raise ApiError(_("Download zu groß (>300 MB)"), "other")
        total = 0
        if progress:
            progress(0, size)
        with open(dest, "wb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise ApiError(_("Abgebrochen"), "cancel")
                try:
                    chunk = r.read(1 << 16)
                except (TimeoutError, socket.timeout) as e:
                    raise ApiError(_("keine Daten seit {seconds} s – Verbindung hängt").format(seconds=timeout), "stall") from e
                except (OSError, http.client.HTTPException) as e:
                    raise ApiError(_("Verbindung abgebrochen ({error})").format(error=e.__class__.__name__), "net") from e
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ApiError(_("Download zu groß (>300 MB)"), "other")
                f.write(chunk)
                if progress:
                    progress(total, size)
    if size is not None and total < size:
        raise ApiError(_("Download unvollständig ({got} von {total})").format(got=fmt_size(total), total=fmt_size(size)), "net")
    return total


def check_zip(path):
    """Keine Zip -> kind=download (falsche Antwort, naechster Weg); CRC-Fehler -> kind=corrupt (neuer Versuch)."""
    if not zipfile.is_zipfile(path):
        raise ApiError(_("Antwort ist keine Zip-Datei"), "download")
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
    except Exception as e:  # noqa: BLE001 - jede Lese-/Entpack-Ausnahme heisst: Datei kaputt
        raise ApiError(_("Zip-Datei beschädigt ({error})").format(error=e), "corrupt") from e
    if bad:
        raise ApiError(_("Zip-Datei beschädigt ({error})").format(error=bad), "corrupt")
