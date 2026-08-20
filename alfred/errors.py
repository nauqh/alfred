"""Errors raised by command checks and player operations.

Every error carries a message that is safe to show to the user - the error handler in
`alfred.bot` replies with it verbatim.
"""

from __future__ import annotations


class AlfredError(Exception):
    """Base class for errors with a user-facing message."""

    default_message = "Something went wrong."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class GuildOnly(AlfredError):
    default_message = "This command can only be used in a server."


class NotInVoice(AlfredError):
    default_message = "Join a voice channel to use this command."


class NotSameVoice(AlfredError):
    default_message = "Join the same voice channel as the bot to use this command."


class PlayerNotConnected(AlfredError):
    default_message = "The bot is not in a voice channel."


class PlayerNotPlaying(AlfredError):
    default_message = "Nothing is playing right now."


class NoResults(AlfredError):
    default_message = "No results for that query."


class NoNodesAvailable(AlfredError):
    default_message = "No Lavalink node is available - try again in a moment."
