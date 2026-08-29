"""Finding and formatting the newest dev log, for the restart post.

Dev logs live in `docs/dev-logs/`, one dated file per day named `YYYY-MM-DD.md`. The newest
is the latest date: ISO dates sort in calendar order, so picking the greatest filename is
choosing the newest log. Nothing here knows Discord or a channel - that is the caller's job -
so this module holds only pure lookups and text shaping, and stays testable on its own.
"""

from __future__ import annotations

import re
from pathlib import Path

from alfred.ui.embeds import MAX_MESSAGE

# A dated dev log file. Its shape doubles as the sort key: `YYYY-MM-DD` filenames order
# chronologically under plain string comparison, which is what makes "newest" a max() over the
# matching names rather than a date parse.
DATE_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")

LOGS_DIRNAME = "dev-logs"


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


def format_messages(content: str, title: str) -> tuple[str, ...]:
    """
    Turn a dev log's text into Discord messages: headers become bold, split across messages.

    Discord does not render `#` heading levels in an ordinary message, so each header becomes
    a bold line. `title` is the date, added as the first line; the file's own `# YYYY-MM-DD`
    title is dropped so it does not appear twice. A log longer than one message is split on
    line boundaries so no single message passes Discord's limit.
    """
    lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("# ", "## ", "### ")):
            lines.append(f"**{stripped.lstrip('# ').strip()}**")
        else:
            lines.append(stripped)

    body = "\n".join(line for line in lines if line)
    return _split_message(f"**{title}**\n\n{body}")


def _split_message(text: str) -> tuple[str, ...]:
    """Split `text` into messages no longer than `MAX_MESSAGE`, breaking between lines."""
    messages: list[str] = []
    current = ""
    for line in text.replace("\r\n", "\n").split("\n"):
        if len(line) > MAX_MESSAGE:
            # A single over-long line (nobody writes one by hand, but be safe) becomes its
            # own hard-sliced message rather than silently dropping the tail.
            if current:
                messages.append(current)
                current = ""
            messages.extend(line[i : i + MAX_MESSAGE] for i in range(0, len(line), MAX_MESSAGE))
            continue
        if not current:
            current = line
        elif len(current) + 1 + len(line) <= MAX_MESSAGE:
            current += "\n" + line
        else:
            messages.append(current)
            current = line
    if current:
        messages.append(current)
    return tuple(messages)
