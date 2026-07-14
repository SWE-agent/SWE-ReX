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
    num_retries: int = 0
    """How often to retry requests that fail with connection errors.
    Retries reuse the same idempotency key (`X-Request-ID` header), so the server
    will not execute a request twice if it already processed it.
    This is useful for deployments that connect through the public internet
    (e.g., cloud sandboxes), where transient connection errors can occur.
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
