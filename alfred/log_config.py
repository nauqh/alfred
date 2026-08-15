"""Logging setup.

The bot logs through loguru. hikari and lavalink.py log through the standard library, so their
records are handed to loguru too - one stream, one format, one set of colours, rather than two
logging systems interleaving on the same terminal.

When ``LOG_DIR`` is set the bot also keeps rotating files: ``bot.log`` for everything, and
``track.log`` for the tracks that were played.
"""

from __future__ import annotations

import logging
import sys

from loguru import logger

# Close to hikari's own console format, which is what this replaced.
CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> <level>{level: <8}</level> <cyan>{name}</cyan>: <level>{message}</level>"
)
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} {level} {name}.{function}:{line}: {message}"
TRACK_FORMAT = "{time:YYYY-MM-DD HH:mm:ss}: {message}"

# Tracks are tagged rather than sent to a separate logger, so `track.log` can be filtered out
# of everything else.
TRACK = "track"


class InterceptHandler(logging.Handler):
    """Hands standard library records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # The standard library already knows which logger this came from, so the name is
        # copied straight across. Walking back through the frames to work it out instead
        # lands on `logging` itself, which is how these records ended up mislabelled.
        patched = logger.patch(lambda r: r.update(name=record.name))
        patched.opt(exception=record.exc_info).log(level, record.getMessage())


def configure(level: str = "INFO", log_dir: str | None = None) -> None:
    """
    Point every logger at loguru, and loguru at the console (and optionally at files).

    Args:
        level: The level for the bot's own messages and for the libraries.
        log_dir: Directory to write log files into. No files are written when this is `None`.
    """
    logger.remove()
    # `colorize=True` rather than left to autodetection: the console script runs behind a
    # launcher shim on Windows, and loguru sees that as "not a terminal" and drops the colour.
    logger.add(sys.stdout, format=CONSOLE_FORMAT, level=level, colorize=True)

    if log_dir is not None:
        logger.add(
            f"{log_dir}/bot.log",
            format=FILE_FORMAT,
            level=level,
            filter=lambda record: not record["extra"].get(TRACK),
            rotation="00:00",
            retention=10,
            encoding="utf-8",
        )
        logger.add(
            f"{log_dir}/track.log",
            format=TRACK_FORMAT,
            level="INFO",
            filter=lambda record: bool(record["extra"].get(TRACK)),
            rotation="00:00",
            retention=10,
            encoding="utf-8",
        )

    # hikari and lavalink.py log through the standard library; this sends those records to
    # loguru as well, so they arrive coloured and in the same shape as everything else.
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("hikari", "lavalink"):
        logging.getLogger(name).setLevel(logging.INFO)
