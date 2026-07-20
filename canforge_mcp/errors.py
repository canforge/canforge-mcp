"""Typed errors that require explicit handling at the MCP boundary."""

from __future__ import annotations

from typing import Literal, TypedDict

UnparseableInputCode = Literal["unparseable_dbc", "unparseable_log"]


class UnparseableInputPayload(TypedDict):
    """Stable structured payload returned for terminal input parse failures."""

    code: UnparseableInputCode
    message: str
    retryable: Literal[False]
    recommended_action: str


class UnparseableInputError(ValueError):
    """A terminal parse failure that clients must report instead of retrying."""

    retryable: Literal[False] = False

    def __init__(
        self,
        *,
        code: UnparseableInputCode,
        message: str,
        recommended_action: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recommended_action = recommended_action

    def to_payload(self) -> UnparseableInputPayload:
        """Return the public MCP error payload."""
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "recommended_action": self.recommended_action,
        }


__all__ = [
    "UnparseableInputCode",
    "UnparseableInputError",
    "UnparseableInputPayload",
]
