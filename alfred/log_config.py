"""Logging setup.

Everything logs through the standard library - the bot's own modules, hikari and lavalink.py -
so there is one stream, one format, rather than two logging systems interleaving on the same
terminal.

When ``LOG_DIR`` is set the bot also keeps rotating files: ``bot.log`` for everything, and
``track.log`` for the tracks that were played.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler

CONSOLE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s.%(funcName)s:%(lineno)d: %(message)s"
TRACK_FORMAT = "%(asctime)s: %(message)s"

TRACK_LOGGER = "alfred.track"

# The tracks that were played. It has its own logger rather than a tag on the shared one, so
# `track.log` can hold nothing else; it still propagates, so tracks show up on the console too.
track_logger = logging.getLogger(TRACK_LOGGER)


def _rotating(path: str, fmt: str, level: int | str) -> TimedRotatingFileHandler:
    """A file handler that turns over at midnight and keeps ten days."""
    handler = TimedRotatingFileHandler(path, when="midnight", backupCount=10, encoding="utf-8")
    handler.setFormatter(logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S"))
    handler.setLevel(level)
    return handler


def configure(level: str = "INFO", log_dir: str | None = None) -> None:
    """
    Point the root logger at the console, and optionally at files.

    Args:
        level: The level for the bot's own messages and for the libraries.
        log_dir: Directory to write log files into. No files are written when this is `None`.
    """
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, "%H:%M:%S"))

    handlers: list[logging.Handler] = [console]

    if log_dir is not None:
        bot_log = _rotating(f"{log_dir}/bot.log", FILE_FORMAT, level)
        # Played tracks belong in `track.log` alone.
        bot_log.addFilter(lambda record: record.name != TRACK_LOGGER)
        handlers.append(bot_log)

        track_logger.addHandler(_rotating(f"{log_dir}/track.log", TRACK_FORMAT, logging.INFO))

    logging.basicConfig(handlers=handlers, level=level, force=True)

    # hikari and lavalink.py are chatty at DEBUG and say little worth reading below INFO.
    for name in ("hikari", "lavalink"):
        logging.getLogger(name).setLevel(logging.INFO)
