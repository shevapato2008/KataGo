# KataGo Real-Time API Usage & Testing Guide

This guide explains how to configure, start, and manually test the KataGo Real-Time API service.

## 1. Prerequisites

- **Compiled KataGo**: Ensure `cpp/katago` is compiled.
- **Neural Network Model**: A `.bin.gz` model file must be available.
- **Python Dependencies**:
  ```bash
  pip install -r requirements.txt
  ```

## 2. Configuration

The API uses `config.yaml` in the project root for configuration.

1. Edit `config.yaml` to match your local paths:
   - `katago.path`: Path to the executable.
   - `katago.model.path`: Path to your model.
   - `katago.config_path`: Path to the analysis config.
2. If `katago.model.auto_download` is true, the model will download from `katago.model.url` when missing.
   The default config uses the latest published KataGo model and stores it under `./models/`.
3. Optional: set `katago.model.sha256` to verify model integrity on startup and after downloads.

## 3. Starting the Service

The recommended way to start the service from the project root:

```bash
PYTHONPATH=python python3 -m realtime_api.main
```

- **Host**: `0.0.0.0` (accessible from other machines).
- **Port**: `8000` (default).
- **Reload**: Enabled (server restarts on code changes).

## 4. Manual Testing

### Health Check
Verify the API and KataGo subprocess are healthy:
```bash
curl http://localhost:8000/health
```

### Analysis Engine (`/analyze`)
Send board positions for analysis.

**Example: Single Move Analysis**
```bash
curl -X POST "http://localhost:8000/analyze" \
     -H "Content-Type: application/json" \
     -d '{
           "id": "req_001",
           "moves": [["B", "Q4"]],
           "rules": "Chinese",
           "komi": 7.5
         }'
```

**Example: Complex Position (Initial Stones)**
```bash
curl -X POST "http://localhost:8000/analyze" \
     -H "Content-Type: application/json" \
     -d '{
           "id": "req_002",
           "initialStones": [["B", "Q4"], ["W", "D4"]],
           "moves": [["B", "R16"]],
           "maxVisits": 50
        }'
```

## 5. Understanding the Response

The API returns a JSON object containing the analysis results. Here is a breakdown of the key fields:

```json
{
  "id": "req_001",
  "rootInfo": {
    "winrate": 0.46,
    "scoreLead": -0.5,
    "visits": 10
  },
  "moveInfos": [
    {
      "move": "D16",
      "visits": 4,
      "winrate": 0.47,
      "scoreLead": -0.4,
      "pv": ["D16", "R16", "C4"]
    }
  ]
}
```

- **`id`**: The request ID you provided, used to match responses to requests.
- **`rootInfo`**: Evaluation of the current board state *before* making a move.
    - `winrate`: Win probability for the current player (0.0 to 1.0).
    - `scoreLead`: Estimated point lead (positive for Black, negative for White).
    - `visits`: Total simulations performed.
- **`moveInfos`**: List of candidate moves, sorted by quality (best first).
    - `move`: The move coordinate (e.g., "D16", "pass").
    - `visits`: Number of simulations for this specific move (higher = more reliable).
    - `winrate`: Win probability after playing this move.
    - `scoreLead`: Estimated point lead after playing this move.
    - `pv` (Principal Variation): The predicted "best play" sequence following this move.

## 6. Troubleshooting

- **503 Service Unavailable**: Usually means the KataGo subprocess failed to start or died. Check the server logs for the specific KataGo error (e.g., "Model file not found").
- **ModuleNotFoundError**: Ensure you are running with `PYTHONPATH=python`.
