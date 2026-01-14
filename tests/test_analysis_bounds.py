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

def test_analysis_bounds_filtering():
    print("Testing analysis bounds filtering...")
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

    # Define a 3x3 region in the top left
    x1, y1, x2, y2 = 0, 0, 2, 2
    query = {
        "id": "test_filtering",
        "moves": [],
        "rules": "Chinese",
        "komi": 7.5,
        "boardXSize": 19,
        "boardYSize": 19,
        "maxVisits": 100,
        "regionBounds": {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2
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

    def is_in_bounds(gtp_loc):
        if gtp_loc == "pass":
            return True
        # GTP loc like "A19", "B18", etc.
        # KataGo GTP uses letters excluding 'I'
        col_char = gtp_loc[0].upper()
        cols = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
        x = cols.index(col_char)
        y = 19 - int(gtp_loc[1:])
        return x1 <= x <= x2 and y1 <= y <= y2

    # Check root move
    root_move = response.get("rootInfo", {}).get("suggestedMove")
    if root_move and not is_in_bounds(root_move):
        print(f"FAIL: Suggested move {root_move} is outside bounds!")
        sys.exit(1)

    # Check all PVs
    move_infos = response.get("moveInfos", [])
    for info in move_infos:
        move = info.get("move")
        if move and not is_in_bounds(move):
            print(f"FAIL: Top-level move {move} is outside bounds!")
            sys.exit(1)
        
        pv = info.get("pv", [])
        for pv_move in pv:
            if not is_in_bounds(pv_move):
                print(f"FAIL: PV move {pv_move} is outside bounds!")
                sys.exit(1)

    print("Successfully verified all moves are within bounds.")

if __name__ == "__main__":
    test_analysis_bounds()
    test_analysis_bounds_filtering()
