"""Runtime configuration, resolved from the environment."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping


class ConfigError(RuntimeError):
    """Raised when the environment does not describe a usable configuration."""


@dataclasses.dataclass(frozen=True, slots=True)
class NodeConfig:
    """Connection details for the Lavalink node."""

    name: str
    host: str
    port: int
    password: str
    region: str
    ssl: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class Config:
    """Everything the bot needs to know before it connects to anything."""

    token: str
    node: NodeConfig
    default_guilds: tuple[int, ...]
    delete_after: float
    log_level: str
    log_dir: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        """
        Resolve the configuration from environment variables.

        Raises:
            ConfigError: If a required variable is missing, or a variable holds a value of the wrong shape.
        """
        env = os.environ if env is None else env

        token = env.get("DISCORD_TOKEN")
        if not token:
            raise ConfigError("'DISCORD_TOKEN' is not set - the bot cannot log in without a token")

        return cls(
            token=token,
            node=NodeConfig(
                name=env.get("LAVALINK_NODE_NAME", "default-node"),
                host=env.get("LAVALINK_HOST", "lavalink"),
                port=_int(env, "LAVALINK_PORT", 2333),
                password=env.get("LAVALINK_PASSWORD", "youshallnotpass"),
                region=env.get("LAVALINK_REGION", "eu"),
                ssl=_bool(env, "LAVALINK_SSL", default=False),
            ),
            default_guilds=_guild_ids(env),
            delete_after=_float(env, "DELETE_AFTER", 60.0),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            log_dir=env.get("LOG_DIR") or None,
        )


def _guild_ids(env: Mapping[str, str]) -> tuple[int, ...]:
    """Parse ``DEFAULT_GUILDS`` - a comma separated list of guild IDs to register commands in."""
    raw = env.get("DEFAULT_GUILDS", "").strip()
    if not raw:
        return ()

    try:
        return tuple(int(part) for part in raw.split(",") if part.strip())
    except ValueError as e:
        raise ConfigError(f"'DEFAULT_GUILDS' must be a comma separated list of guild IDs: {e}") from e


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigError(f"{key!r} must be an integer, got {raw!r}") from e


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise ConfigError(f"{key!r} must be a number, got {raw!r}") from e


def _bool(env: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
