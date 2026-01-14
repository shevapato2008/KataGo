# Tech Stack: KataGo Local Analysis

## Core Engine (C++)
- **Language:** C++17
- **Build System:** CMake (minimum version 3.18.2)
- **Neural Network Backends:**
    - CUDA (NVIDIA GPUs)
    - TensorRT (NVIDIA GPUs, optimized)
    - OpenCL (General GPU support)
    - Metal (macOS specific)
    - Eigen (CPU-based)
- **Key Libraries:** 
    - ZLib (Compression)
    - Libzip (SGF handling)
    - OpenSSL (Distributed training support)
    - TCLAP (Command line argument parsing)

## API and Tooling (Python)
- **Language:** Python 3
- **Framework:** FastAPI (REST API)
- **Server:** Uvicorn (ASGI server)
- **Deep Learning:** PyTorch 2.2.0
- **Data Processing:** NumPy 1.26.4, sgfmill 1.1.1
- **Serialization/Config:** Pydantic 2.6.1, orjson 3.9.15, PyYAML 6.0.1
- **Testing:** Pytest 8.0.1, pytest-asyncio, httpx

## Architecture
- **Monorepo:** Single repository containing both the high-performance C++ engine and the Python service layers.
- **Inter-process Communication:** The Python API wraps the KataGo C++ executable, communicating via standard input/output (GTP or JSON analysis protocol).
