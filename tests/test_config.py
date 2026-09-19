from __future__ import annotations

import pytest

from alfred.config import Config
from alfred.config import ConfigError

MINIMAL = {"DISCORD_TOKEN": "token"}


def test_defaults_need_only_a_token() -> None:
    config = Config.from_env(MINIMAL)

    assert config.token == "token"
    assert config.default_guilds == ()
    assert config.delete_after == 60.0
    assert config.log_dir is None

    node = config.node
    assert (node.name, node.host, node.port, node.password) == ("default-node", "lavalink", 2333, "youshallnotpass")
    assert node.ssl is False


def test_a_missing_token_is_an_error() -> None:
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        Config.from_env({})


def test_node_settings_come_from_the_environment() -> None:
    config = Config.from_env(
        MINIMAL | {"LAVALINK_HOST": "audio.example.com", "LAVALINK_PORT": "443", "LAVALINK_SSL": "true"}
    )

    assert (config.node.host, config.node.port, config.node.ssl) == ("audio.example.com", 443, True)


def test_guild_ids_are_parsed_into_ints() -> None:
    config = Config.from_env(MINIMAL | {"DEFAULT_GUILDS": "123, 456 ,"})

    assert config.default_guilds == (123, 456)


def test_unparseable_guild_ids_are_rejected() -> None:
    with pytest.raises(ConfigError, match="DEFAULT_GUILDS"):
        Config.from_env(MINIMAL | {"DEFAULT_GUILDS": "not-an-id"})


def test_a_non_numeric_port_is_rejected() -> None:
    with pytest.raises(ConfigError, match="LAVALINK_PORT"):
        Config.from_env(MINIMAL | {"LAVALINK_PORT": "http"})


def test_blank_values_fall_back_to_the_defaults() -> None:
    config = Config.from_env(MINIMAL | {"LAVALINK_PORT": "", "DELETE_AFTER": "", "DEFAULT_GUILDS": " "})

    assert config.node.port == 2333
    assert config.delete_after == 60.0
    assert config.default_guilds == ()
