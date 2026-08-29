"""The change log parser: keep-a-changelog entries into plain data."""

from __future__ import annotations

from alfred import changelog

LOG = (
    "# Changelog\n"
    "\n"
    "All notable changes to this project will be documented in this file.\n"
    "\n"
    "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).\n"
    "\n"
    "## [Unreleased]\n"
    "\n"
    "## [2.0.1] - 2026-08-29\n"
    "\n"
    "### Added\n"
    "- Post the changelog on restart\n"
    "- Chat search\n"
    "\n"
    "## [2.0.0] - 2026-08-28\n"
    "\n"
    "### Added\n"
    "- Paginated queue\n"
    "\n"
    "### Fixed\n"
    "- Stuck-track loops\n"
)


def test_newest_entry_skips_unreleased_and_takes_the_first_dated_entry() -> None:
    entry = changelog.newest_entry(LOG)

    assert entry is not None
    assert entry.version == "[2.0.1]"
    assert entry.date == "2026-08-29"


def test_newest_entry_prefers_dated_over_unreleased() -> None:
    content = (
        "## [Unreleased]\n\n### Added\n- WIP\n\n"
        "## [2.0.0] - 2026-08-28\n\n### Fixed\n- X\n"
    )

    entry = changelog.newest_entry(content)

    assert entry is not None
    assert entry.date == "2026-08-28"


def test_newest_entry_falls_back_to_unreleased_when_nothing_is_dated() -> None:
    entry = changelog.newest_entry("## [Unreleased]\n\n### Added\n- WIP\n")

    assert entry is not None
    assert entry.date is None
    assert entry.version == "[Unreleased]"


def test_newest_entry_is_none_when_there_is_no_entry() -> None:
    assert changelog.newest_entry("# Changelog\n\nJust prose, no versions.\n") is None


def test_categories_carry_their_items() -> None:
    entry = changelog.newest_entry(LOG)
    assert entry is not None

    assert [category.name for category in entry.categories] == ["Added"]
    assert entry.categories[0].items == ("Post the changelog on restart", "Chat search")


def test_parse_entries_returns_every_entry_in_order() -> None:
    entries = changelog.parse_entries(LOG)

    # Entries include the undated [Unreleased] section, in file order.
    assert [e.date for e in entries] == [None, "2026-08-29", "2026-08-28"]
    assert entries[2].categories[1].name == "Fixed"
    assert entries[2].categories[1].items == ("Stuck-track loops",)


def test_an_entry_without_version_brackets_is_still_parsed() -> None:
    entry = changelog.newest_entry("## 2.0.0 - 2026-08-29\n\n### Added\n- A\n")

    assert entry is not None
    assert entry.version == "2.0.0"
    assert entry.date == "2026-08-29"


def test_prose_without_an_entry_is_ignored() -> None:
    entry = changelog.newest_entry("# Changelog\n\n### Added\n- Orphan bullets outside an entry\n")

    assert entry is None or entry.categories == ()