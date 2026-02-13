# RK3588 KataGo 编译优化总结

## 测试结论

### 推荐方案: OpenCL (Mali-G610 GPU)

- **推荐后端:** OpenCL
- **推荐编译参数:** `-DUSE_BACKEND=OPENCL -DCMAKE_CXX_FLAGS="-march=armv8-a+crypto -mtune=cortex-a76"`
- **推荐运行时配置:** `numSearchThreads=8-12, openclUseFP16=false`
- **Visits/s (b28c512 模型):** ~5 visits/s (OpenCL 12t) vs ~1.6 visits/s (Eigen 6t)
- **加速比:** **3.07x**

### 备选方案: Eigen (CPU)

如果 Mali 驱动不可用（Docker 未挂载 `/dev/mali0` 等情况），回退到 Eigen：
- **编译参数:** `-DUSE_BACKEND=EIGEN -DCMAKE_CXX_FLAGS="-march=armv8-a+crypto -mtune=cortex-a76"`
- **推荐线程数:** 5-6（仅使用 Cortex-A76 大核）
- **Visits/s (b28c512 模型):** ~1.6 visits/s

## 已知限制

### Mali-G610 OpenCL 驱动状况
- **驱动版本:** libmali-valhall-g610-g13p0-x11-gbm v1.9
- **OpenCL 版本:** 3.0（ICD loader 仅支持 2.1，但功能够用）
- **稳定性:** 正常运行，无崩溃
- **设备权限:** 需要 `video` 组权限访问 `/dev/mali0`

### Auto-tune 结果
- **xGemmDirect (1x1 convolutions):** 成功，最优 ~200 Calls/sec
- **xGemm (convolutions):** 成功，最优 ~208 Calls/sec
- **hGemmWmma (FP16 tensor):** 失败（Mali 不支持 WMMA 指令集）
- **Winograd transform/untransform:** 成功
- **调优缓存位置:** `~/.katago/opencltuning/tune11_gpuMaliG610r0p0_x19_y19_c*.txt`

### FP16 支持
- **硬件支持:** `cl_khr_fp16` 扩展存在
- **KataGo FP16:** 不可用（hGemmWmma 依赖 WMMA，Mali 不支持）
- **建议:** 始终使用 `openclUseFP16=false`

## Docker 部署

### OpenCL 版本
```bash
docker build -t katago-rk3588-opencl -f Dockerfile.rk3588-opencl .
docker run --device /dev/mali0 \
    -v /usr/lib/aarch64-linux-gnu/libmali.so.1:/usr/lib/aarch64-linux-gnu/libmali.so.1:ro \
    -v /etc/OpenCL:/etc/OpenCL:ro \
    -v katago-opencl-cache:/root/.katago \
    -p 8000:8000 katago-rk3588-opencl
```

### Eigen 版本 (Fallback)
```bash
docker build -t katago-rk3588-eigen -f Dockerfile.rk3588-eigen .
docker run -p 8000:8000 katago-rk3588-eigen
```

## 散热与持续性能

> 待补充：需要连续运行 30 分钟后测量 visits/s 衰减情况。
> 如果衰减 >20%，建议：
> 1. 添加主动散热（风扇）
> 2. `echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
> 3. 适当降低 `numSearchThreads`

## 文件清单

| 文件 | 用途 |
|------|------|
| `Dockerfile.rk3588-opencl` | OpenCL 版本 Docker 构建文件 |
| `Dockerfile.rk3588-eigen` | Eigen 版本 Docker 构建文件 (fallback) |
| `docs/rk3588-compiling-optimization/hardware-info.txt` | RK3588 硬件信息采集 |
| `docs/rk3588-compiling-optimization/benchmark-results.md` | 详细 benchmark 对比数据 |
| `docs/rk3588-compiling-optimization/SUMMARY.md` | 本文件 |
