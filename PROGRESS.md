# 火种 AllSpark — 开发状态追踪

> **最后更新：** 2026-07-05（安全审计 P0-P3 修复：H1/H2/H3 + DI + i18n + 日志 + 依赖上界）
> **当前版本：** v1.0.3
> **整体状态：** v1.0.3 稳定性收敛已复核 — 闭环 2026-06-23 审计 P1/P2/P3 队列（SHA-36/37/40/55/56/57/58/59/60 共 9 项）；mypy `check_untyped_defs` 已启用且通过；regression harness 已区分真实失败、允许降级、外部依赖不可用、环境禁止本地 TCP bind；Web 离线图标 fallback 已加覆盖测试。
> **测试规模：** 当前 623 collected；本机/CI 口径预期 617 passed + 6 skipped；受限 sandbox 当前口径 614 passed + 8 skipped，本地 TCP 网络项会显式 skip 或 regression `environment_blocked`，覆盖 Docker、命令层、优先级、预警协议、向量检索、外部知识库、本地视觉、语音会话、Web 契约、初始化向导、Spark Network 双节点、scheduler 等核心模块

---

## 一、已完成功能 ✅（按阶段）

### Phase 1 — MVP ✅
- 规则引擎 + Tier 0 知识（水/火/食物/庇护/医疗）+ CLI
- 五维资源监控（电力/水/食物/火源/存储）+ 四档自适应模式
- 生存评估引擎 + 任务规划器（Phase 0-4 模型）+ 人格系统（三模式）
- 地图系统（POI 管理/文字地图）
- SQLite + FTS5 + LIKE 回退搜索
- Rich CLI 美化输出 + 自然语言输入

### Phase 2 — 智能增强 ✅
- jieba 中文分词 + 本地 LLM 集成（llama-cpp-python + Qwen3）
- 经验日志引擎（记录→模式识别→知识沉淀闭环）
- Tier 1-2 知识扩充（20 条：农业/化学/机械/气象/能源/医疗）
- Web UI（FastAPI 后端 + 纯 HTML/CSS/JS 前端 + 响应式设计 + 初始化向导）
- i18n 双语框架（语言检测/切换/知识库双语/系统消息全 i18n）
- 人格系统扩展为五模式（危机/稳定/陪伴/多人/复兴）

### Phase 3 — 连接与通信 ✅
- SKF 知识包导入/导出（ZIP 格式 + SHA256 checksum）
- 知识验证流程（5 步：格式→来源→一致性→交叉引用→等级标记）
- 火种通信网络（UDP 信标 + TCP 知识交换，支持 LAN/蓝牙/WiFi Direct）
- 图像识别（多模态 LLM 分析，7 种任务类型）
- 目标系统（自动生成目标 + 里程碑追踪 + 6 套目标模板）
- 三级重置管理器（L1 评估/L2 档案/L3 出厂 + 安全约束 + 冷却期 + 自动备份）
- 目标↔任务双向联动（目标拆解为任务 / 任务完成推进里程碑）
- 模块化加载系统（16 模块注册表 + 核心/条件加载 + 手动开关）
- 硬件检测与自适应（CPU/RAM/存储/GPU 五档分级 + 16 项 FeatureFlags + LLM 模型映射）
- 初始化向导（5 步引导：硬件自检→语言→模型→生存者→人格 + 模型下载 + 状态持久化）
- 代码工程化（当时测试覆盖 8 模块，后续已扩展到 612+ 项用例 + 数据库封装统一 + 启动完整性校验 + 评估缓存）

### Phase 4 — 多人与治理 ✅
- 多人权限体系（指挥官/专家/执行者/观察者 四级角色 + 权限矩阵）
- 动态角色分配（基于贡献度和技能自动推荐晋升）
- 冲突调解机制（全流程 + AI 辅助调解建议）
- 生存价值计算（5 维度评估）
- 组织架构评估 + 火种间知识交易（提议/接受/拒绝/评估）
- Tier 3 知识库（17 条社区/工程/农业/医疗/通信/防御/文明知识）

### Phase 5 — 硬件适配 ✅
- 电力真实监控（RPi GPIO ADC + SPI 接口 + 模拟/手动回退）
- 传感器数据接入（I2C/GPIO/Serial 多接口：温湿度/气压/GPS/光照/空气质量/水位/运动）
- 数据固化机制（自动定时保存 + 紧急保存 + 快照/恢复 + 信号处理 SIGTERM/SIGINT/SIGHUP）
- 启动优化（启动计时 + 分阶段记录 + systemd service 模板 + watchdog）

### Phase 6 — 生存体验增强 ✅
- 每日简报（资源 + 预警 + 目标 + 任务 + 知识提示）
- 生存时间线（7 种事件类型 + 按天查看 + 自动记录目标/里程碑/资源变动）
- 火种日记（文字记录 + 情绪标记 + 关键词 + 日期索引 + 隐私保护）
- 离线天气预测（气压数据→12h 预报 + 云图指南 + 手动输入 + 传感器集成）
- 心理状态追踪（孤独指数 + 压力指数 + 交互语气分析 + 5 题自评问卷 + 心理干预触发）
- 日记与时间线联动

### Phase 7 — GPS 与环境感知 ✅
- GPS 管理器（传感器/手动定位 + 位置持久化 + 轨迹记录 + Haversine 距离 + 方位角）
- 环境评估模块（气候/地形/威胁/机会 四维评估 + 综合评分 + 推荐建议）
- 资源维度关联（环境评估自动关联电力/水源状态）

### Phase 8 — 架构重构 + Docker 弹性部署 ✅
- **ServiceContainer** — 统一服务容器，消除 RuleEngine 上帝对象
- **Command Pattern** — 10 个命令模块 / 32 个具体 Command 类，自动发现注册
- **ApplicationBootstrap** — 模块初始化编排
- **i18n 纯净化** — 700+ key，消除所有硬编码中英文混杂
- **DeployMode 枚举** — PROCESS/DOCKER/INTEGRATION 三级部署模式
- **DockerManager** — 容器生命周期管理（启停/迁移/重置）
- **Docker Compose** — Core/LLM/RAG/Web/Kiwix 服务编排
- **Docker CLI** — docker status/start/stop/logs/migrate 命令
- L3 重置回归（出厂重置时停止容器 + 删除卷，回归进程模式）
- Docker 专项测试 50 项

### PRD 补强（2026-06-05）✅
- **多维度优先级算法** — PriorityCalculator 五维加权（urgency/impact/feasibility/dependency/cost）
- **目标追踪频率** — Scheduler 注册 goal_review / goal_critical_check，按运行模式自适应
- **结构化问卷** — 初始化向导支持位置/庇护/威胁/技能/健康编号选择
- **资源预警闭环** — WarningProtocol 六步闭环 + ActionPlan 持久化
- **RAG 向量检索** — VectorEngine + FTS5/向量 RRF 混合检索 + optional deps
- **外部知识库集成** — Kiwix/Kolibri/ProtoMaps 本地客户端
- **本地图像识别** — LocalVisionEngine ONNX 可选后端 + metadata/filename fallback
- **完整语音交互** — VoiceSession + VADRecorder + 唤醒词 + 命令/LLM 路由

---

## 二、待收敛项 ⚠️

### 当前工程化尾巴（v1.1+）

| # | 功能 | 优先级 | 说明 |
|---|------|--------|------|
| 1 | 真实环境集成验证 | 🟡 P2 | 已建立 `docs/REAL_WORLD_VALIDATION.md` 记录；下一步在 GPU/Docker/RPi/传感器/LLM 实机上跑验证矩阵 |
| 2 | 视觉回归基线 | 🟢 P3 | Web 主要 UX 已收敛；仍可补 Playwright 截图基线防止布局/图标回退 |
| 3 | bench `--hard-fail` 升级 | 🟢 P3 | 当前 `scripts/bench_import.py --check` 低于 600 ms 门槛，待多机基线稳定后切硬阈值 |
| 4 | 发布/维护文档节奏 | 🟢 P3 | AGENTS/PROGRESS/ARCHITECTURE 已更新为当前测试口径；后续每次审计/发布后同步 |
| 5 | database.py 领域拆分 | 🟡 P2 | 1125 行上帝对象混合 12+ 领域持久化（resources/knowledge/FTS/goals/diary/community/...）；按 KnowledgeRepository / GoalRepository / DiaryRepository 等拆分。2026-07-05 审计 M3 登记，v1.1 单独重构（遵循"修复与重构分开提交"） |

### 远期功能（本轮不做）

| # | 功能 | 阶段 | 说明 |
|---|------|------|------|
| 1 | 人格进化 | v2.0+ | 参数化人格模型，随经验积累微调（PRD §7.3） |
| 2 | 支线任务系统 | v2.0+ | 智能升级/知识获取/环境探索等（PRD §10.1） |
| 3 | 孤独/文明指数深化 | v2.0+ | 当前已有心理状态追踪；长期指数模型待细化 |
| 4 | 自杀行为干预协议 | v2.0+ | Level 1-3 分级响应，需专业安全评审（PRD §8.2） |
| 5 | 知识库签名验证 | v2.0+ | 防篡改机制、密钥管理、签名体系（PRD §12.3） |
| 6 | 硬件实机验证 | v1.2+ | RPi4/5 实测 + GPS/传感器/电力监控/语音/LLM 硬件集成 |

### 已完成并归档

Apache 2.0 许可证、Database 层封装统一、备份文件验证场景下的数据库连接、评估缓存、网络配置外置、Web 模板化、多维度优先级算法、Scheduler、日志系统、SKF route DI 收尾、目录重组 Phase D 均已完成。

---

## 三、技术债务

### 代码 Review 汇总表（2026-05-15 Beta 1.0 Review）

共发现 18 项问题（4 冗余 + 6 设计 + 8 优化），**18 项全部修复**。

| 编号 | 分类 | 问题 | 状态 |
|------|------|------|------|
| R1 | 🔴 冗余 | web_ui.py 42 处懒加载重复代码 → 提取 `_get_or_create()` | ✅ |
| R2 | 🔴 冗余 | cli.py 7 处懒加载重复 → 提取 `_lazy_init()` | ✅ |
| R3 | 🔴 冗余 | rule_engine 帮助文本缺 Phase 3+ 命令 → 已补全 | ✅ |
| R4 | 🔴 冗余 | PROGRESS.md 偏离表状态未更新 → 已修正 | ✅ |
| D1 | 🟡 设计 | governance/trade_engine/spark_network 绕过 Database 层 | ✅ 已通过 db 封装方法调用 |
| D2 | 🟡 设计 | data_preservation 用 `sqlite3.connect()` 绕过 Database 实例 | ✅ 合理场景（备份文件验证/启动回退） |
| D3 | 🟡 设计 | power_monitor 通过 `ResourceManager.__new__` 调用私有方法 → 已内联 | ✅ |
| D4 | 🟡 设计 | rule_engine 每次输入都完整评估 → 已加 60s TTL 缓存 | ✅ |
| D5 | 🟡 设计 | cli.py 81 处中英文判断重复 → 提取 `_t(zh, en)` | ✅ |
| D6 | 🟡 设计 | 4 个知识数据文件无统一入口 → 新建 `knowledge_loader.py` | ✅ |
| O1 | 🟢 优化 | models.py 8 处 `list` → `list[str]` 类型注解 | ✅ |
| O2 | 🟢 优化 | spark_network 端口/消息格式硬编码 → 移至 config.py | ✅ |
| O3 | 🟢 优化 | Phase 3-5 模块未自动加载 → 已在 RuleEngine.initialize() 中补充 | ✅ |
| O4 | 🟢 优化 | FeatureFlags 缺 Phase 3-5 flag → 已补充 | ✅ |
| O5 | 🟢 优化 | pyproject.toml 版本 0.1.0 不一致 → 已更新 | ✅ |
| O6 | 🟢 优化 | cli.py banner 硬编码版本号 → 改为 `__version__` | ✅ |
| O7 | 🟢 优化 | web_ui.py HTML 内嵌 Python 字符串 → 提取为 templates/*.html 文件 | ✅ |
| O8 | 🟢 优化 | 无自动化测试 → 已建自动化测试体系（用例数以 `pytest tests/ -q` 输出为准） | ✅ |

### GitHub 上线前修复摘要（2026-05-16）

| 类别 | 修复内容 |
|------|---------|
| 品牌升级 | `spark/` → `allspark/` 包重命名，125+ import 更新，数据目录 `~/.spark/` → `~/.allspark/` 自动迁移 |
| 模拟数据清理 | 资源默认值清零、电力/传感器零值回退、自动检测不再返回假数据 |
| Bug 修复 | GoalEngine 缺失方法、CLI 代码混入、传感器 always-true 逻辑、数据库迁移崩溃修复、i18n 缺失键 |
| 交互优化 | 运行模式 emoji/预警图标/空状态引导/帮助文本补全/简报自动生成/LLM 命令完整化 |
| i18n 增强 | 资源摘要/节能建议全面 i18n + 21 个新 key、语言持久化、CLI 45+ 处硬编码替换 |

### PRD 收敛概览

| 状态 | 说明 |
|------|------|
| 已对齐 | 核心规则引擎、资源、目标、任务、Web/CLI、i18n、Docker、预警闭环、RAG、外部知识库、本地视觉、语音会话等已实现 |
| 部分实现 | 语音、通信、本地图像识别已具备软件框架和降级路径；硬件实测、灾后物理通道、模型质量评估仍待后续验证 |
| 远期保留 | 人格进化、支线任务系统、自杀行为干预协议、知识库签名验证、硬件实机验证 |
| 新增能力 | 地图系统、LIKE 回退搜索、资源手动矫正、Rich CLI、双语命令、Docker 弹性部署 |

---

## 四、版本变更日志

| 版本 | 日期 | 核心变更 |
|------|------|---------|
| v0.1.0 | 2026-05-14 | MVP：规则引擎 + Tier 0 知识 + 五维资源 + CLI + 生存评估 + 任务规划 + 人格系统 + 地图 |
| v0.2.0 | 2026-05-15 | i18n 双语框架 + 人格五模式 + 英文知识库 + Beta 1.0 代码 Review |
| v0.3.0 | 2026-05-16 | 硬件检测/分级 + 初始化向导 + 模块化加载 + 目标系统 + 三级重置 + 初版自动化测试体系 |
| v0.4.0 | 2026-05-17 | jieba 分词 + 本地 LLM + 经验引擎 + Tier 1-2 知识 + Web UI + 每日简报/时间线/日记/天气/心理 |
| v0.5.0 | 2026-05-17 | GPS 管理器 + 环境评估 + 资源维度关联 |
| v0.6.0 | 2026-05-18 | 语音交互（Whisper STT + pyttsx3 TTS + 语音日记） |
| v0.7.0 | 2026-05-20 | **架构重构**（ServiceContainer + Command Pattern + Bootstrap）+ i18n 纯净化（700+ key 外置为 YAML）+ **Docker 弹性部署** + 知识数据 YAML 外置 + 命令层测试 + Ruff lint 全清 |
| v1.0.0 | 2026-06-13 | **首次公开发布** — SKF Web 路径遍历安全加固 + sdist 卫生修复（不再泄漏 tests/）+ TYPING_ROADMAP/BENCHMARKS/ADR 工程化文档落位 + Trove classifier 升级到 Production/Stable |
| v1.0 后维护 | 2026-06-14~17 | 22 项回归 bug（B-1~B-22）全部修复 / SHA-29 mypy Step 1–4 + 10（56 errors paid off）/ SHA-30 CI bench 软门槛 / Node 20 deprecation 修复 / `union-attr` 全部清零 |
| v1.0.1 | 2026-06-17 | **maintenance release** — 22 项回归 bug 闭环 + mypy Step 5（index, +10 errors paid off, allowlist 9→4）+ SHA-39 i18n 历史数据迁移脚本 + SHA-36 manual verification checklist + version bump |
| v1.0.2 | 2026-06-17 | **模型外置** — 模型清单外置为 `data/models.yaml`（recommendations + catalog + override 入口）+ Qwen2.5→Qwen3 全 tier 升级 + DeepSeek-V4-Flash override 入口 |
| v1.0.3 | 2026-06-24 | **稳定性收敛** — 闭环 2026-06-23 审计 P1/P2/P3（SHA-36/37/40/55/56/57/58/59/60 共 9 项）：Web 契约漂移 + 初始化向导问卷修复；tier1/2/3 英文知识库补齐；mypy 4 个 disabled code 全清（68→0）；Web 离线样式 token 收敛 + 原生弹窗替换为 toast/modal；全局搜索/通知/资源编辑反馈补齐；System 降级与环境评估改为可读卡片；Repository SKF 结果改为可读摘要；regression harness 区分允许降级；新增 Network/Docker/scheduler 回归 + 硬件 live 标记 |
| Unreleased | 2026-07-05 | **安全审计 P0-P3 修复** — H1: KnowledgeSigner `_db_path` 密钥派生 bug 修复（属性名 `db_path`，密钥不再全局常量化）；H2: Spark Network 加 `SPARKNET_MAX_INCOMING_BYTES` DoS 上限 + 接收路径 soft 签名校验（`network_shared_secret` 配置后启用，签名缺失接受为 unverified）+ 传输日志；H3: Web 非回环绑定强制 bearer token（`--web-token`，`/api/init/*` 豁免，HTML 注入 token + fetch 自动加 header）；L1/L2: ai.py/comms.py DI 违规修复 + bootstrap vision factory + self_learning 重复注册清理；L3: vision_engine 改用 `get_status()`；L8: 运行时+dev 依赖加上界；M4: ~15 处静默 except 加日志；i18n: ~76 处硬编码清理 + 67 新 key；CLAUDE.md/CONTRIBUTING.md 同步。617 passed + 6 skipped |

---

## 五、项目文件结构

```
AllSpark/
├── PRD.md                    # 产品需求文档
├── PROGRESS.md               # 本文件：开发状态追踪
├── pyproject.toml            # 项目配置
├── allspark/
│   ├── __init__.py           # __version__ = "1.0.3"
│   ├── __main__.py           # CLI 入口
│   ├── adapters/             # CLI + Web UI
│   ├── commands/             # Command Pattern 命令类（自动发现注册）
│   ├── core/                 # models / database / i18n / config / tokenizer
│   ├── infrastructure/       # hardware / module_loader / boot_manager / data_preservation
│   ├── services/             # ~25 业务服务
│   ├── container.py          # ServiceContainer
│   ├── bootstrap.py          # ApplicationBootstrap
│   ├── base_service.py       # 服务基类
│   ├── docker_manager.py     # DockerManager
│   ├── docker/               # Docker Compose 编排
│   ├── data/                 # YAML 知识数据
│   ├── locales/              # i18n YAML (zh.yaml / en.yaml)
│   └── templates/            # Web UI HTML 模板
└── tests/                    # 测试文件数与用例数以 `pytest tests/ -q` 实际输出为准
```

---

## 六、如何运行

```bash
pip install -e .
python3 -m allspark        # CLI 模式
python3 -m allspark --web  # Web UI 模式（端口 8000）
allspark                   # 如果 PATH 已配置
```

---

## 七、开发路线图

```
2026 Q2 ✅ 已完成
  v0.1 MVP → v0.2 i18n → v0.3 目标/重置/硬件 → v0.4 体验增强/LLM/Web
  v0.5 GPS/环境 → v0.6 语音 → v0.7 架构重构 + Docker
  v1.0 公开发布：开源文档 + pyproject metadata + SKF 安全加固 + sdist 卫生 +
       TYPING_ROADMAP / BENCHMARKS / ADR 工程化文档落位

2026 Q3 🔜 下一阶段
  v1.0 后观察期（GitHub Release 至少 7 天）+ 准备 v1.0.1 patch 预案
  v1.1 稳定性打磨：备份自动化 + bench 软门槛固化 + mypy 类型债开始偿还
       （按 docs/TYPING_ROADMAP.md 顺序）

2026 Q4
  v1.2 硬件适配：RPi4/5 实测 + 传感器/GPS/电力/语音硬件集成

2027+
  v2.0 高级特性：人格进化 + 支线任务 + ADR 001/002/003 落地（通信加密/
       Tier3 双签/SKF Ed25519 签名）+ 干预协议专业评审
```
