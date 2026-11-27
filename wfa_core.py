"""Kernlogik des Addon-Managers fuer WoW: Forever (nur Standardbibliothek).

Keine Ein-/Ausgabe fuer Interaktion: Meldungen laufen ueber den log-Callback des Managers.
"""
from __future__ import annotations

# Fassade: der Code liegt in den Modulen wfa_*.py; hier bleiben alle bisherigen Namen erreichbar.
from concurrent.futures import ThreadPoolExecutor  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from datetime import datetime  # noqa: F401
from pathlib import Path  # noqa: F401

from wfa_base import (  # noqa: F401
    APP_ID, APP_NAME, ApiError, BROWSER_UA, BackupSet, CATALOG, CF_API, CF_CDNS, CF_KEY_URL, CF_SITE, CURRENT,
    Candidate, DEFAULT_CLIENT, DL_ATTEMPTS, DL_BACKOFF, DL_TIMEOUT, DepNeed, ERROR, FOREVER_RE,
    FOREVER_TYPE_FALLBACK, HELD, HISTORY_MAX, IMAGE_HOSTS, InstallPlan, KEEP_BACKUPS, MAX_DOWNLOAD, MAX_IMAGE,
    MAX_UNPACKED, NEWER, NOKEY, NO_FOREVER, Package, Remote, Result, SKIPPED, SORT_FIELDS, Suggestion, SvSet,
    TYPE_NAMES, UA, UNASSIGNED, UNCHECKED, UNKNOWN, UPDATE, UninstallPlan, WOW_DETECT_OVERRIDE, _HOST_SPAWN,
    _KIND, __version__, _read_text, host_spawn_available, in_flatpak, install_kind, managed_install,
    package_channel,
)
from wfa_paths import (  # noqa: F401
    BROWSERS, Config, Paths, SCHEMA, _NONE, _chromium_dir, _firefox_dir, _firefox_profile, _match_default,
    browser_download_dirs, default_browser_desktop, mask, tilde, xdg_user_dir,
)
from wfa_http import (  # noqa: F401
    _Redirect, _gh_token, _open, _opener, check_zip, download_file, fmt_size, github_token, http_json,
)
from wfa_toc import (  # noqa: F401
    VER_RE, _SKIP_TOKEN, _TOC_INC, _XML_INC, _collect, _file_hash, _resolve_ci, _slug, _version_token,
    clean_title, client_interface, client_version, compare, display_version, fingerprint, forever_toc,
    interfaces, murmur2, norm, parse_toc, short_version, toc_dependencies, toc_dependency_names, toc_files,
    toc_meta, version_interface,
)
from wfa_sources import (  # noqa: F401
    CurseForge, _gh_remote, _html_to_text, channel_types, gh_latest, gh_pick_asset, gh_releases, is_zip_url,
    parse_github,
)
from wfa_files import (  # noqa: F401
    _desktop_exec, _desktop_quote, _drive_c_dirs, _expand, _forever_in_drive_c, _is_forever_root, _remove,
    _steam_libraries, asset_path, autostart_enabled, autostart_path, find_addon_dirs, find_forever_installs,
    flatpak_override_cmd, install_desktop_entry, is_addon_dir, normalize_addons_dir, portal_path,
    safe_extract, sandbox_blocked_libraries, sandbox_hint, set_autostart, validate_addons_dir,
)
from wfa_pins import (  # noqa: F401
    _pin_record, _remote_newer, pin_text,
)
from wfa_assign import (  # noqa: F401
    ASSIGN_MAX_LOOKUPS, ASSIGN_RETRY_S, EXPORT_FORMAT, _SRC_RE, export_text, parse_import,
)
from wfa_manager import (  # noqa: F401
    Manager,
)
