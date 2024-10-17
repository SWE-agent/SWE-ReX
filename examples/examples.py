#!/usr/bin/env python3

from swerex.models import (
    Action,
    CloseRequest,
    CreateShellRequest,
)
from swerex.runtime.remote import RemoteRuntime

if __name__ == "__main__":
    runtime = RemoteRuntime("http://localhost:8000")
    # fmt: off
    print(runtime.is_alive())
    print(runtime.create_shell(CreateShellRequest()))
    print(runtime.run_in_shell( Action( command="doesnexist",)))
    print(runtime.run_in_shell( Action( command="ls",)))
    print(runtime.run_in_shell(Action(command="python", is_interactive_command=True, expect=[">>> "])))
    print(runtime.run_in_shell(Action(command="print('hello world')", is_interactive_command=True, expect=[">>> "])))
    print(runtime.run_in_shell(Action(command="quit()\n", is_interactive_quit=True)))
    print(runtime.run_in_shell( Action( command="echo 'test'",)))
    print(runtime.run_in_shell( Action( command="echo 'answer'",)))
    print(runtime.run_in_shell( Action( command="doesnexist",)))
    print(runtime.close_shell(CloseRequest()))
    # fmt: on
