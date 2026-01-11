# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

KataGo is a strong open-source Go bot with neural net backends (OpenCL, CUDA, TensorRT, Eigen, Metal). The repository contains:
- **C++ engine** (`cpp/`) - core search engine, backends, GTP interface, analysis engine
- **Python training** (`python/`) - neural net training pipeline using PyTorch
- **Real-time API** (`python/realtime_api/`) - REST/WebSocket wrapper for the analysis engine

## Build Commands

### C++ Engine

Build from the `cpp/` directory:

```bash
cd cpp
cmake . -DUSE_BACKEND=OPENCL  # or CUDA, TENSORRT, EIGEN, METAL
make -j$(nproc)
```

Common CMake options:
- `-DUSE_BACKEND={OPENCL|CUDA|TENSORRT|EIGEN|METAL}` - select neural net backend (required)
- `-DUSE_AVX2=1` - enable AVX2 for Eigen backend (recommended for modern CPUs)
- `-DBUILD_DISTRIBUTED=1` - enable distributed training support
- `-DTENSORRT_ROOT_DIR=path` - specify TensorRT installation path if not in system paths

The compiled binary is `cpp/katago`.

### TensorRT with Docker

For TensorRT builds with version compatibility issues, use the provided Dockerfile:

```bash
docker build -t katago-trt .
docker run -d --gpus all -p 8000:8000 katago-trt
```

## Running the Engine

### Basic Usage

Test the engine with benchmark:
```bash
./cpp/katago benchmark -model <MODEL>.bin.gz -config cpp/configs/gtp_example.cfg
```

Run GTP engine (for GUI integration):
```bash
./cpp/katago gtp -model <MODEL>.bin.gz -config cpp/configs/gtp_example.cfg
```

Generate custom config interactively:
```bash
./cpp/katago genconfig -model <MODEL>.bin.gz -output custom.cfg
```

### Analysis Engine

Run parallel position analysis (JSON API on stdin/stdout):
```bash
./cpp/katago analysis -model <MODEL>.bin.gz -config cpp/configs/analysis_example.cfg
```

See `python/query_analysis_engine_example.py` for example Python usage.

### Real-Time API Service

The REST/WebSocket API wrapper is configured via `config.yaml` in the repo root.

Start the service:
```bash
# From repository root
PYTHONPATH=python python3 -m realtime_api.main
```

Test endpoints:
```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"id":"test","moves":[["B","Q4"]]}'
```

## Testing

### C++ Tests

```bash
# Basic tests (no model required)
./cpp/katago runtests

# Search tests (requires model and config)
./cpp/katago runsearchtests -model <MODEL>.bin.gz -config <CONFIG>.cfg
```

### Python Tests

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r requirements-api.txt  # for real-time API tests

# Run real-time API tests
pytest tests/test_realtime_api.py
pytest tests/test_realtime_api_multitenancy.py
pytest tests/test_human_model.py
```

## Architecture Overview

### C++ Source Structure (`cpp/`)

Listed in dependency order from low to high level:

- **external/** - Third-party dependencies included inline
- **core/** - Low-level utilities (hashing, RNG, string ops, filesystem)
- **game/** - Board representation and rules
  - `board.{cpp,h}` - Core board without history (Benson's algorithm, ladder search)
  - `boardhistory.{cpp,h}` - Board with move history, handles superko, scoring, komi
  - `rules.{cpp,h}` - Rule variations support (Japanese, Chinese, etc.)
  - `graphhash.{cpp,h}` - History-sensitive hash for monte-carlo graph search
- **neuralnet/** - GPU backends and neural net interface
  - `nneval.{cpp,h}` - Top-level thread-safe batching wrapper
  - `nninputs.{cpp,h}` - Neural net input feature computation
  - `{cuda,opencl,eigen,trt,metal}backend.cpp` - Backend implementations
  - `desc.{cpp,h}` - Neural net structure and weights
- **search/** - MCTS engine
  - `search.{cpp,h}` - Multithreaded MCTS implementation
  - `searchparams.{cpp,h}` - Configurable search parameters
  - `asyncbot.{cpp,h}` - Thread-safe wrapper with pondering support
- **dataio/** - SGF I/O and training data writing
- **program/** - High-level utilities (setup, match running, stats)
- **command/** - User-facing subcommands (see Subcommands section)
- **tests/** - Tests and small models for testing

### Python Source Structure (`python/`)

**Training pipeline:**
- `shuffle.py` - Shuffles selfplay data into npz files for training
- `train.py` - Trains neural net from shuffled data using PyTorch
- `export_model_pytorch.py` - Exports PyTorch checkpoints to KataGo .bin.gz format
- `katago/train/model_pytorch.py` - Neural net architecture implementation
- `katago/train/data_processing_pytorch.py` - Data loading and augmentation
- `katago/train/modelconfigs.py` - Network size configurations (b6c96, etc.)

**Real-time API:**
- `realtime_api/main.py` - FastAPI server entry point
- `realtime_api/engine.py` - Core analysis engine logic
- `realtime_api/katago_wrapper.py` - KataGo process wrapper
- `realtime_api/config.py` - Config loading from `config.yaml`

**Selfplay scripts:**
- `selfplay/*.sh` - Bash wrappers for running training components (shuffle, train, export, etc.)

### Key Subcommands (`cpp/command/`)

- `gtp.cpp` - GTP engine for GUI integration
- `analysis.cpp` - JSON-based parallel analysis engine
- `benchmark.cpp` - Performance benchmarking
- `selfplay.cpp` - Selfplay data generation for training
- `gatekeeper.cpp` - Tests and filters nets during training
- `match.cpp` - Parallel match engine for testing parameters
- `contribute.cpp` - Distributed training contribution

## Configuration Files

Configs live in `cpp/configs/`:
- `gtp_example.cfg` - Standard GTP engine config
- `analysis_example.cfg` - Parallel analysis engine config
- `server_analysis.cfg` - Config for real-time API backend
- `training/*.cfg` - Selfplay and gatekeeper configs for training runs

**Key tuning parameters:**
- `numSearchThreads` - MCTS threads per position (tune with benchmark)
- `nnCacheSizePowerOfTwo` - Neural net cache size (increase for more RAM)
- `numAnalysisThreads` - Parallel positions to analyze (analysis engine only)
- `maxVisits` - Max playouts per move

## Selfplay Training

KataGo can train nets from scratch via selfplay. This requires significant GPU resources and involves 5 concurrent processes:

1. **Selfplay** (C++) - Generates games using latest accepted model
2. **Shuffler** (Python) - Shuffles selfplay data into training samples
3. **Training** (Python) - Trains neural net on shuffled data
4. **Exporter** (Python) - Converts PyTorch checkpoints to .bin.gz format
5. **Gatekeeper** (C++) - Tests and filters new models (optional)

### Synchronous Training (Single Machine)

For smaller runs or testing:

```bash
# Edit parameters in the script first
python/selfplay/synchronous_loop.sh
```

This loops through all 5 steps sequentially. Edit the script to configure board size, threads, GPU settings, etc.

### Asynchronous Training (Multi-Machine)

For production training, run all 5 processes simultaneously on different machines with a shared filesystem. See `SelfplayTraining.md` for detailed setup.

Example workflow:
```bash
# Selfplay (produces data)
./cpp/katago selfplay -output-dir $BASEDIR/selfplay \
  -models-dir $BASEDIR/models \
  -config cpp/configs/training/selfplay1.cfg

# Shuffler + exporter
cd python && ./selfplay/shuffle_and_export_loop.sh \
  $NAMEOFRUN $BASEDIR $TMPDIR $THREADS $BATCHSIZE $USE_GATING

# Training
cd python && ./selfplay/train.sh $BASEDIR $TRAININGNAME b6c96 \
  $BATCHSIZE main -lr-scale 1.0 -max-train-bucket-per-new-data 4

# Gatekeeper (optional)
./cpp/katago gatekeeper -rejected-models-dir $BASEDIR/rejected \
  -accepted-models-dir $BASEDIR/models \
  -test-models-dir $BASEDIR/modelstobetested \
  -config cpp/configs/training/gatekeeper1.cfg
```

## Development Notes

### Code Style

- **C++**: 2-space indentation, brace-on-same-line, see `.clang-format`
- **Python**: 4-space indentation, snake_case functions, CamelCase classes
- Prefer editing existing files over creating new ones

### Neural Net Models

Download models from [katagotraining.org](https://katagotraining.org/). Models use `.bin.gz` format.

Small test models are in `cpp/tests/models/` for testing without downloading.

The real-time API can auto-download models on first run if configured in `config.yaml`.

### Backend Selection

- **OpenCL**: Most compatible (NVIDIA, AMD, Intel GPUs). Auto-tunes on first run.
- **TensorRT**: Best performance for modern NVIDIA GPUs. Requires TensorRT 8.5+.
- **CUDA**: NVIDIA GPUs, requires CUDA + CUDNN.
- **Eigen**: CPU-only. Use `-DUSE_AVX2=1` on modern CPUs.
- **Metal**: MacOS GPU acceleration.

### TensorRT Version Compatibility

If system TensorRT version mismatches (e.g., v10 vs v8), extract compatible libraries via Docker:

```bash
mkdir -p libs/TensorRT-8.6/{include,lib}
docker pull nvcr.io/nvidia/tensorrt:23.10-py3
id=$(docker create nvcr.io/nvidia/tensorrt:23.10-py3)
docker cp $id:/usr/include/x86_64-linux-gnu/. libs/TensorRT-8.6/include/
docker cp $id:/usr/lib/x86_64-linux-gnu/. libs/TensorRT-8.6/lib/
docker rm -v $id

# Build with local path
cd cpp
cmake . -DUSE_BACKEND=TENSORRT -DTENSORRT_ROOT_DIR=../libs/TensorRT-8.6
make -j$(nproc)

# Run with library path
export LD_LIBRARY_PATH=$(pwd)/../libs/TensorRT-8.6/lib:$LD_LIBRARY_PATH
./katago benchmark -model <MODEL>.bin.gz -config <CONFIG>.cfg
```

### Distributed Training

For contributing to the public distributed run, use:

```bash
./cpp/katago contribute -config cpp/configs/contribute_example.cfg
```

Backend scripts (`upload_model.py`, `upload_poses.py`) are only needed if running your own katago-server instance.

### Important Files

- `SelfplayTraining.md` - Comprehensive selfplay training guide
- `docs/Analysis_Engine.md` - Analysis engine protocol and usage
- `docs/GTP_Extensions.md` - KataGo-specific GTP commands (kata-analyze, etc.)
- `docs/KataGoMethods.md` - Training techniques and improvements
- `docs/GraphSearch.md` - Monte-carlo graph search explanation
- `docs/RealTimeAPI_TestGuide.md` - Real-time API testing guide
