"""Profile registry: module.yaml lists the profiles; frozen ones are verified by sha256 on load.

Create an adjustable copy by adding a new version file under config/profiles/ and a new entry
(frozen: false) in config/module.yaml; activate it with `active_profile`. Never edit a frozen file.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from app.modules.eba_rules.domain.profile_schema import validate_profile

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
ENTRY_KEYS = {"name", "version", "file", "frozen", "sha256"}


class ProfileIntegrityError(ValueError):
    """A frozen profile does not match its recorded sha256, or the registry is inconsistent."""


def module_config() -> dict[str, Any]:
    """Parsed config/module.yaml (active profile and profile list)."""
    config = yaml.safe_load((CONFIG_DIR / "module.yaml").read_text(encoding="utf-8"))
    unknown = sorted(set(config) - {"active_profile", "profiles"})
    if unknown:
        raise ValueError(f"module.yaml: unknown keys {unknown}")
    for entry in config["profiles"]:
        extra = sorted(set(entry) - ENTRY_KEYS)
        if extra:
            raise ValueError(f"module.yaml profile {entry.get('name')}: unknown keys {extra}")
    return config


def active_profile_name() -> str:
    """Name of the profile the worker evaluates by default."""
    return module_config()["active_profile"]


def profile_entry(name: str) -> dict[str, Any]:
    """Registry entry of a profile name; KeyError when the name is not registered."""
    for entry in module_config()["profiles"]:
        if entry["name"] == name:
            return entry
    raise KeyError(f"alert profile not registered in module.yaml: {name}")


def load_profile(name: str | None = None) -> tuple[dict[str, Any], str]:
    """Load and validate a profile; return (profile, sha256 of the file bytes).

    Frozen profiles must match the sha256 in module.yaml, or ProfileIntegrityError is raised.
    """
    name = name or active_profile_name()
    entry = profile_entry(name)
    raw = (CONFIG_DIR / entry["file"]).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if entry.get("frozen") and sha != entry.get("sha256"):
        raise ProfileIntegrityError(
            f"frozen profile {name} v{entry['version']} was modified: sha256 {sha} != {entry.get('sha256')}. "
            "Restore the file or create a new version.")
    profile = yaml.safe_load(raw) or {}
    validate_profile(profile)
    if profile["profile"] != name or str(profile.get("version")) != str(entry["version"]):
        raise ProfileIntegrityError(f"{entry['file']}: profile name/version differ from module.yaml")
    if bool(profile.get("frozen", False)) != bool(entry.get("frozen", False)):
        raise ProfileIntegrityError(f"{entry['file']}: `frozen` differs from module.yaml")
    return profile, sha


def profile_info(name: str) -> dict[str, Any]:
    """{'version', 'frozen'} of a registered profile, {} when the name is unknown."""
    try:
        profile, _ = load_profile(name)
    except KeyError:
        return {}
    return {"version": profile.get("version"), "frozen": profile.get("frozen")}


def regulatory_levels(profile: str | None = None) -> dict[str, float]:
    """R0 alert levels (cet1, tier1, total_capital) of a profile (default: the active one)."""
    config = yaml.safe_load((CONFIG_DIR / "regulatory_levels.yaml").read_text(encoding="utf-8"))
    levels = config["r0_levels"].get(profile or active_profile_name())
    if not levels:
        raise ValueError(f"no regulatory levels configured for profile {profile or active_profile_name()}")
    return dict(levels)


def r1_margin_grid_pp() -> list[float]:
    """Candidate R1 margins in percentage points."""
    config = yaml.safe_load((CONFIG_DIR / "regulatory_levels.yaml").read_text(encoding="utf-8"))
    return list(config["r1"]["margin_grid_pp"])
