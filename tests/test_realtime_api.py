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
    # stdin.write is a synchronous method on StreamWriter, so use MagicMock
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdin.drain = AsyncMock()
    
    process.stdout = AsyncMock()
    process.stderr = AsyncMock()
    process.returncode = None
    
    # Prevent infinite loops in log readers by default: return EOF immediately
    process.stderr.readline.return_value = b""
    process.stdout.readline.return_value = b"" 
    
    # terminate() and kill() are synchronous methods on the Process object
    process.terminate = MagicMock()
    process.kill = MagicMock()
    
    return process
@pytest.mark.asyncio
async def test_katago_wrapper_lifecycle():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        process = mock_process()
        process.stdout.readline.return_value = b""
        mock_exec.return_value = process
        
        wrapper = KataGoWrapper("katago", "config", "model")
        
        await wrapper.start()
        
        assert wrapper.process is not None
        assert wrapper.running is True
        
        await wrapper.stop()
        assert wrapper.running is False
        assert wrapper.process is None

@pytest.mark.asyncio
async def test_katago_wrapper_query():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        process = mock_process()
        
        # Prepare a response
        response_data = {"id": "test_id", "result": "ok"}
        response_line = json.dumps(response_data).encode() + b"\n"
        
        # read_loop will call readline. 
        # 1. First call: returns response
        # 2. Second call: returns b"" (EOF) to stop the loop
        process.stdout.readline.side_effect = [response_line, b""]
        mock_exec.return_value = process
        
        wrapper = KataGoWrapper("katago", "config", "model")
        await wrapper.start()
        
        # Send query
        result = await wrapper.query({"id": "test_id"})
        
        assert result == response_data
        
        # Check that stdin was written to
        process.stdin.write.assert_called_once()
        written = process.stdin.write.call_args[0][0]
        assert b"test_id" in written
        
        await wrapper.stop()

@pytest.mark.asyncio
async def test_api_analyze_success():
    # Patch the global INSTANCE in main directly
    with patch("realtime_api.main.katago_wrapper", new_callable=MagicMock) as mock_wrapper:
        mock_wrapper.start = AsyncMock()
        mock_wrapper.stop = AsyncMock()
        mock_wrapper.process = MagicMock()
        mock_wrapper.process.returncode = None
        
        expected_response = {"id": "req_1", "moveInfos": []}
        mock_wrapper.query = AsyncMock(return_value=expected_response)
        
        # Use ASGITransport for modern httpx compatibility
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "id": "req_1",
                "moves": [["B", "Q4"]],
                "rules": "Chinese"
            }
            response = await client.post("/analyze", json=payload)
            assert response.status_code == 200
            assert response.json() == expected_response
            
            mock_wrapper.query.assert_called_once()
            call_arg = mock_wrapper.query.call_args[0][0]
            assert call_arg["id"] == "req_1"
            assert call_arg["moves"] == [("B", "Q4")]

@pytest.mark.asyncio
async def test_api_health_check_success():
    with patch("realtime_api.main.katago_wrapper", new_callable=MagicMock) as mock_wrapper:
        mock_wrapper.start = AsyncMock()
        mock_wrapper.stop = AsyncMock()
        mock_wrapper.process = MagicMock()
        mock_wrapper.process.returncode = None
        mock_wrapper.process.pid = 1234
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "pid": 1234}

@pytest.mark.asyncio
async def test_api_health_check_failure():
    with patch("realtime_api.main.katago_wrapper", new_callable=MagicMock) as mock_wrapper:
        mock_wrapper.start = AsyncMock()
        mock_wrapper.stop = AsyncMock()
        
        # Case 1: Process died (returncode is not None)
        mock_wrapper.process = MagicMock()
        mock_wrapper.process.returncode = 1
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 503
            assert "exited" in response.json()["detail"]
