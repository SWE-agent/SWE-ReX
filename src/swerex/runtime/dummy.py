import logging
from typing import Any

from typing_extensions import Self

from swerex.exceptions import DummyOutputsExhaustedError
from swerex.runtime.abstract import (
    AbstractRuntime,
    Action,
    BashObservation,
    CloseBashSessionResponse,
    CloseResponse,
    CloseSessionRequest,
    CloseSessionResponse,
    Command,
    CommandResponse,
    CreateBashSessionResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    IsAliveResponse,
    Observation,
    ReadFileRequest,
    ReadFileResponse,
    UploadRequest,
    UploadResponse,
    WriteFileRequest,
    WriteFileResponse,
)
from swerex.runtime.config import DummyRuntimeConfig
from swerex.utils.log import get_logger


class DummyRuntime(AbstractRuntime):
    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        """This runtime returns blank or predefined outputs.
        Useful for testing.

        Args:
            **kwargs: Keyword arguments (see `DummyRuntimeConfig` for details).
        """
        self.run_in_session_outputs: list[BashObservation] | BashObservation = BashObservation(exit_code=0)
        """Predefine returns of run_in_session. If set to list, will pop from list, else will 
        return the same value.
        """
        self._config = DummyRuntimeConfig(**kwargs)
        self.logger = logger or get_logger("rex-runtime")

    @classmethod
    def from_config(cls, config: DummyRuntimeConfig) -> Self:
        return cls(**config.model_dump())

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        return IsAliveResponse(is_alive=True)

    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        if request.session_type == "bash":
            return CreateBashSessionResponse()
        msg = f"Unknown session type: {request.session_type}"
        raise ValueError(msg)

    async def run_in_session(self, action: Action) -> Observation:
        if isinstance(self.run_in_session_outputs, list):
            try:
                return self.run_in_session_outputs.pop(0)
            except IndexError:
                msg = f"Dummy runtime's run_in_session_outputs list is empty: No output for {action.command!r}"
                raise DummyOutputsExhaustedError(msg) from None
        return self.run_in_session_outputs

    async def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
        if request.session_type == "bash":
            return CloseBashSessionResponse()
        msg = f"Unknown session type: {request.session_type}"
        raise ValueError(msg)

    async def execute(self, command: Command) -> CommandResponse:
        return CommandResponse(stdout="", stderr="", exit_code=0)

    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        return ReadFileResponse()

    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        return WriteFileResponse()

    async def upload(self, request: UploadRequest) -> UploadResponse:
        return UploadResponse()

    async def close(self) -> CloseResponse:
        return CloseResponse()
