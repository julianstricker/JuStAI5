"""Domain errors. The API layer maps them to HTTP responses with stable codes."""

from __future__ import annotations

from typing import Any


class JustAIError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str = "", *, code: str | None = None, **details: Any) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        self.details = details


class NotFound(JustAIError):
    status_code = 404
    code = "not_found"


class Conflict(JustAIError):
    status_code = 409
    code = "conflict"


class ValidationFailed(JustAIError):
    status_code = 422
    code = "validation_failed"


class Forbidden(JustAIError):
    status_code = 403
    code = "forbidden"


class Unauthorized(JustAIError):
    status_code = 401
    code = "unauthorized"


class TooManyRequests(JustAIError):
    status_code = 429
    code = "too_many_requests"


class Unavailable(JustAIError):
    status_code = 503
    code = "unavailable"


class RoutingDenied(Forbidden):
    """The Output Router refused an output target."""

    code = "routing_denied"


class PolicyViolation(Forbidden):
    """A privacy policy prevented an operation (e.g. cloud transfer of personal data)."""

    code = "policy_violation"
