class BadInputError(ValueError):
    """→ 400."""


class NotFoundError(LookupError):
    """→ 404."""


class ConflictError(FileExistsError):
    """→ 409."""


class ForbiddenError(PermissionError):
    """Знаю кто ты, нельзя. → 403."""


class RateLimitError(Exception):
    """→ 429."""
