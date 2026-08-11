#!/usr/bin/env python3

import argparse
import asyncio
import shutil
import tempfile
import traceback
import zipfile
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from swerex import __version__
from swerex.runtime.abstract import (
    Action,
    CloseResponse,
    CloseSessionRequest,
    Command,
    CreateSessionRequest,
    ReadFileRequest,
    UploadResponse,
    WriteFileRequest,
    _ExceptionTransfer,
)
from swerex.runtime.local import LocalRuntime

app = FastAPI()
runtime = LocalRuntime()

AUTH_TOKEN = ""
api_key_header = APIKeyHeader(name="X-API-Key")


def serialize_model(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


class ResponseManager:
    """Deduplicates requests by their idempotency key (`X-Request-ID` header)
    so that client retries never execute a request twice.

    Responses of completed requests are kept in a bounded LRU cache. Requests
    that are still executing are tracked separately, so that a duplicate
    arriving while the original is in flight waits for the original's response
    instead of executing the request again.
    """

    def __init__(self, max_entries: int = 256):
        self._max_entries = max_entries
        self._completed: OrderedDict[str, Response] = OrderedDict()
        self._in_flight: dict[str, asyncio.Future] = {}

    def get_completed(self, request_id: str) -> Response | None:
        response = self._completed.get(request_id)
        if response is not None:
            self._completed.move_to_end(request_id)
        return response

    def get_in_flight(self, request_id: str) -> asyncio.Future | None:
        return self._in_flight.get(request_id)

    def start(self, request_id: str) -> None:
        self._in_flight[request_id] = asyncio.get_running_loop().create_future()

    def finish(self, request_id: str, response: Response) -> None:
        self._completed[request_id] = response
        if len(self._completed) > self._max_entries:
            self._completed.popitem(last=False)
        self._in_flight.pop(request_id).set_result(response)

    def fail(self, request_id: str, exc: BaseException) -> None:
        future = self._in_flight.pop(request_id)
        future.set_exception(exc)
        # Mark the exception as retrieved so that a duplicate-free failure
        # doesn't emit an "exception was never retrieved" warning.
        future.exception()


response_manager = ResponseManager()


@app.middleware("http")
async def authenticate(request: Request, call_next):
    """Authenticate requests with an API key (if set)."""
    if AUTH_TOKEN:
        api_key = await api_key_header(request)
        if api_key != AUTH_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid API Key")
    return await call_next(request)


@app.middleware("http")
async def handle_request_id(request: Request, call_next):
    """Handle request ID for idempotency."""
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        return await call_next(request)

    cached = response_manager.get_completed(request_id)
    if cached is not None:
        return cached

    in_flight = response_manager.get_in_flight(request_id)
    if in_flight is not None:
        # A duplicate of a request that is still executing (e.g., the client
        # timed out and retried): wait for the original instead of executing
        # the request a second time. Shielded so that the duplicate's
        # disconnect cannot cancel the shared future.
        return await asyncio.shield(in_flight)

    response_manager.start(request_id)
    try:
        response = await call_next(request)
        body_content = b""
        async for chunk in response.body_iterator:
            body_content += chunk
        new_response = Response(
            content=body_content,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
    except BaseException as exc:
        # Failed executions are not cached: any waiting duplicate fails too,
        # and a later retry executes the request again.
        response_manager.fail(request_id, exc)
        raise
    response_manager.finish(request_id, new_response)
    return new_response


@app.exception_handler(Exception)
async def exception_handler(request: Request, exc: Exception):
    """We catch exceptions that are thrown by the runtime, serialize them to JSON and
    return them to the client so they can reraise them in their own code.
    """
    if isinstance(exc, HTTPException | StarletteHTTPException):
        return await http_exception_handler(request, exc)
    extra_info = getattr(exc, "extra_info", {})
    _exc = _ExceptionTransfer(
        message=str(exc),
        class_path=type(exc).__module__ + "." + type(exc).__name__,
        traceback=traceback.format_exc(),
        extra_info=extra_info,
    )
    return JSONResponse(status_code=511, content={"swerexception": _exc.model_dump()})


@app.get("/")
async def root():
    return {"message": "hello world"}


@app.get("/is_alive")
async def is_alive():
    return serialize_model(await runtime.is_alive())


@app.post("/create_session")
async def create_session(request: CreateSessionRequest):
    return serialize_model(await runtime.create_session(request))


@app.post("/run_in_session")
async def run(action: Action):
    return serialize_model(await runtime.run_in_session(action))


@app.post("/close_session")
async def close_session(request: CloseSessionRequest):
    return serialize_model(await runtime.close_session(request))


@app.post("/execute")
async def execute(command: Command):
    return serialize_model(await runtime.execute(command))


@app.post("/read_file")
async def read_file(request: ReadFileRequest):
    return serialize_model(await runtime.read_file(request))


@app.post("/write_file")
async def write_file(request: WriteFileRequest):
    return serialize_model(await runtime.write_file(request))


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    target_path: str = Form(...),  # type: ignore
    unzip: bool = Form(False),
):
    target_path: Path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # First save the file to a temporary directory and potentially unzip it.
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = Path(temp_dir) / "temp_file_transfer"
        try:
            with open(file_path, "wb") as f:
                f.write(await file.read())
        finally:
            await file.close()
        if unzip:
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                zip_ref.extractall(target_path)
            file_path.unlink()
        else:
            shutil.move(file_path, target_path)
    return UploadResponse()


@app.post("/close")
async def close():
    await runtime.close()
    return CloseResponse()


def main():
    import uvicorn

    # First parser just for version checking
    version_parser = argparse.ArgumentParser(add_help=False)
    version_parser.add_argument("-v", "--version", action="store_true")
    version_args, remaining_args = version_parser.parse_known_args()

    if version_args.version:
        if remaining_args:
            print("Error: --version cannot be combined with other arguments")
            exit(1)
        print(__version__)
        return

    # Main parser for other arguments
    parser = argparse.ArgumentParser(description="Run the SWE-ReX server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    parser.add_argument("--auth-token", default="", help="token to authenticate requests", required=True)

    args = parser.parse_args(remaining_args)
    global AUTH_TOKEN
    AUTH_TOKEN = args.auth_token
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
