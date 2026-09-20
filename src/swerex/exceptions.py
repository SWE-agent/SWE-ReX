from typing import Any


class SwerexException(Exception):
    """Any exception that is raised by SWE-Rex."""


class TruncatedUnicodeDecodeError(UnicodeDecodeError):
    """A remote decode error with bounded byte context, still catchable as UnicodeDecodeError.

    ``object`` is only a window of the original decoder object. ``start`` and ``end``
    index the retained portion of the failure within that window. ``original_start``
    and ``original_end`` preserve the original error span (end exclusive), while
    ``object_offset`` and ``object_length`` identify the window and original length.
    The encoding and reason are unchanged; args and str differ from the local error.
    """

    def __init__(self, encoding, object, start, end, reason, *, object_offset: int, object_length: int):
        super().__init__(encoding, object, start - object_offset, min(end - object_offset, len(object)), reason)
        self.original_start = start
        self.original_end = end
        self.object_offset = object_offset
        self.object_length = object_length

    def __str__(self):
        return (
            f"{super().__str__()} [truncated byte context; original byte span "
            f"[{self.original_start}, {self.original_end}) in an object of {self.object_length} bytes; "
            f"context offset {self.object_offset}]"
        )


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


class CommandTimeoutError(SwerexException, RuntimeError, TimeoutError): ...


class NoExitCodeError(SwerexException, RuntimeError): ...


class SessionExistsError(SwerexException, ValueError): ...


class SessionDoesNotExistError(SwerexException, ValueError): ...


class DeploymentNotStartedError(SwerexException, RuntimeError):
    def __init__(self, message="Deployment not started"):
        super().__init__(message)


class DeploymentStartupError(SwerexException, RuntimeError): ...


class DockerPullError(DeploymentStartupError): ...


class DummyOutputsExhaustedError(SwerexException, RuntimeError):
    """Raised if we try to pop from the dummy runtime's run_in_session_outputs list, but it's empty."""
