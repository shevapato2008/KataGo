# KataGo

KataGo is a strong open-source Go bot and analysis tool, capable of reaching top levels of play entirely from scratch via self-play training. It supports widely varied rules, board sizes, and provides features like score estimation and detailed analysis.

## Project Overview

*   **Core Logic (C++):** The main engine is written in C++ for performance, utilizing various backends for neural network inference:
    *   **OpenCL:** General GPU support (NVIDIA, AMD, Intel).
    *   **CUDA:** Specific to NVIDIA GPUs.
    *   **TensorRT:** Optimized for NVIDIA GPUs (often fastest).
    *   **Eigen:** CPU-based backend (slower, but works without a GPU).
    *   **Metal:** macOS specific.
*   **Training (Python):** Python scripts are used for the self-play training loop, data shuffling, and model training/exporting using PyTorch.

## Directory Structure

*   `cpp/`: C++ source code for the KataGo engine.
    *   `core/`, `game/`, `neuralnet/`, `search/`: Core engine components.
    *   `command/`: Implementation of CLI subcommands (gtp, benchmark, etc.).
    *   `configs/`: Example configuration files (`gtp_example.cfg`).
    *   `tests/`: Unit tests.
*   `python/`: Python scripts for training and auxiliary tasks.
    *   `katago/`: Python package modules.
    *   `train.py`: Main training script.
    *   `play.py`: Simple Python GTP engine for testing.
*   `docs/`: Detailed documentation on algorithms and usage.

## Building KataGo

KataGo uses **CMake**. The build process generally involves:

### Linux

1.  **Dependencies:** Ensure you have `cmake`, `g++` (C++14+), `zlib`, `libzip` (optional), and backend-specific libraries (OpenCL headers, CUDA, TensorRT, or Eigen).
2.  **Build:**
    ```bash
    cd cpp
    cmake . -DUSE_BACKEND=OPENCL  # or CUDA, TENSORRT, EIGEN
    make -j$(nproc)
    ```
    *   Add `-DUSE_AVX2=1` for Eigen backend on modern CPUs.
    *   Add `-DBUILD_DISTRIBUTED=1` for distributed training support (requires OpenSSL).

### Windows

Requires Visual Studio (MSVC) or MinGW, and CMake.
1.  Use CMake GUI to configure the project in `cpp/`.
2.  Set `USE_BACKEND` (OPENCL, CUDA, TENSORRT, EIGEN).
3.  Point `ZLIB_INCLUDE_DIR` and `ZLIB_LIBRARY` to your ZLib installation.
4.  Generate and build with Visual Studio.

### macOS

1.  **Dependencies:** `cmake`, `libzip`.
2.  **Build:**
    ```bash
    cd cpp
    cmake . -G Ninja -DUSE_BACKEND=METAL # or OPENCL, EIGEN
    ninja
    ```

## Running KataGo

After building, the `katago` executable is generated in `cpp/`.

*   **Benchmark:**
    ```bash
    ./katago benchmark -model <NEURALNET>.bin.gz -config configs/gtp_example.cfg
    ```
*   **GTP Engine (for GUIs):**
    ```bash
    ./katago gtp -model <NEURALNET>.bin.gz -config configs/gtp_example.cfg
    ```
*   **Generate Config:**
    ```bash
    ./katago genconfig -model <NEURALNET>.bin.gz -output gtp_custom.cfg
    ```

## Development & Training (Python)

To run the training loop or other Python tools:

*   **Training:** `python/train.py` is the main entry point.
*   **Exporting:** `python/export_model.py` converts PyTorch checkpoints to KataGo's `.bin.gz` format.
*   **Self-play:** `python/selfplay/` contains shell scripts to orchestrate the self-play loop.

## Key Files to Know

*   `README.md`: General project info and quick start.
*   `cpp/CMakeLists.txt`: Build configuration.
*   `cpp/configs/gtp_example.cfg`: extensively commented configuration file explaining many engine parameters.
*   `Compiling.md`: Detailed compilation instructions for all platforms.
*   `docs/GTP_Extensions.md`: Documentation for KataGo's specific GTP extensions (analysis, rules, etc.).

## Real-Time API Service

KataGo now includes a Python-based REST/WebSocket API for real-time analysis, useful for integrating into web services.

### 1. Configuration
`config.yaml` in the project root is used for configuration.
*   **Settings:** `katago.path`, `katago.model.path`, `katago.config_path`, and optional model auto-download.

### 2. Starting the Service
Run from the project root:
```bash
PYTHONPATH=python python3 -m realtime_api.main
```
The service defaults to `0.0.0.0:8000`.

### 3. Testing
**Health Check:**
```bash
curl http://localhost:8000/health
```

**Analysis Request:**
```bash
curl -X POST "http://localhost:8000/analyze" \
     -H "Content-Type: application/json" \
     -d '{
           "id": "test",
           "moves": [["B","Q4"]],
           "rules": "Chinese"
         }'
```
See `docs/RealTimeAPI_TestGuide.md` for a complete guide.

### 4. Server Optimization
The service is optimized for **single-process batch inference** to handle concurrent requests efficiently without model duplication.
*   **Strategy:** "Middle Ground" threading (8 concurrent analysis threads × 8 search threads per request).
*   **Config:** `cpp/configs/server_analysis.cfg` (derived from `analysis_example.cfg`).
*   **Batching:** Max batch size set to 64 to match total thread count, ensuring GPU saturation.
*   **Logging:** Batch size logging added to `NNEvaluator` in C++ to monitor batch formation effectiveness.
