import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from realtime_api.main import app

@pytest.mark.asyncio
async def test_api_analyze_with_region_bounds():
    mock_wrapper = MagicMock()
    mock_wrapper.start = AsyncMock()
    mock_wrapper.stop = AsyncMock()
    mock_wrapper.process = MagicMock()
    mock_wrapper.process.returncode = None

    expected_response = {"id": "req_region", "moveInfos": []}
    mock_wrapper.query = AsyncMock(return_value=expected_response)

    with patch.dict("realtime_api.main.wrappers", {"default": mock_wrapper}, clear=True), \
         patch("realtime_api.main.default_model_name", "default"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "id": "req_region",
                "moves": [],
                "rules": "Chinese",
                "regionBounds": {
                    "x1": 0, "y1": 0, "x2": 5, "y2": 5
                }
            }
            response = await client.post("/analyze", json=payload)
            assert response.status_code == 200
            # /analyze stamps the serving model's identity onto every reply (attestation);
            # the region-bounds passthrough below is what this test is actually about.
            body = response.json()
            assert {k: v for k, v in body.items() if k != "_wrapper"} == expected_response
            assert body["_wrapper"]["selected_model"] == "default"


            mock_wrapper.query.assert_called_once()
            call_arg = mock_wrapper.query.call_args[0][0]
            assert call_arg["id"] == "req_region"
            assert "regionBounds" in call_arg
            assert call_arg["regionBounds"] == {"x1": 0, "y1": 0, "x2": 5, "y2": 5}

@pytest.mark.asyncio
async def test_api_analyze_with_invalid_region_bounds():
    # Pydantic should catch invalid types
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "id": "req_invalid",
            "regionBounds": {
                "x1": "invalid", "y1": 0, "x2": 5, "y2": 5
            }
        }
        response = await client.post("/analyze", json=payload)
        assert response.status_code == 422 # Unprocessable Entity
