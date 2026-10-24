from fastapi import HTTPException


class CodedHTTPError(HTTPException):
    """An error whose body also carries a machine-readable `code` (and any `extra` fields), so the
    staff app can pick the dialog without parsing `detail`; see its handler in `main.py`."""

    def __init__(self, status_code: int, detail: str, code: str, **extra: object) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
        self.extra = extra
