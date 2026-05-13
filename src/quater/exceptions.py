"""Framework exceptions."""

from __future__ import annotations


class QuaterError(Exception):
    """Base class for Quater framework errors."""


class ConfigurationError(QuaterError, ValueError):
    """Raised when app configuration is invalid."""


class LifespanStateError(QuaterError, RuntimeError):
    """Raised when lifespan hooks are mutated or run in an invalid state."""


class HTTPError(QuaterError):
    """Exception converted into an HTTP-style error response.

    Raise it from handlers, middleware, or auth-adjacent code when you want a
    specific status code and client-facing detail.
    """

    status_code = 500
    detail = "Internal Server Error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        status_code: int | None = None,
    ) -> None:
        self.status_code = self.status_code if status_code is None else status_code
        self.detail = self.detail if detail is None else detail
        super().__init__(self.detail)


class BadRequestError(HTTPError):
    """Raised when request data cannot be parsed."""

    status_code = 400
    detail = "Bad Request"


class RequestJSONError(BadRequestError):
    """Raised when a request body is not valid JSON."""

    detail = "Malformed JSON body"


class PayloadTooLargeError(HTTPError):
    """Raised when a request body exceeds the configured limit."""

    status_code = 413
    detail = "Payload Too Large"


class UnauthorizedError(HTTPError):
    """Raised when a configured auth hook does not authenticate the request."""

    status_code = 401
    detail = "Unauthorized"


class ResponseConversionError(QuaterError, TypeError):
    """Raised when a handler return value cannot become a response."""


class RouteError(QuaterError):
    """Base class for route registration and dispatch errors."""


class RouteConflictError(RouteError):
    """Raised when two routes cannot be compiled together."""


class RouteBindingError(RouteError):
    """Raised when a handler signature cannot be bound to request data."""


class MiddlewareStateError(QuaterError, RuntimeError):
    """Raised when middleware is registered after the pipeline is compiled."""
