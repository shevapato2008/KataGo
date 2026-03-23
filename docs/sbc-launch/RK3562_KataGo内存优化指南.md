# RK3562 KataGo 内存优化指南

## 问题背景

RK3562 只有 2GB 物理内存 + 2GB swap（eMMC），运行 KataGo 加载两个模型时触发 OOM。

根本原因：

1. 主模型 `b28c512`（28 blocks, 512 channels）是 KataGo 最大的模型，权重加载到内存约 1GB
2. Human 模型 `b18c384` 额外占用约 400MB
3. 搜索线程数 8、分析线程数 8，每个 Eigen backend thread 都维护独立的神经网络 buffer
4. NN 缓存 `nnCacheSizePowerOfTwo = 23`（8M 条目）占用大量内存

---

## 已实现方案：SBC 启动模式

通过 `--mode` 参数区分服务器和单板机的启动方式，一套代码适配两种运行环境。

### 启动方式

```bash
# 服务器模式（默认）— 使用 config.yaml，加载 b28c512 + human model
PYTHONPATH=python python3 -m realtime_api.main

# SBC 模式 — 使用 config.sbc.yaml，加载 b18c384，无 human model
PYTHONPATH=python python3 -m realtime_api.main --mode sbc
```

### 配置文件对应关系

| 模式 | 应用配置 | 引擎配置 | 主模型 | Human 模型 |
|------|---------|---------|-------|-----------|
| `server` | `config.yaml` | `cpp/configs/server_analysis.cfg` | b28c512 | b18c384 |
| `sbc` | `config.sbc.yaml` | `cpp/configs/rk3562_analysis.cfg` | b18c384 | 无 |

### SBC 模式关键参数（`rk3562_analysis.cfg`）

```ini
numSearchThreads = 1            # 单搜索线程
numAnalysisThreads = 1          # 单分析线程
nnCacheSizePowerOfTwo = 16      # 64K 缓存条目（vs 默认 8M）
nnMaxBatchSize = 1              # 单批次
nnMutexPoolSizePowerOfTwo = 12  # 4K mutex pool
maxVisits = 200                 # 足够日常对弈
numEigenThreadsPerModel = 2     # Eigen 模式下限制 CPU 线程
```

### 预估 SBC 模式内存占用

| 组件 | 占用 |
|------|------|
| 系统（Debian + 桌面） | ~300-500MB |
| b18c384 模型 + 1 线程 | ~450MB |
| KaTrain / 其他应用 | ~200MB |
| **合计** | **~950MB - 1.15GB** |

在 2GB 物理内存下有充足余量，swap 仅作为安全网。

---

## 可选模型对比

| 模型 | 参数规模 | 文件大小 | 单线程内存占用 | 棋力 |
|------|---------|---------|-------------|------|
| kata1-b6c96 | 6 blocks, 96 channels | ~15MB | ~100MB | 业余5-6段 |
| kata1-b18c384 | 18 blocks, 384 channels | ~120MB | ~400MB | 职业级 |
| kata1-b28c512 | 28 blocks, 512 channels | ~800MB | ~1GB+ | 最强 |

当前 SBC 模式选用 `b18c384`（职业级），满足低段位对弈需求。高段位对弈和复盘请求转发至服务器。

---

## 系统层面优化（可选）

### 关闭不必要的服务（省约 400MB）

```bash
# Docker（最大头，省 ~104MB）
sudo systemctl disable --now docker docker.socket containerd

# 蓝牙（省 ~92MB）
sudo systemctl disable --now bluetooth

# VPN 相关
sudo systemctl disable --now strongswan-starter xl2tpd

# 4G 模块服务
sudo systemctl disable --now quectel-CM

# 文件索引
sudo systemctl mask tracker-miner-fs
```

### 桌面进程优化

```bash
# 关闭虚拟键盘（省 ~67MB）
killall onboard

# 关闭蓝牙托盘（省 ~44MB）
killall blueman-tray blueman-applet

# 关闭文件管理器守护进程（省 ~41MB）
killall Thunar
```

### 不启动桌面（最激进，省 ~300MB）

如果主要通过 SSH 操作，可以默认不启动图形界面：

```bash
sudo systemctl set-default multi-user.target

# 需要桌面时手动启动
sudo systemctl start display-manager
```

### Swap 调优

```bash
# 降低 swappiness，尽量用物理内存
echo 'vm.swappiness=10' >> /etc/sysctl.conf
sysctl vm.swappiness=10
```

不建议进一步扩大 swap。eMMC 的随机读写性能很差，频繁使用 swap 会让 KataGo 推理极慢且加速 eMMC 磨损。swap 应作为安全网而非日常依赖。

如果确实需要更多 swap 空间，建议外接 USB3.0 SSD 并将 swap 放在 SSD 上。
