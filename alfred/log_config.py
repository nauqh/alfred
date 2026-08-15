"""Logging setup.

Everything the bot writes goes through loguru. hikari and lavalink.py log through the standard
library, so those are intercepted and re-emitted into loguru - one stream, one format, rather
than two logging systems interleaving on the same terminal.

When ``LOG_DIR`` is set the bot also keeps rotating files: ``bot.log`` for everything, and
``track.log`` for the tracks that were played.
"""

from __future__ import annotations

import logging
import sys

from loguru import logger

CONSOLE_FORMAT = (
    "<level>{level: <1.1}</level> <dim>{time:YYYY-MM-DD HH:mm:ss}</dim> "
    "<bold>{name}</bold>: <level>{message}</level>"
)
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} {level} {name}.{function}:{line}: {message}"
TRACK_FORMAT = "{time:YYYY-MM-DD HH:mm:ss}: {message}"

# Tracks are tagged with this rather than being a separate logger, so `track.log` can be
# filtered out of everything else.
TRACK = "track"


class InterceptHandler(logging.Handler):
    """Hands standard library records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk out of the logging machinery so the message is attributed to whatever called
        # it, not to this handler.
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure(level: str = "INFO", log_dir: str | None = None) -> None:
    """
    Point every logger at loguru, and loguru at the console (and optionally at files).

    Args:
        level: The level for the bot's own messages and for the libraries.
        log_dir: Directory to write log files into. No files are written when this is `None`.
    """
    logger.remove()
    logger.add(sys.stdout, format=CONSOLE_FORMAT, level=level, filter=_not_track)
    logger.add(sys.stdout, format=TRACK_FORMAT, level="INFO", filter=_is_track)

    if log_dir is not None:
        logger.add(
            f"{log_dir}/bot.log",
            format=FILE_FORMAT,
            level=level,
            filter=_not_track,
            rotation="00:00",
            retention=10,
            encoding="utf-8",
        )
        logger.add(
            f"{log_dir}/track.log",
            format=TRACK_FORMAT,
            level="INFO",
            filter=_is_track,
            rotation="00:00",
            retention=10,
            encoding="utf-8",
        )

    # hikari and lavalink.py log through the standard library. Replacing the root handlers
    # sends those records to loguru too.
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("hikari", "lavalink"):
        logging.getLogger(name).setLevel(logging.INFO)


def _is_track(record: dict) -> bool:
    return bool(record["extra"].get(TRACK))


def _not_track(record: dict) -> bool:
    return not record["extra"].get(TRACK)
