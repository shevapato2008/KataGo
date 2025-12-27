FROM nvcr.io/nvidia/tensorrt:23.10-py3

# Install dependencies
RUN apt-get update && apt-get install -y \
    cmake \
    git \
    libssl-dev \
    libzip-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy source
COPY . /app

# Build
WORKDIR /app/cpp
# Clean up any local build artifacts that might have been copied
RUN rm -rf CMakeCache.txt CMakeFiles cmake_install.cmake Makefile katago

# Configure and Build
RUN cmake . -DUSE_BACKEND=TENSORRT -DNO_GIT_REVISION=1 && \
    make -j$(nproc)
