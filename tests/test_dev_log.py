"""The dev log picker (newest file) and its Discord text shaping."""

from __future__ import annotations

from alfred import dev_log
from alfred.ui.embeds import MAX_MESSAGE

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


# --- format_messages -----------------------------------------------------------------------


def test_headers_become_bold_and_the_title_is_prepended() -> None:
    messages = dev_log.format_messages(LOG, title="Alfred dev log - 2026-08-28")

    assert len(messages) == 1
    body = messages[0]
    assert body.startswith("**Alfred dev log - 2026-08-28**\n\n")
    # The file's own `#` date title and the `##` section headers all become bold lines.
    assert "**2026-08-28**" in body
    assert "**Queue is now paginated**" in body
    assert "Long queues are one page at a time." in body


def test_a_log_longer_than_a_message_is_split() -> None:
    section = "# 2026-08-29\n\n"
    section += "## Long log\n"
    section += "\n".join(f"line {i} - " + "x" * 80 for i in range(80)) + "\n"

    messages = dev_log.format_messages(section, title="Alfred dev log - 2026-08-29")

    assert len(messages) > 1
    assert all(len(m) <= MAX_MESSAGE for m in messages)
    # Nothing is lost across the split.
    assert sum(m.count("line ") for m in messages) == 80
    assert messages[0].startswith("**Alfred dev log - 2026-08-29**")


def test_a_single_overlong_line_is_hard_sliced() -> None:
    total = MAX_MESSAGE + 50
    messages = dev_log.format_messages(f"# 2026-08-29\n\n{'y' * total}", title="t")

    # The over-long line is sliced into MAX_MESSAGE pieces, and nothing is dropped.
    assert any(len(m) == MAX_MESSAGE for m in messages)
    assert sum(m.count("y") for m in messages) == total
