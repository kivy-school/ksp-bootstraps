"""Merge a user-provided ``xcode.yaml`` into the generated XcodeGen spec.

Users can drop an ``xcode.yaml`` (or ``xcode.yml``) in the project root to
add extra entries (packages, dependencies, settings, ...) to the
``project.yml`` that ksproject generates for XcodeGen.

Merge semantics — additive:

- dictionaries merge recursively
- lists are appended (generated entries first, then user entries)
- only where the same scalar key exists on both sides does the user value win
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

USER_SPEC_NAMES = ("xcode.yaml", "xcode.yml")


class UserSpecError(Exception):
    pass


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge ``override`` on top of ``base``."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        elif isinstance(current, list) and isinstance(value, list):
            merged[key] = current + value
        else:
            merged[key] = value
    return merged


def find_user_spec(project_root: Path) -> Path | None:
    for name in USER_SPEC_NAMES:
        path = project_root / name
        if path.is_file():
            return path
    return None


def load_user_spec(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise UserSpecError(f"{path.name} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise UserSpecError(
            f"{path.name} must contain a YAML mapping at the top level, "
            f"got {type(data).__name__}"
        )
    return data


def merge_user_spec(spec: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Overlay the project-root ``xcode.yaml`` (if any) onto ``spec``."""
    path = find_user_spec(project_root)
    if path is None:
        return spec
    user_spec = load_user_spec(path)
    if not user_spec:
        return spec
    print(f"[ksproject] merging {path.name} into generated project.yml")
    return deep_merge(spec, user_spec)
