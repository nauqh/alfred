"""Talking to a model on OpenRouter.

OpenRouter speaks the OpenAI chat-completions shape, so this is a single POST and needs no
SDK. `aiohttp` arrives with hikari, so nothing new is installed for it either.

The model ids that end in `:free` rot faster than anything else here - OpenRouter rotates
which models carry a free tier, and a retired id comes back as a 404 rather than as anything
descriptive. `OPENROUTER_MODEL` exists so that swapping one is an .env edit:
    https://openrouter.ai/models?q=free

This module knows nothing about Alfred's commands. The tools are passed in by the caller, so
what the client does is talk to a model - `alfred.chat.actions` decides what may be asked of
it, and `alfred.chat.completions` reads what comes back.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from typing import Final

import aiohttp
from loguru import logger

from alfred.chat import completions
from alfred.chat.completions import ChatError
from alfred.chat.completions import ToolCall
from alfred.chat.prompt import DEFAULT_SYSTEM_PROMPT
from alfred.config import ChatConfig
from alfred.ui.embeds import MAX_MESSAGE
from alfred.ui.embeds import Reply

API_URL: Final = "https://openrouter.ai/api/v1/chat/completions"

# Sent as `HTTP-Referer`/`X-Title`, which is how OpenRouter attributes requests on its public
# leaderboard. Neither is required, and neither affects whether a request is served.
REFERER: Final = "https://nauqh.github.io/alfred/"
APP_TITLE: Final = "Alfred"

# The API wants a tool call and its result tied together by id. Only one call is ever in
# flight, and the pair is built and sent in a single request, so a constant does the job.
TOOL_CALL_ID: Final = "alfred-action"


class ChatClient:
    """A thin OpenRouter client, holding one session for the life of the bot."""

    def __init__(self, config: ChatConfig) -> None:
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self.system_prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT

    @property
    def model(self) -> str:
        """The OpenRouter model id being asked, for the embed footer."""
        return self._config.model

    async def start(self) -> None:
        """Open the HTTP session. Connections are pooled across replies rather than per-call."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._config.timeout),
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "HTTP-Referer": REFERER,
                    "X-Title": APP_TITLE,
                },
            )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _post(self, turns: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None) -> Any:
        """
        Send one chat-completions request and return the decoded body.

        Args:
            turns: Everything after the system prompt.
            tools: Whether to offer the tools. Off for the confirmation round trip, where the
                action has already run - offering them again invites the model to run it twice.

        Raises:
            ChatError: On a transport failure or a non-200 response.
        """
        if self._session is None or self._session.closed:
            await self.start()
        assert self._session is not None

        # `response_format: json_object` is deliberately not sent. Support for it varies across
        # the providers OpenRouter fronts, and the ones that do not support it answer 400 rather
        # than ignoring it - which would make every free model a coin toss. The prompt asks for
        # JSON and `parse_reply` copes when it does not arrive.
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [{"role": "system", "content": self.system_prompt}, *turns],
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            # Several of the free models are reasoning models, and a reasoning model's thinking
            # is content unless you say otherwise - the first version of this posted a model's
            # entire "Here's a thinking process:" monologue into the channel as the answer.
            # `exclude` keeps the thinking (the answers are better for it) and drops it from the
            # response, where it arrives in `message.reasoning` rather than `message.content`.
            # OpenRouter drops parameters a model does not support, so this is safe to always
            # send - unlike `response_format`, which 400s on the providers that lack it.
            "reasoning": {"exclude": True},
        }
        if tools:
            payload["tools"] = tools

        logger.info(
            "Asking {} with {} turn(s), max_tokens={}{}",
            self._config.model,
            len(turns),
            self._config.max_tokens,
            "" if tools else " (confirming, no tools)",
        )
        logger.debug("Prompt turns: {}", turns)

        try:
            async with self._session.post(API_URL, json=payload) as response:
                body = await response.text()
                if response.status != 200:
                    raise ChatError(f"OpenRouter answered {response.status}: {body[:300]}")
                return await response.json(content_type=None)
        except asyncio.TimeoutError as e:
            raise ChatError(f"OpenRouter did not answer within {self._config.timeout:g}s") from e
        except aiohttp.ClientError as e:
            raise ChatError(f"Could not reach OpenRouter: {e}") from e

    async def confirm(self, turns: list[dict[str, str]], call: ToolCall, summary: str) -> str:
        """
        Ask the model to confirm, in its own voice, an action that has already run.

        A second round trip - the model returns no text of its own alongside a tool call, so
        without this an action is silent. Measured at 1.5-3.3s on the default model, on top of
        the call that chose the action.

        Args:
            turns: The turns that produced the tool call.
            call: The action that ran.
            summary: What it did, from `alfred.actions`.

        Returns:
            One line to post. Falls back to `summary` itself if the model cannot be reached -
            the action already happened, so staying silent about it is the one wrong answer.
        """
        # The tool result is fed back in the shape the API expects, which is what lets the model
        # answer as though it had done the thing rather than been told about it.
        followed = [
            *turns,
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": TOOL_CALL_ID,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": TOOL_CALL_ID, "name": call.name, "content": summary},
        ]

        try:
            data = await self._post(followed, tools=None)
            return completions.clamp(completions.strip_thinking(completions.extract_content(data)), MAX_MESSAGE)
        except ChatError as e:
            logger.warning("Could not get a confirmation for {!r}, using the summary: {}", call.name, e)
            return summary

    async def complete(self, turns: list[dict[str, str]], tools: list[dict[str, Any]]) -> Reply | ToolCall:
        """
        Ask the model to answer, given the system prompt and `turns`.

        Returns:
            A `ToolCall` when the model wants to run one of Alfred's commands, and a `Reply`
            when it is answering in words. A tool call is a proposal - `alfred.actions` decides
            whether it runs.

        Raises:
            ChatError: On a transport failure, a non-200 response, or an empty completion.
        """
        started = time.monotonic()
        data = await self._post(turns, tools=tools)
        elapsed = time.monotonic() - started

        # Checked before the content is, because a model making a tool call leaves `content`
        # empty or as a couple of newlines - reading it first would raise on an empty
        # completion for what is actually the successful path.
        call = completions.tool_call(data)
        if call is not None:
            logger.info(
                "{} asked to run {!r} in {:.2f}s, args {} - {}",
                self._config.model,
                call.name,
                elapsed,
                call.arguments,
                completions.usage(data),
            )
            return call

        content = completions.extract_content(data)
        # The raw completion is what explains a reply that came out plain when an embed was
        # wanted, or vice versa - the parse below is deterministic, so this is the only part
        # worth keeping when the output is wrong.
        logger.debug("Raw completion ({} chars): {}", len(content), content)

        if completions.finish_reason(data) == "length":
            # The answer stops mid-sentence. Worth a warning rather than a silent shrug: it
            # means `CHAT_MAX_TOKENS` is too low for this model, not that anything is broken.
            logger.warning(
                "{} hit the {} token ceiling and was cut off - raise CHAT_MAX_TOKENS",
                self._config.model,
                self._config.max_tokens,
            )

        reply = completions.parse_reply(content)
        logger.info(
            "{} answered in {:.2f}s as {} - {} chars, {} field(s), {}",
            self._config.model,
            elapsed,
            "an embed" if reply.is_embed else "plain text",
            len(reply.description),
            len(reply.fields),
            completions.usage(data),
        )
        return reply
