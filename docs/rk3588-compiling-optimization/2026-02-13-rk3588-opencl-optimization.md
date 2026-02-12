# RK3588 KataGo 编译优化实施计划：OpenCL (Mali-G610) vs Eigen (CPU)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 RK3588 上验证 OpenCL (Mali-G610 GPU) 后端是否比 Eigen (CPU) 后端更快，并产出最优的 Docker 编译方案。

**Architecture:** 分三阶段进行——先在 RK3588 上搭建 OpenCL 环境并编译 KataGo OpenCL 版本，然后与现有 Eigen 版本做 benchmark 对比，最后根据结果更新 Dockerfile 和部署文档。

**Tech Stack:** CMake, ARM GCC, OpenCL 1.2+, libmali (Mali-G610 驱动), Eigen3, Docker (ARM64)

---

## 背景

### 当前状况
- RK3588 板卡 (D-3588, 亮钻科技) 使用 Eigen CPU 后端运行 KataGo
- 现有 `Dockerfile.rk3588` 使用 `-DUSE_BACKEND=EIGEN -march=armv8-a+crypto -mtune=cortex-a76`
- 用户反馈"运行很慢"

### RK3588 硬件
| 计算单元 | 规格 | KataGo 可用后端 |
|---------|------|---------------|
| CPU 大核 | 4x Cortex-A76 + NEON | Eigen (当前) |
| CPU 小核 | 4x Cortex-A55 | Eigen (贡献有限) |
| GPU | Mali-G610 MP4, OpenCL 2.2/3.0 | **OpenCL (待验证)** |
| NPU | 6 TOPS RKNN | 无对应后端 |

### 预期收益
根据调研，Mali-G610 OpenCL 计算能力约为 CPU 的 **2-6 倍**（取决于负载类型）。KataGo 的卷积运算属于 GPU 擅长的并行计算，预期有 **2-4 倍提速**。

### 关键风险
1. Mali OpenCL 驱动可能不稳定或不完整
2. KataGo 的 OpenCL kernel (Winograd 变换) 未在 Mali 上调优过
3. auto-tune 过程可能失败或产生极差参数
4. FP16 支持 (`cl_khr_fp16`) 不确定

### 关键代码文件参考
- 后端选择: `cpp/CMakeLists.txt:127-148`（OpenCL 和 Eigen 后端定义）
- ARM 检测: `cpp/CMakeLists.txt:555-561`（ARM 架构自动添加 `-fsigned-char`）
- OpenCL 设备发现: `cpp/neuralnet/openclhelpers.cpp:346-448`
- OpenCL 自动调优: `cpp/neuralnet/opencltuner.cpp`（`autoTuneEverything` 函数）
- FP16 支持检测: `cpp/neuralnet/openclhelpers.cpp:448`
- 现有 RK3588 Dockerfile: `Dockerfile.rk3588:36-39`

---

## Phase 1: RK3588 上搭建 OpenCL 环境

### Task 1: 确认板卡硬件信息

**在 RK3588 板卡上执行以下命令，记录输出。**

**Step 1: 采集板卡身份信息**

```bash
# 板卡型号（最关键）
tr -d '\0' </proc/device-tree/model; echo
tr -d '\0' </proc/device-tree/compatible; echo

# 系统信息
uname -a
cat /etc/os-release

# CPU 信息
lscpu | head -20

# 已有 GPU 驱动
ls -la /usr/lib/aarch64-linux-gnu/libmali* 2>/dev/null || echo "No libmali found"
ls -la /usr/lib/libmali* 2>/dev/null || echo "No libmali found in /usr/lib"
```

**Expected:** 能看到 `Cortex-A76`/`Cortex-A55`，以及操作系统版本。

**Step 2: 检查现有 OpenCL 支持**

```bash
# 检查是否已有 OpenCL
apt list --installed 2>/dev/null | grep -i -E "opencl|mali|mesa"
ldconfig -p | grep -i -E "OpenCL|mali"

# 如果 clinfo 已安装
clinfo 2>/dev/null || echo "clinfo not installed"
```

**Expected:** 大概率没有 OpenCL 环境，需要在 Task 2 中安装。

**Step 3: 记录结果**

将上述输出保存到 `docs/rk3588-compiling-optimization/hardware-info.txt`。

---

### Task 2: 安装 Mali OpenCL 驱动 (libmali)

**核心依赖:** RK3588 的 Mali-G610 OpenCL 支持需要 Rockchip 提供的 `libmali` 闭源驱动。

**Step 1: 获取 libmali 驱动**

方法 A — 从厂商固件中提取（最稳）：
```bash
# 厂商固件通常已包含 libmali，检查位置
find / -name "libmali*" -o -name "libOpenCL*" 2>/dev/null
```

方法 B — 从 Rockchip GitHub 仓库获取：
```bash
# Rockchip 官方 libmali 仓库（选择 g610 对应版本）
git clone https://github.com/JeffyCN/rockchip_mirrors.git --depth 1
# 或直接下载对应 .deb / .so
# 参考: https://clehaxze.tw/gemlog/2023/06-17-setting-up-opencl-on-rk3588-using-libmali.gmi
```

方法 C — 使用 Armbian / ubuntu-rockchip 的 mali 包：
```bash
# 如果使用 Armbian，可能有 mali-g610 的打包
apt search mali 2>/dev/null
```

**Step 2: 安装驱动和 OpenCL 头文件**

```bash
# 安装 OpenCL 头文件和 ICD loader
sudo apt-get update
sudo apt-get install -y ocl-icd-opencl-dev opencl-headers clinfo

# 复制 libmali.so 到系统路径（如果是手动获取的）
# sudo cp libmali-valhall-g610-g13p0-gbm.so /usr/lib/aarch64-linux-gnu/libmali.so
# sudo ln -sf /usr/lib/aarch64-linux-gnu/libmali.so /usr/lib/aarch64-linux-gnu/libOpenCL.so
# sudo ln -sf /usr/lib/aarch64-linux-gnu/libmali.so /usr/lib/aarch64-linux-gnu/libOpenCL.so.1

# 创建 ICD 注册文件
# sudo mkdir -p /etc/OpenCL/vendors
# echo "/usr/lib/aarch64-linux-gnu/libmali.so" | sudo tee /etc/OpenCL/vendors/mali.icd
```

**Step 3: 验证 OpenCL 环境**

```bash
clinfo
```

**Expected output (关键字段):**
```
Number of platforms:                 1
  Platform Name:                     ARM Platform
  Platform Version:                  OpenCL 3.0
Number of devices:                   1
  Device Name:                       Mali-G610
  Device Type:                       GPU
  Device Version:                    OpenCL 3.0
  Extensions:                        cl_khr_fp16 ...  <-- 关注是否有 fp16 支持
  Max compute units:                 4               <-- Mali-G610 MP4 = 4 核
  Max work group size:               ...
  Global memory size:                ...              <-- 与 CPU 共享内存
```

**如果 clinfo 能看到 Mali-G610 GPU，继续 Task 3。如果失败，排查驱动安装问题。**

**Step 4: Commit**

```bash
git add docs/rk3588-compiling-optimization/hardware-info.txt
git commit -m "docs: add RK3588 hardware info for OpenCL investigation"
```

---

### Task 3: 编译 KataGo OpenCL 版本

**Step 1: 安装编译依赖**

```bash
sudo apt-get install -y \
    build-essential \
    cmake \
    git \
    libssl-dev \
    libzip-dev \
    zlib1g-dev \
    ocl-icd-opencl-dev \
    opencl-headers \
    pkg-config \
    libatomic1
```

**Step 2: 编译 KataGo OpenCL 版本**

```bash
cd /path/to/KataGo/cpp

# 清理旧构建
rm -rf CMakeCache.txt CMakeFiles cmake_install.cmake Makefile

# 编译 OpenCL 版本（ARM 优化）
cmake . -DUSE_BACKEND=OPENCL \
    -DNO_GIT_REVISION=1 \
    -DCMAKE_CXX_FLAGS="-march=armv8-a+crypto -mtune=cortex-a76 -fsigned-char"

make -j4
```

**Expected:** 编译成功，生成 `katago` 二进制文件。

**如果编译失败，常见问题：**
- `OpenCL not found` → 检查 `libOpenCL.so` 路径，可能需要 `-DOpenCL_LIBRARY=/usr/lib/aarch64-linux-gnu/libmali.so`
- 链接错误 → 确认 libmali.so 暴露了 OpenCL symbols：`nm -D /usr/lib/aarch64-linux-gnu/libmali.so | grep clCreate`

**Step 3: 验证编译产物**

```bash
./katago version
# 应该显示 OpenCL backend
```

**Step 4: 首次运行 auto-tune**

这是关键步骤。KataGo OpenCL 首次运行会对 GPU 进行调优，生成 `KataGoOpenCLTuner` 缓存文件。

```bash
# 使用小模型做 tune（减少时间）
./katago benchmark \
    -model /path/to/b18c384nbt-humanv0.bin.gz \
    -config ../cpp/configs/gtp_example.cfg \
    -override-config "numSearchThreads=1"
```

**Expected:**
- 首次运行会输出 "Tuning OpenCL kernels..." 并花费 **5-30 分钟**
- 如果 tune 成功，会在 `~/.katago/` 或当前目录生成 tuning 缓存
- 如果 tune 失败（kernel 编译错误），记录错误信息

**可能的调优失败原因：**
- Mali OpenCL 编译器不支持某些 kernel 语法
- FP16 kernel 编译失败（可通过 `-override-config "openclUseFP16=false"` 绕过）
- 工作组大小超限（Mali 可能有较小的 max work group size）

**Step 5: Commit**

不需要提交编译产物，只需记录编译命令和调优结果。

---

## Phase 2: Benchmark 对比

### Task 4: 运行 Eigen 版本 Benchmark

**Step 1: 编译 Eigen 版本（如已有可跳过）**

```bash
cd /path/to/KataGo/cpp

rm -rf CMakeCache.txt CMakeFiles cmake_install.cmake Makefile

cmake . -DUSE_BACKEND=EIGEN \
    -DNO_GIT_REVISION=1 \
    -DCMAKE_CXX_FLAGS="-march=armv8-a+crypto -mtune=cortex-a76 -fsigned-char"

make -j4

# 重命名以区分
cp katago katago-eigen
```

**Step 2: 运行标准 Benchmark**

```bash
# 小模型 (b18c384)
./katago-eigen benchmark \
    -model /path/to/b18c384nbt-humanv0.bin.gz \
    -config ../cpp/configs/gtp_example.cfg \
    -override-config "numSearchThreads=4" \
    2>&1 | tee benchmark-eigen-b18-t4.log

# 大模型 (b28c512)
./katago-eigen benchmark \
    -model /path/to/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz \
    -config ../cpp/configs/gtp_example.cfg \
    -override-config "numSearchThreads=4" \
    2>&1 | tee benchmark-eigen-b28-t4.log
```

**Step 3: 记录关键指标**

从 benchmark 输出中提取：
- `Visits/s` (核心指标)
- `NNEvals/s` (神经网络评估速度)
- 内存占用 (通过 `top` 或 `htop` 观察)

保存到 `docs/rk3588-compiling-optimization/benchmark-results.md`。

---

### Task 5: 运行 OpenCL 版本 Benchmark

**Step 1: 运行标准 Benchmark**

```bash
# 重命名 OpenCL 版本
cp katago katago-opencl

# 小模型 (b18c384) — 单线程（OpenCL 通常不需要多搜索线程）
./katago-opencl benchmark \
    -model /path/to/b18c384nbt-humanv0.bin.gz \
    -config ../cpp/configs/gtp_example.cfg \
    -override-config "numSearchThreads=1" \
    2>&1 | tee benchmark-opencl-b18-t1.log

# 小模型 — 2 线程
./katago-opencl benchmark \
    -model /path/to/b18c384nbt-humanv0.bin.gz \
    -config ../cpp/configs/gtp_example.cfg \
    -override-config "numSearchThreads=2" \
    2>&1 | tee benchmark-opencl-b18-t2.log

# 大模型 (b28c512) — 单线程
./katago-opencl benchmark \
    -model /path/to/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz \
    -config ../cpp/configs/gtp_example.cfg \
    -override-config "numSearchThreads=1" \
    2>&1 | tee benchmark-opencl-b28-t1.log

# 如果支持 FP16，额外测试
./katago-opencl benchmark \
    -model /path/to/b18c384nbt-humanv0.bin.gz \
    -config ../cpp/configs/gtp_example.cfg \
    -override-config "numSearchThreads=1,openclUseFP16=true" \
    2>&1 | tee benchmark-opencl-b18-fp16.log
```

**Step 2: 更新 benchmark 结果文档**

将 OpenCL 结果追加到 `docs/rk3588-compiling-optimization/benchmark-results.md`。

**Expected 结果表格模板:**

```markdown
## Benchmark 结果对比

测试环境: RK3588 (D-3588), Ubuntu XX.XX, 模型 b18c384nbt-humanv0

| 后端 | 线程数 | FP16 | Visits/s | NNEvals/s | 内存(MB) |
|------|--------|------|----------|-----------|----------|
| Eigen | 4 | N/A | ??? | ??? | ??? |
| OpenCL | 1 | off | ??? | ??? | ??? |
| OpenCL | 2 | off | ??? | ??? | ??? |
| OpenCL | 1 | on  | ??? | ??? | ??? |

结论: OpenCL 比 Eigen 快 ???x / 慢 ???x
```

**Step 3: Commit**

```bash
git add docs/rk3588-compiling-optimization/benchmark-results.md
git commit -m "docs: add RK3588 Eigen vs OpenCL benchmark results"
```

---

## Phase 3: 根据结果更新部署方案

### Task 6 (如果 OpenCL 胜出): 创建 Dockerfile.rk3588-opencl

**Files:**
- Create: `Dockerfile.rk3588-opencl`
- Reference: `Dockerfile.rk3588` (现有 Eigen 版本)

**Step 1: 编写 OpenCL Dockerfile**

```dockerfile
# Stage 1: Builder
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ jammy main restricted universe multiverse" > /etc/apt/sources.list && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ jammy-updates main restricted universe multiverse" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ jammy-backports main restricted universe multiverse" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ jammy-security main restricted universe multiverse" >> /etc/apt/sources.list

# Install build dependencies (including OpenCL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    libssl-dev \
    libzip-dev \
    zlib1g-dev \
    ocl-icd-opencl-dev \
    opencl-headers \
    pkg-config \
    python3-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
WORKDIR /app/cpp

RUN rm -rf CMakeCache.txt CMakeFiles cmake_install.cmake Makefile katago

# Build with OpenCL backend + ARM optimizations
RUN cmake . -DUSE_BACKEND=OPENCL -DNO_GIT_REVISION=1 \
    -DCMAKE_CXX_FLAGS="-march=armv8-a+crypto -mtune=cortex-a76" && \
    make -j2

# Stage 2: Runtime
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ jammy main restricted universe multiverse" > /etc/apt/sources.list && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ jammy-updates main restricted universe multiverse" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ jammy-backports main restricted universe multiverse" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ jammy-security main restricted universe multiverse" >> /etc/apt/sources.list

# Runtime dependencies: OpenCL ICD loader + libmali
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    libzip4 \
    zlib1g \
    libssl3 \
    libatomic1 \
    ocl-icd-libopencl1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# CRITICAL: Copy Mali GPU driver from host
# The libmali.so must be provided by the host system or pre-installed
# Option 1: Mount from host at runtime via docker --device and volume
# Option 2: Copy a pre-built libmali into the image (uncomment below)
# COPY libmali-valhall-g610-g13p0-gbm.so /usr/lib/aarch64-linux-gnu/libmali.so
# RUN ln -sf /usr/lib/aarch64-linux-gnu/libmali.so /usr/lib/aarch64-linux-gnu/libOpenCL.so.1 && \
#     mkdir -p /etc/OpenCL/vendors && \
#     echo "/usr/lib/aarch64-linux-gnu/libmali.so" > /etc/OpenCL/vendors/mali.icd

WORKDIR /app

COPY python /app/python
COPY config.yaml /app/config.yaml
COPY requirements-api.txt /app/
COPY cpp/configs /app/cpp/configs

RUN python3 -m pip install --trusted-host pypi.tuna.tsinghua.edu.cn \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --default-timeout=100 --no-cache-dir --upgrade pip wheel && \
    python3 -m pip install --trusted-host pypi.tuna.tsinghua.edu.cn \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --default-timeout=100 --no-cache-dir -r requirements-api.txt

COPY --from=builder /app/cpp/katago /app/cpp/katago

RUN mkdir -p /app/models

ARG MODEL_BASE_URL=https://go.sailorvoyage.top/docs
RUN if [ -z "$(ls -A /app/models)" ]; then \
    apt-get update && apt-get install -y wget && \
    wget -q ${MODEL_BASE_URL}/b18c384nbt-humanv0.bin.gz -O /app/models/b18c384nbt-humanv0.bin.gz && \
    wget -q ${MODEL_BASE_URL}/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz -O /app/models/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz && \
    apt-get purge -y wget && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*; \
    fi

ENV PYTHONPATH=/app/python
ENV KATAGO_CONFIG_FILE=/app/config.yaml
ENV PATH="/app/cpp:${PATH}"

EXPOSE 8000

# NOTE: Docker run 需要挂载 GPU 设备和 Mali 驱动
# docker run --device /dev/mali0 \
#   -v /usr/lib/aarch64-linux-gnu/libmali.so:/usr/lib/aarch64-linux-gnu/libmali.so:ro \
#   -v /etc/OpenCL:/etc/OpenCL:ro \
#   -p 8000:8000 katago-rk3588-opencl

CMD ["python3", "-m", "realtime_api.main"]
```

**Step 2: 验证编译**

```bash
docker build -t katago-rk3588-opencl -f Dockerfile.rk3588-opencl .
```

**Step 3: 运行测试**

```bash
docker run --device /dev/mali0 \
    -v /usr/lib/aarch64-linux-gnu/libmali.so:/usr/lib/aarch64-linux-gnu/libmali.so:ro \
    -v /etc/OpenCL:/etc/OpenCL:ro \
    -p 8000:8000 \
    katago-rk3588-opencl
```

**Step 4: Commit**

```bash
git add Dockerfile.rk3588-opencl
git commit -m "feat: add RK3588 OpenCL (Mali-G610) Dockerfile"
```

---

### Task 7 (如果 Eigen 仍然更优): 优化现有 Eigen 方案

**如果 OpenCL 方案因驱动问题失败或性能不如预期，专注优化 Eigen 方案。**

**Files:**
- Modify: `Dockerfile.rk3588`
- Modify: `cpp/configs/server_analysis.cfg` (或创建 RK3588 专用配置)

**Step 1: 优化编译参数**

```bash
# 在 Dockerfile.rk3588 中，把 -O2 (默认) 升级到 -O3
cmake . -DUSE_BACKEND=EIGEN -DNO_GIT_REVISION=1 \
    -DCMAKE_CXX_FLAGS="-march=armv8-a+crypto -mtune=cortex-a76 -O3 -fsigned-char"
```

> 注意: KataGo 的 CMakeLists.txt 默认设置 `-g -O2` (line 570)。
> 覆盖为 `-O3` 可能带来 5-15% 的性能提升，但需要 benchmark 验证。

**Step 2: 创建 RK3588 专用运行时配置**

创建 `cpp/configs/rk3588_analysis.cfg`，关键参数：

```ini
# RK3588 Eigen 优化配置
# 只用 4 个大核 (Cortex-A76)，避免小核拖慢
numSearchThreads = 4

# 神经网络缓存（RK3588 8GB 内存，留 4GB 给系统和浏览器）
nnCacheSizePowerOfTwo = 20

# 分析引擎并发（端侧建议低并发）
numAnalysisThreads = 1

# 每步预算（分级对弈用 maxTime 更稳定）
# 低难度: maxVisits = 50,  maxTime = 0.2
# 中难度: maxVisits = 200, maxTime = 0.5
# 高难度: maxVisits = 800, maxTime = 1.0
# 最高:   maxVisits = 2000, maxTime = 2.0

# 关闭 pondering（端侧省 CPU）
ponderingEnabled = false
```

**Step 3: 更新 Dockerfile.rk3588 编译优化**

修改 `Dockerfile.rk3588:37-39`，添加 `-O3`：

```dockerfile
RUN cmake . -DUSE_BACKEND=EIGEN -DNO_GIT_REVISION=1 \
    -DCMAKE_CXX_FLAGS="-march=armv8-a+crypto -mtune=cortex-a76 -O3" && \
    make -j2
```

**Step 4: Benchmark 验证 -O3 的提升**

```bash
# 对比 -O2 (默认) 和 -O3 的 visits/s
./katago-eigen-O2 benchmark -model model.bin.gz -config rk3588_analysis.cfg
./katago-eigen-O3 benchmark -model model.bin.gz -config rk3588_analysis.cfg
```

**Step 5: Commit**

```bash
git add Dockerfile.rk3588 cpp/configs/rk3588_analysis.cfg
git commit -m "perf: optimize RK3588 Eigen build with -O3 and dedicated config"
```

---

### Task 8: 更新部署文档

**Files:**
- Modify: `docs/sbc-setup/RK3588_deployment.md`
- Create: `docs/rk3588-compiling-optimization/SUMMARY.md`

**Step 1: 编写总结文档**

`docs/rk3588-compiling-optimization/SUMMARY.md` 应包含：

```markdown
# RK3588 KataGo 编译优化总结

## 测试结论

(根据 Phase 2 benchmark 结果填写)

### 推荐方案: [OpenCL / Eigen]

- 推荐后端: ???
- 推荐编译参数: ???
- 推荐运行时配置: ???
- Visits/s: ???

### 备选方案

(如果主方案不可用的 fallback)

## 已知限制

- Mali-G610 OpenCL 驱动状况: ???
- Auto-tune 结果: ???
- FP16 支持: ???

## 散热与持续性能

- 持续 30 分钟运行后性能衰减: ???%
- 建议散热方案: ???
```

**Step 2: 更新 RK3588_deployment.md**

在现有文档中添加"编译优化"章节，引用本次测试结果。

**Step 3: Commit**

```bash
git add docs/rk3588-compiling-optimization/SUMMARY.md docs/sbc-setup/RK3588_deployment.md
git commit -m "docs: add RK3588 compilation optimization results and recommendations"
```

---

## 决策树总结

```
开始
  │
  ├─ Task 1-2: 搭建 OpenCL 环境
  │     │
  │     ├─ clinfo 能识别 Mali-G610? ──No──→ 排查驱动，尝试不同 libmali 版本
  │     │                                    │
  │     │                                    └─ 仍然失败? → 放弃 OpenCL，走 Task 7 优化 Eigen
  │     │
  │     └─ Yes → Task 3: 编译 OpenCL 版 KataGo
  │           │
  │           ├─ 编译成功? ──No──→ 检查 OpenCL 库路径，尝试指定 -DOpenCL_LIBRARY
  │           │
  │           └─ Yes → auto-tune 成功?
  │                 │
  │                 ├─ No → 尝试 openclUseFP16=false，或手动调整 tuning 参数
  │                 │
  │                 └─ Yes → Task 4-5: Benchmark 对比
  │                       │
  │                       ├─ OpenCL > Eigen 1.5x+ → Task 6: 创建 OpenCL Dockerfile
  │                       │
  │                       └─ OpenCL <= Eigen → Task 7: 优化 Eigen 方案
  │
  └─ Task 8: 文档更新
```

---

## 附录: 散热与持续性能测试

无论最终选择哪个后端，必须做的验证：

```bash
# 连续运行 30 分钟，观察 visits/s 是否衰减
# 使用 while 循环反复 benchmark
for i in $(seq 1 10); do
    echo "=== Run $i ==="
    ./katago benchmark \
        -model /path/to/b18c384nbt-humanv0.bin.gz \
        -config rk3588_analysis.cfg \
        2>&1 | grep "visits/s"
    sleep 10
done
```

如果 visits/s 明显下降（>20%），说明降频严重，需要：
1. 添加主动散热（风扇）
2. 调整 CPU governor: `echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
3. 降低 `numSearchThreads` 从 4 到 3
