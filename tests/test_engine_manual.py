import sys
import time
import json
import threading
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
        try:
            request = json.loads(data)
        except json.JSONDecodeError:
            return

        # Fake a KataGo analysis response
        response = {
            "id": request["id"],
            "isDuringSearch": False,
            "moveInfos": [
                {
                    "move": "Q16", 
                    "visits": 50, 
                    "winrate": 0.48, 
                    "scoreLead": -0.5, 
                    "scoreSelfplay": 0.0,
                    "utility": 0.0,
                    "prior": 0.1, 
                    "order": 0, 
                    "pv": []
                }
            ],
            "rootInfo": {"winrate": 0.48, "scoreLead": -0.5, "visits": 50, "utility": 0.0}
        }
        
        # Simulate KataGo outputting to stdout after a delay
        def emit_output():
            time.sleep(0.5)
            # We inject this into the engine's processing loop
            print("[Mock KataGo] Sending response...")
            engine._handle_response_line(json.dumps(response))
            
        threading.Thread(target=emit_output).start()

    engine.process.stdin.write.side_effect = write_side_effect
    return engine

def main():
    # 2. Setup the Engine
    engine = mock_katago_behavior()

    # 3. Define a callback
    def handle_result(response):
        print(f"\n[Client] Callback Received!")
        print(f"  ID: {response.id}")
        if response.moveInfos:
            print(f"  Best Move: {response.moveInfos[0].move}")
            print(f"  Winrate: {response.moveInfos[0].winrate}")
        else:
            print("  No move info received.")

    # 4. Submit a Request
    req = AnalysisRequest(id="manual_test_1", moves=[("B", "Q4")])
    print("[Client] Submitting request...")
    engine.submit_analysis(req, callback=handle_result)

    # 5. Keep alive to wait for callback
    time.sleep(2)
    engine.stop()

if __name__ == "__main__":
    main()
