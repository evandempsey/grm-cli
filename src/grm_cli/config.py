"""Where grm signs in to, and with what.

A profile is a server address with a token for it. The token is kept in the operating system's keychain (`keyring`),
never in a file and never taken as a command argument (it would land in shell history). `GRM_TOKEN` and `GRM_URL` in
the environment are for CI and win over the profile; `GRM_PROFILE` picks a profile, as `--profile` does.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
import keyring.errors
import platformdirs
import yaml

from grm_cli.errors import GrmError

DEFAULT_URL = "https://app.generationalrunmachine.com"
SERVICE = "grm-cli"


def config_path() -> Path:
    return platformdirs.user_config_path("grm") / "config.yaml"


def load() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"profiles": {}}
    data = yaml.safe_load(path.read_text()) or {}
    data.setdefault("profiles", {})
    return data


def save(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True))


@dataclass
class Profile:
    name: str
    url: str
    token: str | None
    from_env: bool = False


def chosen(name: str | None = None) -> str:
    return name or os.environ.get("GRM_PROFILE") or load().get("default") or "default"


def profile(name: str | None = None) -> Profile:
    """The profile to use: its address and its token, the environment's where it gives them."""
    name = chosen(name)
    stored = load()["profiles"].get(name, {})
    url = (os.environ.get("GRM_URL") or stored.get("url") or DEFAULT_URL).rstrip("/")
    token = os.environ.get("GRM_TOKEN")
    if token:
        return Profile(name, url, token, from_env=True)
    return Profile(name, url, _get(name))


def _get(name: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, name)
    except keyring.errors.KeyringError:
        return None


def remember(name: str, url: str, token: str) -> None:
    """Keep a profile: its address in the config file, its token in the keychain."""
    try:
        keyring.set_password(SERVICE, name, token)
    except keyring.errors.KeyringError as e:
        raise GrmError(
            "There's no keychain here to keep the token in",
            "Set GRM_TOKEN in the environment instead (and GRM_URL for a server other than GRM's own).",
            code="no_keychain",
        ) from e
    data = load()
    data["profiles"][name] = {"url": url.rstrip("/")}
    data.setdefault("default", name)
    save(data)


def forget(name: str) -> bool:
    """Take a profile's token out of the keychain. Says whether there was one."""
    try:
        keyring.delete_password(SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        return False
    except keyring.errors.KeyringError:
        return False
    return True
