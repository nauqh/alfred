from __future__ import annotations

import json

import pytest

from alfred.chat.completions import ChatError
from alfred.chat.completions import extract_content
from alfred.chat.completions import finish_reason
from alfred.chat.completions import parse_reply
from alfred.chat.completions import strip_thinking
from alfred.ui import embeds
from alfred.ui.embeds import MAX_DESCRIPTION
from alfred.ui.embeds import MAX_FIELD_VALUE
from alfred.ui.embeds import MAX_FIELDS
from alfred.ui.embeds import MAX_MESSAGE
from alfred.ui.embeds import Reply


def completion(content: str) -> dict[str, object]:
    """A chat-completions response carrying `content`."""
    return {"choices": [{"message": {"content": content}}]}


def test_a_json_answer_becomes_its_parts() -> None:
    reply = parse_reply(json.dumps({"title": "Queueing", "description": "Use `/play`."}))

    assert reply.title == "Queueing"
    assert reply.description == "Use `/play`."


def test_prose_is_kept_as_the_description() -> None:
    reply = parse_reply("Use /play to queue something.")

    assert reply.description == "Use /play to queue something."
    assert reply.title is None
    assert reply.fields == ()


def test_plain_prose_is_not_an_embed() -> None:
    assert parse_reply("Just an answer.").is_embed is False


@pytest.mark.parametrize(
    "payload",
    [
        {"description": "d", "title": "A subject"},
        {"description": "d", "fields": [{"name": "n", "value": "v"}]},
    ],
)
def test_structure_is_what_earns_an_embed(payload: dict[str, object]) -> None:
    assert parse_reply(json.dumps(payload)).is_embed is True


def test_json_carrying_only_a_description_is_posted_plain() -> None:
    """A bare envelope is a plain answer, and gets an ordinary message rather than an embed."""
    reply = parse_reply(json.dumps({"description": "Nothing structured here."}))

    assert reply.description == "Nothing structured here."
    assert reply.is_embed is False


def test_a_plain_answer_is_clamped_to_the_message_limit() -> None:
    """Plain answers get less room than embed descriptions, so they are clamped harder."""
    reply = parse_reply("p" * (MAX_MESSAGE + 500))

    assert reply.is_embed is False
    assert len(reply.description) == MAX_MESSAGE


@pytest.mark.parametrize(
    "wrapper",
    [
        '```json\n{"description": "Answered."}\n```',
        '```\n{"description": "Answered."}\n```',
        'Sure! Here you go:\n{"description": "Answered."}',
        '{"description": "Answered."}\nHope that helps.',
    ],
)
def test_json_is_found_however_the_model_wraps_it(wrapper: str) -> None:
    assert parse_reply(wrapper).description == "Answered."


def test_json_without_a_description_falls_back_to_the_raw_text() -> None:
    content = json.dumps({"title": "Only a title"})

    assert parse_reply(content).description == content


def test_fields_are_parsed_and_bad_entries_dropped() -> None:
    reply = parse_reply(
        json.dumps(
            {
                "description": "Two of these are usable.",
                "fields": [
                    {"name": "/play", "value": "Queue a track", "inline": True},
                    {"name": "  ", "value": "blank name"},
                    "not an object",
                    {"name": "/skip", "value": "Skip it"},
                ],
            }
        )
    )

    assert [(f.name, f.inline) for f in reply.fields] == [("/play", True), ("/skip", False)]


def test_oversized_text_is_clamped_to_discord_limits() -> None:
    reply = parse_reply(
        json.dumps(
            {
                "description": "d" * (MAX_DESCRIPTION + 500),
                "fields": [{"name": "n", "value": "v" * (MAX_FIELD_VALUE + 500)}] * (MAX_FIELDS + 5),
            }
        )
    )

    assert len(reply.description) == MAX_DESCRIPTION
    assert reply.description.endswith("…")
    assert len(reply.fields) <= MAX_FIELDS
    assert all(len(f.value) <= MAX_FIELD_VALUE for f in reply.fields)


def test_tagged_thinking_is_stripped() -> None:
    assert strip_thinking("<think>They want X. I should say Y.</think>\nY, then.") == "Y, then."


def test_thinking_cut_off_mid_thought_leaves_nothing_to_post() -> None:
    """A model that spends its whole budget thinking has produced no answer, not a short one."""
    with pytest.raises(ChatError, match="only its own thinking"):
        strip_thinking("<think>Let me work through what they are asking for and")


def test_an_answer_before_an_unclosed_think_tag_survives() -> None:
    assert strip_thinking("Use `/play`.\n<think>Should I also mention") == "Use `/play`."


def test_ordinary_text_passes_through_untouched() -> None:
    assert strip_thinking("  Just an answer.  ") == "Just an answer."


@pytest.mark.parametrize(
    "preamble",
    [
        "Here's a thinking process:\n\nAnalyze User Input: user says 'what can you do'.",
        "Thinking process: the user wants a list.",
        "Let me think about what they are asking.",
        "Okay, so the user wants to know what I do.",
        "The user is asking about my commands.",
        "First, I need to understand the persona constraints.",
    ],
)
def test_untagged_thinking_is_refused_rather_than_posted(preamble: str) -> None:
    """The failure that reached a real channel: a monologue with no `<think>` tags around it."""
    with pytest.raises(ChatError, match="narrated its reasoning"):
        strip_thinking(preamble)


@pytest.mark.parametrize(
    "imitation",
    [
        "<|tool_call_start|>[/stats()]<|tool_call_end|>",
        "<|tool_call_start|>[play(url='https://www.youtube.com/watch?v=1Xh9f4j0r3I')]<|tool_call_end|>",
    ],
)
def test_an_imitated_tool_call_is_refused(imitation: str) -> None:
    """Observed from `lfm-2.5-2.6b`, which has no tools and imitates calling one anyway."""
    with pytest.raises(ChatError, match="imitated a tool call"):
        strip_thinking(imitation)


def test_a_stray_token_beside_a_real_answer_is_only_stripped() -> None:
    assert strip_thinking("<|im_end|>Use `/play`.") == "Use `/play`."


@pytest.mark.parametrize(
    "answer",
    [
        "Let me know if that doesn't work.",
        "The user manual is at the link in my bio.",
        "First, I need a URL from you - then `/play` does the rest.",
        "Thinking about it, Deezer would suit you better.",
    ],
)
def test_answers_that_merely_resemble_a_preamble_are_kept(answer: str) -> None:
    """The guard is anchored and narrow, so ordinary sentences that start similarly survive."""
    assert strip_thinking(answer) == answer


def test_a_truncated_response_is_still_read() -> None:
    """`finish_reason: length` is worth a warning, but the partial answer is better than nothing."""
    data = {"choices": [{"message": {"content": "Use `/play` to"}, "finish_reason": "length"}]}

    assert finish_reason(data) == "length"
    assert extract_content(data) == "Use `/play` to"


def test_a_completion_is_read_out_of_the_response() -> None:
    assert extract_content(completion("  hello  ")) == "hello"


@pytest.mark.parametrize(
    "data",
    [
        {"error": {"message": "rate limited"}},
        {"choices": []},
        {"choices": [{"message": {"content": "   "}}]},
        {"nothing": "useful"},
    ],
)
def test_unusable_responses_raise(data: dict[str, object]) -> None:
    with pytest.raises(ChatError):
        extract_content(data)


def test_the_embed_carries_the_reply_and_names_the_model() -> None:
    embed = embeds.chat_reply(Reply(description="Answered.", title="Subject"), model="vendor/model:free")

    assert (embed.title, embed.description) == ("Subject", "Answered.")
    assert embed.footer is not None and embed.footer.text == "vendor/model:free"


def test_fields_past_the_total_budget_are_dropped() -> None:
    # Each field is a fifth of the ceiling, so only some of the ten can survive alongside it.
    filler = "x" * (embeds.MAX_EMBED_TOTAL // 5)
    reply = parse_reply(json.dumps({"description": "Short.", "fields": [{"name": "n", "value": filler}] * 10}))
    embed = embeds.chat_reply(reply, model="m")

    assert 0 < len(embed.fields) < 10
    assert sum(len(f.name) + len(f.value) for f in embed.fields) <= embeds.MAX_EMBED_TOTAL
