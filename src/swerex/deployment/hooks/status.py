from collections.abc import Callable

from swerex.deployment.hooks.abstract import DeploymentHook


class SetStatusDeploymentHook(DeploymentHook):
    def __init__(self, id: str, callable: Callable[[str, str], None]):
        self._callable = callable
        self._id = id

    def _update(self, message: str):
        self._callable(self._id, message)  # type: ignore

    def on_custom_step(self, message: str):
        self._update(message)
