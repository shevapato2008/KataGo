import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from realtime_api.main import app

@pytest.mark.asyncio
async def test_api_analyze_multitenancy_fields():
    # Patch the global INSTANCE in main directly
    with patch("realtime_api.main.katago_wrapper", new_callable=MagicMock) as mock_wrapper:
        mock_wrapper.start = AsyncMock()
        mock_wrapper.stop = AsyncMock()
        mock_wrapper.process = MagicMock()
        mock_wrapper.process.returncode = None
        
        expected_response = {"id": "req_1", "moveInfos": []}
        mock_wrapper.query = AsyncMock(return_value=expected_response)
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Test with gameId and userId
            payload = {
                "id": "req_1",
                "moves": [["B", "Q4"]],
                "gameId": "game_2026",
                "userId": "user_123",
                "includeOwnership": True
            }
            response = await client.post("/analyze", json=payload)
            assert response.status_code == 200
            
            mock_wrapper.query.assert_called_once()
            call_arg = mock_wrapper.query.call_args[0][0]
            assert call_arg["gameId"] == "game_2026"
            assert call_arg["userId"] == "user_123"
            assert call_arg["includeOwnership"] is True

            # Test logging (implicitly, check logs if possible, but assert logic passes)
            # We would need to mock logger to verify logging, but basic flow verification is here.
