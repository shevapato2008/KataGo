import pytest
import os
import asyncio
import subprocess
import time
import sys
import httpx

def board_coords_to_pos(x, y, size_x, size_y):
    col_map = "ABCDEFGHJKLMNOPQRST"
    col = col_map[x]
    row = size_y - y
    return f"{col}{row}"

def is_in_bounds(move, x1, y1, x2, y2, size_x, size_y):
    if move.lower() == "pass":
        return True
    
    col_map = "ABCDEFGHJKLMNOPQRST"
    col_str = move[0].upper()
    row_str = move[1:]
    
    try:
        x = col_map.index(col_str)
        row_val = int(row_str)
        y = size_y - row_val
        return x1 <= x <= x2 and y1 <= y <= y2
    except (ValueError, IndexError):
        return False

@pytest.fixture(scope="module")
def api_server():
    if not os.path.exists("./cpp/katago"):
        pytest.skip("KataGo binary not found at ./cpp/katago")
    
    env = os.environ.copy()
    env["KATAGO_CONFIG_FILE"] = "tests/test_config.yaml"
    env["PYTHONPATH"] = "python"
    
    # Use absolute paths for the config file if needed, but we already updated it.
    
    proc = subprocess.Popen(
        [sys.executable, "-m", "realtime_api.main"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for KataGo to be ready (it logs "Started, ready to begin handling requests" to stderr)
    start_time = time.time()
    ready = False
    while time.time() - start_time < 30:
        line = proc.stderr.readline()
        if not line:
            break
        print(f"API: {line.strip()}")
        if "ready to begin handling requests" in line or "Application startup complete" in line:
            # We need to wait a bit more for KataGo itself if we only saw FastAPI startup
            if "ready to begin handling requests" in line:
                ready = True
                break
        time.sleep(0.1)
    
    if not ready:
        # Check if it's already running by calling health
        try:
            resp = httpx.get("http://127.0.0.1:8000/health", timeout=2.0)
            if resp.status_code == 200:
                ready = True
        except:
            pass

    if not ready:
        proc.terminate()
        proc.wait()
        pytest.fail("API server failed to start or KataGo failed to initialize")
        
    yield "http://127.0.0.1:8000"
    
    proc.terminate()
    proc.wait()

@pytest.mark.asyncio
async def test_full_integration_bounds(api_server):
    x1, y1, x2, y2 = 0, 0, 2, 2
    size_x, size_y = 19, 19
    
    async with httpx.AsyncClient(base_url=api_server, timeout=60.0) as client:
        payload = {
            "id": "full_test_bounds",
            "moves": [],
            "rules": "Chinese",
            "komi": 7.5,
            "boardXSize": size_x,
            "boardYSize": size_y,
            "maxVisits": 40,
            "regionBounds": {
                "x1": x1, "y1": y1, "x2": x2, "y2": y2
            }
        }
        
        response = await client.post("/analyze", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        assert "moveInfos" in data
        assert len(data["moveInfos"]) > 0
        
        for move_info in data["moveInfos"]:
            move = move_info["move"]
            assert is_in_bounds(move, x1, y1, x2, y2, size_x, size_y), f"Move {move} outside bounds"
            
            if "pv" in move_info:
                for pv_move in move_info["pv"]:
                    assert is_in_bounds(pv_move, x1, y1, x2, y2, size_x, size_y), f"PV move {pv_move} outside bounds"

@pytest.mark.asyncio
async def test_full_integration_no_bounds(api_server):
    async with httpx.AsyncClient(base_url=api_server, timeout=60.0) as client:
        payload = {
            "id": "full_test_no_bounds",
            "moves": [],
            "maxVisits": 20
        }
        
        response = await client.post("/analyze", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        assert "moveInfos" in data
        assert len(data["moveInfos"]) > 0