"""Framework exceptions."""

from __future__ import annotations


class QuaterError(Exception):
    """Base class for Quater framework errors."""


class ImproperlyConfigured(QuaterError, ValueError):
    """Raised when Quater detects setup that cannot run correctly."""


class ConfigurationError(ImproperlyConfigured):
    """Backward-compatible name for invalid framework configuration."""


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


class RequestFormError(BadRequestError):
    """Raised when a request body is not valid form data."""

    detail = "Malformed form body"


class PayloadTooLargeError(HTTPError):
    """Raised when a request body exceeds the configured limit."""

    status_code = 413
    detail = "Payload Too Large"


class UnsupportedMediaTypeError(HTTPError):
    """Raised when the request content type cannot satisfy the handler."""

    status_code = 415
    detail = "Unsupported Media Type"


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


__all__ = [
    "BadRequestError",
    "ConfigurationError",
    "HTTPError",
    "ImproperlyConfigured",
    "LifespanStateError",
    "MiddlewareStateError",
    "PayloadTooLargeError",
    "QuaterError",
    "RequestFormError",
    "RequestJSONError",
    "ResponseConversionError",
    "RouteBindingError",
    "RouteConflictError",
    "RouteError",
    "UnsupportedMediaTypeError",
    "UnauthorizedError",
]
