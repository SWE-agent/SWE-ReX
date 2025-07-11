# SWE-ReX Library API Documentation

## Overview
SWE-ReX is a Python library for remote code execution and deployment management. It provides abstractions for running code in various environments including local, Docker, Modal, AWS Fargate, and remote servers.

## Installation
```bash
pip install swerex
```

## Core API

### Main Factory Function
```python
from swerex.deployment import get_deployment
from swerex.deployment.config import DeploymentConfig

def get_deployment(config: DeploymentConfig) -> AbstractDeployment
```
Factory function to create deployment instances based on configuration.

### Abstract Base Classes

#### AbstractDeployment
```python
from swerex.deployment.abstract import AbstractDeployment

class AbstractDeployment(ABC):
    async def is_alive(*, timeout: float | None = None) -> IsAliveResponse
    async def start(*args, **kwargs)
    async def stop(*args, **kwargs)
    @property
    def runtime -> AbstractRuntime
    def add_hook(hook: DeploymentHook)
```

#### AbstractRuntime
```python
from swerex.runtime.abstract import AbstractRuntime

class AbstractRuntime(ABC):
    async def is_alive(*, timeout: float | None = None) -> IsAliveResponse
    async def create_session(request: CreateSessionRequest) -> CreateSessionResponse
    async def run_in_session(action: Action) -> Observation
    async def close_session(request: CloseSessionRequest) -> CloseSessionResponse
    async def execute(command: Command) -> CommandResponse
    async def read_file(request: ReadFileRequest) -> ReadFileResponse
    async def write_file(request: WriteFileRequest) -> WriteFileResponse
    async def upload(request: UploadRequest) -> UploadResponse
    async def close() -> CloseResponse
```

## Deployment Types

### LocalDeployment
```python
from swerex.deployment.local import LocalDeployment
from swerex.deployment.config import LocalDeploymentConfig

config = LocalDeploymentConfig()
deployment = get_deployment(config)
```
Runs code locally on the host machine.

### DockerDeployment
```python
from swerex.deployment.docker import DockerDeployment
from swerex.deployment.config import DockerDeploymentConfig

config = DockerDeploymentConfig(
    image="python:3.11",
    port=8080,
    docker_args=["--rm"]
)
deployment = get_deployment(config)
```
Runs code in Docker containers with configurable images and ports.

### ModalDeployment
```python
from swerex.deployment.modal import ModalDeployment
from swerex.deployment.config import ModalDeploymentConfig

config = ModalDeploymentConfig(
    image="python:3.11",
    startup_timeout=300
)
deployment = get_deployment(config)
```
Deploys to Modal.com cloud platform.

### FargateDeployment
```python
from swerex.deployment.fargate import FargateDeployment
from swerex.deployment.config import FargateDeploymentConfig

config = FargateDeploymentConfig(
    # AWS configuration required
)
deployment = get_deployment(config)
```
Deploys to AWS Fargate.

### RemoteDeployment
```python
from swerex.deployment.remote import RemoteDeployment
from swerex.deployment.config import RemoteDeploymentConfig

config = RemoteDeploymentConfig(
    host="remote-server.com",
    port=8080
)
deployment = get_deployment(config)
```
Connects to existing SWE-ReX servers.

### DummyDeployment
```python
from swerex.deployment.dummy import DummyDeployment
from swerex.deployment.config import DummyDeploymentConfig

config = DummyDeploymentConfig(
    outputs=["output1", "output2"]
)
deployment = get_deployment(config)
```
Testing deployment with predefined outputs.

## Runtime Types

### LocalRuntime
```python
from swerex.runtime.local import LocalRuntime
```
Executes commands on local machine, manages bash sessions.

### RemoteRuntime
```python
from swerex.runtime.remote import RemoteRuntime
```
Connects to remote SWE-ReX servers via HTTP.

### DummyRuntime
```python
from swerex.runtime.dummy import DummyRuntime
```
Testing runtime with configurable outputs.

## Data Models

### Commands and Responses
```python
from swerex.runtime.abstract import (
    Command,
    CommandResponse,
    BashAction,
    BashObservation,
    CreateBashSessionRequest,
    CreateBashSessionResponse,
    CloseSessionRequest,
    CloseSessionResponse
)
```

### File Operations
```python
from swerex.runtime.abstract import (
    ReadFileRequest,
    ReadFileResponse,
    WriteFileRequest,
    WriteFileResponse,
    UploadRequest,
    UploadResponse
)
```

### Status
```python
from swerex.runtime.abstract import IsAliveResponse
```

## Exceptions

### Base Exception
```python
from swerex.exceptions import SwerexException
```

### Runtime Exceptions
```python
from swerex.exceptions import (
    SessionNotInitializedError,    # Shell session not initialized
    NonZeroExitCodeError,          # Command returned non-zero exit code
    BashIncorrectSyntaxError,      # Bash syntax errors
    CommandTimeoutError,           # Command execution timeout
    NoExitCodeError,              # No exit code available
    SessionExistsError,           # Session already exists
    SessionDoesNotExistError      # Session doesn\'t exist
)
```

### Deployment Exceptions
```python
from swerex.exceptions import (
    DeploymentNotStartedError,     # Deployment not started
    DeploymentStartupError,        # Deployment startup failed
    DockerPullError,              # Docker image pull failed
    DummyOutputsExhaustedError    # Dummy runtime outputs exhausted
)
```

## Utilities

### Logging
```python
from swerex.utils.log import get_logger

def get_logger(name: str, *, emoji: str = "🦖") -> logging.Logger
```
Get configured logger with rich formatting and emoji support.

### Port Management
```python
from swerex.utils.free_port import find_free_port

def find_free_port(max_attempts: int = 10, sleep_between_attempts: float = 0.1) -> int
```
Find an available port for network services.

## Usage Examples

### Basic Local Execution
```python
import asyncio
from swerex.deployment import get_deployment
from swerex.deployment.config import LocalDeploymentConfig
from swerex.runtime.abstract import Command

async def main():
    config = LocalDeploymentConfig()
    deployment = get_deployment(config)
    
    await deployment.start()
    runtime = deployment.runtime
    
    # Execute a command
    result = await runtime.execute(Command(command="echo \'Hello World\'"))
    print(result.stdout)
    
    await deployment.stop()

asyncio.run(main())
```

### Docker Deployment
```python
from swerex.deployment.config import DockerDeploymentConfig

config = DockerDeploymentConfig(
    image="python:3.11",
    port=8080
)
deployment = get_deployment(config)
await deployment.start()
# ... use deployment
await deployment.stop()
```

### Session Management
```python
from swerex.runtime.abstract import CreateBashSessionRequest, BashAction

# Create session
session_req = CreateBashSessionRequest(session="my_session")
await runtime.create_session(session_req)

# Run commands in session
action = BashAction(command="cd /tmp && ls", session="my_session")
result = await runtime.run_in_session(action)
print(result.output)
```

### File Operations
```python
from swerex.runtime.abstract import ReadFileRequest, WriteFileRequest

# Read file
read_req = ReadFileRequest(path="/path/to/file.txt")
response = await runtime.read_file(read_req)
print(response.content)

# Write file
write_req = WriteFileRequest(path="/path/to/output.txt", content="Hello World")
await runtime.write_file(write_req)
```

## Key Features

1. **Multiple Deployment Targets**: Local, Docker, Modal, AWS Fargate, Remote
2. **Session Management**: Persistent bash sessions with state
3. **File Operations**: Read, write, and upload files
4. **Async/Await Support**: Full async API
5. **Rich Logging**: Emoji-enhanced logging with threading support
6. **Error Handling**: Comprehensive exception hierarchy
7. **Configuration-Driven**: Pydantic-based configuration system

## Import Summary

- **Main factory**: `from swerex.deployment import get_deployment`
- **Deployments**: `from swerex.deployment.{local,docker,modal,fargate,remote,dummy}`
- **Runtimes**: `from swerex.runtime.{local,remote,dummy}`
- **Configs**: `from swerex.deployment.config import *Config`
- **Exceptions**: `from swerex.exceptions import *`
- **Utils**: `from swerex.utils.{log,free_port}`
- **Data Models**: `from swerex.runtime.abstract import *`
