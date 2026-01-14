import json
import subprocess
import os
import sys

def test_analysis_bounds():
    katago_path = "./cpp/katago"
    config_path = "./cpp/configs/analysis_example.cfg"
    model_path = "./models/b18c384nbt-humanv0.bin.gz"

    if not os.path.exists(model_path):
        model_path = "./models/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz"

    if not os.path.exists(katago_path) or not os.path.exists(config_path) or not os.path.exists(model_path):
        print("Skipping integration test: missing binary, config, or model.")
        return

    # Start KataGo analysis engine
    proc = subprocess.Popen(
        [katago_path, "analysis", "-config", config_path, "-model", model_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True
    )

    # Query with region bounds: 3x3 square in the top left
    query = {
        "id": "test_bounds",
        "moves": [],
        "rules": "Chinese",
        "komi": 7.5,
        "boardXSize": 19,
        "boardYSize": 19,
        "maxVisits": 10,
        "regionBounds": {
            "x1": 0, "y1": 0, "x2": 2, "y2": 2
        }
    }

    proc.stdin.write(json.dumps(query) + "\n")
    proc.stdin.flush()

    line = proc.stdout.readline()
    proc.stdin.close()
    proc.terminate()

    if not line:
        print("FAIL: No response from KataGo")
        sys.exit(1)

    response = json.loads(line)
    if "error" in response:
        print(f"FAIL: KataGo returned error: {response['error']}")
        sys.exit(1)

    print("Response received successfully.")
    # For now, we just verify that it parsed the regionBounds without error.
    # The actual move filtering is not yet implemented in the search.
    # But we can verify that if we provide invalid bounds, it returns an error.

    # Test invalid bounds
    proc = subprocess.Popen(
        [katago_path, "analysis", "-config", config_path, "-model", model_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True
    )
    query_invalid = query.copy()
    query_invalid["regionBounds"] = {"x1": 5, "y1": 5, "x2": 2, "y2": 2} # x1 > x2

    proc.stdin.write(json.dumps(query_invalid) + "\n")
    proc.stdin.flush()
    line_invalid = proc.stdout.readline()
    proc.stdin.close()
    proc.terminate()

    response_invalid = json.loads(line_invalid)
    if "error" in response_invalid and "x1 must be <= x2" in response_invalid["error"]:
        print("Successfully caught invalid bounds error.")
    else:
        print(f"FAIL: Did not catch invalid bounds error. Response: {line_invalid}")
        sys.exit(1)

    print("Integration test for parsing passed!")

if __name__ == "__main__":
    test_analysis_bounds()
