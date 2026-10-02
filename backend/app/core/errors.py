"""One error type for everything the client is meant to read."""
from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found() -> ApiError:
    return ApiError(404, "not_found", "We couldn't find that.")


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}})
