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


class UnknownLevelError(ValueError):
    """Запрошенный level_id не существует. → 422.

    Сиблинг BadInputError (тоже ValueError), но со своим маппингом 422: FastAPI
    матчит обработчик по MRO самого исключения, на BadInputError не свалится."""

    def __init__(self, unknown_ids: list[str]) -> None:
        self.unknown_ids = unknown_ids
        super().__init__(f"Unknown level ids: {unknown_ids}")
