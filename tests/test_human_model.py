import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from realtime_api.main import app
from realtime_api.katago_wrapper import KataGoWrapper

# Helper to mock process
def mock_process():
    process = AsyncMock()
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdin.drain = AsyncMock()
    process.stdout = AsyncMock()
    process.stderr = AsyncMock()
    process.returncode = None
    process.stderr.readline.return_value = b""
    process.stdout.readline.return_value = b"" 
    process.terminate = MagicMock()
    process.kill = MagicMock()
    return process

@pytest.mark.asyncio
async def test_katago_wrapper_with_human_model():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        process = mock_process()
        process.stdout.readline.return_value = b""
        mock_exec.return_value = process
        
        wrapper = KataGoWrapper(
            "katago", 
            "config", 
            "model",
            human_model_path="human_model.bin.gz"
        )
        
        assert wrapper.has_human_model is True
        
        await wrapper.start()
        
        # Check that -human-model was passed in args
        args = mock_exec.call_args[0]
        cmd_args = list(args)
        assert "-human-model" in cmd_args
        assert "human_model.bin.gz" in cmd_args
        
        await wrapper.stop()

@pytest.mark.asyncio
async def test_katago_wrapper_without_human_model():
    wrapper = KataGoWrapper("katago", "config", "model")
    assert wrapper.has_human_model is False

@pytest.mark.asyncio
async def test_api_health_check_with_human_model():
    # Mock the wrapper in main
    with patch("realtime_api.main.katago_wrapper", new_callable=MagicMock) as mock_wrapper:
        mock_wrapper.start = AsyncMock()
        mock_wrapper.stop = AsyncMock()
        mock_wrapper.process = MagicMock()
        mock_wrapper.process.returncode = None
        mock_wrapper.process.pid = 1234
        mock_wrapper.has_human_model = True  # Simulate human model present
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            json_resp = response.json()
            assert json_resp["status"] == "ok"
            assert json_resp["has_human_model"] is True

@pytest.mark.asyncio
async def test_api_health_check_without_human_model():
    with patch("realtime_api.main.katago_wrapper", new_callable=MagicMock) as mock_wrapper:
        mock_wrapper.start = AsyncMock()
        mock_wrapper.stop = AsyncMock()
        mock_wrapper.process = MagicMock()
        mock_wrapper.process.returncode = None
        mock_wrapper.process.pid = 1234
        mock_wrapper.has_human_model = False
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            json_resp = response.json()
            assert json_resp["status"] == "ok"
            assert json_resp["has_human_model"] is False