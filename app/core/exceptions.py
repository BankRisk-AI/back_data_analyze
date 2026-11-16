"""Errors that every module can raise. The API layer turns them into application/problem+json (RFC 9457) without knowing the module."""


class AppError(Exception):
    """Base of every refusal. `kind` is the stable problem type, `status` the HTTP status, `title` the short human title."""

    kind = "error"
    status = 500
    title = "Error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail


class NotFoundError(AppError):
    kind = "not-found"
    status = 404
    title = "Not found"


class InvalidParameter(AppError):
    kind = "invalid-parameter"
    status = 422
    title = "Invalid parameter"


class BadRequestError(AppError):
    kind = "bad-request"
    status = 400
    title = "Bad request"
