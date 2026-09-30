"""Shared provider failure with the original evidence attached."""


class FetchError(ValueError):
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload or {"mock": False, "error": message}
