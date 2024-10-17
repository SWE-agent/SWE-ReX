#!/usr/bin/env python3

from swerex.models import (
    A,
    CloseSessionRequest,
    CreateSessionRequest,
)
from swerex.runtime.remote import RemoteRuntime

if __name__ == "__main__":
    runtime = RemoteRuntime("http://localhost:8000")
    # fmt: off
    print(runtime.is_alive())
    print(runtime.create_session(CreateSessionRequest()))
    print(runtime.run_in_session( A( command="doesnexist",)))
    print(runtime.run_in_session( A( command="ls",)))
    print(runtime.run_in_session(A(command="python", is_interactive_command=True, expect=[">>> "])))
    print(runtime.run_in_session(A(command="print('hello world')", is_interactive_command=True, expect=[">>> "])))
    print(runtime.run_in_session(A(command="quit()\n", is_interactive_quit=True)))
    print(runtime.run_in_session( A( command="echo 'test'",)))
    print(runtime.run_in_session( A( command="echo 'answer'",)))
    print(runtime.run_in_session( A( command="doesnexist",)))
    print(runtime.close_session(CloseSessionRequest()))
    # fmt: on
