# Real-Time KataGo Integration Plan

This document outlines the strategy for integrating KataGo into a high-performance, real-time application capable of meeting strict latency (<50ms), uptime (99.9%), and throughput (1000 RPS) requirements.

## 1. Architecture Overview

To meet the high throughput and low latency goals, the system will use a tiered architecture:

```mermaid
graph LR
    Client -->|HTTP/WebSocket| LoadBalancer
    LoadBalancer --> API_Server_Cluster
    subgraph "Worker Node"
        API_Server[API Gateway (FastAPI/Go)] <-->|Stdin/Stdout| KataGo_Process[KataGo Analysis Engine]
        KataGo_Process -->|CUDA/TensorRT| GPU
    end
```

*   **KataGo Mode:** Use the **Analysis Engine** (`./katago analysis`) rather than the GTP engine. The Analysis Engine allows for batching multiple positions from different games, significantly increasing throughput compared to the serial nature of GTP.
*   **API Gateway:** A lightweight server (Python FastAPI or Go) wraps the KataGo subprocess. It accepts web requests, manages a queue, batches requests into the JSON format KataGo expects, and routes asynchronous responses back to the correct client.

## 2. Key Integration Points

### 2.1. API Endpoints

The API Gateway should expose the following endpoints:

*   **`POST /analyze`**: Accepts a game state (SGF or current board setup) and returns the best move/winrate.
    *   *Input:* JSON containing `moves`, `initialStones`, `komi`, `rules`.
    *   *Output:* JSON with `move`, `winrate`, `scoreLead`, `principalVariation`.
*   **`WS /stream_analysis`**: WebSocket endpoint for real-time analysis streaming during a live game.
    *   Allows pushing board updates and receiving continuous analysis updates (using KataGo's `reportDuringSearchEvery` feature).
*   **`GET /health`**: Health check for the load balancer. Returns 200 OK if KataGo is responsive.

### 2.2. KataGo Configuration (`analysis.cfg`)

Crucial settings for real-time performance:

*   **`numAnalysisThreads`**: Set to match the expected batch size (e.g., 8-16). Allows analyzing multiple concurrent requests.
*   **`numSearchThreadsPerAnalysisThread`**: Lower this (e.g., 6-10) to reduce latency per request at the cost of slightly weaker individual playouts.
*   **`nnCacheSizePowerOfTwo`**: Maximize based on available RAM to avoid re-evaluating common positions.
*   **`useAnalysisMsg`**: Ensure JSON output is strictly formatted.

## 3. Data Handling & Serialization

*   **Format:** The Analysis Engine uses distinct JSON objects separated by newlines.
    *   *Request:* `{"id": "req_123", "moves": [["B","Q4"], ...], "rules": "chinese", ...}`
    *   *Response:* `{"id": "req_123", "moveInfos": [...], "rootInfo": {...}}`
*   **Serialization:**
    *   Use rapid JSON libraries (e.g., `orjson` in Python or `encoding/json` in Go).
    *   **Optimization:** Pre-validate SGF/Move strings at the API Gateway level before sending to KataGo to prevent engine crashes on malformed input.

## 4. Performance & Scalability Strategy

### 4.1. Latency (<50ms)
*   **Backend:** Use **TensorRT** on NVIDIA GPUs. This provides the highest inference speed (visits/second).
*   **Playout Cap:** For <50ms response, limit `maxVisits` dynamically. A "fast estimate" might use 50-100 visits, while deeper analysis runs asynchronously.
*   **Model Size:** Use a smaller, optimized model (e.g., a 15-block or 20-block network) instead of the largest 40-block or 60-block networks. The speed gain is often worth the minor strength trade-off for real-time needs.
*   **Keep-Alive:** The KataGo process must stay running. Do *not* spawn a new subprocess per request.

### 4.2. Throughput (1000 RPS)
*   **Batching:** The API Gateway must aggregate incoming requests into batches before sending to KataGo. KataGo's internal batching on the GPU is the primary mechanism for high throughput.
*   **Horizontal Scaling:** 1000 RPS is likely beyond a single GPU's capacity for meaningful analysis.
    *   Deploy multiple Worker Nodes behind the Load Balancer.
    *   Estimate: If 1 request takes 50ms (20 RPS per thread), and you have batch size 16 => ~320 RPS per GPU. You would need ~3-4 high-end GPUs to hit 1000 RPS comfortably.

### 4.3. Uptime (99.9%)
*   **Process Management:** Use `supervisord` or `systemd` to restart KataGo immediately if it crashes.
*   **Health Checks:** The API Gateway should periodically send a trivial query (e.g., empty board analysis with 1 visit) to KataGo to verify it's not hung.
*   **Graceful Degradation:** If the GPU is overloaded, return a "busy" status or a cached result immediately rather than queuing indefinitely.

## 5. Tooling & Libraries

*   **Language:** Python (FastAPI/Uvicorn) is recommended for ease of integration with AI tooling, or Go (Gin/Fiber) for maximum concurrent connection handling.
*   **KataGo Wrapper:** Custom `subprocess` wrapper (reference `python/query_analysis_engine_example.py`) implementing a non-blocking consumer/producer queue.
*   **Monitoring:**
    *   **Prometheus:** Track API latency, Request Queue Depth, and Error Rates.
    *   **KataGo Internal Logs:** Monitor "visits per second" and GPU utilization (via `nvidia-smi`).

## 6. Implementation Roadmap

1.  **Prototype (Day 1-2):**
    *   Setup KataGo with TensorRT.
    *   Create a basic Python script using `subprocess` to keep KataGo running and accept JSON via stdin.
2.  **API Wrapper (Day 3-5):**
    *   Build FastAPI application with `POST /analyze`.
    *   Implement an async queue to manage concurrent requests to the single KataGo stdin pipe.
3.  **Optimization (Day 6-7):**
    *   Benchmark latency vs. `maxVisits` vs. Model Size.
    *   Tune `analysis.cfg` for max batch throughput.
4.  **Scaling (Day 8+):**
    *   Dockerize the setup (TensorRT base image for GPU builds).
    *   Deploy behind Nginx/HAProxy load balancer.
