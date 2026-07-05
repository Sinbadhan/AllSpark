# AllSpark 架构设计文档

> **版本：** v1.4
> **日期：** 2026-06-24
> **状态：** v1.0.3 稳定性收敛已完成；真实硬件与 v2.0 ADR 项保持后续规划

---

## 一、架构演进

### 1.1 v0.7 前的问题（已解决）

v0.7 重构前，代码存在 6 大架构问题，现已全部通过基础设施层解决：

| # | 问题 | 严重度 | v0.7 解决方案 |
|---|------|--------|--------------|
| P1 | RuleEngine 上帝对象（3 重职责） | 🔴 | ServiceContainer + 职责收窄 |
| P2 | CLI 1940 行、29 个 _handle_xxx 内联 | 🔴 | Command Pattern + CommandDispatcher |
| P3 | 模块双重实例化（RuleEngine + CLI 各建一份） | 🟡 | ServiceContainer 统一实例化 |
| P4 | i18n 硬编码残留 ~50 处 | 🟡 | 已全部迁移至 i18n 系统 |
| P5 | 配置散落（运行时/展示/NLP 混合） | 🟡 | config.py 清理，展示文本走 i18n |
| P6 | 缺乏统一模块接口和错误处理 | 🟡 | BaseService 基类 |

### 1.2 当前实现状态

| 组件 | 状态 | 文件 |
|------|------|------|
| ✅ ServiceContainer | 已实现 | `container.py` |
| ✅ CommandDispatcher | 已实现 | `commands/dispatcher.py` |
| ✅ ApplicationBootstrap | 已实现 | `bootstrap.py` |
| ✅ BaseService 基类 | 已实现 | `base_service.py` |
| ✅ Command 拆分 | 已实现 | `commands/*.py`（10 个命令模块 / 32 个具体 Command 类） |
| ✅ i18n 纯净化 | 已完成 | `i18n.py` |
| ✅ Docker 部署支持 | 已实现 | `docker_manager.py` + `docker/` |
| ✅ 目录重组（Phase D） | **已完成** | core/services/infrastructure/adapters 子目录 |
| ✅ Web UI 模板化 | **已完成** | HTML 提取为 templates/*.html |

---

## 二、目标架构

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    表现层 (Presentation)                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │   CLI    │  │  Web UI  │  │  Voice   │                  │
│  │ Adapter  │  │ Adapter  │  │ Adapter  │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │              │              │                         │
├───────┴──────────────┴──────────────┴───────────────────────┤
│                    命令层 (Command)                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              CommandDispatcher                        │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │   │
│  │  │ SetCmd │ │GovCmd  │ │ResCmd  │ │ ...Cmd │       │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘       │   │
│  └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                    服务层 (Service)                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              ServiceContainer                         │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐             │   │
│  │  │Resource  │ │Knowledge │ │Governance│ ...          │   │
│  │  │Manager   │ │Engine    │ │Engine    │             │   │
│  └──────────┘ └──────────┘ └──────────┘             │   │
│  └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                    核心层 (Core)                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │ Database │ │  Models  │ │   i18n   │ │  Config  │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
├─────────────────────────────────────────────────────────────┤
│                    基础层 (Infrastructure)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │ Hardware │ │  Module  │ │  Boot    │ │  Data    │     │
│  │ Detect   │ │ Registry │ │ Manager  │ │Preserve  │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 设计原则

| 原则 | 说明 | 解决的问题 |
|------|------|-----------|
| **单一职责** | 每个模块只做一件事 | P1: RuleEngine 上帝对象 |
| **依赖注入** | 模块通过构造函数接收依赖，不自己创建 | P3: 双重实例化 |
| **命令模式** | CLI 命令拆分为独立 Command 类 | P2: CLI 臃肿 |
| **服务容器** | 统一的模块注册/查询机制 | P1+P3: getattr/hasattr 散落 |
| **接口协议** | 所有服务模块实现统一基类 | P6: 错误处理不一致 |
| **i18n 纯净** | 所有用户可见文本走 t() | P4: 硬编码残留 |
| **配置分离** | 运行时配置 vs 展示文本 vs NLP 数据 | P5: 配置散落 |

---

## 三、核心组件设计

### 3.1 ServiceContainer

统一的服务注册/查询/惰性实例化容器，替代 RuleEngine 的服务定位器职责。

**文件：** `container.py`

```python
class ServiceContainer:
    def __init__(self, db: Database, flags: FeatureFlags)
    def register(self, name: str, instance: Any)
    def register_factory(self, name: str, factory: Callable, *, requires: list[str] = None)
    def get(self, name: str) -> Optional[Any]        # 惰性实例化
    def has(self, name: str) -> bool
    def require(self, name: str) -> Any              # 不存在时抛 ServiceNotFoundError
```

**关键设计决策：**
- `register_factory` 声明依赖，首次 `get()` 时才创建（惰性实例化）
- `require()` 替代静默返回 None，服务不存在时明确报错
- 彻底消除 `getattr(self, 'xxx', None)` 和 `hasattr(self.engine, 'xxx')`

### 3.2 CommandDispatcher + Command Pattern

29 个内联 `_handle_xxx` 方法拆分为独立 Command 类。

**文件：** `commands/base.py`, `commands/dispatcher.py`, `commands/*.py`

```python
class BaseCommand:
    name: str
    aliases: list[str]
    help_key: str  # i18n key
    def __init__(self, container: ServiceContainer)
    def execute(self, args: list[str]) -> None
    def is_available(self) -> bool  # 统一处理模块未加载

class CommandDispatcher:
    def __init__(self, container: ServiceContainer)
    def dispatch(self, user_input: str) -> bool  # 解析 → 查找 → 执行
```

**关键设计决策：**
- cli.py 从 1940 行 → ~200 行（仅保留 REPL 循环和 banner）
- 每个 Command 类 50-150 行，职责单一
- `is_available()` 统一处理 feature flag 检查，消除 13 处 hasattr
- 命令别名集中管理

**已实现的命令：** ai, basic, comms, docker, goals, governance, hardware, help, knowledge, survival 共 10 个命令模块，当前包含 32 个具体 Command 类。

### 3.3 RuleEngine 职责收窄

从"上帝对象"收窄为纯决策引擎，仅保留：

**文件：** `rule_engine.py`

```python
class RuleEngine:
    def __init__(self, container: ServiceContainer)
    def assess(self) -> dict              # 生存评估
    def process_input(self, user_input: str) -> str  # 自然语言处理
```

**已移除的职责：**
- ❌ 模块初始化编排 → `ApplicationBootstrap`
- ❌ 模块实例持有 → `ServiceContainer`
- ❌ 帮助文本生成 → `CommandDispatcher`
- ❌ 模块注册 → `ModuleRegistry`

### 3.4 ApplicationBootstrap

独立的启动编排器，替代 RuleEngine.initialize()。

**文件：** `bootstrap.py`

```python
class ApplicationBootstrap:
    def __init__(self, db: Database, flags: FeatureFlags)
    def bootstrap(self) -> ServiceContainer     # 编排启动流程
    def _register_core_services(self)           # 无条件注册
    def _register_conditional_services(self)    # 基于 feature flag 注册
```

启动流程：核心服务 → 条件服务 → 知识加载 → 返回容器。

### 3.5 BaseService 接口协议

所有服务模块的统一基类。

**文件：** `base_service.py`

```python
class BaseService:
    SERVICE_NAME: str
    def __init__(self, db: Database, **kwargs)
    def is_available(self) -> bool
    def get_status(self) -> dict
    def startup(self) -> None
    def shutdown(self) -> None
```

提供统一的生命周期管理（startup/shutdown）、可用性检查和状态查询。

### 3.6 i18n 纯净化

所有 `console.print()` / Rich Table/Panel 中的文本必须通过 `t()` 获取。config.py 仅保留结构化数据（阈值、枚举、小时范围），展示文本全部迁移至 i18n 键值。

---

## 四、目录结构（Phase D 已完成）

v0.8 目录重组已完成，当前结构如下：

```
allspark/
├── __init__.py
├── __main__.py
│
├── core/                    # 核心层
│   ├── models.py            # 枚举 + dataclass
│   ├── database.py          # SQLite
│   ├── i18n.py              # 国际化
│   ├── config.py            # 纯结构化配置
│   └── tokenizer.py
│
├── infrastructure/          # 基础层
│   ├── hardware.py          # 硬件检测 + FeatureFlags
│   ├── module_loader.py     # ModuleRegistry
│   ├── boot_manager.py
│   └── data_preservation.py
│
├── services/                # 服务层（~25 个服务）
│   ├── resource_manager.py
│   ├── knowledge_engine.py
│   ├── survival_engine.py
│   ├── rule_engine.py       # 收窄版
│   ├── governance.py
│   ├── llm_engine.py
│   └── ...                  # 其余服务
│
├── commands/                # 命令层（当前已存在）
│   ├── base.py
│   ├── dispatcher.py
│   └── *.py                 # 10 个命令模块 / 32 个 Command 类
│
├── adapters/                # 表现层
│   ├── cli.py               # 精简版（仅 REPL）
│   └── web_ui.py
│
├── docker/                  # 部署
│   ├── docker-compose.yml
│   └── Dockerfile.*
│
├── container.py
├── bootstrap.py
├── base_service.py
├── docker_manager.py
└── data/                    # 知识数据
```

---

## 五、Docker 弹性部署

### 5.1 部署模式

| 模式 | 适用硬件 | 说明 |
|------|---------|------|
| PROCESS | ≤4GB RAM | 所有服务原生运行，无 Docker 依赖 |
| DOCKER | 8-16GB RAM | 核心服务容器化（LLM, RAG, Web UI） |
| INTEGRATION | 32GB+ RAM | Docker + NOMAD 全家桶 |

**降级链：** `INTEGRATION → DOCKER → PROCESS`

Docker 守护进程不可用时自动降级到下一级，不阻塞启动。

### 5.2 DockerManager

**文件：** `docker_manager.py`

```python
class DockerManager:
    def is_docker_available(self) -> bool
    def start_all(self) / stop_all(self)
    def start_service(service) / stop_service(service)
    def migrate_to_docker() / migrate_to_process()
    def get_logs(service, lines=50)
    def reset()  # 停止所有容器 + 删除容器和卷
```

### 5.3 容器化服务

| 服务 | 必要性 | 端口 |
|------|--------|------|
| allspark-core | 必须 | — |
| allspark-llm | 可选 | 11434 |
| allspark-rag (Qdrant) | 可选 | 6333 |
| allspark-web | 可选 | 8080 |
| allspark-kiwix | 可选 | 8081 |

**L3 出厂重置：** 停止所有容器 → 删除容器和卷 → 回归 PROCESS 模式。

### 5.4 CLI 命令

```
docker status              — 查看容器状态
docker start [服务]        — 启动服务（无参数=全部）
docker stop [服务]         — 停止服务
docker logs [服务]         — 查看日志
docker migrate docker      — 迁移到 Docker 模式
docker migrate process     — 降级回进程模式
```

---

## 六、依赖关系对比

### 重构前
```
cli.py (1940行) ──→ RuleEngine ──→ 20+ 模块实例
  │                      │
  │                      └── getattr/hasattr × 33
  ├── _lazy_init × 8  ←── 与 RuleEngine 双重实例化
  └── 29 个 _handle_xxx 内联
```

### 重构后（v0.7）
```
cli.py (~200行) ──→ CommandDispatcher ──→ Command 类
                         │
                         └──→ ServiceContainer ──→ 各 Service
                                    │
                                    ├── register() / get() / has()
                                    └── 惰性实例化 + 依赖注入
```

---

## 七、成功指标

| 指标 | 重构前 | v0.7 当前 | 目标 |
|------|--------|----------|------|
| cli.py 行数 | 1940 | 167 | < 300 |
| web_ui.py 行数 | 1254 | 301 | < 400 |
| i18n.py 行数 | 2244 | 96 | < 200 |
| hasattr/getattr 防御检查 | 33 处 | 0 | 0 |
| _lazy_init 双重实例化 | 8 处 | 0 | 0 |
| i18n 硬编码 | ~50 处 | 0 | 0 |
| 裸 print() 调用 | ~15 处 | 0（源码内无裸 print；展示层使用 Rich console.print） | 0 |
| 测试用例 | 281 | 622 collected（本机/CI 口径：616 passed + 6 skipped；受限 sandbox 当前 614 passed + 8 skipped，本地 TCP 网络项显式 skip / environment_blocked） | 400+ |

---

## 八、后续待办

1. ~~**目录重组（Phase D）**~~ — ✅ 已完成
2. ~~**Web UI 模板化修复**~~ — ✅ 已完成
3. ~~**测试覆盖提升至 350+**~~ — ✅ 已完成（当前以 `pytest tests/ -q` 实际输出为准）
4. **模块加载时间基准测试** — `tests/bench_import.py` 已存在，后续可补正式基准记录与门槛
5. ~~**SKF route DI 收尾**~~ — ✅ 已完成，`KnowledgeVerifier` 已由 ServiceContainer 提供
