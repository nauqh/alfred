"""The dev log picker (newest file) and the markdown parser."""

from __future__ import annotations

from alfred import dev_log

LOG = (
    "# 2026-08-28\n"
    "\n"
    "## Queue is now paginated\n"
    "Long queues are one page at a time.\n"
    "\n"
    "## The bar keeps moving\n"
    "It catches up every 15 seconds.\n"
)


def _write(docs_dir, name: str, text: str) -> None:
    logs_dir = docs_dir / "dev-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / name).write_text(text, encoding="utf-8")


# --- newest_dev_log ------------------------------------------------------------------------


def test_newest_dev_log_picks_the_latest_date(tmp_path) -> None:
    _write(tmp_path, "2026-08-26.md", LOG)
    _write(tmp_path, "2026-08-29.md", LOG)
    _write(tmp_path, "2026-08-28.md", LOG)

    assert dev_log.newest_dev_log(tmp_path).name == "2026-08-29.md"


def test_newest_dev_log_ignores_non_dated_files(tmp_path) -> None:
    _write(tmp_path, "notes.md", LOG)
    _write(tmp_path, "2026-08-29.md", LOG)

    assert dev_log.newest_dev_log(tmp_path).name == "2026-08-29.md"


def test_newest_dev_log_is_none_when_there_is_no_folder(tmp_path) -> None:
    assert dev_log.newest_dev_log(tmp_path) is None


def test_newest_dev_log_is_none_when_no_dated_files_exist(tmp_path) -> None:
    _write(tmp_path, "2026-08-29.txt", LOG)
    (tmp_path / "dev-logs" / "archive").mkdir(parents=True)
    (tmp_path / "dev-logs" / "archive" / "2026-08-28.md").write_text(LOG, encoding="utf-8")

    assert dev_log.newest_dev_log(tmp_path) is None


# --- parse ---------------------------------------------------------------------------------


def test_parse_reads_the_title_and_the_sections() -> None:
    parsed = dev_log.parse(LOG)

    assert parsed.title == "2026-08-28"
    assert parsed.description == ""
    assert [s.heading for s in parsed.sections] == ["Queue is now paginated", "The bar keeps moving"]
    assert parsed.sections[0].body == "Long queues are one page at a time."
    assert parsed.sections[1].body == "It catches up every 15 seconds."


def test_parse_puts_prose_before_the_first_section_in_the_description() -> None:
    parsed = dev_log.parse("# 2026-08-29\n\nA short intro line.\n\n## A section\nBody here.\n")

    assert parsed.title == "2026-08-29"
    assert parsed.description == "A short intro line."
    assert parsed.sections[0].body == "Body here."


def test_parse_handles_deeper_headings() -> None:
    parsed = dev_log.parse("# 2026-08-29\n\n### Deep heading\nDeep body.\n")

    assert parsed.sections[0].heading == "Deep heading"
    assert parsed.sections[0].body == "Deep body."


def test_parse_drops_blank_padding_and_heading_marks() -> None:
    parsed = dev_log.parse("# 2026-08-29\n\n\n##  A heading  \n\n  trimmed prose  \n\n\n")

    assert parsed.title == "2026-08-29"
    assert parsed.sections[0].heading == "A heading"
    assert parsed.sections[0].body == "trimmed prose"


def test_parse_keeps_multiline_prose() -> None:
    parsed = dev_log.parse("# 2026-08-29\n\n## A section\nfirst line\nsecond line\n")

    assert parsed.sections[0].body == "first line\nsecond line"


def test_parse_of_empty_content_has_no_parts() -> None:
    parsed = dev_log.parse("")

    assert parsed.title == ""
    assert parsed.description == ""
    assert parsed.sections == ()
