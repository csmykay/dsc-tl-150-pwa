"""Panel settings in config/settings.txt (JSON). Secrets stay in config/.env only."""
from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/app/config")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.txt")
ZONE_NAMES_JSON = os.path.join(CONFIG_DIR, "zone_names.json")

log = logging.getLogger(__name__)

_DEFAULTS: dict[str, Any] = {
    "zone_list": "16",
    "app_title": "Home Security",
    "app_short_name": "Home",
    "poll_secs": 10,
    "arming_countdown_secs": 45,
    "zone_columns": 2,
    "default_arm_mode": "stay",
}

_settings_cache: dict[str, Any] | None = None
_settings_mtime: float | None = None

# Hand-edited JSON often has a trailing comma after the last property (invalid for json.loads).
_TRAILING_COMMA_BEFORE_CLOSE = re.compile(r",(\s*[}\]])")


def _loads_json_with_trailing_comma_fallback(text: str) -> tuple[Any, bool]:
    """Parse JSON; allow trailing commas before closing } or ]. Returns (value, used_lenient)."""
    try:
        return json.loads(text), False
    except json.JSONDecodeError:
        t = text.strip()
        for _ in range(64):
            t2 = _TRAILING_COMMA_BEFORE_CLOSE.sub(r"\1", t)
            if t2 == t:
                break
            t = t2
        return json.loads(t), True


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(_DEFAULTS)
    for k, v in data.items():
        # Zone labels live only in zone_names.json — ignore legacy key in settings.txt
        if k == "zone_names":
            continue
        elif k == "zone_columns":
            try:
                c = int(v)
                out["zone_columns"] = min(3, max(1, c))
            except (TypeError, ValueError):
                pass
        elif k == "arming_countdown_secs":
            try:
                t = int(v)
                out["arming_countdown_secs"] = min(300, max(5, t))
            except (TypeError, ValueError):
                pass
        elif k == "poll_secs":
            try:
                p = int(v)
                out["poll_secs"] = min(120, max(3, p))
            except (TypeError, ValueError):
                pass
        elif k == "default_arm_mode":
            vm = str(v).strip().lower() if v is not None else ""
            if vm in ("stay", "away"):
                out["default_arm_mode"] = vm
        elif k in _DEFAULTS:
            out[k] = v
    return out


def invalidate_cache() -> None:
    global _settings_cache, _settings_mtime
    _settings_cache = None
    _settings_mtime = None


def load_settings(force_reload: bool = False) -> dict[str, Any]:
    global _settings_cache, _settings_mtime
    path = Path(SETTINGS_FILE)
    if not path.is_file():
        return deepcopy(_DEFAULTS)
    m = path.stat().st_mtime
    if not force_reload and _settings_cache is not None and _settings_mtime == m:
        return _settings_cache
    try:
        # utf-8-sig strips BOM; lenient pass allows trailing commas (common hand-edit mistake)
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
        raw, lenient = _loads_json_with_trailing_comma_fallback(text)
        if lenient:
            log.info("Loaded %s after allowing trailing commas (invalid strict JSON)", SETTINGS_FILE)
        if not isinstance(raw, dict):
            raw = {}
    except Exception as e:
        log.warning("Could not parse %s: %s — using defaults", SETTINGS_FILE, e)
        raw = {}
    _settings_cache = _merge_defaults(raw)
    _settings_mtime = m
    return _settings_cache


def save_settings(settings: dict[str, Any]) -> None:
    Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    merged = _merge_defaults(settings)
    merged.pop("zone_names", None)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
        f.write("\n")
    invalidate_cache()
    load_settings(force_reload=True)


def _read_zone_names_json() -> dict[str, str]:
    """Load zone_names.json from disk (not cached with settings)."""
    p = Path(ZONE_NAMES_JSON)
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            text = f.read()
        raw, _lenient = _loads_json_with_trailing_comma_fallback(text)
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) if v is not None else "" for k, v in raw.items()}
    except Exception:
        return {}


def _write_zone_names_json(names: dict[str, str]) -> None:
    """Persist zone labels to zone_names.json (same format as historical installs)."""
    Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    out = {str(k): str(v) for k, v in names.items()}
    path = Path(ZONE_NAMES_JSON)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")


def migrate_from_env_and_legacy() -> None:
    """
    Create settings.txt from env if missing (first boot only).
    DSC_ZONE_LIST / DSC_ZONE_COLUMNS are used only here — not after settings.txt exists.
    """
    if Path(SETTINGS_FILE).is_file():
        return
    s = deepcopy(_DEFAULTS)
    zl = os.environ.get("DSC_ZONE_LIST", "").strip() or os.environ.get("ZONE_LIMIT", "").strip()
    if zl:
        s["zone_list"] = zl
    zc = os.environ.get("DSC_ZONE_COLUMNS", "").strip()
    if zc:
        try:
            s["zone_columns"] = min(3, max(1, int(zc)))
        except (TypeError, ValueError):
            pass
    if os.environ.get("APP_TITLE", "").strip():
        s["app_title"] = os.environ["APP_TITLE"].strip()
    if os.environ.get("APP_SHORT_NAME", "").strip():
        s["app_short_name"] = os.environ["APP_SHORT_NAME"].strip()
    try:
        ps = int(os.environ.get("POLL_SECS", "10"))
        if ps > 0:
            s["poll_secs"] = ps
    except ValueError:
        pass
    save_settings(s)


def get_zone_names_map() -> dict[str, str]:
    """Zone labels: only zone_names.json (separate from app settings)."""
    return _read_zone_names_json()


def set_zone_names_map(names: dict[str, str]) -> None:
    """Persist zone labels to zone_names.json only."""
    _write_zone_names_json(names)


def migrate_zone_names_out_of_settings_txt() -> None:
    """
    If settings.txt still has a legacy `zone_names` key: copy into zone_names.json when that
    file is empty, then strip `zone_names` from settings.txt (zone labels are not app settings).
    """
    path = Path(SETTINGS_FILE)
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8-sig")
        raw, _lenient = _loads_json_with_trailing_comma_fallback(text)
    except Exception:
        return
    if not isinstance(raw, dict) or "zone_names" not in raw:
        return
    embedded = raw.get("zone_names")
    existing = _read_zone_names_json()
    if (
        isinstance(embedded, dict)
        and embedded
        and not existing
    ):
        _write_zone_names_json({str(k): str(v) for k, v in embedded.items() if v is not None})
    raw.pop("zone_names", None)
    merged = _merge_defaults(raw)
    merged.pop("zone_names", None)
    Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
        f.write("\n")
    invalidate_cache()
    load_settings(force_reload=True)
