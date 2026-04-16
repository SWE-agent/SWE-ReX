"""Daytona Runtime - SDK-based runtime for Daytona sandboxes.

This runtime communicates with the swerex server running inside a Daytona sandbox
by using the Daytona SDK's command execution capabilities instead of HTTP requests.
This bypasses the OAuth authentication issues with Preview URLs.
"""

import json
import logging
import shlex
from typing import Any

from daytona_sdk import SessionExecuteRequest
from pydantic import BaseModel
from typing_extensions import Self

from swerex.runtime.abstract import (
    AbstractRuntime,
    Action,
    CloseResponse,
    CloseSessionRequest,
    CloseSessionResponse,
    Command,
    CommandResponse,
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
from swerex.runtime.config import RemoteRuntimeConfig
from swerex.utils.log import get_logger

__all__ = ["DaytonaRuntime", "DaytonaRuntimeConfig"]


class DaytonaRuntimeConfig(RemoteRuntimeConfig):
    """Configuration for DaytonaRuntime.
    
    Inherits from RemoteRuntimeConfig for compatibility but uses SDK
    instead of HTTP for communication.
    """
    
    # Override port to be optional since we don't use it for HTTP
    port: int | None = None


class DaytonaRuntime(AbstractRuntime):
    """Runtime that communicates with swerex server inside a Daytona sandbox via SDK.
    
    Instead of making HTTP requests to the swerex server, this runtime uses the
    Daytona SDK's command execution to run curl inside the sandbox, which then
    communicates with the swerex server running on localhost:8000.
    
    This bypasses OAuth authentication issues with Preview URLs.
    """
    
    def __init__(
        self,
        *,
        sandbox: Any = None,
        session_id: str = "swerex-runtime",
        auth_token: str = "",
        port: int = 8000,
        logger: logging.Logger | None = None,
        **kwargs: Any,
    ):
        """Initialize the Daytona runtime.
        
        Args:
            sandbox: The Daytona sandbox object.
            session_id: The session ID to use for command execution.
            auth_token: The authentication token for the swerex server.
            port: The port the swerex server is running on inside the sandbox.
            logger: Optional logger instance.
        """
        self._sandbox = sandbox
        self._session_id = session_id
        self._auth_token = auth_token
        self._port = port
        self.logger = logger or get_logger("rex-daytona-runtime")
        self._swerex_url = f"http://localhost:{self._port}"
    
    @classmethod
    def from_config(cls, config: DaytonaRuntimeConfig) -> Self:
        """Create from config. Note: sandbox must be set separately."""
        return cls(**config.model_dump())
    
    def _get_headers_json(self) -> str:
        """Get headers as JSON string for curl."""
        headers = {"X-API-Key": self._auth_token, "Content-Type": "application/json"}
        return json.dumps(headers)
    
    async def _execute_request(
        self,
        endpoint: str,
        payload: BaseModel | None = None,
        method: str = "POST",
        timeout: float = 60.0,
    ) -> dict:
        """Execute an HTTP request inside the sandbox to call the swerex API.
        
        Uses Python's urllib instead of curl to avoid dependency on curl.
        Uses base64 encoding to avoid quote escaping issues.
        
        Args:
            endpoint: The API endpoint (e.g., "run_in_session").
            payload: Optional request payload.
            method: HTTP method.
            timeout: Command timeout in seconds.
            
        Returns:
            The JSON response from the swerex server.
            
        Raises:
            RuntimeError: If the request fails or returns an error.
        """
        import base64
        
        url = f"{self._swerex_url}/{endpoint}"
        
        # Build Python command for HTTP request using base64 encoding
        if payload:
            payload_json = json.dumps(payload.model_dump())
            payload_b64 = base64.b64encode(payload_json.encode()).decode()
            data_line = f"data = base64.b64decode('{payload_b64}')"
        else:
            data_line = "data = None"
        
        # Write the script to a temp file and execute it
        # This avoids all escaping issues with shell commands
        script_content = f'''import urllib.request, urllib.error, json, base64, sys

url = '{url}'
method = '{method}'
timeout = {timeout}
auth_token = '{self._auth_token}'
{data_line}

req = urllib.request.Request(url, method=method, data=data)
req.add_header('Content-Type', 'application/json')
req.add_header('X-API-Key', auth_token)

try:
    resp = urllib.request.urlopen(req, timeout=timeout)
    result = {{"status": resp.status, "body": resp.read().decode()}}
except urllib.error.HTTPError as e:
    result = {{"status": e.code, "body": e.read().decode()}}
except Exception as e:
    result = {{"status": 500, "error": str(e)}}

print(json.dumps(result))
'''
        
        # Base64 encode the script to avoid any escaping issues
        script_b64 = base64.b64encode(script_content.encode()).decode()
        
        # Decode and execute the script
        python_cmd = f"echo '{script_b64}' | base64 -d | python"
        
        # Execute via SDK
        response = await self._sandbox.process.execute_session_command(
            self._session_id,
            SessionExecuteRequest(command=python_cmd, run_async=False),
        )
        
        # Get the output
        logs = await self._sandbox.process.get_session_command_logs(
            self._session_id, response.cmd_id
        )
        
        if response.exit_code != 0:
            self.logger.error(
                f"HTTP request failed with exit code {response.exit_code}: {logs.stderr}"
            )
            raise RuntimeError(f"Failed to call swerex API: {logs.stderr}")
        
        # Parse JSON response
        try:
            result = json.loads(logs.stdout.strip())
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON response: {logs.stdout}")
            raise RuntimeError(f"Invalid JSON response from swerex: {logs.stdout}") from e
        
        # Check for errors
        if "error" in result:
            raise RuntimeError(f"Request failed: {result['error']}")
        
        status = result.get("status", 200)
        body = result.get("body", "")
        
        # Handle HTTP errors
        if status >= 400:
            try:
                error_data = json.loads(body)
                # Check for swerexception (511 status)
                if "swerexception" in error_data:
                    exc_info = error_data["swerexception"]
                    self.logger.error(
                        f"swerex exception: {exc_info.get('message', 'Unknown error')}\n"
                        f"Traceback: {exc_info.get('traceback', 'N/A')}"
                    )
                    raise RuntimeError(
                        f"swerex exception: {exc_info.get('message', 'Unknown error')}"
                    )
                raise RuntimeError(f"HTTP {status}: {error_data}")
            except json.JSONDecodeError:
                raise RuntimeError(f"HTTP {status}: {body}")
        
        # Parse the actual response body
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse response body: {body}")
            raise RuntimeError(f"Invalid JSON response body: {body}") from e
    
    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive."""
        try:
            # Use Python urllib for health check (more reliable than curl)
            health_cmd = (
                f"python -c \""
                f"import urllib.request; "
                f"req = urllib.request.Request('{self._swerex_url}/is_alive'); "
                f"req.add_header('X-API-Key', '{self._auth_token}'); "
                f"resp = urllib.request.urlopen(req, timeout=5); "
                f"print(resp.read().decode())"
                f"\""
            )
            
            response = await self._sandbox.process.execute_session_command(
                self._session_id,
                SessionExecuteRequest(command=health_cmd, run_async=False),
            )
            
            if response.exit_code == 0:
                logs = await self._sandbox.process.get_session_command_logs(
                    self._session_id, response.cmd_id
                )
                data = json.loads(logs.stdout.strip())
                return IsAliveResponse(**data)
            else:
                return IsAliveResponse(
                    is_alive=False, 
                    message=f"Health check failed with exit code {response.exit_code}"
                )
        except Exception as e:
            return IsAliveResponse(is_alive=False, message=str(e))
    
    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        """Creates a new session."""
        data = await self._execute_request("create_session", request)
        return CreateSessionResponse(**data)
    
    async def run_in_session(self, action: Action) -> Observation:
        """Runs a command in a session."""
        data = await self._execute_request("run_in_session", action)
        return Observation(**data)
    
    async def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
        """Closes a shell session."""
        data = await self._execute_request("close_session", request)
        return CloseSessionResponse(**data)
    
    async def execute(self, command: Command) -> CommandResponse:
        """Executes a command (independent of any shell session)."""
        data = await self._execute_request("execute", command)
        return CommandResponse(**data)
    
    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        """Reads a file."""
        data = await self._execute_request("read_file", request)
        return ReadFileResponse(**data)
    
    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        """Writes a file."""
        data = await self._execute_request("write_file", request)
        return WriteFileResponse(**data)
    
    async def upload(self, request: UploadRequest) -> UploadResponse:
        """Uploads a file.
        
        Note: This is a simplified implementation that uses base64 encoding
        to transfer file content through the SDK command execution.
        """
        import base64
        from pathlib import Path
        
        source = Path(request.source_path).resolve()
        
        if source.is_dir():
            # For directories, create a tar and transfer
            import tempfile
            import tarfile
            
            with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
                with tarfile.open(tmp.name, "w") as tar:
                    tar.add(source, arcname=source.name)
                
                with open(tmp.name, "rb") as f:
                    content = f.read()
            
            # Encode and transfer
            encoded = base64.b64encode(content).decode()
            transfer_cmd = (
                f"mkdir -p {shlex.quote(request.target_path)} && "
                f"echo '{encoded}' | base64 -d | tar -x -C {shlex.quote(request.target_path)}"
            )
        elif source.is_file():
            # For files, use base64 encoding
            with open(source, "rb") as f:
                content = f.read()
            
            encoded = base64.b64encode(content).decode()
            transfer_cmd = (
                f"mkdir -p {shlex.quote(str(Path(request.target_path).parent))} && "
                f"echo '{encoded}' | base64 -d > {shlex.quote(request.target_path)}"
            )
        else:
            raise ValueError(f"Source path {source} is not a file or directory")
        
        response = await self._sandbox.process.execute_session_command(
            self._session_id,
            SessionExecuteRequest(command=transfer_cmd, run_async=False),
        )
        
        if response.exit_code != 0:
            logs = await self._sandbox.process.get_session_command_logs(
                self._session_id, response.cmd_id
            )
            raise RuntimeError(f"Upload failed: {logs.stderr}")
        
        return UploadResponse()
    
    async def close(self) -> CloseResponse:
        """Closes the runtime."""
        try:
            await self._execute_request("close", None)
        except Exception as e:
            self.logger.warning(f"Error closing swerex server: {e}")
        return CloseResponse()
