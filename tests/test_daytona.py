"""Unit tests for Daytona runtime and deployment.

Uses Mock to isolate external dependencies (Daytona SDK, network calls).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from swerex.deployment.config import DaytonaDeploymentConfig
from swerex.deployment.daytona import DaytonaDeployment
from swerex.runtime.abstract import (
    BashAction,
    CloseBashSessionRequest,
    Command,
    CreateBashSessionRequest,
    ReadFileRequest,
    WriteFileRequest,
)
from swerex.runtime.daytona import DaytonaRuntime, DaytonaRuntimeConfig

# ============================================================================
# DaytonaRuntimeConfig Tests
# ============================================================================


def test_daytona_runtime_config_defaults():
    """Test default values for DaytonaRuntimeConfig."""
    config = DaytonaRuntimeConfig(auth_token="test-token")
    assert config.port is None
    assert config.auth_token == "test-token"


def test_daytona_runtime_config_custom_values():
    """Test custom values for DaytonaRuntimeConfig."""
    config = DaytonaRuntimeConfig(auth_token="test-token", port=9000)
    assert config.port == 9000
    assert config.auth_token == "test-token"


# ============================================================================
# DaytonaDeploymentConfig Tests
# ============================================================================


def test_daytona_deployment_config_defaults():
    """Test default values for DaytonaDeploymentConfig."""
    config = DaytonaDeploymentConfig()
    assert config.api_url is None
    assert config.api_key == ""
    assert config.target == "us"
    assert config.port == 8000
    assert config.container_timeout == 60 * 15
    assert config.runtime_timeout == 60
    assert config.image == "python:3.11"


def test_daytona_deployment_config_custom_values():
    """Test custom values for DaytonaDeploymentConfig."""
    config = DaytonaDeploymentConfig(
        api_url="https://daytona.example.com",
        api_key="test-key",
        target="eu",
        port=9000,
        container_timeout=3600,
        runtime_timeout=120,
        image="python:3.12",
    )
    assert config.api_url == "https://daytona.example.com"
    assert config.api_key == "test-key"
    assert config.target == "eu"
    assert config.port == 9000
    assert config.container_timeout == 3600
    assert config.runtime_timeout == 120
    assert config.image == "python:3.12"


def test_daytona_deployment_config_get_deployment():
    """Test get_deployment method."""
    config = DaytonaDeploymentConfig(
        api_url="https://daytona.example.com",
        api_key="test-key",
    )
    deployment = config.get_deployment()
    assert isinstance(deployment, DaytonaDeployment)


# ============================================================================
# DaytonaRuntime Tests
# ============================================================================


@pytest.fixture
def mock_sandbox():
    """Create a mock sandbox object."""
    sandbox = MagicMock()
    sandbox.process = MagicMock()
    sandbox.process.execute_session_command = AsyncMock()
    sandbox.process.get_session_command_logs = AsyncMock()
    return sandbox


@pytest.fixture
def daytona_runtime(mock_sandbox):
    """Create a DaytonaRuntime instance with mock sandbox."""
    return DaytonaRuntime(
        sandbox=mock_sandbox,
        session_id="test-session",
        auth_token="test-token",
        port=8000,
    )


class TestDaytonaRuntime:
    """Tests for DaytonaRuntime class."""

    def test_init(self, mock_sandbox):
        """Test initialization."""
        runtime = DaytonaRuntime(
            sandbox=mock_sandbox,
            session_id="test-session",
            auth_token="test-token",
            port=8000,
        )
        assert runtime._sandbox == mock_sandbox
        assert runtime._session_id == "test-session"
        assert runtime._auth_token == "test-token"
        assert runtime._port == 8000
        assert runtime._swerex_url == "http://localhost:8000"

    def test_from_config(self):
        """Test from_config class method."""
        config = DaytonaRuntimeConfig(auth_token="test-token", port=9000)
        runtime = DaytonaRuntime.from_config(config)
        assert runtime._port == 9000
        assert runtime._auth_token == "test-token"

    def test_get_headers_json(self, daytona_runtime):
        """Test _get_headers_json method."""
        headers_json = daytona_runtime._get_headers_json()
        headers = json.loads(headers_json)
        assert headers["X-API-Key"] == "test-token"
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_is_alive_success(self, daytona_runtime, mock_sandbox):
        """Test is_alive when server is healthy."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps({"is_alive": True, "message": ""})
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        result = await daytona_runtime.is_alive()
        assert result.is_alive is True

    @pytest.mark.asyncio
    async def test_is_alive_failure(self, daytona_runtime, mock_sandbox):
        """Test is_alive when server is not healthy."""
        # Mock the response with failure
        mock_response = MagicMock()
        mock_response.exit_code = 1
        mock_sandbox.process.execute_session_command.return_value = mock_response

        result = await daytona_runtime.is_alive()
        assert result.is_alive is False
        assert "exit code 1" in result.message

    @pytest.mark.asyncio
    async def test_is_alive_exception(self, daytona_runtime, mock_sandbox):
        """Test is_alive when exception occurs."""
        mock_sandbox.process.execute_session_command.side_effect = Exception("Connection failed")

        result = await daytona_runtime.is_alive()
        assert result.is_alive is False
        assert "Connection failed" in result.message

    @pytest.mark.asyncio
    async def test_create_session(self, daytona_runtime, mock_sandbox):
        """Test create_session method."""
        # Mock the response with proper format (status + body)
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps({"status": 200, "body": json.dumps({"output": "", "session_type": "bash"})})
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        request = CreateBashSessionRequest()
        result = await daytona_runtime.create_session(request)
        assert result.session_type == "bash"

    @pytest.mark.asyncio
    async def test_run_in_session(self, daytona_runtime, mock_sandbox):
        """Test run_in_session method."""
        # Mock the response with proper format
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps(
            {
                "status": 200,
                "body": json.dumps(
                    {
                        "output": "hello",
                        "exit_code": 0,
                        "failure_reason": "",
                        "expect_string": "",
                        "session_type": "bash",
                    }
                ),
            }
        )
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        action = BashAction(command="echo hello")
        result = await daytona_runtime.run_in_session(action)
        assert result.output == "hello"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_close_session(self, daytona_runtime, mock_sandbox):
        """Test close_session method."""
        # Mock the response with proper format
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps({"status": 200, "body": json.dumps({"session_type": "bash"})})
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        request = CloseBashSessionRequest()
        result = await daytona_runtime.close_session(request)
        assert result.session_type == "bash"

    @pytest.mark.asyncio
    async def test_execute(self, daytona_runtime, mock_sandbox):
        """Test execute method."""
        # Mock the response with proper format
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps(
            {
                "status": 200,
                "body": json.dumps(
                    {
                        "stdout": "output",
                        "stderr": "",
                        "exit_code": 0,
                    }
                ),
            }
        )
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        command = Command(command="ls -la")
        result = await daytona_runtime.execute(command)
        assert result.stdout == "output"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_read_file(self, daytona_runtime, mock_sandbox):
        """Test read_file method."""
        # Mock the response with proper format
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps({"status": 200, "body": json.dumps({"content": "file content"})})
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        request = ReadFileRequest(path="/test/file.txt")
        result = await daytona_runtime.read_file(request)
        assert result.content == "file content"

    @pytest.mark.asyncio
    async def test_write_file(self, daytona_runtime, mock_sandbox):
        """Test write_file method."""
        # Mock the response with proper format
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps({"status": 200, "body": json.dumps({})})
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        request = WriteFileRequest(content="test content", path="/test/file.txt")
        result = await daytona_runtime.write_file(request)
        # WriteFileResponse has no attributes to check, just verify no exception
        assert result is not None

    @pytest.mark.asyncio
    async def test_close(self, daytona_runtime, mock_sandbox):
        """Test close method."""
        # Mock the response with proper format
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps({"status": 200, "body": json.dumps({})})
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        result = await daytona_runtime.close()
        assert result is not None

    @pytest.mark.asyncio
    async def test_upload_file(self, daytona_runtime, mock_sandbox, tmp_path):
        """Test upload method with a file."""
        # Create a temporary file to upload
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("test content")

        # Mock the response
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        from swerex.runtime.abstract import UploadRequest

        request = UploadRequest(source_path=str(test_file), target_path="/remote/test_file.txt")
        result = await daytona_runtime.upload(request)
        assert result is not None
        # Verify the command was executed
        mock_sandbox.process.execute_session_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_directory(self, daytona_runtime, mock_sandbox, tmp_path):
        """Test upload method with a directory."""
        # Create a temporary directory to upload
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")

        # Mock the response
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        from swerex.runtime.abstract import UploadRequest

        request = UploadRequest(source_path=str(test_dir), target_path="/remote/test_dir")
        result = await daytona_runtime.upload(request)
        assert result is not None
        # Verify the command was executed
        mock_sandbox.process.execute_session_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_nonexistent_path(self, daytona_runtime, mock_sandbox):
        """Test upload method with non-existent path."""
        from swerex.runtime.abstract import UploadRequest

        request = UploadRequest(source_path="/nonexistent/path", target_path="/remote/path")
        with pytest.raises(ValueError, match="is not a file or directory"):
            await daytona_runtime.upload(request)

    @pytest.mark.asyncio
    async def test_upload_failure(self, daytona_runtime, mock_sandbox, tmp_path):
        """Test upload method when command fails."""
        # Create a temporary file to upload
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("test content")

        # Mock the response with failure
        mock_response = MagicMock()
        mock_response.exit_code = 1
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stderr = "Upload failed"
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        from swerex.runtime.abstract import UploadRequest

        request = UploadRequest(source_path=str(test_file), target_path="/remote/test_file.txt")
        with pytest.raises(RuntimeError, match="Upload failed"):
            await daytona_runtime.upload(request)


# ============================================================================
# DaytonaDeployment Tests
# ============================================================================


class TestDaytonaDeployment:
    """Tests for DaytonaDeployment class."""

    def test_init(self):
        """Test initialization."""
        deployment = DaytonaDeployment()
        assert deployment._runtime is None
        assert deployment._sandbox is None
        assert deployment._sandbox_id is None

    def test_add_hook(self):
        """Test add_hook method."""
        from swerex.deployment.hooks.abstract import DeploymentHook

        deployment = DaytonaDeployment()

        # Create a mock hook
        mock_hook = MagicMock(spec=DeploymentHook)

        # Add the hook
        deployment.add_hook(mock_hook)

        # Verify the hook was added (hooks are stored in _hooks)
        assert deployment._hooks is not None

    def test_from_config(self):
        """Test from_config class method."""
        config = DaytonaDeploymentConfig(
            api_url="https://daytona.example.com",
            api_key="test-key",
        )
        deployment = DaytonaDeployment.from_config(config)
        assert isinstance(deployment, DaytonaDeployment)

    def test_init_daytona_self_hosted(self):
        """Test _init_daytona with self-hosted configuration."""
        deployment = DaytonaDeployment(
            api_url="https://daytona.example.com",
            api_key="test-key",
        )
        deployment._init_daytona()
        assert deployment._daytona is not None

    def test_init_daytona_cloud(self):
        """Test _init_daytona with cloud configuration."""
        deployment = DaytonaDeployment(
            api_key="test-key",
            target="eu",
        )
        deployment._init_daytona()
        assert deployment._daytona is not None

    def test_get_token(self):
        """Test _get_token generates unique tokens."""
        deployment = DaytonaDeployment()
        token1 = deployment._get_token()
        token2 = deployment._get_token()
        assert token1 != token2
        assert len(token1) == 36  # UUID format

    def test_get_command(self):
        """Test _get_command generates correct command."""
        deployment = DaytonaDeployment(port=8000, container_timeout=900)
        command = deployment._get_command(token="test-token")
        assert "swerex" in command
        assert "--port 8000" in command
        assert "--auth-token test-token" in command
        # container_timeout is a float, so it may have decimal point
        assert "timeout 900" in command

    @pytest.mark.asyncio
    async def test_is_alive_not_started(self):
        """Test is_alive raises error when not started."""
        from swerex.exceptions import DeploymentNotStartedError

        deployment = DaytonaDeployment()
        with pytest.raises(DeploymentNotStartedError):
            await deployment.is_alive()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Test stop when deployment was never started."""
        deployment = DaytonaDeployment()
        # Should not raise any exception
        await deployment.stop()

    def test_runtime_property_not_started(self):
        """Test runtime property raises error when not started."""
        deployment = DaytonaDeployment()
        with pytest.raises(RuntimeError, match="Runtime not started"):
            _ = deployment.runtime


# ============================================================================
# Integration-style Tests (with more complex mocking)
# ============================================================================


class TestDaytonaRuntimeIntegration:
    """Integration-style tests with more complex mocking scenarios."""

    @pytest.mark.asyncio
    async def test_execute_request_success(self, mock_sandbox):
        """Test _execute_request with successful response."""
        runtime = DaytonaRuntime(
            sandbox=mock_sandbox,
            session_id="test-session",
            auth_token="test-token",
            port=8000,
        )

        # Mock the response
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps({"status": 200, "body": json.dumps({"result": "success"})})
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        from swerex.runtime.abstract import CreateBashSessionRequest

        request = CreateBashSessionRequest()
        result = await runtime._execute_request("create_session", request)
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_execute_request_http_error(self, mock_sandbox):
        """Test _execute_request with HTTP error response."""
        runtime = DaytonaRuntime(
            sandbox=mock_sandbox,
            session_id="test-session",
            auth_token="test-token",
            port=8000,
        )

        # Mock the response with HTTP error
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps({"status": 500, "body": json.dumps({"error": "Internal server error"})})
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        from swerex.runtime.abstract import CreateBashSessionRequest

        request = CreateBashSessionRequest()
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await runtime._execute_request("create_session", request)

    @pytest.mark.asyncio
    async def test_execute_request_swerexception(self, mock_sandbox):
        """Test _execute_request with swerexception response."""
        runtime = DaytonaRuntime(
            sandbox=mock_sandbox,
            session_id="test-session",
            auth_token="test-token",
            port=8000,
        )

        # Mock the response with swerexception
        mock_response = MagicMock()
        mock_response.exit_code = 0
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stdout = json.dumps(
            {
                "status": 511,
                "body": json.dumps({"swerexception": {"message": "Command failed", "traceback": "traceback here"}}),
            }
        )
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        from swerex.runtime.abstract import CreateBashSessionRequest

        request = CreateBashSessionRequest()
        with pytest.raises(RuntimeError, match="swerex exception"):
            await runtime._execute_request("create_session", request)

    @pytest.mark.asyncio
    async def test_execute_request_command_failure(self, mock_sandbox):
        """Test _execute_request when command fails."""
        runtime = DaytonaRuntime(
            sandbox=mock_sandbox,
            session_id="test-session",
            auth_token="test-token",
            port=8000,
        )

        # Mock the response with failure
        mock_response = MagicMock()
        mock_response.exit_code = 1
        mock_response.cmd_id = "cmd-123"
        mock_sandbox.process.execute_session_command.return_value = mock_response

        mock_logs = MagicMock()
        mock_logs.stderr = "Command failed"
        mock_sandbox.process.get_session_command_logs.return_value = mock_logs

        from swerex.runtime.abstract import CreateBashSessionRequest

        request = CreateBashSessionRequest()
        with pytest.raises(RuntimeError, match="Failed to call swerex API"):
            await runtime._execute_request("create_session", request)
