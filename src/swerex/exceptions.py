from typing import Any


class SwerexException(Exception):
    """Any exception that is raised by SWE-Rex."""


class SessionNotInitializedError(SwerexException, RuntimeError):
    """Raised if we try to run a command in a shell that is not initialized."""


class NonZeroExitCodeError(SwerexException, RuntimeError):
    """Can be raised if we execute a command in the shell and it has a non-zero exit code."""


class BashIncorrectSyntaxError(SwerexException, RuntimeError):
    """Before running a bash command, we check for syntax errors.
    This is the error message for those syntax errors.
    """

    def __init__(self, message: str, *, extra_info: dict[str, Any] = None):
        super().__init__(message)
        if extra_info is None:
            extra_info = {}
        self.extra_info = extra_info


class CommandTimeoutError(SwerexException, RuntimeError, TimeoutError):
    """Raised if a command times out. For commands in a shell session, `extra_info.get("output")`
    holds the output collected so far (the key is absent for other commands and older servers).
    """

    def __init__(self, message: str = "", *, extra_info: dict[str, Any] = None):
        super().__init__(message)
        if extra_info is None:
            extra_info = {}
        self.extra_info = extra_info


class NoExitCodeError(SwerexException, RuntimeError):
    """Raised if we can't get the exit code of a command in a shell session.
    `extra_info.get("output")` holds the output collected so far (the key is absent for older servers).
    """

    def __init__(self, message: str = "", *, extra_info: dict[str, Any] = None):
        super().__init__(message)
        if extra_info is None:
            extra_info = {}
        self.extra_info = extra_info


class SessionExistsError(SwerexException, ValueError): ...


class SessionDoesNotExistError(SwerexException, ValueError): ...


class DeploymentNotStartedError(SwerexException, RuntimeError):
    def __init__(self, message="Deployment not started"):
        super().__init__(message)


class DeploymentStartupError(SwerexException, RuntimeError): ...


class DockerPullError(DeploymentStartupError): ...


class DummyOutputsExhaustedError(SwerexException, RuntimeError):
    """Raised if we try to pop from the dummy runtime's run_in_session_outputs list, but it's empty."""
