# 🔥 火种 AllSpark — 离线人工智能生存系统

**v0.2.0** | [English](README.md)

> **在极端条件下，保存并重建人类文明。**

火种 AllSpark（AllSpark: A Survival-centric Offline AI Resource Kit）是一个离线优先的 AI 生存辅助系统。它可以在从树莓派到笔记本电脑的硬件上运行，在文明基础设施崩溃时提供知识、决策支持和社区治理能力。

---

## 核心原则

- **离线优先** — 无需网络即可运行，所有数据和模型存储在本地
- **渐进智能** — 从纯规则引擎到本地 LLM，根据硬件能力弹性升级
- **知识即生命** — 内置多层生存知识库，支持节点间知识交换
- **自适应生存** — 根据资源状态自动调整运行模式和交互人格
- **文明传承** — 记录经验、验证知识、传承技能，重建文明根基

---

## 功能概览

### 🧠 智能引擎
| 功能 | 描述 |
|------|------|
| 规则引擎 | 基于知识库的确定性生存建议，意图识别 + 知识检索 |
| 本地 LLM | llama-cpp-python 推理，Qwen2.5 系列（1.5B~72B），按硬件自动选择 |
| 生存评估 | 5维资源评估 + 阶段判定 + 瓶颈识别 |
| 人格系统 | 危机/稳定/伴侣/多人/复兴 — 5种自适应模式 |
| 经验积累 | 经验记录 → 模式识别 → 知识条目循环 |

### 📚 知识体系
| 层级 | 内容 | 条目数 |
|------|------|--------|
| Tier 0 | 即时生存（水/火/食物/庇护/医疗） | 23 |
| Tier 1 | 短期生存（农业/化学/力学/天气/能源） | 10 |
| Tier 2 | 中期自足（堆肥/造纸/水电/沼气/草药） | 10 |
| Tier 3 | 长期社区（治理/锻造/发电/法律/文明档案） | 17 |

### 📡 连接与通信
| 功能 | 描述 |
|------|------|
| SKF 知识包 | ZIP 格式标准化知识导入/导出 |
| 知识验证 | 5步验证：格式 → 来源 → 一致性 → 交叉引用 → 评级 |
| 火种网络 | UDP 信标 + TCP 知识交换，局域网/蓝牙/WiFi Direct |
| 知识交易 | 提议/接受/拒绝/评估 节点间知识交换协议 |
| 图像识别 | 多模态 LLM 分析（植物/伤口/危险/庇护所/水源/工具） |

### 👥 多人与治理
| 功能 | 描述 |
|------|------|
| 权限系统 | 指挥官/专家/执行者/观察者 — 4级角色 + 权限矩阵 |
| 动态角色 | 基于贡献和技能自动推荐角色晋升 |
| 冲突调解 | 创建 → AI 调解 → 解决 全流程 |
| 生存价值 | 5维评估（仅指挥官，仅供参考） |
| 组织评估 | 自动评估结构合理性，建议分组/角色补充 |

### ⚡ 硬件适配
| 功能 | 描述 |
|------|------|
| 电源监控 | RPi GPIO ADC + 模拟/手动回退，电源注册 + 运行时间估算 |
| 传感器中枢 | I2C/GPIO/串口多接口，8种传感器自动检测 |
| 数据保存 | 定时保存 + 紧急保存 + 快照/恢复 + 信号处理 |
| 启动优化 | 启动计时 + systemd 服务模板 + 看门狗脚本 |

### 🖥 界面
| 界面 | 描述 |
|------|------|
| CLI | Rich 增强终端，中英双语命令 |
| Web UI | FastAPI + 响应式前端，手机/平板/桌面均可访问 |
| 初始化向导 | CLI/Web 双模式，语言 → 硬件检测 → 模型 → 幸存者档案 |

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
knowledge <关键词>      — 搜索知识库
experience log <事件> <结果>  — 记录经验
map add <名称> <类型>   — 添加地图地点
llm load               — 加载 LLM 模型
skf export <路径>      — 导出知识包
community add <名字> [角色] — 添加社区成员
power status           — 电源监控状态
preserve snapshot [标签] — 创建数据快照
help                   — 完整帮助
```

---

## 硬件要求

| 等级 | 内存 | 存储 | 设备 | LLM 模型 |
|------|------|------|------|----------|
| 残影 | 2 GB | 16 GB | 树莓派 4 | Qwen2.5-1.5B-Q4 |
| 最低 | 4 GB | 32 GB | 树莓派 5 | Qwen2.5-3B-Q4 |
| 推荐 | 8 GB | 64 GB | 迷你主机 | Qwen2.5-7B-Q4 |
| 舒适 | 16 GB | 128 GB | 笔记本 | Qwen2.5-14B-Q4 |
| 旗舰 | 32 GB+ | 256 GB+ | 工作站 | Qwen2.5-72B-Q4 |

> 没有 LLM，系统仍可通过规则引擎正常运行，仅失去开放式问答能力。

### 功能可用性矩阵

| 功能 | 残影 | 最低 | 推荐 | 舒适 | 旗舰 |
|------|------|------|------|------|------|
| 规则引擎 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 本地 LLM | 1.5B | 3B | 7B | 14B | 72B |
| 知识库 (FTS+RAG) | FTS | FTS+轻量RAG | FTS+RAG | FTS+RAG | FTS+完整RAG |
| 图像识别 | ❌ | ⚠️ | ✅ | ✅ | ✅ |
| Web UI | ❌ | ⚠️ | ✅ | ✅ | ✅ |
| 社区治理 | ❌ | ❌ | ✅ | ✅ | ✅ |
| 知识交易 | ❌ | ❌ | ⚠️ | ✅ | ✅ |
| 电源监控 | ❌ | ⚠️ | ✅ | ✅ | ✅ |
| 传感器中枢 | ❌ | ❌ | ⚠️ | ✅ | ✅ |
| 数据保存 | ❌ | ✅ | ✅ | ✅ | ✅ |
| 启动优化 | ❌ | ❌ | ⚠️ | ✅ | ✅ |

---

## 项目结构

```
AllSpark/
├── pyproject.toml                  # 项目配置
├── README.md                       # 英文 README
├── README_CN.md                    # 本文件（中文）
│
└── allspark/                       # 核心代码
    ├── __main__.py                 # 入口
    ├── __init__.py                 # 版本
    ├── cli.py                      # CLI 界面
    ├── web_ui.py                   # Web UI (FastAPI)
    │
    ├── models.py                   # 数据模型
    ├── database.py                 # SQLite 数据库层
    ├── config.py                   # 配置常量
    ├── i18n.py                     # 国际化
    │
    ├── rule_engine.py              # 规则引擎
    ├── survival_engine.py          # 生存评估
    ├── mission_planner.py          # 任务规划
    ├── knowledge_engine.py         # 知识引擎
    ├── knowledge_loader.py         # 统一知识加载
    ├── resource_manager.py         # 资源管理
    ├── personality.py              # 人格系统
    ├── map_system.py               # 地图系统
    ├── experience_engine.py        # 经验积累
    ├── llm_engine.py              # 本地 LLM
    │
    ├── skf_manager.py             # SKF 知识包
    ├── knowledge_verifier.py      # 知识验证
    ├── spark_network.py           # 火种网络
    ├── vision_engine.py           # 图像识别
    │
    ├── governance.py              # 社区治理
    ├── trade_engine.py            # 知识交易
    │
    ├── power_monitor.py           # 电源监控
    ├── sensor_hub.py              # 传感器中枢
    ├── data_preservation.py       # 数据保存
    ├── boot_manager.py            # 启动管理
    │
    ├── hardware.py                # 硬件检测
    ├── module_loader.py           # 模块注册
    ├── init_wizard.py             # 初始化向导
    ├── tokenizer.py               # 中文分词
    │
    ├── knowledge_data.py          # Tier 0 知识（中文）
    ├── knowledge_data_en.py       # Tier 0 知识（英文）
    ├── knowledge_data_tier12.py   # Tier 1-2 知识
    └── knowledge_data_tier3.py    # Tier 3 知识
```

---

## API 端点

Web UI 提供 70+ RESTful API 端点：

| 模块 | 端点 | 描述 |
|------|------|------|
| 核心 | `/api/status` `/api/resources` `/api/tasks` `/api/chat` | 状态/资源/任务/对话 |
| 知识 | `/api/knowledge/search` `/api/knowledge/category` `/api/knowledge/detail` | 搜索/分类/详情 |
| LLM | `/api/llm/status` `/api/llm/load` `/api/llm/chat` | 模型管理/对话 |
| 经验 | `/api/experience/log` `/api/experience/patterns` | 记录/模式 |
| SKF | `/api/skf/info` `/api/skf/export` `/api/skf/import` | 知识包管理 |
| 验证 | `/api/verify/stats` `/api/verify/entry` `/api/verify/batch` | 知识验证 |
| 网络 | `/api/network/status` `/api/network/start` `/api/network/exchange` | 火种网络 |
| 视觉 | `/api/vision/status` `/api/vision/analyze` | 图像分析 |
| 治理 | `/api/governance/members` `/api/governance/assess` `/api/governance/conflicts` | 社区治理 |
| 交易 | `/api/trade/status` `/api/trade/propose` `/api/trade/evaluate` | 知识交易 |
| 电源 | `/api/power/status` `/api/power/monitor/start` `/api/power/runtime` | 电源监控 |
| 传感器 | `/api/sensor/status` `/api/sensor/snapshot` `/api/sensor/detect` | 环境感知 |
| 保存 | `/api/preserve/status` `/api/preserve/snapshot` `/api/preserve/emergency` | 数据保护 |

---

## 开发阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1 — MVP | 规则引擎 + Tier 0 知识 + CLI + 5维资源 + 人格 + 地图 | ✅ |
| 2 — 智能 | jieba 分词 + 本地 LLM + 经验 + Web UI + Tier 1-2 | ✅ |
| 3 — 连接 | SKF 包 + 知识验证 + 火种网络 + 图像识别 | ✅ |
| 4 — 多人 | 权限系统 + 动态角色 + 冲突调解 + 知识交易 + Tier 3 | ✅ |
| 5 — 硬件 | 电源监控 + 传感器 + 数据保存 + 启动优化 | ✅ |

---

## 参与贡献

欢迎贡献！你可以：

- 提交 Issue 报告 Bug 或建议功能
- 提交 Pull Request 改进代码
- 扩充知识库内容（Tier 0-3 条目）
- 将知识库翻译为更多语言

---

## 许可证

Apache License 2.0

---

> *火种不灭，文明永续。*
