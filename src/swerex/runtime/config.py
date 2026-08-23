from typing import Literal

from pydantic import BaseModel, ConfigDict

from swerex.runtime.abstract import AbstractRuntime


class LocalRuntimeConfig(BaseModel):
    """Configuration for a local runtime."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["local"] = "local"
    """Discriminator for (de)serialization/CLI. Do not change."""

    def get_runtime(self) -> AbstractRuntime:
        from swerex.runtime.local import LocalRuntime

        return LocalRuntime.from_config(self)


class RemoteRuntimeConfig(BaseModel):
    auth_token: str
    """The token to use for authentication."""
    host: str = "http://127.0.0.1"
    """The host to connect to."""
    port: int | None = None
    """The port to connect to."""
    timeout: float = 0.15
    """The timeout for the runtime."""
    num_retries: int = 3
    """How many times to retry a request that failed with a transport-level error.

    Retries reuse the request's `X-Request-ID`, so the server returns the original
    response instead of executing the action a second time. Set to 0 to disable.
    """

    type: Literal["remote"] = "remote"
    """Discriminator for (de)serialization/CLI. Do not change."""

    model_config = ConfigDict(extra="forbid")

    def get_runtime(self) -> AbstractRuntime:
        from swerex.runtime.remote import RemoteRuntime

        return RemoteRuntime.from_config(self)


class DummyRuntimeConfig(BaseModel):
    """Configuration for a dummy runtime."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["dummy"] = "dummy"
    """Discriminator for (de)serialization/CLI. Do not change."""

    def get_runtime(self) -> AbstractRuntime:
        from swerex.runtime.dummy import DummyRuntime

        return DummyRuntime.from_config(self)


RuntimeConfig = LocalRuntimeConfig | RemoteRuntimeConfig | DummyRuntimeConfig


def get_runtime(config: RuntimeConfig) -> AbstractRuntime:
    return config.get_runtime()
