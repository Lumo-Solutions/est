from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class AppError(Exception):
    """Base for application errors rendered as RFC 9457 problem+json."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_type: str = "about:blank"
    title: str = "Application error"

    def __init__(self, detail: str, **extra: object) -> None:
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    error_type = "urn:installtec:not-found"
    title = "Resource not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    error_type = "urn:installtec:conflict"
    title = "Conflict"


class DuplicateVendorError(ConflictError):
    error_type = "urn:installtec:duplicate-vendor"
    title = "Likely duplicate vendor"


class ValidationAppError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_type = "urn:installtec:validation-error"
    title = "Validation error"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_type = "urn:installtec:unauthorized"
    title = "Authentication required"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    error_type = "urn:installtec:forbidden"
    title = "Not authorized"


class StepUpRequiredError(ForbiddenError):
    error_type = "urn:installtec:step-up-required"
    title = "Re-authentication (MFA step-up) required"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    body = {
        "type": exc.error_type,
        "title": exc.title,
        "status": exc.status_code,
        "detail": exc.detail,
        "instance": str(request.url.path),
        **exc.extra,
    }
    return JSONResponse(status_code=exc.status_code, content=body, media_type="application/problem+json")


_INTEGRITY_ERROR_PATTERNS = (
    ("UniqueViolationError", status.HTTP_409_CONFLICT, "urn:installtec:conflict", "Conflict",
     "This record conflicts with an existing one (duplicate key)."),
    ("ForeignKeyViolationError", status.HTTP_422_UNPROCESSABLE_CONTENT, "urn:installtec:invalid-reference",
     "Invalid reference", "This request refers to a record that does not exist."),
    ("ExclusionViolationError", status.HTTP_409_CONFLICT, "urn:installtec:conflict", "Conflict",
     "This record overlaps with an existing one for the same key/period."),
    ("CheckViolationError", status.HTTP_422_UNPROCESSABLE_CONTENT, "urn:installtec:validation-error",
     "Validation error", "This request violates a data constraint."),
)


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Translates the Postgres constraint violations every service can hit
    (unique/exclusion/FK/check) into RFC 9457 responses instead of a bare
    500 -- see docs/security-rls.md's note on this handler for why it lives
    here rather than being caught ad hoc in every service function."""
    cause_name = type(exc.orig.__cause__).__name__ if exc.orig is not None and exc.orig.__cause__ else ""
    for marker, status_code, error_type, title, detail in _INTEGRITY_ERROR_PATTERNS:
        if marker in cause_name or marker in str(exc.orig):
            return JSONResponse(
                status_code=status_code,
                media_type="application/problem+json",
                content={
                    "type": error_type,
                    "title": title,
                    "status": status_code,
                    "detail": detail,
                    "instance": str(request.url.path),
                },
            )
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        media_type="application/problem+json",
        content={
            "type": "urn:installtec:conflict",
            "title": "Conflict",
            "status": status.HTTP_409_CONFLICT,
            "detail": "This request violates a database constraint.",
            "instance": str(request.url.path),
        },
    )
