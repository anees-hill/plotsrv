# src/plotsrv/settings.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Mapping

import os

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


_UNSET = object()
_TRUNCATE_OFF = object()


@dataclass(slots=True)
class RuntimeContext:
    name: str | None = None
    config_path: Path | None = None
    truncate_override: object = _UNSET


_CTX = RuntimeContext()
_CONFIG_CACHE: dict[str, dict[str, Any]] = {}


def set_runtime_context(
    *,
    name: str | None = None,
    config_path: str | Path | None = None,
    truncate_override: object = _UNSET,
) -> None:
    if name is not None:
        _CTX.name = name.strip() or None

    if config_path is not None:
        p = Path(config_path).expanduser().resolve()
        _CTX.config_path = p

    if truncate_override is not _UNSET:
        _CTX.truncate_override = truncate_override


def get_runtime_name() -> str | None:
    if _CTX.name:
        return _CTX.name
    env = os.environ.get("PLOTSRV_NAME", "").strip()
    return env or None


def _resolve_config_path() -> Path | None:
    if _CTX.config_path is not None:
        return _CTX.config_path

    env = os.environ.get("PLOTSRV_CONFIG", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.exists() and p.is_file():
            return p.resolve()

    cwd = Path.cwd()
    for name in ("plotsrv.yml", "plotsrv.yaml"):
        p = cwd / name
        if p.exists() and p.is_file():
            return p.resolve()

    return None


def get_runtime_config_path() -> Path | None:
    return _resolve_config_path()


def get_runtime_config_dir() -> Path | None:
    p = _resolve_config_path()
    return p.parent if p else None


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("pyyaml is not available but is required for YAML config.")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("plotsrv YAML config must be a mapping (top-level dict).")
    return data


def load_config() -> dict[str, Any]:
    p = _resolve_config_path()
    if p is None:
        return {}

    key = str(p)
    cached = _CONFIG_CACHE.get(key)
    if cached is not None:
        return cached

    data = _load_yaml_file(p)
    _CONFIG_CACHE[key] = data
    return data


def _split_global_and_instances(
    section_value: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(section_value, dict):
        return {}, {}

    instances_raw = section_value.get("instances")
    if not isinstance(instances_raw, dict):
        instances_raw = section_value.get("instance")

    instances: dict[str, Any] = instances_raw if isinstance(instances_raw, dict) else {}

    default_raw = section_value.get("default")
    if isinstance(default_raw, dict):
        global_cfg: dict[str, Any] = dict(default_raw)
    else:
        global_cfg = {
            k: v
            for k, v in section_value.items()
            if k not in ("instances", "instance", "default")
        }

    return global_cfg, instances


def _deep_merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        cur = out.get(k)
        if isinstance(cur, Mapping) and isinstance(v, Mapping):
            out[k] = _deep_merge_dicts(dict(cur), dict(v))
        else:
            out[k] = v
    return out


def get_section(section_key: str) -> dict[str, Any]:
    cfg = load_config()
    sec = cfg.get(section_key)
    global_cfg, instances = _split_global_and_instances(sec)

    name = get_runtime_name()
    if name and name in instances and isinstance(instances[name], dict):
        return _deep_merge_dicts(dict(global_cfg), dict(instances[name]))

    return dict(global_cfg)


def get_truncate_override() -> int | None | object:
    if _CTX.truncate_override is not _UNSET:
        return _CTX.truncate_override

    env = os.environ.get("PLOTSRV_TRUNCATE", "").strip()
    if not env:
        return _UNSET

    if env.lower() in ("off", "none", "false", "0"):
        return _TRUNCATE_OFF

    try:
        n = int(float(env))
        return max(1, n)
    except Exception:
        return _UNSET


def is_truncate_override_unset(value: object) -> bool:
    return value is _UNSET


def is_truncate_override_off(value: object) -> bool:
    return value is _TRUNCATE_OFF
