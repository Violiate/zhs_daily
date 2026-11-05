<div align="center">

# 🌲 zhs_daily (`zhsgo`)

**智慧树（知到）每日 25 分钟全自动学习助手 · 习惯分拉满 · 风控感知架构**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Protocol: 2026 Latest](https://img.shields.io/badge/Protocol-2026%20V2%20Dual--Channel-success)](#)
[![Anti-Bot: Pacer + Relay](https://img.shields.io/badge/Anti--Bot-Pacer%20%2B%20Browser%20Relay-orange)](#)
[![Tests: 137 Passed](https://img.shields.io/badge/Tests-137%20Passed-brightgreen)](#七离线自检与回归测试)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

*拒绝无脑一天刷完丢光平时分，像真人一样每天自动打卡 25 分钟，静默拿满习惯分与视频分。*

[核心亮点](#一为什么做这个项目) • [快速开始](#二3-分钟快速上手) • [开机自动打卡](#三一键配置每日自动运行推荐) • [技术架构](#四硬核反风控设计) • [常见问题](#八常见问题-faq)

</div>

---

> [!IMPORTANT]
> **合规与免责声明**：本项目仅用于网络协议分析与反爬对抗技术研究，与智慧树（知到）平台及任何高校无关联。使用前请完整阅读 [`DISCLAIMER.md`](DISCLAIMER.md)。请仅在本人账号上按正常学习节奏使用，**严禁用于收费代刷等商业牟利行为**。

---

## 一、为什么做这个项目？

市面上大多数智慧树脚本都在追求「**10 倍速一天刷完一门课**」，但用过的人往往会踩两个大坑：

1. **习惯分直接归零**：智慧树共享课的平时成绩包含高权重的**「学习习惯分」**——要求在不同自然日坚持有效学习满 **25 分钟/天**，累计达到规定天数才能拿满。一天刷完所有视频 = 有效学习天数只有 1 天 = 平时分大幅扣减。
2. **极易触发风控封禁**：单日连续挂机数小时、固定 30 秒死板心跳、整秒 `*000` 时间戳、伪造倍速、只发进度不拉视频流，在平台风控眼里几乎等同于「明牌脚本」。

**`zhs_daily` 提供「双模式」自由切换，兼顾平时分与赶进度需求**：
- 🎯 **模式一：每日 25 分钟习惯分模式（默认推荐）**：每天自动学习 **26 分钟**（留 1 分钟余量，确保服务端稳稳记满 **25 分钟**习惯分门槛），达标后立即落库收工，第二天从断点无缝续学。
- 🚀 **模式二：`--all` 一口气刷完模式（冲刺赶课）**：针对没有习惯分要求或临近结课死线的同学，只需加一个 `--all` 参数（或双击 `run_all.bat`），即可解除每日 26 分钟限制，在全套拟人节拍与防封间歇休息保护下**一口气刷完所有未完成视频**。
- ⚡ **平时纯协议零打扰，遇验证码自动接管**：99% 的时间在后台纯 HTTP 协议静默运行（内存占用不到 30MB，不弹浏览器窗口）；仅在偶发 `code=-12` 验证码时按需唤起本机 Edge 浏览器自动过滑块/点选并回灌凭证。
- 🧠 **视频弹题全题型秒解**：单选/多选/判断直接提取接口标准答案；**填空题**与无答案题目自动调用**智慧树内置大模型**（零成本、无需配置任何第三方 API Key）或自定义 DeepSeek/OpenAI 接口作答。

---

## 二、3 分钟快速上手

### 1. 安装依赖（必做第一步）

- **系统**：Windows 10 / 11（推荐，直接复用系统自带 Microsoft Edge 过验证码）、macOS 或 Linux
- **环境**：Python 3.10+

克隆仓库后，**请先安装依赖包**：

```powershell
git clone https://github.com/<your-username>/zhs_daily.git
cd zhs_daily
pip install -r requirements.txt
```

> 💡 **提示**：
> - **无需手动创建 `config.yaml`**：首次运行 `daily.py` 时，程序会自动检测并从 [`config.example.yaml`](config.example.yaml) 生成一份开箱即用的 `config.yaml`。
> - **无需额外下载浏览器**：Windows 10/11 默认直接调用系统自带 Edge 处理验证码；若在 macOS / Linux 下使用，可执行 `python -m playwright install chromium` 安装内置内核。

### 2. 扫码登录（首次运行）

```powershell
python daily.py --login
```
*(Windows 用户也可以直接双击 `run_login.bat`)*

- 终端会直接渲染字符二维码，同时在 `state/login_qr.png` 生成高清二维码图片；
- 打开手机 **「知到」App** 扫码确认；
- 登录态与专属浏览器指纹会自动加密/持久化至本地 `state/state.json`，一次扫码可维持数周有效。

### 3. 选择你的模式开始刷课

#### 方案 A：每日 25 分钟打卡模式（拿满平时习惯分，最推荐）

```powershell
# （可选）拉取在学课程清单到 courses.json，支持手动开关指定课程
python daily.py --fetch

# 正式启动今日 25 分钟学习任务（配额 26 分钟）
python daily.py
```
*(Windows 用户日常可直接双击 `run_daily.bat`)*

当累计有效学习满 **26 分钟** 时，程序会主动触发一次数据库层持久化上报（`saveDatabaseIntervalTimeV2`），确保服务端进度一秒不丢，随后干净退出。当天重复运行会自动识别「今日配额已达标」并秒退。

#### 方案 B：一口气刷完模式（期末冲刺 / 无习惯分课程）

如果你想直接一口气把所有未完成的视频全部刷完，无需修改配置文件，直接加上 `--all`（或双击 `run_all.bat`）：

```powershell
# 一口气刷完所有课程（默认每连续刷 ~2 小时自动短暂休息 10~25 分钟防风控）
python daily.py --all

# 一口气刷完 + 全程不休息连续直通 + 1.25 倍速
python daily.py --all --no-rest --speed 1.25

# 只一口气刷完指定的某门课
python daily.py --all --course <课程ID>
```
*(Windows 用户可直接双击 `run_all.bat` 一键启动冲刺模式)*

---

## 三、一键配置每日自动运行（推荐）

想要彻底忘掉刷课这件事、稳拿整学期习惯分？项目内置了 Windows 任务计划程序一键安装脚本 [`install_task.ps1`](install_task.ps1)（**无需管理员权限**）：

```powershell
# 默认注册每天 09:00（附带 0~15 分钟随机抖动）自动学习 26 分钟
powershell -ExecutionPolicy Bypass -File .\install_task.ps1

# 也可以自定义每天触发时间（例如晚上 20:30）并立即测试运行一次
powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Time 20:30 -Minutes 26 -RunNow
```

**为什么比自己写死定时任务更稳？**
- 🎲 **每日随机延迟（RandomDelay）**：每天在设定时间基础上随机延后 `0~15 分钟` 启动，彻底消除「每天固定同一秒上线」的机器人作息特征；
- 🔄 **关机/睡眠错过自动补跑（`StartWhenAvailable`）**：如果设定时间电脑没开，当天任意时刻开机联网后会自动补跑当天的 26 分钟；
- 🔒 **防重入文件锁（`RunLock`）**：内置进程存活检测与陈旧锁自动回收，计划任务与手动运行绝不撞车。

```powershell
# 查看今日打卡状态与完成进度
python daily.py --status

# 卸载计划任务
powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Uninstall
```

---

## 四、硬核反风控设计

`zhs_daily` 针对智慧树 2026 最新前端与风控审计维度做了全链路对齐：

| 风控审计维度 | 传统脚本常见死法 | `zhs_daily` (`zhsgo`) 的对抗方案 |
| :--- | :--- | :--- |
| **进度上报通道** | 只发一种接口，导致网页端进度回档或服务端报 `code=-1` | **DB + Cache 双通道 10 字段对齐**：入场、完课、每日配额收尾走 `saveDatabaseIntervalTimeV2` 落库；播放途中走 `saveCacheIntervalTimeV2` 缓存心跳 |
| **心跳时间间隔** | 固定 `sleep(30)`，方差为 0，一眼假 | **对数正态分布节拍器 (`Pacer`)**：上报间隔在 `20~40s` 连续随机分布，叠加随机微暂停与 `4%` 概率「短暂离开」模拟 |
| **时间戳尾数** | `int(time.time()) * 1000`，毫秒位永远是 `000` | **真实毫秒级单调时钟**：带 `[-40ms, +40ms]` 自然抖动，毫秒尾数 100% 离散且严格单调递增 |
| **观看点序列 (`ewssw`)** | 每次上报都从 `0,1` 重头算，与累计时长严重矛盾 | **跨批次单调推进 (`WatchPoint`)**：仅首包携带 `0,1`，后续批次按 `int(t // 5 + 2)` 连续推进，暂停期间心跳仍携带当前观看点避免空串异常 |
| **CDN 流媒体校验** | 只有 API 进度上报，CDN 侧 0 字节视频流量 | **真实流媒体预热 (`prime_video`)**：进视频时真实请求 `video.zhihuishu.com` 的 `.m3u8` 与首段 `.ts` 分片（`Range: bytes=0-65535`） |
| **设备指纹与 UA** | 硬编码过时或不存在的 Chrome 版本，或每次启动随机换 UA | **宿主机平台对齐 + 指纹永久固化**：首次运行生成真实 Chrome 版本并与宿主机 OS 绑定写入 `state.json`，HTTP 头、Client Hints 与浏览器中继完全一致 |
| **`-12` 验证码拦截** | 直接崩溃退出或死循环重试导致封号 | **智能浏览器中继 (`BrowserRelay`)**：注入 `STEALTH_JS` 抹除自动化特征，结合 OpenCV 缺口识别 + 人类最小急动度（Minimum-Jerk）曲线拖拽滑块，支持人工兜底 |

---

## 五、命令行与退出码速查

### 1. 每日调度入口：`daily.py`

| 命令 | 功能说明 |
| :--- | :--- |
| `python daily.py` | **每日模式**：学习满 `26` 分钟自动落库收工（稳拿 25 分钟习惯分） |
| `python daily.py --all` | **一口气刷完模式**：解除单日时长与会话限制，刷完所有未完成视频（每 ~2h 智能小憩防封） |
| `python daily.py --all --no-rest` | **全速直通模式**：一口气连续刷完所有视频，关闭跨会话休息（仅保留视频间数秒停顿） |
| `python daily.py --login` | 强制重新扫码登录并刷新 `state/state.json` |
| `python daily.py --fetch` | 拉取当前账号所有在学课程清单并保存至 `courses.json` |
| `python daily.py --status` | 查看今日已学分钟数、最近一次运行结果及是否需要重登 |
| `python daily.py --course <ID>` | 只学习指定课程 ID（可传多个，可配合 `--all` 使用） |
| `python daily.py --minutes 60` | 临时覆盖今日学习时长目标（传 `0` 等同于 `--all`） |
| `python daily.py --speed 1.25` | 临时覆盖播放倍速（默认 `1.0` 原速最稳，上限 `1.5`） |
| `python daily.py --force` | 忽略「今日已达标」记录，强制再跑一轮 |
| `python daily.py --dry-run` | 只检查并打印配置信息，不发起任何网络请求 |

**标准退出码（方便自动化脚本监控）**：
- `0`：今日学习达标收工 / 今日已完成无需重跑
- `2`：登录态失效，需运行 `python daily.py --login`（同时写入 `state/NEED_LOGIN`）
- `3`：触发 `-12` 人机验证且未能自动/手动通过
- `4`：触发风控锁定上限（`RiskLocked`），自动熔断保护账号
- `5`：已有另一个 `daily.py` 实例正在运行

### 2. 全功能 CLI 入口：`main.py`

支持交互式选课、列出课程详情、运行内置离线测试套件等：

```powershell
python main.py --list          # 列出所有共享课 / 校内课 / AI 课
python main.py --self-test     # 一键运行内置离线自检套件
```

---

## 六、核心配置说明（`config.yaml`）

首次运行时若不存在 `config.yaml`，程序会自动从 [`config.example.yaml`](config.example.yaml) 生成默认配置：

```yaml
fingerprint:
  chrome_major: 0        # 0 = 首次运行随机挑选真实 Chrome 版本并固定写入 state.json
  platform: ""           # "" = 自动检测当前系统平台 (Windows / macOS)

pacer:
  enabled: true
  max_speed: 1.5
  default_speed: 1.0     # 1.0 = 原速播放最安全；想略微加快可改 1.25
  report_interval: [20, 40]
  real_millisecond_ts: true

budget:
  enabled: true
  daily_minutes: 26      # 每日有效学习时长上限（26 分钟确保服务端稳记 25 分钟习惯分）
  daily_sessions: 2      # 单日允许启动会话次数（含失败重试余量）
  session_minutes: [45, 65]

study:
  end_threshold: 0.99    # 视频播放达 99% 时自动补齐完整时长并标记完课
  initial_report: true   # 开启 DB 层持久化上报
  prime_video: true      # 开启 CDN 首分片流量预热

ai:
  enabled: true          # 遇到无标准答案弹题（如填空题）或 AI 课程时自动调用
  backend: zhidao        # zhidao = 复用智慧树内置大模型（免费、免 Key）
                         # openai = 自定义 OpenAI 兼容接口（如 DeepSeek）
  skip_exam: true        # 默认跳过章节测试（仅完成视频与视频内弹题）
```

---

## 七、离线自检与回归测试

项目配备了基于虚拟时钟（`FakeClock`）的完整离线测试套件，无需联网、无需登录，1 秒内即可验证加密往返、节拍分布、观看点单调性、半截视频补齐落库、弹题全题型作答等 **137 项断言**：

```powershell
python tests/run_tests.py
python tests/test_popup.py
python tests/test_progress.py
```

---

## 八、常见问题（FAQ）

<details>
<summary><b>Q1：为什么习惯分要求 25 分钟，默认配置里写的是 26 分钟？</b></summary>

因为进度上报是每隔 `20~40` 秒发送一次。如果刚满 25 分 00 秒就切断，万一遇到网络抖动或服务端四舍五入，可能会出现「本地计满 25 分钟、服务端只记了 24 分半」而漏掉当天习惯分的情况。多留 **1 分钟余量（26 分钟）**，并在收工瞬间强制补发一次 `saveDatabaseIntervalTimeV2` 数据库持久化请求，能 100% 保证当天习惯分稳稳到账。
</details>

<details>
<summary><b>Q2：之前看过 90% 但网页上没显示绿勾的「半截视频」会怎么处理？</b></summary>

脚本通过服务端返回的 `watchState == 1` 判断视频是否真正完课，而不是只看播放秒数。对于之前卡在 90%~98% 未完课的视频，脚本会自动接续播放完最后几秒，并补齐 100% 完整视频时长落库，确保点亮绿勾。
</details>

<details>
<summary><b>Q3：遇到 -12 验证码弹窗时我需要做什么？</b></summary>

默认什么都不用做！脚本会自动唤起浏览器尝试识别并拖动滑块。只有在罕见的复杂点选验证码连续自动识别失败时，程序才会发出提示音并保留浏览器窗口——这时你只需在弹出的浏览器里手动滑一下，脚本检测到验证消失后会自动接管 Cookie 并继续学习。
</details>

---

## 九、开源许可

本项目采用 [MIT License](LICENSE) 开源。如果这个项目帮到了你，欢迎点一颗 ⭐ **Star** 支持！
