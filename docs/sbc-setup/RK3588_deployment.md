# RK3588部署服务围棋服务及界面设计规划ver1.0

你的整体规划（**RK3588 本地只做分级对弈 + 服务器端做高强度分析 + 前端用你自己的 Web KaTrain**）是很合理的：它把“低延迟交互”和“高算力分析”拆开，既能在端侧离线可用，又能把成本集中在服务器。

下面按你担心的两点来评估，并给你一些“落地时最容易踩坑/最有效提升”的点。

---

## (1) RK3588 本地算力够不够做“分层级 AI 对弈”？

**大概率够**，前提是你本地目标是“对弈体验/教学难度分级”，而不是“高 visits 的专业分析”。

### 为什么说够（工程视角）

* RK3588 的大核是 **4× Cortex-A76**，再加 4×A55。对 KataGo(Eigen/CPU) 来说，**大核决定体验**，小核贡献有限（甚至会拖慢同步开销）。
* 你又用 **human 模型**（通常比最强网小/更偏“人类风格”），并且允许“难度分级”（本质就是控制 visits/时间/策略噪声），这正好适合端侧 CPU。
* 真正压垮端侧的，是“高 visits、多分支、长时间、多局并发”的分析模式——你已经明确放到服务器了。

### 你需要把“难度分级”设计成对 CPU 友好的形式

建议你把难度分级拆成三类旋钮（非常有效）：

1. **每步预算（核心）**

* `maxVisits` / `maxTime`（例如：低难度 50–200 visits，中难度 200–800 visits，高难度 800–2000 visits）
* 端侧建议优先用 **maxTime**（比如 0.2s / 0.5s / 1.0s / 2.0s），体验更稳定。

2. **线程数（强烈建议只用大核）**

* 从 4 线程开始试（对齐 4 个 A76），再测 5/6/8 线程实际收益。
  KataGo 自己也有“自动尝试不同线程数做调优”的流程，你可以利用它来找甜点位。 ([GitHub][1])

3. **“人味”难度（几乎不耗算力）**

* 通过增加随机性/温度、policy 采样、限制读取深度、偶尔选次优点等方式做分级，比单纯堆 visits 更划算。

### 你最该担心的其实是“持续满载降频”

杂牌板子“硬件差不多”这个判断：**算力峰值差不多，但持续算力差很多**，主要差在：

* 散热（有没有风扇/散热片、热设计）
* 供电（电源质量、板载 PMIC、是否稳压）
* 内存带宽/频率（RK3588 对内存带宽敏感）
  RK3588 做性能调优时，内存/频率设置能明显影响整体表现。 ([SBCwiki][2])

**建议你用一个硬指标验收：**跑 20–30 分钟“连续对弈/连续分析小预算”，观察 visits/s 是否明显衰减。如果衰减大，优先解决散热与 governor。

### 你应该做的“一步到位验证”

在板子上直接跑：`katago benchmark -model human.bin.gz -config 你的cfg`
这个数一出来，你就能立刻把“每步预算/线程/响应时间”定到不会卡顿的范围（比任何理论估计都靠谱）。

---

## (2) Ubuntu 初始界面能做到像 Android 一体机那样吗？

**可以做到外观和体验上“几乎一样”**（开机直达、全屏、不可退出、触控友好），而且对你这种“Web UI 为主”的产品形态，Ubuntu 反而更顺。

### 典型实现：Linux Kiosk（开机进全屏 Web）

你要的效果通常是：

* 自动登录
* 自动启动一个全屏 Chromium（`--kiosk`）
* 隐藏鼠标光标、禁用系统快捷键/桌面元素
* 崩溃自拉起（watchdog/systemd）
* 可远程 ssh 管理

实现路径很多，常见组合：

* **Openbox + Chromium Kiosk**（轻量、成熟）
* **Wayland/Weston + 全屏应用/浏览器**（更“嵌入式/工业”路线）
  Weston 本身就面向包含 kiosks 在内的“非桌面用途”。 ([GitHub][3])
  也有人专门推荐 Openbox+Chromium 作为触控终端/全屏应用的轻量方案。 ([ARM Solutions][4])

### Ubuntu 做到“像安卓”你需要注意的 3 件事

1. **不要上完整 GNOME 桌面**：资源占用、弹窗、更新提示会破坏“一体机感”。选轻量 WM/Wayland kiosk 更像“设备”。
2. **触控与输入法**：如果需要中文输入，提前选好方案（fcitx5 等）并在 kiosk 场景里测试。
3. **自恢复**：用 systemd 把你的浏览器壳/前端壳做成服务，异常退出自动重启。

---

## 对你计划的整体建议（我会这么落地）

1. **OS 选 Ubuntu/Armbian**（你已有 Docker 经验，迁移成本最低；Android 不适合当“像 Ubuntu 一样跑 Docker”的目标）
2. **RK3588 本地只跑一个轻量服务**：你的 `katago /analyze`（低预算、低并发）
3. **服务器端跑重分析**：同一套 HTTP 协议，前端按“模式”切换 endpoint
4. **前端用 Web Kiosk**：板子本地就是一个全屏浏览器，渲染你的网页版 KaTrain
5. **把难度分级做成三旋钮**：每步时间预算 + 线程数（优先4）+ 人味随机性

---

如果你愿意，我可以按你现在的“/analyze 协议”和你希望的难度档位，给你一套**推荐的端侧默认参数表**（每档：threads、maxTime/maxVisits、随机性参数、预计响应时间目标），以及一套 **Ubuntu kiosk 的 systemd 启动模板**（开机即进你的网页、掉线自恢复）。你只要告诉我：你希望端侧“最快一档”每步目标延迟是 0.2s 还是 0.5s。

[1]: https://github.com/lightvector/KataGo/issues/399?utm_source=chatgpt.com "Testing number of threads in tuning section within ..."
[2]: https://sbcwiki.com/news/articles/tune-your-rk3588/?utm_source=chatgpt.com "Optimizing RK3588 Performance (April 2025) - SBCwiki"
[3]: https://github.com/JeffyCN/weston?utm_source=chatgpt.com "JeffyCN/weston: Wayland compositor with hacks for ..."
[4]: https://armbasedsolutions.com/blog-detail/recommended-lightweight-ubuntu-desktop-gui-options-based-on-arm-architecture?utm_source=chatgpt.com "lightweight Ubuntu desktop GUI options based on ARM ..."
