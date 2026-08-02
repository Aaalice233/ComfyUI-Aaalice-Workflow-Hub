from __future__ import annotations

class UserFacingError(ValueError):
    """An actionable error whose wording belongs to the frontend dictionary."""

    def __init__(self, code: str, params: dict[str, str | int] | None = None) -> None:
        self.code = code
        self.params: dict[str, str | int] = params or {}
        super().__init__(code)
