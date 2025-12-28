FROM nvcr.io/nvidia/tensorrt:23.10-py3

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    libssl-dev \
    libzip-dev \
    python3-pip \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy source
COPY . /app

# Install Python dependencies
RUN python3 -m pip install --no-cache-dir -r /app/requirements.txt

# Build
WORKDIR /app/cpp
# Clean up any local build artifacts that might have been copied
RUN rm -rf CMakeCache.txt CMakeFiles cmake_install.cmake Makefile katago

# Configure and Build
RUN cmake . -DUSE_BACKEND=TENSORRT -DNO_GIT_REVISION=1 && \
    make -j$(nproc)

WORKDIR /app
RUN mkdir -p /app/models

ENV PYTHONPATH=/app/python
ENV KATAGO_CONFIG_FILE=/app/config.yaml
EXPOSE 8000

CMD ["python3", "-m", "realtime_api.main"]
