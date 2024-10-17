#!/usr/bin/env python3

import argparse

from fastapi import FastAPI

from swerex.models import (
    Action,
    CloseRequest,
    Command,
    CreateShellRequest,
    ReadFileRequest,
    WriteFileRequest,
)
from swerex.runtime.local import Runtime

app = FastAPI()
runtime = Runtime()


@app.get("/")
async def root():
    return {"message": "running"}


@app.post("/create_shell")
async def create_shell(request: CreateShellRequest):
    return (await runtime.create_shell(request)).model_dump()


@app.post("/run_in_shell")
async def run(action: Action):
    return (await runtime.run_in_shell(action)).model_dump()


@app.post("/close_shell")
async def close(request: CloseRequest):
    return (await runtime.close_shell(request)).model_dump()


@app.post("/execute")
async def execute(command: Command):
    return (await runtime.execute(command)).model_dump()


@app.post("/read_file")
async def read_file(request: ReadFileRequest):
    return (await runtime.read_file(request)).model_dump()


@app.post("/write_file")
async def write_file(request: WriteFileRequest):
    return (await runtime.write_file(request)).model_dump()


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the SWE-ReX FastAPI server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")

    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
