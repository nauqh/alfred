"""Finding and parsing the newest entry of the change log, for the restart post.

The bot follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/): one `CHANGELOG.md`
at the repo root, newest entry first, each entry a version heading with a date and category
sub-headings (`### Added`, `### Fixed`, ...) over bullet items. Newest means the first entry
that carries a date - entries without one are unreleased, and are posted only when nothing
dated exists yet. Parsing turns markdown into plain data, so nothing here knows Discord;
rendering is `alfred.ui.embeds`'s job.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

CHANGELOG_FILENAME = "CHANGELOG.md"

# `## [2.0.0] - 2026-08-29` - a dated entry. The trailing date is what makes an entry postable;
# a heading without one (typically `[Unreleased]`) is kept only as a fallback.
_DATE_TAIL = " - "


@dataclasses.dataclass(frozen=True, slots=True)
class Category:
    """One keep-a-changelog category: `### Added` and the bullets under it."""

    name: str
    items: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class Entry:
    """One `##` section of the change log: a version, its date, and its categories."""

    version: str
    date: str | None
    categories: tuple[Category, ...] = ()


def newest_entry(content: str) -> Entry | None:
    """The newest dated entry in the log, or the first undated one when nothing is dated."""
    entries = parse_entries(content)
    if not entries:
        return None
    return next((entry for entry in entries if entry.date is not None), entries[0])


def parse_entries(content: str) -> tuple[Entry, ...]:
    """
    Turn a change log's markdown into its entries.

    `##` headings start an entry (a trailing ` - YYYY-MM-DD` becomes its date), `###` headings
    start a category, and `- ` bullets under a category become its items. Everything else -
    the intro, links, prose - is ignored.
    """
    entries: list[Entry] = []
    version = ""
    date: str | None = None
    categories: list[Category] = []
    category_name = ""
    items: list[str] = []

    def finish_category() -> None:
        if category_name:
            categories.append(Category(name=category_name, items=tuple(items)))

    def finish_entry() -> None:
        if version:
            finish_category()
            entries.append(Entry(version=version, date=date, categories=tuple(categories)))
            categories.clear()

    for raw in content.replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        if not stripped:
            continue

        if stripped.startswith("## "):
            finish_entry()
            rest = stripped[3:].strip()
            version, date = _split_version(rest)
            category_name = ""
            items = []
            continue

        if stripped.startswith("### "):
            finish_category()
            category_name = stripped[4:].strip()
            items = []
            continue

        if stripped.startswith("- ") and category_name:
            items.append(stripped[2:].strip())
            continue

    finish_entry()
    return tuple(entries)


def _split_version(rest: str) -> tuple[str, str | None]:
    """Split `[2.0.0] - 2026-08-29` into its version and date; an undated heading keeps it whole."""
    if _DATE_TAIL in rest:
        version, _, date = rest.rpartition(_DATE_TAIL)
        return version.strip(), date.strip()
    return rest, None


def newest_change_log_path(project_root: Path) -> Path:
    """Where the change log lives: `CHANGELOG.md` at the project root."""
    return project_root / CHANGELOG_FILENAME