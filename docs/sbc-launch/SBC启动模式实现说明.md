# SBC 启动模式实现说明

## 背景

智能棋盘使用 RK3562 单板机（2GB RAM + 2GB eMMC swap），直接使用服务器配置启动 KataGo 会 OOM。
需要一套轻量配置，满足低段位用户在棋盘上本地对弈的需求。高段位对弈和复盘请求转发至服务器。

## 改动清单

### 新增文件

| 文件 | 用途 |
| ---- | ---- |
| `cpp/configs/rk3562_analysis.cfg` | RK3562 专用引擎配置，最小化内存占用 |
| `config.sbc.yaml` | SBC 模式应用配置，使用 b18c384 模型，无 human model |

### 修改文件

| 文件 | 改动 |
| ---- | ---- |
| `python/realtime_api/config.py` | 新增 `MODE_CONFIG_MAP` 和 `get_config_path_for_mode()` |
| `python/realtime_api/main.py` | 新增 `--mode` CLI 参数（server/sbc），更新 `/health` 返回 model 路径 |
| `tests/test_realtime_api.py` | 修复 health 测试的缩进 bug，更新断言以匹配新的响应字段 |
| `Dockerfile.sbc-opencl` | 拷贝 `config.sbc.yaml`，支持 `--mode sbc` 启动 |
| `Dockerfile.sbc-eigen` | 同上 |
| `README.md` | 添加 SBC 启动模式说明 |

### 未修改

| 文件 | 原因 |
| ---- | ---- |
| `Dockerfile`（TensorRT） | 服务器专用，不需要 SBC 模式 |
| `config.yaml` | 服务器配置保持不变 |
| `cpp/configs/server_analysis.cfg` | 服务器引擎配置保持不变 |

## 架构设计

### 模式切换机制

```
用户 --mode sbc
  → main.py argparse 解析
    → get_config_path_for_mode("sbc")
      → 返回 config.sbc.yaml 路径
        → load_config() 加载
          → KataGoWrapper 使用 b18c384 + rk3562_analysis.cfg 启动
```

优先级：`KATAGO_CONFIG_FILE` 环境变量 > `--mode` 参数 > 默认 server 模式

### 配置对比

| 参数 | server 模式 | sbc 模式 |
| ---- | ----------- | -------- |
| 应用配置 | `config.yaml` | `config.sbc.yaml` |
| 引擎配置 | `server_analysis.cfg` | `rk3562_analysis.cfg` |
| 主模型 | b28c512 (~1GB) | b18c384 (~400MB) |
| Human 模型 | b18c384 | 无 |
| 分析线程 | 8 | 1 |
| 搜索线程 | 8 | 1 |
| NN 缓存 | 2^23 (8M 条目) | 2^16 (64K 条目) |
| 最大访问次数 | 500 | 200 |
| Eigen 线程 | 自动 | 2 |

### SBC 模式内存预估

| 组件 | 占用 |
| ---- | ---- |
| 系统（Debian + 桌面） | ~300-500MB |
| b18c384 模型 + 1 线程 | ~450MB |
| KaTrain / 其他应用 | ~200MB |
| **合计** | **~950MB - 1.15GB** |

## 启动方式

### 本地启动

```bash
# 服务器模式（默认）
PYTHONPATH=python python3 -m realtime_api.main

# SBC 模式
PYTHONPATH=python python3 -m realtime_api.main --mode sbc
```

### Docker 启动

```bash
# 服务器模式（默认）
docker run -d -p 8000:8000 katago-sbc-opencl

# SBC 模式
docker run -d -p 8000:8000 katago-sbc-opencl python3 -m realtime_api.main --mode sbc
```

## 扩展性

添加新的启动模式只需：

1. 在 `config.py` 的 `MODE_CONFIG_MAP` 添加映射
2. 创建对应的 `config.<mode>.yaml`
3. 创建对应的引擎配置 `cpp/configs/<board>_analysis.cfg`（可选）

## 测试验证

- 14 个单元测试全部通过
- 配置解析测试：server/sbc 模式正确加载对应配置
- 参数校验：无效模式被 argparse 拒绝
- 向后兼容：不加 `--mode` 参数等同于 `--mode server`
