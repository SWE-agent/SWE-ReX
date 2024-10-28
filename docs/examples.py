import asyncio

from swerex.deployment.local import LocalDeployment
from swerex.runtime.abstract import BashAction as A
from swerex.runtime.abstract import (
    CloseSessionRequest,
    CreateSessionRequest,
)

deployment = LocalDeployment()
asyncio.run(deployment.start())
r = deployment.runtime
# fmt: off
print(r.is_alive())
print(r.create_session(CreateSessionRequest()))
print(r.run_in_session(A(command="doesnexist",)))
print(r.run_in_session(A(command="ls",)))
print(r.run_in_session(A(command="python", is_interactive_command=True, expect=[">>> "])))
print(r.run_in_session(A(command="print('hello world')", is_interactive_command=True, expect=[">>> "])))
print(r.run_in_session(A(command="quit()\n", is_interactive_quit=True)))
print(r.run_in_session(A(command="echo 'test'",)))
print(r.run_in_session(A(command="echo 'answer'",)))
print(r.run_in_session(A(command="doesnexist",)))
print(r.close_session(CloseSessionRequest()))
# fmt: on
