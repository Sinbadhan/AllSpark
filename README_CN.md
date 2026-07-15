# 🔥 火种 AllSpark — 离线人工智能生存系统

**v1.0.3** | 发布候选版 | [English](README.md)

> **在极端条件下，保存并重建人类文明。**

火种 AllSpark（AllSpark: A Survival-centric Offline AI Resource Kit）是一个离线优先的 AI 生存辅助系统。代码包含桌面端与树莓派适配器，但 v1.0.3 的稳定支持边界是下文定义的桌面 PROCESS 模式核心能力。

---

## 核心原则

- **离线优先** — 无需网络即可运行，所有数据和模型存储在本地
- **渐进智能** — 从纯规则引擎到本地 LLM，根据硬件能力弹性升级
- **知识即生命** — 内置多层生存知识库，支持节点间知识交换
- **自适应生存** — 根据资源状态自动调整运行模式和交互人格
- **文明传承** — 记录经验、验证知识、传承技能，重建文明根基

---

## v1.0.3 发布支持边界

下表定义本次公开发布的预期支持范围。候选版只有在
[发布清单](docs/RELEASE_CHECKLIST.md)全部通过后才可称为 Stable；代码存在不等于已经验收。

| 状态 | 范围 |
|------|------|
| 稳定支持 | Python 3.10-3.12；桌面 PROCESS 模式；CLI 与 Web UI；本地 SQLite；规则评估；知识搜索/导入/导出；资源、目标、任务和日记；本地快照/恢复；macOS VoiceOver 核心 Web 流程 |
| Experimental | 治理/RBAC（成员身份和服务端授权完成验证前保持禁用）；Windows 读屏兼容性（NVDA，测试阶段）；Docker/INTEGRATION；真实 GGUF/LLM 与 GPU；麦克风/STT/TTS；摄像头/视觉；树莓派 GPIO/I2C/串口、传感器、电力与硬件 GPS；跨主机火种网络；可移动介质灾难恢复 |
| v1.0.3 不支持 | 蓝牙和 Wi-Fi Direct 传输。当前火种网络传输层是局域网 TCP；无线通道可用性探测不等于实现传输。 |

单机独立进程间的火种网络交换已有自动化集成证据，但不能证明跨主机、无线电或野外部署可用。
当前证据见[真实环境验证](docs/REAL_WORLD_VALIDATION.md)。
Windows 读屏兼容性仍处于测试阶段；在真实 Windows + NVDA 证据附上前，
不属于 v1.0.3 的稳定无障碍支持声明。

---

## 功能概览

### 🧠 智能引擎
| 功能 | 描述 |
|------|------|
| 规则引擎 | 基于知识库的确定性生存建议，意图识别 + 知识检索 |
| 本地 LLM（Experimental） | llama-cpp-python 推理路径与 Qwen3 规格建议；尚未认证发布用 GGUF 运行时 |
| 生存评估 | 5维资源评估 + 阶段判定 + 瓶颈识别 |
| 人格系统 | 危机/稳定/伴侣/多人/复兴 — 5种自适应模式 |
| 经验积累 | 经验记录 → 模式识别 → 知识条目循环 |
| 每日简报 | 自动生成生存日报：资源 + 警告 + 目标 + 任务 + 知识提示 |
| 心理追踪（Experimental） | 孤独/压力指数 + 自评问卷 + 干预触发 |

### 🎯 目标与任务系统
| 功能 | 描述 |
|------|------|
| 目标引擎 | 资源状态自动生成目标 + 6模板 + 手动目标 |
| 里程碑追踪 | 里程碑自动计算进度；全部完成 → 目标完成 |
| 目标-任务联动 | 目标 → 任务双向同步；完成任务推进里程碑 |
| 天气-目标联动（Experimental） | 恶劣天气自动暂停户外目标 + 创建庇护所加固 |
| 三级重置 | L1（评估）/ L2（档案）/ L3（出厂）+ 安全约束 + 冷却期 |

### 📚 知识体系
| 层级 | 内容 | 条目数 |
|------|------|--------|
| Tier 0 | 即时生存（水/火/食物/庇护/医疗） | 23 |
| Tier 1 | 短期生存（农业/化学/力学/天气/能源） | 10 |
| Tier 2 | 中期自足（堆肥/造纸/水电/沼气/草药） | 10 |
| Tier 3 | 长期社区（治理/锻造/发电/法律/文明档案） | 17 |
| SKF 知识包 | ZIP 格式标准化知识导入/导出，SHA256 校验 |

### 📡 连接与通信
| 功能 | 描述 |
|------|------|
| 知识验证 | 5步验证：格式 → 来源 → 一致性 → 交叉引用 → 评级 |
| 火种网络（Experimental） | UDP 发现 + 局域网 TCP 知识交换；单机多进程已验证，跨主机未认证 |
| 知识交易（Experimental） | 提议/接受/拒绝/评估 节点间知识交换协议 |
| 图像识别（Experimental） | 多模态分析路径；摄像头与目标模型运行时未认证 |

### 👥 多人与治理（Experimental，已禁用）
| 功能 | 描述 |
|------|------|
| 权限系统（Experimental） | 原型代码包含角色矩阵，但 Web/CLI 操作者尚未绑定社区成员，因此当前不是实际执行的 RBAC 安全边界。 |
| 治理操作（Unavailable） | v1 的 Web 与 CLI 成员、角色和冲突操作均服务端 fail closed。 |
| 生存价值（Unavailable） | v1 产品不暴露；没有经过验证的成员身份时，无法执行“仅指挥官可见”。 |

### 🌍 环境与导航
| 功能 | 描述 |
|------|------|
| GPS 管理器 | 手动定位稳定支持；物理 GPS/传感器输入仍为 Experimental |
| 环境评估（Experimental） | 4维：气候/地形/威胁/机会 + 综合评分 |
| 天气预测（Experimental） | 气压 → 12h 预报（晴/雨/暴风）+ 云图指南 |
| 地图系统（Experimental） | 文本地图 + POI 管理 + 分类视图 |

### 📝 日记与时间线
| 功能 | 描述 |
|------|------|
| 火种日记 | 文字/情感记录 + 关键词标签 + 日期索引 + 隐私保护 |
| 生存时间线 | 7种事件类型 + 逐日视图 + 自动记录目标/里程碑/资源变化 |
| 日记-时间线联动 | 日记条目自动出现在生存时间线 |

### 🎙️ 语音交互（Experimental）
| 功能 | 描述 |
|------|------|
| 语音转文字 | Whisper 多语言模型，麦克风录音 + 文件转录 |
| 文字转语音 | pyttsx3 离线语音输出 |
| 语音日记 | 语音 → 转录 → 自动保存到日记系统 |
| 优雅降级 | Whisper/pyttsx3 不可用时提供友好安装提示 |

### 🐳 Docker 弹性部署（Experimental）
| 功能 | 描述 |
|------|------|
| 部署模式 | PROCESS / DOCKER / INTEGRATION — 按硬件等级自动选择 |
| Docker 管理器 | 容器生命周期管理（启动/停止/迁移/重置） |
| Docker Compose | Core/LLM/RAG/Web/Kiwix 服务编排 |
| 弹性降级 | Docker 不可用时自动降级为进程模式 |
| 重置回归 | L3 出厂重置清除所有容器，回归进程模式 |

### ⚡ 硬件适配
| 功能 | 描述 |
|------|------|
| 电源监控（硬件 Experimental） | 模拟/手动回退可用；RPi GPIO ADC 尚未实机认证 |
| 传感器中枢（Experimental） | I2C/GPIO/串口适配器已实现，目标传感器尚未实机认证 |
| 数据保存 | 本地原子快照/恢复 + checksum/完整性检查；可移动介质恢复为 Experimental |
| 启动优化（Experimental） | 启动计时 + systemd/看门狗模板；目标 Linux 启动部署未认证 |
| 启动完整性 | DB 文件 + 表完整性 + 启动时缺失表检测 |

### 🖥 界面
| 界面 | 描述 |
|------|------|
| CLI | Rich 增强终端，中英双语命令（30+ 命令） |
| Web UI | FastAPI + 响应式前端，手机/平板/桌面均可访问 |
| 初始化向导 | CLI/Web 双模式，语言 → 硬件检测 → 模型 → 幸存者档案 |
| i18n | 完整中英双语系统，运行时语言切换（700+ key） |

---

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/Sinbadhan/AllSpark.git && cd AllSpark

# 安装依赖
pip install -e .

# （可选）安装本地 LLM 支持
pip install llama-cpp-python

# （可选）树莓派硬件支持
pip install RPi.GPIO smbus2 pyserial

# （可选）语音交互
pip install openai-whisper sounddevice pyttsx3
```

### 启动

```bash
# CLI 模式（首次启动自动运行初始化向导）
python3 -m allspark

# Web UI 模式
python3 -m allspark --web
# 或
python3 -m allspark -w
```

### 常用命令

```
status                  — 查看生存状态和资源
resource                — 查看5维资源详情
goals                   — 查看和管理生存目标
briefing                — 生成每日生存简报
diary add               — 写日记
weather                 — 天气预测
gps set <lat> <lon>     — 设置 GPS 位置
psychology              — 查看心理状态
environment             — 环境评估
voice load              — 加载 Whisper 语音模型
docker status           — Docker 部署状态
help                    — 完整帮助
```

---

## 硬件规格建议

| 等级 | 内存 | 存储 | 设备 | LLM 模型 | 部署模式 |
|------|------|------|------|----------|----------|
| 残影 | 2 GB | 16 GB | 树莓派 4 | Qwen3-1.7B-Instruct-Q4 | 进程模式 |
| 最低 | 4 GB | 32 GB | 树莓派 5 | Qwen3-4B-Instruct-Q4 | 进程模式 |
| 推荐 | 8 GB | 64 GB | 迷你主机 | Qwen3-8B-Instruct-Q4 | Docker 模式 |
| 舒适 | 16 GB | 128 GB | 笔记本 | Qwen3-14B-Instruct-Q4 | Docker 模式 |
| 旗舰 | 32 GB+ | 256 GB+ | 工作站 | Qwen3-32B-Instruct-Q4 | 集成模式 |

> 没有 LLM，系统仍可通过规则引擎正常运行，仅失去开放式问答能力。
>
> 模型与部署模式是容量建议，不是 v1.0.3 支持认证。Docker/INTEGRATION、
> 树莓派和真实 GGUF 执行在真实环境矩阵通过前均为 Experimental。

---

## 项目结构

```
AllSpark/
├── pyproject.toml                  # 项目配置
├── LICENSE                         # Apache 2.0
├── README.md                       # 英文 README
├── README_CN.md                    # 本文件（中文）
│
├── allspark/                       # 源代码
│   ├── __main__.py                 # 入口（CLI/Web 模式切换）
│   ├── __init__.py                 # 版本
│   ├── bootstrap.py                # 应用引导与初始化
│   ├── container.py                # ServiceContainer 依赖注入容器
│   ├── base_service.py             # 服务生命周期基类
│   ├── docker_manager.py           # Docker 容器生命周期管理
│   ├── py.typed                    # PEP 561 类型标记
│   │
│   ├── adapters/                   # 表现层
│   │   ├── cli.py                  # Rich 终端 REPL
│   │   ├── web_ui.py               # FastAPI 应用 + 初始化路由
│   │   ├── init_wizard.py          # CLI 初始化向导
│   │   └── routes/                 # Web API 路由模块
│   │
│   ├── commands/                   # 命令模式层
│   │   ├── base.py                 # BaseCommand 抽象类
│   │   ├── dispatcher.py           # 自动发现 CommandDispatcher
│   │   ├── basic.py                # 状态/资源/帮助命令
│   │   ├── survival.py             # 生存/评估命令
│   │   ├── knowledge.py            # 知识/搜索命令
│   │   ├── ai.py                   # LLM/经验命令
│   │   ├── goals.py                # 目标/任务/重置命令
│   │   ├── governance.py           # 社区/权限命令
│   │   ├── comms.py                # 网络/交易命令
│   │   ├── hardware.py             # 电源/传感器/保存命令
│   │   ├── docker.py               # Docker 管理命令
│   │   └── help.py                 # 帮助命令
│   │
│   ├── core/                       # 核心数据/配置层
│   │   ├── config.py               # 配置常量
│   │   ├── database.py             # SQLite 数据库层 (FTS5)
│   │   ├── i18n.py                 # 国际化加载器
│   │   ├── models.py               # 数据模型
│   │   └── tokenizer.py            # 中文分词
│   │
│   ├── services/                   # 业务服务层（约 25 个服务）
│   │   ├── rule_engine.py          # 核心决策引擎
│   │   ├── resource_manager.py     # 资源管理
│   │   ├── survival_engine.py      # 生存评估
│   │   ├── mission_planner.py      # 任务规划
│   │   ├── knowledge_engine.py     # 知识检索
│   │   ├── knowledge_loader.py     # YAML 知识加载
│   │   ├── goal_engine.py          # 目标与里程碑
│   │   ├── priority_calculator.py  # 多维度优先级评分
│   │   ├── warning_protocol.py     # 资源预警闭环
│   │   ├── vector_engine.py        # FTS/向量混合检索
│   │   ├── external_kb.py          # Kiwix/Kolibri/ProtoMaps 集成
│   │   ├── voice.py                # 语音会话路由
│   │   └── ...                     # 治理、日记、天气、GPS 等
│   │
│   ├── infrastructure/             # 硬件/平台层
│   │   ├── hardware.py             # 硬件检测 + FeatureFlags
│   │   ├── module_loader.py        # 模块注册表
│   │   ├── data_preservation.py    # 快照/恢复/完整性检查
│   │   └── boot_manager.py         # systemd/watchdog 启动支持
│   │
│   ├── data/                       # YAML 生存知识数据
│   │   └── knowledge/              # Tier 0-3 知识条目
│   ├── locales/                    # zh/en i18n YAML 文件
│   ├── templates/                  # Web UI HTML 模板
│   └── docker/                     # Dockerfile + docker-compose.yml
│
└── tests/                          # 已跟踪自动化测试（数量以 pytest tests/ -q / CI 为准）
```

---

## 开发阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1 — MVP | 规则引擎 + Tier 0 知识 + CLI + 5维资源 + 人格 + 地图 | ✅ |
| 2 — 智能 | jieba 分词 + 本地 LLM + 经验 + Web UI + Tier 1-2 + i18n | 核心完成；LLM Experimental |
| 3 — 连接 | SKF 包 + 知识验证 + 火种网络 + 图像识别 | SKF 完成；网络/视觉 Experimental |
| 4 — 多人 | Experimental 治理原型 + 知识交易 + Tier 3 知识 | Experimental |
| 5 — 硬件 | 电源监控 + 传感器 + 数据保存 + 启动优化 | 本地数据保存完成；硬件 Experimental |
| 6 — 目标与环境 | 目标引擎 + 三级重置 + 每日简报 + 时间线 + 日记 + 天气 + 心理 + GPS + 环境 + 语音 | 核心完成；物理 I/O Experimental |
| 7 — 架构与Docker | ServiceContainer 依赖注入 + Command 命令模式 + Bootstrap + i18n 纯净化 + Docker 弹性部署 | 架构完成；Docker Experimental |

---

## 质量状态

| 检查项 | 状态 |
|--------|------|
| 自动化测试 | ✅ 以 CI / pytest 输出为准 |
| Ruff lint | ✅ 0 errors |
| mypy | ✅ CI 强制执行 `check_untyped_defs`，无禁用 error-code 类别 |
| 类型发布标记 | ✅ 已包含 `py.typed` |
| 公开仓库卫生 | ✅ 测试已跟踪以复现 CI；运行时数据、本地模型、密钥与构建产物保持忽略 |

---

## 测试

```bash
# 运行全部测试
python3 -m pytest tests/ -v --tb=short

# 运行特定模块
python3 -m pytest tests/test_goal_engine.py -v
```

---

## 参与贡献

欢迎贡献。请先阅读以下项目文档：

- [贡献指南](CONTRIBUTING.md) — 开发环境、检查命令、PR 规范、编码约定
- [安全策略](SECURITY.md) — 私下漏洞报告与敏感数据边界
- [行为准则](CODE_OF_CONDUCT.md) — 社区协作行为预期
- [变更日志](CHANGELOG.md) — 版本历史
- [配置指南](docs/CONFIGURATION.md) — 本地数据、可选功能、Docker 模式、SKF/网络边界
- [发布清单](docs/RELEASE_CHECKLIST.md) — 版本号、QA、打包与发布步骤

---

## 许可证

Apache License 2.0

---

> *火种不灭，文明永续。*
