# RK3588 Benchmark Results: OpenCL (Mali-G610) vs Eigen (CPU)

**Date:** 2026-02-12
**Board:** Rockchip RK3588 DXB LP4 V10 Board (D-3588, 亮钻科技)
**OS:** Ubuntu 20.04.6 LTS, Kernel 5.10.198
**GPU Driver:** libmali-valhall-g610-g13p0-x11-gbm v1.9
**KataGo Version:** v1.16.4

## Test Configuration

- **Model:** kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz (b28c512)
- **Board Size:** 19x19
- **maxVisits:** 500 (default benchmark)
- **OpenCL FP16:** Disabled (`openclUseFP16=false`)
  - Reason: Mali-G610 lacks WMMA support; hGemmWmma kernel compilation fails
  - FP32 used for all OpenCL kernels

## Results: Eigen (CPU) Backend

| Threads | visits/s | nnEvals/s | nnBatches/s | avgBatchSize | Time (s) | EloDiff |
|---------|----------|-----------|-------------|--------------|----------|---------|
| 3       | 1.20     | 1.14      | 1.13        | 1.00         | 684.9    | baseline |
| 4       | 1.47     | 1.41      | 1.40        | 1.01         | 565.5    | +61     |
| **5**   | **1.60** | 1.56      | 1.54        | 1.01         | 525.4    | +79     |
| **6**   | **1.62** | **1.59**  | 1.57        | 1.01         | 523.4    | +73     |
| 8       | 1.53     | 1.52      | 1.49        | 1.02         | 568.7    | +25     |
| 12      | 1.54     | 1.56      | 1.21        | 1.29         | 590.5    | -22     |

**Best Eigen config:** 5-6 threads, ~1.62 visits/s

**Observations:**
- Performance peaks at 5-6 threads (matches 4x Cortex-A76 big cores + partial A55 help)
- Beyond 6 threads, small cores (Cortex-A55) drag down overall performance
- Batch size stays at ~1.0 (CPU backend processes one evaluation at a time)
- nnEvals/s bottleneck at ~1.59 regardless of thread count

## Results: OpenCL (Mali-G610) Backend

| Threads | visits/s | nnEvals/s | nnBatches/s | avgBatchSize | Time (s) | EloDiff |
|---------|----------|-----------|-------------|--------------|----------|---------|
| 3       | 3.98     | 3.29      | 2.17        | 1.52         | 2016.3   | baseline |
| 4       | 3.86     | 3.28      | 1.55        | 2.12         | 2078.7   | -23     |
| 5       | 4.38     | 3.65      | 1.45        | 2.51         | 1835.5   | +10     |
| **6**   | **4.54** | 3.79      | 1.21        | 3.14         | 1770.7   | **+11** |
| 8       | 4.71     | 3.93      | 0.92        | 4.29         | 1713.2   | -0      |
| **12**  | **4.97** | **4.18**  | 0.70        | **5.97**     | 1631.9   | -30     |

**Best OpenCL config for raw speed:** 12 threads, 4.97 visits/s
**Best OpenCL config for playing strength:** 5-6 threads (EloDiff +10/+11)

**Observations:**
- More threads = larger batch sizes = better GPU utilization = higher visits/s
- But EloDiff peaks at 5-6 threads — too many threads trades search quality for speed
- 12 threads achieve avgBatchSize 5.97 but EloDiff -30 (search quality degradation)
- For analysis (high visits): prefer 8-12 threads for throughput
- For playing (fixed time): prefer 5-6 threads for strongest play

## Head-to-Head Comparison

| Metric | Eigen (best) | OpenCL (best) | Speedup |
|--------|-------------|---------------|---------|
| visits/s | 1.62 (6t) | 4.97 (12t) | **3.07x** |
| nnEvals/s | 1.59 (6t) | 4.18 (12t) | **2.63x** |
| avgBatchSize | 1.01 | 5.97 | 5.9x |

**At same thread count (5 threads):**

| Metric | Eigen | OpenCL | Speedup |
|--------|-------|--------|---------|
| visits/s | 1.60 | 4.38 | **2.74x** |
| nnEvals/s | 1.56 | 3.65 | **2.34x** |

## Conclusion

**OpenCL (Mali-G610) is the clear winner**, delivering **3.07x speedup** over Eigen at optimal configurations.

### Recommended Configuration
- **Backend:** OpenCL
- **For playing/对弈:** `numSearchThreads=5-6` (best EloDiff, ~4.5 visits/s)
- **For analysis/分析:** `numSearchThreads=8-12` (max throughput, ~5 visits/s)
- **openclUseFP16:** false (WMMA not supported on Mali)
- **Expected visits/s on b28c512:** 4.4-5.0 visits/s depending on thread count

### Key Advantages of OpenCL
1. GPU parallelism enables effective batching (5-6x batch size improvement)
2. Neural network evaluations are ~2.6x faster
3. Frees CPU cores for search tree operations
4. Scales better with more search threads

### Caveats
1. First-run auto-tune takes ~10 minutes (one-time cost, cached afterward)
2. No FP16 acceleration (Mali WMMA not available)
3. Requires `libmali` driver and `/dev/mali0` device access
4. Docker deployment needs `--device /dev/mali0` and driver volume mounts
