"""Errors the professor can act on."""


class ProfassistError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


def require_same_tenant(row_org: object, request_org: object) -> None:
    """Hide another tenant's row. Callers turn this into a not-found response."""
    if row_org != request_org:
        raise ProfassistError(404, "Not found in this workspace")
