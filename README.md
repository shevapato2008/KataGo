# KataGo

* [Overview](#overview)
* [Training History and Research](#training-history-and-research)
* [Quick Start (Linux)](#quick-start-linux)
* [Detailed Setup and Running](#detailed-setup-and-running)
  * [GUIs](#guis)
  * [Backends (OpenCL vs CUDA vs TensorRT vs Eigen)](#backends)
  * [How To Use](#how-to-use)
  * [Tuning for Performance](#tuning-for-performance)
* [Compiling from Source](#compiling-from-source)
  * [Linux](#linux-compiling)
  * [Windows](#windows-compiling)
  * [MacOS](#macos-compiling)
  * [Troubleshooting TensorRT Builds](#troubleshooting-tensorrt-builds)
* [Common Questions and Issues](#common-questions-and-issues)
* [Features for Developers](#features-for-developers)
* [Real-Time API Service](#real-time-api-service)
* [Selfplay Training](#selfplay-training)
* [Contributors and License](#contributors-and-license)

## Overview

KataGo's public distributed training run is ongoing! See https://katagotraining.org/ for more details, to download the latest and strongest neural nets, or to learn how to contribute if you want to help KataGo improve further! Also check out the computer Go [discord channel](https://discord.gg/bqkZAz3)!

As of 2025, KataGo remains one of the strongest open source Go bots available online. KataGo was trained using an AlphaZero-like process with many enhancements and improvements, and is capable of reaching top levels rapidly and entirely from scratch with no outside data.

KataGo's engine aims to be a useful tool for Go players and developers, and supports the following features:
* Estimates territory and score, rather than only "winrate".
* Cares about maximizing score, enabling strong play in handicap games when far behind.
* Supports alternative values of komi and board sizes ranging from 7x7 to 19x19.
* Supports a wide variety of rules (Japanese, Chinese, etc).
* For tool/back-end developers - supports a JSON-based analysis engine.

## Training History and Research

* Paper about the major new ideas and techniques used in KataGo: [Accelerating Self-Play Learning in Go (arXiv)](https://arxiv.org/abs/1902.10565).
* Newer improvements: [KataGoMethods.md](docs/KataGoMethods.md).
* Monte-Carlo Graph Search: [GraphSearch.md](docs/GraphSearch.md).
* For more details about KataGo's older training runs: [Older Training History and Research](TrainingHistory.md).

## Quick Start (Linux)

This section guides you through downloading and setting up KataGo with default models and configs so you can run it easily.

### 1) Download KataGo
1. Go to [KataGo Releases](https://github.com/lightvector/KataGo/releases) and download the Linux build that matches your backend (e.g., CUDA).
2. Extract the executable:
   ```bash
   mkdir -p ~/katago
   # Copy the 'katago' executable here
   chmod +x ~/katago/katago
   ```

### 2) Download a Model
Download a `.bin.gz` neural net model from [katagotraining.org](https://katagotraining.org/) and save it to `~/katago/models/`.

### 3) Set Up Defaults
KataGo looks for `default_model.bin.gz` and `default_gtp.cfg` in its directory to run without extra flags.

1. **Link the Model:**
   ```bash
   ln -sf ~/katago/models/YOUR_DOWNLOADED_MODEL.bin.gz ~/katago/default_model.bin.gz
   ```
2. **Get the Config:**
   Download `cpp/configs/gtp_example.cfg` from this repo and save it as `default_gtp.cfg` in `~/katago/`.
   ```bash
   # Or if you have the repo cloned:
   cp cpp/configs/gtp_example.cfg ~/katago/default_gtp.cfg
   ```

### 4) Launch
```bash
cd ~/katago
./katago gtp
```

## Detailed Setup and Running

KataGo implements a GTP engine (text protocol). It does NOT have a GUI on its own.

### GUIs
You generally need a GUI to play/analyze:
* [KaTrain](https://github.com/sanderland/katrain): Easy all-in-one setup for non-technical users.
* [Lizzie](https://github.com/featurecat/lizzie): Popular for analysis.
* [Sabaki](https://sabaki.yichuanshen.de/), [q5Go](https://github.com/bernds/q5Go), [Ogatak](https://github.com/rooklift/ogatak).

### Backends
* **OpenCL:** General GPU backend (NVIDIA, AMD, Intel). Easiest to get working. Tunes itself on first run (can take time).
* **TensorRT:** Best performance for modern NVIDIA GPUs. Requires installing TensorRT.
* **CUDA:** NVIDIA GPUs only. Requires CUDA+CUDNN.
* **Eigen:** CPU only. Slower, but works on anything. Use AVX2 build if supported by your CPU.

### How To Use
**Test and Tune:**
Run benchmark to ensure it works and find the optimal thread count:
```bash
./katago benchmark -model <NEURALNET>.bin.gz -config <CONFIG>.cfg
```

**Run Engine:**
Command for your GUI:
```bash
./katago gtp -model <NEURALNET>.bin.gz -config <CONFIG>.cfg
```

**Generate Config:**
Interactively generate a custom config:
```bash
./katago genconfig -model <NEURALNET>.bin.gz -output custom.cfg
```

### Tuning for Performance
* **Threads:** Adjust `numSearchThreads` in your `.cfg` file based on the benchmark results.
* **FP16:** For TensorRT/CUDA on modern GPUs, FP16 is usually faster.

## Compiling from Source

KataGo is written in C++ (C++14 or later).

### Linux-Compiling
**Requirements:** CMake 3.18.2+, g++, zlib, libzip.
* **Backends:**
    * OpenCL: OpenCL headers.
    * CUDA: CUDA Toolkit + CUDNN.
    * TensorRT: CUDA Toolkit + TensorRT 8.5+.
    * Eigen: Eigen3 (plus OpenSSL for distributed).

**Build:**
```bash
git clone https://github.com/lightvector/KataGo.git
cd KataGo/cpp
cmake . -DUSE_BACKEND=OPENCL  # or CUDA, TENSORRT, EIGEN
# Add -DUSE_AVX2=1 for Eigen on modern CPUs
# Add -DBUILD_DISTRIBUTED=1 for distributed training support
make -j$(nproc)
```

### Windows-Compiling
Requires CMake and MSVC 2017+ or MinGW.
1. Use CMake GUI to configure `KataGo/cpp`.
2. Set `USE_BACKEND` and point `ZLIB`/`LIBZIP` paths (use vcpkg for easy dependency management).
3. Generate and build in Visual Studio.

### MacOS-Compiling
Requires Homebrew, CMake, AppleClang.
```bash
brew install cmake libzip
cd KataGo/cpp
cmake . -G Ninja -DUSE_BACKEND=METAL  # or OPENCL, EIGEN
ninja
```

### Building with Docker
KataGo includes a `Dockerfile` for building a containerized version, which is especially useful for avoiding dependency hell (like TensorRT version mismatches). The container builds the TensorRT backend and starts the real-time API by default.

1. **Build the Image:**
   ```bash
   docker build -t katago-trt .
   ```

2. **Run the Real-Time API:**
   (Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed)
   ```bash
   docker run --gpus all -p 8000:8000 katago-trt
   ```
   The container will auto-download the default model on first start (as configured in `config.yaml`).

3. **Run KataGo directly (optional):**
   ```bash
   docker run --gpus all -it katago-trt ./cpp/katago benchmark -model /app/models/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz -config /app/cpp/configs/analysis_example.cfg
   ```

### Troubleshooting TensorRT Builds
If you encounter build errors due to a mismatch between your system's TensorRT version (e.g., v10.x) and KataGo's supported version (v8.x), or "API Usage Errors", you can fix this without downgrading your system drivers by using a local copy of the libraries.

**Solution: Extract Compatible Libraries via Docker**
1.  **Extract Libraries:** Use an NVIDIA Docker image with the correct TensorRT version (e.g., `nvcr.io/nvidia/tensorrt:23.10-py3` for TensorRT 8.6) to copy the headers and libraries to a local folder like `libs/TensorRT-8.6`.
    ```bash
    mkdir -p libs/TensorRT-8.6/include libs/TensorRT-8.6/lib
    # Run these commands to copy files from the docker image to your local folder
    # (Requires docker installed)
    sudo docker pull nvcr.io/nvidia/tensorrt:23.10-py3
    id=$(sudo docker create nvcr.io/nvidia/tensorrt:23.10-py3)
    sudo docker cp $id:/usr/include/x86_64-linux-gnu/. libs/TensorRT-8.6/include/
    sudo docker cp $id:/usr/lib/x86_64-linux-gnu/. libs/TensorRT-8.6/lib/
    sudo docker rm -v $id
    # Clean up unrelated files from the copy if desired, keeping only Nv* headers and libnvinfer* libs.
    ```
2.  **Build with Local Path:** Configure CMake to use this local directory.
    ```bash
    cd cpp
    cmake . -DUSE_BACKEND=TENSORRT -DTENSORRT_ROOT_DIR=../libs/TensorRT-8.6
    make -j$(nproc)
    ```
3.  **Run with LD_LIBRARY_PATH:** When running KataGo, tell it where to find the shared libraries.
    ```bash
    export LD_LIBRARY_PATH=$(pwd)/../libs/TensorRT-8.6/lib:$LD_LIBRARY_PATH
    ./katago benchmark ...
    ```

## Common Questions and Issues
* **"Loading" forever:** OpenCL tuning can take time. Run `benchmark` to see progress.
* **Specific GPU Issues:**
    * AMD RX 5700: Often has buggy drivers on Linux.
    * Integrated Graphics: Can be buggy or slow.
* **GTP/GUI Errors:** Check your file paths. Avoid spaces in paths.

## Features for Developers
* **GTP Extensions:** [GTP_Extensions.md](docs/GTP_Extensions.md) - `kata-analyze`, rule changes.
* **Analysis Engine:** [Analysis_Engine.md](docs/Analysis_Engine.md) - JSON-based batch evaluation.
* **Python:** Example code in `python/query_analysis_engine_example.py`.

## Real-Time API Service
A REST/WebSocket API wrapper for real-time analysis is available in `python/realtime_api`.

**1. Configuration:**
Edit `config.yaml` in the repo root to set the KataGo binary/config paths, model location, and any runtime library paths.
The default config points at the latest KataGo model URL and will auto-download it on first run if enabled.

**2. Start the Service:**
```bash
# From the project root
PYTHONPATH=python python3 -m realtime_api.main
```

**3. Test:**
```bash
curl http://localhost:8000/health
curl -X POST "http://localhost:8000/analyze" -H "Content-Type: application/json" -d '{"id":"test","moves":[["B","Q4"]]}'
```

See [docs/RealTimeAPI_TestGuide.md](docs/RealTimeAPI_TestGuide.md) for full details.

## Selfplay Training
If you'd like to run the full self-play loop and train your own neural nets, see [Selfplay Training](SelfplayTraining.md).

## Contributors and License
See [CONTRIBUTORS](CONTRIBUTORS) for the list of contributors.
Code is licensed under [LICENSE](LICENSE).
