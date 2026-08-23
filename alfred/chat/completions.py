"""Turning a raw model completion into something postable.

The free models on OpenRouter are the weakest it carries, and what comes back is often not
what was asked for: thinking left in the answer, JSON fenced or prefaced, a chat-template
token emitted as text, an answer cut off mid-object. Every one of those has reached a real
channel at some point, and each is handled here rather than at the call site.

Split out of `client` so this is testable on its own: the parsing is pure, and the tests for
it need no HTTP at all.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any
from typing import Final

from loguru import logger

from alfred.ui.embeds import MAX_DESCRIPTION
from alfred.ui.embeds import MAX_FIELD_NAME
from alfred.ui.embeds import MAX_FIELD_VALUE
from alfred.ui.embeds import MAX_FIELDS
from alfred.ui.embeds import MAX_MESSAGE
from alfred.ui.embeds import MAX_TITLE
from alfred.ui.embeds import Field
from alfred.ui.embeds import Reply


class ChatError(RuntimeError):
    """Raised when OpenRouter cannot be reached, or answers with something unusable."""


@dataclasses.dataclass(frozen=True, slots=True)
class ToolCall:
    """
    An action the model proposed, and the arguments it read out of the message.

    A proposal, not a decision: `alfred.actions` applies the checks and decides whether it runs.
    """

    name: str
    arguments: dict[str, Any]

    @property
    def query(self) -> str:
        """The `play` argument, trimmed. Empty when the model called `play` with nothing usable."""
        raw = self.arguments.get("query")
        return raw.strip() if isinstance(raw, str) else ""


# The convention reasoning models use when they leave their thinking in `content` - see
# `strip_thinking`, which is the backstop for when the request parameter does not take.
THINK_BLOCK: Final = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# Special tokens from a model's own chat template, which some of them emit as ordinary text
# rather than keeping to themselves. `lfm-2.5-2.6b` answers "why is the music stuttering?" with
# a bare `<|tool_call_start|>[/stats()]<|tool_call_end|>` - it has no tools, and is imitating
# the shape of calling one.
SPECIAL_TOKEN: Final = re.compile(r"<\|[^|]*\|>")
TOOL_CALL_TOKEN: Final = re.compile(r"<\|[^|]*tool[_ ]?call[^|]*\|>", re.IGNORECASE)

# How the same monologue opens when it arrives with no tags around it at all, which is the
# form that actually reached a channel here. Anchored to the start and kept narrow on purpose:
# these are phrases a model uses to address itself, and none of them is a plausible opening for
# an answer addressed to somebody else.
THINKING_PREAMBLE: Final = re.compile(
    r"^\s*(?:"
    r"here'?s?\s+(?:a|my|the)\s+thinking|"
    r"thinking\s+process\s*:|"
    r"let me (?:think|work through|analyz|break)|"
    r"okay,?\s+so\s+the\s+user|"
    r"the user (?:is asking|wants|says)|"
    r"analyz(?:e|ing)\s+user\s+input|"
    r"first,?\s+i\s+need\s+to\s+(?:understand|figure)"
    r")",
    re.IGNORECASE,
)


def usage(data: Any) -> str:
    """
    Describe the token usage of a response, for the log line.

    Free models still report usage, and it is the number that explains a truncated answer -
    a completion count sitting exactly on `CHAT_MAX_TOKENS` means the model was cut off, not
    that it had nothing more to say.
    """
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return "usage not reported"

    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if prompt is None and completion is None:
        return "usage not reported"

    return f"{prompt} prompt + {completion} completion tokens"


def tool_call(data: Any) -> ToolCall | None:
    """
    Read the first tool call out of a response, if the model made one.

    Only the first is taken. The model is answering one message from one person, and running a
    string of actions off a single sentence is a good way to surprise a channel - if it wants
    two things done, the second can be asked for.
    """
    try:
        calls = data["choices"][0]["message"].get("tool_calls")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None

    if not isinstance(calls, list) or not calls:
        return None

    function = calls[0].get("function") if isinstance(calls[0], dict) else None
    if not isinstance(function, dict) or not isinstance(function.get("name"), str):
        logger.warning("Model returned a tool call with no usable function: {}", str(calls[0])[:200])
        return None

    # Arguments arrive as a JSON *string*, and a weak model can produce a malformed one. An
    # unreadable argument list is not fatal: `actions` treats a `play` with no query as a
    # request to ask what to play, which is the right outcome anyway.
    raw = function.get("arguments")
    arguments: dict[str, Any] = {}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Model returned unparseable tool arguments: {!r}", raw[:200])
        else:
            if isinstance(parsed, dict):
                arguments = parsed
    elif isinstance(raw, dict):
        arguments = raw

    return ToolCall(name=function["name"], arguments=arguments)


def finish_reason(data: Any) -> str | None:
    """Why the model stopped. `"length"` means it ran into `max_tokens` mid-answer."""
    try:
        return data["choices"][0].get("finish_reason")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def extract_content(data: Any) -> str:
    """
    Pull the message text out of a chat-completions response.

    OpenRouter fronts a lot of different providers, and a few of them return a 200 carrying an
    `error` object instead of `choices` - so the happy shape is checked rather than assumed.
    """
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        raise ChatError(f"OpenRouter returned an error: {data['error'].get('message', data['error'])}")

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ChatError(f"Unexpected response shape from OpenRouter: {str(data)[:300]}") from e

    if not isinstance(content, str) or not content.strip():
        raise ChatError("OpenRouter returned an empty completion")

    return strip_thinking(content)


def strip_thinking(content: str) -> str:
    """
    Remove any thinking the model left inline.

    `reasoning: {"exclude": true}` on the request is what should keep thinking out of `content`
    in the first place, and for a model OpenRouter knows to be a reasoning model it does. This
    is the backstop for the ones it does not: a model that wraps its own monologue in `<think>`
    tags, and the truncated case where a cut-off answer is *nothing but* the opening of one.

    Raises:
        ChatError: If stripping leaves nothing, which means the model spent its whole budget
            thinking and never began the answer.
    """
    cleaned = THINK_BLOCK.sub("", content)

    # An unclosed tag means the answer was cut off inside the model's thinking, so everything
    # from the tag onwards is monologue with no answer after it.
    opening = cleaned.find("<think>")
    if opening != -1:
        cleaned = cleaned[:opening]

    # A tool call is refused outright rather than stripped: what is left after removing the
    # tokens is the call's arguments, not an answer - `[/stats()]`, or a YouTube id the model
    # invented. Alfred exposes no tools, so any of this is the model imitating a shape it was
    # trained on. Other template tokens are just noise, and are cut out.
    if TOOL_CALL_TOKEN.search(cleaned):
        raise ChatError(f"The model imitated a tool call instead of answering: {cleaned[:120]!r}")

    cleaned = SPECIAL_TOKEN.sub("", cleaned).strip()
    if not cleaned:
        raise ChatError("The model returned only its own thinking - no answer to post")

    # Untagged thinking cannot be cut out, because there is no reliable mark for where it stops
    # and the answer starts. Refusing is the right call anyway: what follows a model narrating
    # its own instructions is either nothing, or an answer nobody should have to scroll past a
    # monologue to reach. The caller turns this into an ordinary "try again" message.
    if THINKING_PREAMBLE.match(cleaned):
        raise ChatError(f"The model narrated its reasoning instead of answering: {cleaned[:120]!r}")

    if cleaned != content.strip():
        logger.debug("Stripped inline thinking from the completion")

    return cleaned


def parse_reply(content: str) -> Reply:
    """
    Turn a completion into a `Reply`.

    A plain-text answer stays plain text - that is the model choosing an ordinary message over
    an embed, and it is the common case.

    When JSON does arrive it is the weakest models on OpenRouter producing it, so it arrives
    fenced, prefaced with "Sure!", or abandoned halfway on a `max_tokens` cut about as often as
    it arrives clean. None of that is worth failing a reply over: anything unparseable is
    treated as the plain-text answer it looks like, and the user still gets something.
    """
    payload = _json_object(content)
    if payload is None:
        return Reply(description=clamp(content, MAX_MESSAGE))

    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        # Structured, but with the one required key missing. The raw text is better than nothing.
        logger.debug("Model returned JSON without a usable description: {}", content[:200])
        return Reply(description=clamp(content, MAX_MESSAGE))

    raw_title = payload.get("title")
    title = clamp(raw_title.strip(), MAX_TITLE) if isinstance(raw_title, str) and raw_title.strip() else None
    fields = _fields(payload.get("fields"))

    # Structured JSON with neither a title nor fields is a plain answer wearing an envelope, so
    # it is posted as one - and has to fit an ordinary message rather than an embed.
    limit = MAX_DESCRIPTION if title is not None or fields else MAX_MESSAGE
    return Reply(description=clamp(description.strip(), limit), title=title, fields=fields)


def _json_object(content: str) -> dict[str, Any] | None:
    """
    Find and parse the JSON object in a completion, if there is one.

    Slicing between the outermost braces handles the fenced and prefaced cases in one go,
    without a regex per wrapper style the models invent.
    """
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        return None

    try:
        parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None


def _fields(raw: Any) -> tuple[Field, ...]:
    """Build the embed fields, dropping any entry that is not a usable name/value pair."""
    if not isinstance(raw, list):
        return ()

    fields: list[Field] = []
    for item in raw[:MAX_FIELDS]:
        if not isinstance(item, dict):
            continue
        name, value = item.get("name"), item.get("value")
        if not isinstance(name, str) or not isinstance(value, str) or not name.strip() or not value.strip():
            continue
        fields.append(
            Field(
                name=clamp(name.strip(), MAX_FIELD_NAME),
                value=clamp(value.strip(), MAX_FIELD_VALUE),
                inline=bool(item.get("inline", False)),
            )
        )

    return tuple(fields)


def clamp(text: str, limit: int) -> str:
    """Cut `text` to `limit` characters, marking the cut so a clipped answer does not read as a bug."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
