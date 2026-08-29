"""Finding and parsing the newest dev log, for the restart post.

Dev logs live in `docs/dev-logs/`, one dated file per day named `YYYY-MM-DD.md`. The newest
is the latest date: ISO dates sort in calendar order, so picking the greatest filename is
choosing the newest log. Parsing turns a log's markdown into plain data - the date, an
optional intro, and the dated sections - so nothing here knows Discord. Turning that data
into an embed is `alfred.ui.embeds`'s job, which is why this module imports nothing from it.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

# A dated dev log file. Its shape doubles as the sort key: `YYYY-MM-DD` filenames order
# chronologically under plain string comparison, which is what makes "newest" a max() over the
# matching names rather than a date parse.
DATE_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")

LOGS_DIRNAME = "dev-logs"


@dataclasses.dataclass(frozen=True, slots=True)
class LogSection:
    """One dated section of a dev log: a heading and the prose under it."""

    heading: str
    body: str


@dataclasses.dataclass(frozen=True, slots=True)
class DevLog:
    """A parsed dev log: its date, an optional intro, and its sections."""

    title: str
    description: str = ""
    sections: tuple[LogSection, ...] = ()


def newest_dev_log(docs_dir: Path) -> Path | None:
    """The newest dated dev log under `docs_dir/dev-logs`, or `None` if there is none."""
    logs_dir = docs_dir / LOGS_DIRNAME
    if not logs_dir.is_dir():
        return None

    best: Path | None = None
    for candidate in logs_dir.glob("*.md"):
        if DATE_FILE.match(candidate.name) and (best is None or candidate.name > best.name):
            best = candidate
    return best


def parse(content: str) -> DevLog:
    """
    Turn a dev log's markdown into a `DevLog`.

    The top-level `# YYYY-MM-DD` title becomes `DevLog.title`; prose before the first section
    becomes `description`; every other heading starts a `LogSection`, and the lines under it
    become its body. Heading marks and blank padding are dropped.
    """
    title = ""
    intro: list[str] = []
    sections: list[LogSection] = []
    heading = ""
    body: list[str] = []

    def finish() -> None:
        if heading:
            sections.append(LogSection(heading=heading, body=_paragraphs(body)))

    for raw in content.replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        if not stripped:
            continue

        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            rest = stripped[hashes:].strip()
            if hashes == 1 and not title:
                title = rest
            else:
                finish()
                heading = rest
                body = []
            continue

        if heading:
            body.append(stripped)
        else:
            intro.append(stripped)

    finish()
    return DevLog(title=title, description=_paragraphs(intro), sections=tuple(sections))


def _paragraphs(lines: list[str]) -> str:
    """Join a section's lines, preserving single line breaks and dropping blank padding."""
    return "\n".join(line for line in lines if line)
