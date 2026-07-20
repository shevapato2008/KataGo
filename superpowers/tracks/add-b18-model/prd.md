# PRD — realtime_api 多模型服务 (b28 + b18 + humanSL)

- **日期**: 2026-07-20
- **分支 / worktree**: `feature/add-b18-model` @ `/Users/fan/Repositories/KataGo-add-b18-model`(基于 `develop` @ 16827757）
- **状态**: 设计定稿,待写实现计划(plan.md)
- **范围**: 仅 KataGo `python/realtime_api` 服务侧。KaTrain 侧改动为外部依赖(见 §8)。

---

## 1. 背景与问题

KaTrain 的 galaxy(server 模式)对弈 AI 目前由 `realtime_api` 提供的**单一** KataGo 分析引擎承担:一个 `cpp/katago analysis` 子进程,`-model <主网>` + `-human-model <人类网>`。当前 server 配置的主网是 **b28**(`kata1-b28c512nbt-adam-s11165M`)。

产品希望在 galaxy 里做**按任务分模型**:

- **b18**(`kata1-b18c384nbt-s9996604416`)承担**高阶(5D+ / net_search 档)对弈** —— 它是 b28 ~40% 算力的高性价比强网,用于省算力。
- **b28** 承担**最高一档对弈 + 复盘(分析)** —— 最强,精度优先。
- **humanSL**(人类网 `b18c384nbt-humanv0`)承担**低段位拟人对弈**(现状不变)。

需要服务能**按 HTTP 请求参数**把一次 `/analyze` 路由到 b28 / b18,并且**只用一份 yaml 配置**声明这些模型。

## 2. 关键技术事实(约束设计)

1. **一个 katago analysis 进程 = 1 个主网 + 1 个人类网**(`-model` + 可选 `-human-model`)。主网在进程启动时定死,无法逐请求切换。
2. **humanSL 不是独立进程**,是"人类网那一侧":随主网进程一起加载,由每请求的 `overrideSettings.humanSLProfile` 触发;其结果**只取决于人类网,与同进程装哪个主网无关**。
3. **b28 与 b18 是两个不同主网,一个进程装不下** → 要同时提供两者,**必须起两个 katago 子进程**。
4. 主网通过 **`-model` CLI 参数**传入(`katago_wrapper.py` 从 `config.model.path` 拼命令行),**不写死在 `.cfg` 里** → 增删模型是纯配置 + 进程管理问题,不改 `.cfg`。
5. `/analyze` 转发给 katago 前已经会**剥掉服务层字段**(`gameId`/`userId`,见 `katago_wrapper.query` 的 `safe_query_data`)——路由字段可沿用同一机制剥除。

## 3. 目标 / 非目标

**目标(本 PRD 范围)**
- `realtime_api` 支持在**一份 yaml** 里声明**多个模型**,启动时各起一个子进程,`/analyze` 按请求路由到指定模型。
- server 模式(`config.yaml`)声明 **b28 + b18**(各挂 humanv0 人类网),默认 b28。
- 对现有请求(不带路由字段)**行为逐字节不变**(路由到默认模型 = 当前 b28)。
- worktree 可跑通(解决 git-ignored 的 `cpp/katago` 二进制不在 worktree 的问题)。

**非目标(明确排除)**
- **KaTrain 侧**在请求里设置路由字段的改动(另一个 repo,外部依赖,见 §8)。
- **board / kiosk(`config.sbc.yaml`)**:本次**不改**,保持 b6c96+human(靠向后兼容继续跑)。RK3562 维持 b6c96 仅保活。
- **RK3562 高段位走本地封顶 vs 新建"对弈→远端 GPU"路由**:这是 KaTrain 侧路由决策,**不在** KataGo 服务范围,不阻塞本 PRD。
- **b18-capable SBC(RK3576/3588)本地 b18**:留作后续(依赖上一条 + 逐机型 visits 上限)。
- **强度校验本身**(b18 vs b28 对标星阵):独立的 calibration 工作,本 PRD 只提供可被校验的服务能力。

## 4. 设计

### 4.1 配置 schema:`model` → `models[]`

`config.py` 的 `KataGoConfig`:

- 新增 `models: List[NamedModelConfig]`,每项 = `{ name, path, url?, auto_download, sha256?, human_model? }`(`human_model` 为可选、逐模型的 `ModelConfig`)。
- 新增 `default_model: str`(请求未指定路由字段时的兜底,必须命中 `models[].name` 之一)。
- **向后兼容**:若 yaml 用老的单 `model:`(+ 可选 `human_model:`),自动包装成一个名为 `"default"` 的单元素 `models[]`,`default_model="default"`。→ `config.sbc.yaml`、`tests/test_config.yaml` **一字不改**照常工作。
- 路径解析(`_resolve_path`)对 `models[]` 每项的 `path` / `human_model.path` 逐一相对 base_dir 解析(沿用现有逻辑)。

### 4.2 server 配置(`config.yaml`)

```yaml
katago:
  path: ./cpp/katago
  config_path: ./cpp/configs/server_analysis.cfg   # 两模型共用同一搜索 .cfg（公平对比）
  models:
    - name: b28                     # 最高档对弈 + 复盘
      path: ./models/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz
      url:  https://media.katagotraining.org/uploaded/networks/models/kata1/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz
      sha256: 798da8fe3e9819f09535240b1bc29cb3047a4fa981433c56c491e57007a3d3f0
      auto_download: true
      human_model:
        path: ./models/b18c384nbt-humanv0.bin.gz
        url:  https://github.com/lightvector/KataGo/releases/download/v1.15.0/b18c384nbt-humanv0.bin.gz
        sha256: 637746e44f0efe00ad1245a50aa9bbf0716efe364c43965ead97bd6835d84ab5
        auto_download: true
    - name: b18                     # 5D+ / net_search 档对弈
      path: ./models/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz
      url:  https://media.katagotraining.org/uploaded/networks/models/kata1/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz
      sha256: 9d7a6afed8ff5b74894727e156f04f0cd36060a24824892008fbb6e0cba51f1d
      auto_download: true
      human_model:                  # 与 b28 相同的 humanv0，使该进程也能答 humanSL
        path: ./models/b18c384nbt-humanv0.bin.gz
        url:  https://github.com/lightvector/KataGo/releases/download/v1.15.0/b18c384nbt-humanv0.bin.gz
        sha256: 637746e44f0efe00ad1245a50aa9bbf0716efe364c43965ead97bd6835d84ab5
        auto_download: true
  default_model: b28
  additional_args: []
  ld_library_paths: [./libs/TensorRT-8.6/lib, /usr/local/cuda/lib64]   # prod(TensorRT)；Mac/Metal 会忽略，无害
api: { host: 0.0.0.0, port: 8000, reload: false }
```

### 4.3 进程注册表(`main.py` lifespan)

- 遍历 `models[]`,对每个模型:`_ensure_models_available`(复用现有 auto_download + sha256 校验),再 `KataGoWrapper(...)` 各起一个子进程。
- 存进 `wrappers: Dict[str, KataGoWrapper]`(`name → wrapper`),替代当前的单个全局 `katago_wrapper`。
- 某个模型起不来时:记录错误、保留其余(与现有"起不来也不拖垮 app"的容错一致);`/health` 如实汇报。

### 4.4 路由(`/analyze`)

- 读 `payload["overrideSettings"]["model"]`(值 = `models[].name`);缺省 → `default_model`。
- 选中对应 wrapper;**转发给 katago 前,从 `overrideSettings` 里删掉 `model` 这个 key**(katago 不认此 override,和现有剥 `gameId`/`userId` 同理)。`humanSLProfile` **保留**在 `overrideSettings` 里照常转发。
- 未知模型名 → **HTTP 400**(明确报错,不静默降级,避免打字错误悄悄用错网)。

**为什么放 `overrideSettings.model`(而非顶层字段)**:① 请求形状几乎不变——KaTrain 只是往它本就在发的 `overrideSettings` dict 里多塞一个 key;② 缺省即等于现状,**不影响现有逻辑**;③ 避开 pydantic `model_` 命名空间与顶层 `model` 字段打架的坑;④ 与 `humanSLProfile` 天然正交,可组合(路由到 b18 进程 + 用其人类网出招)。

### 4.5 健康检查(`/health`)

- 汇报**每个**模型的状态:`name`、是否 running、`has_human_model`、`model` 路径。保留一个顶层汇总(如 `default_model`、整体 healthy 布尔)。

### 4.6 worktree 可运行性

`cpp/katago`(Metal 二进制)与 `models/` 均被 gitignore,**不在 worktree**(实测 `--mode server` 在 worktree 里因 `No such file or directory: .../cpp/katago` 起不来)。二进制是自包含的(Metal shader 静态链接,唯一动态依赖是已装的 Homebrew libzip)。

- setup 步骤:`ln -s /Users/fan/Repositories/KataGo/cpp/katago /Users/fan/Repositories/KataGo-add-b18-model/cpp/katago`。
- 网络文件由 `auto_download` 自动拉取(b28/b18/humanv0)。

## 5. 路由契约(KaTrain 面向)

| 需求 | 请求怎么写 | 服务怎么做 |
|---|---|---|
| b28 对弈 / 复盘 | 不带 `model`,或 `overrideSettings.model="b28"` | 路由 P_b28 |
| b18 高阶对弈 | `overrideSettings.model="b18"` | 路由 P_b18 |
| humanSL 拟人对弈 | `overrideSettings.humanSLProfile="rank_xd"`(现状,可再带 `model` 指定落在哪个进程) | 所选/默认 wrapper 用其人类网出招 |

- 缺省(无 `model`)= `default_model`(server = b28)= **现有行为不变**。

## 6. 向后兼容

- 老的单 `model:` yaml → 自动包成单元素 `models[]`(名 `default`)。
- 现有 `/analyze` 请求(无 `overrideSettings.model`)→ 默认模型 → 逐字节等价当前行为。
- `config.sbc.yaml`、`tests/test_config.yaml`(老 schema)不改照跑。

## 7. 测试

- `tests/test_config.py`:多模型 yaml 加载、`default_model` 校验、路径解析、**向后兼容单-model**、未知 `default_model` 报错。
- `tests/test_realtime_api.py`(可用 mock wrapper,不真起 katago):`/analyze` 按 `overrideSettings.model` 路由到正确 wrapper、缺省走默认、未知模型 400、**转发前 `model` 被剥掉而 `humanSLProfile` 保留**、`/health` 多模型汇报。

## 8. 依赖与后续(不在本 PRD 实现)

- **KaTrain 侧(另一个 repo)**:发 `/analyze` 时按任务/段位设 `overrideSettings.model`——5D+/net_search 档设 `"b18"`,最高档+复盘设 `"b28"`(或留默认);humanSL 继续发 `humanSLProfile`。这是让本服务生效的配套改动。
- **RK3562 高段位路径**(KaTrain 侧,未决):阶梯封顶到 6段(humanSL 本地可跑)**或**新建"对弈→远端 GPU"路由。与本 PRD 解耦。
- **b18-capable SBC**(RK3576/3588 本地 b18):后续,依赖上一条 + 逐机型 visits 上限。
- **b18 vs b28 强度/算力校验**:独立 calibration 工作。

## 9. 资源与风险

- server 模式同时常驻 **2 个 katago 子进程**(b28+b18)→ 约 2× GPU 显存/算力。prod GPU 充裕;Mac Metal 开发偏重但可用(可只起需要的一个做局部测试)。
- 未知路由值静默降级的风险 → 用 400 显式拒绝规避。
- `overrideSettings.model` 未剥净就转发 → katago 报未知 override → 用测试锁死"转发前必删"。

## 10. 开放问题

无阻塞项。KaTrain 侧路由字段命名(`model` vs `mainNet`/`net`)在实现时与 KaTrain 侧对齐即可;服务侧读取键名可配置/易改。
