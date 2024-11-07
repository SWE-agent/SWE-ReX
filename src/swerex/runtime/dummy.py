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


class DummyRuntime(AbstractRuntime):
    """This runtime does nothing.
    Useful for testing.
    """

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        return IsAliveResponse(is_alive=True)

    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        if request.session_type == "bash":
            return CreateBashSessionResponse()
        msg = f"Unknown session type: {request.session_type}"
        raise ValueError(msg)

    async def run_in_session(self, action: Action) -> Observation:
        if action.session_type == "bash":
            return BashObservation(exit_code=0)
        msg = f"Unknown session type: {action.session_type}"
        raise ValueError(msg)

    async def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
        if request.session_type == "bash":
            return CloseBashSessionResponse()
        msg = f"Unknown session type: {request.session_type}"
        raise ValueError(msg)

    async def execute(self, command: Command) -> CommandResponse:
        return CommandResponse(exit_code=0)

    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        return ReadFileResponse()

    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        return WriteFileResponse()

    async def upload(self, request: UploadRequest) -> UploadResponse:
        return UploadResponse()

    async def close(self) -> CloseResponse:
        return CloseResponse()
