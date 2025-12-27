# Real-Time KataGo API - Testing Guide

This guide explains how to test the newly implemented Real-Time KataGo API prototype. The implementation includes data models and a persistent engine wrapper that manages the KataGo subprocess.

## 1. Prerequisites

Ensure you have the following set up:

*   **Python 3.8+** (Recommended: Use the `py311_katago` environment if available)
*   **Git**

If using the conda environment:
```bash
conda activate py311_katago
```

## 2. Running Unit Tests

We have included a suite of unit tests that mock the KataGo process, so **you do not need the actual KataGo executable or model files to run these tests.** They verify the logic of the Python wrapper, JSON serialization, and threading.

To run the tests, execute the following command from the repository root:

```bash
PYTHONPATH=python python tests/test_realtime_api.py
```

**Expected Output:**
```
....
----------------------------------------------------------------------
Ran 4 tests in 0.209s

OK
```

### What is tested?
*   **`TestModels`**: Verifies that `AnalysisRequest` and `AnalysisResponse` correctly convert between Python objects and JSON dictionaries.
*   **`TestEngine`**:
    *   **Initialization**: Checks if the subprocess is started with the correct arguments.
    *   **Submit Analysis**: Verifies that requests are correctly written to the subprocess `stdin` and that responses from `stdout` are correctly parsed and routed to the callback function.

## 3. Manual Verification Script

If you want to see the engine in action (using a mock to simulate KataGo), you can create and run the following script.

**File:** `test_engine_manual.py`

```python
import sys
import time
import json
from unittest.mock import MagicMock
from realtime_api.engine import KataGoEngine
from realtime_api.models import AnalysisRequest

# 1. Mock the KataGo process behavior (so we don't need the binary)
def mock_katago_behavior():
    # This mock behaves like the real engine: reads line, waits, prints response
    import subprocess
    
    # We create a dummy engine but swap out its internal process 
    # with a mock that we control manually for this demo.
    engine = KataGoEngine("dummy_path", "dummy.cfg", "dummy.model")
    
    # Kill the real (failing) subprocess spawned by init
    engine.process.kill()
    
    # Create Mocks
    engine.process = MagicMock()
    engine.process.stdin = MagicMock()
    engine.process.stdout = MagicMock()
    engine.process.stderr = MagicMock()
    
    # Logic to simulate a response when we submit
    def write_side_effect(data):
        print(f"\n[Mock KataGo] Received input: {data.strip()}")
        request = json.loads(data)
        
        # Fake a KataGo analysis response
        response = {
            "id": request["id"],
            "isDuringSearch": False,
            "moveInfos": [
                {"move": "Q16", "visits": 50, "winrate": 0.48, "scoreLead": -0.5, "prior": 0.1, "order": 0, "utility": 0.0, "scoreSelfplay": 0.0, "pv": []}
            ],
            "rootInfo": {"winrate": 0.48, "scoreLead": -0.5, "visits": 50, "utility": 0.0}
        }
        
        # Simulate KataGo outputting to stdout after a delay
        def emit_output():
            time.sleep(0.5)
            # We inject this into the engine's processing loop via a little hack 
            # or just call the handler directly for this manual test:
            print("[Mock KataGo] Sending response...")
            engine._handle_response_line(json.dumps(response))
            
        import threading
        threading.Thread(target=emit_output).start()

    engine.process.stdin.write.side_effect = write_side_effect
    return engine

# 2. Setup the Engine
engine = mock_katago_behavior()

# 3. Define a callback
def handle_result(response):
    print(f"\n[Client] Callback Received!")
    print(f"  ID: {response.id}")
    print(f"  Best Move: {response.moveInfos[0].move}")
    print(f"  Winrate: {response.moveInfos[0].winrate}")

# 4. Submit a Request
req = AnalysisRequest(id="manual_test_1", moves=[("B", "Q4")])
print("[Client] Submitting request...")
engine.submit_analysis(req, callback=handle_result)

# 5. Keep alive to wait for callback
time.sleep(2)
engine.stop()
```

Run it with:
```bash
PYTHONPATH=python python test_engine_manual.py
```

## 4. Integration with Real KataGo (Optional)

If you have a compiled `katago` binary and a model file, you can test the real integration.

1.  Locate your binary (e.g., `cpp/katago`) and model (e.g., `model.bin.gz`).
2.  Create a `config.cfg` (or use `cpp/configs/analysis_example.cfg`).
3.  Run the following python script:

```python
from realtime_api.engine import KataGoEngine
from realtime_api.models import AnalysisRequest
import time

# Paths to your actual files
KATAGO_PATH = "./cpp/katago"
CONFIG_PATH = "./cpp/configs/analysis_example.cfg"
MODEL_PATH = "./model.bin.gz" 

engine = KataGoEngine(KATAGO_PATH, CONFIG_PATH, MODEL_PATH)

def callback(resp):
    print(f"Received analysis for {resp.id}: {resp.rootInfo}")

req = AnalysisRequest(id="real_1", moves=[("B", "Q4")], maxVisits=10)
engine.submit_analysis(req, callback)

time.sleep(5) # Wait for engine to load and respond
engine.stop()
```
