# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

AllSpark（火种）— 离线人工智能生存系统，面向极客/生存主义者。极端环境下提供生存决策、资源管理、知识检索、多人治理。Python 3.10+，当前版本 v1.0.3。

## 常用命令

```bash
# 安装（开发模式）
pip install -e ".[dev]"

# 运行
allspark                          # 入口，等同 python -m allspark

# 测试
pytest tests/ -q                  # 全量测试；CI 复现完整 tracked tests（以 `pytest tests/ -q` / CI 实际输出为准）
pytest tests/test_container.py    # 单个测试文件
pytest -k "test_register"         # 按名匹配
python3 tests/regression/run_all.py  # 脚本化回归；受限 sandbox 会显式标记 environment_blocked

# Lint & 类型检查
ruff check allspark/ tests/
python3 -m mypy allspark/ --ignore-missing-imports  # pyproject 已启用 check_untyped_defs

# 启动性能门槛
python3 scripts/bench_import.py --check

# CI 等效本地检查（GitHub Actions 已配置：ruff + mypy + pytest on 3.10/3.11/3.12）
```

## 架构

四层分层 + 依赖注入，v0.7 从"上帝对象"重构而来：

```
表现层 (adapters/)     CLI / Web UI / Voice
    ↓
命令层 (commands/)     CommandDispatcher → 10 个命令模块 / 32 个 Command 类
    ↓
服务层 (services/)     ServiceContainer 管理的 ~25 个 Service
    ↓
核心层 (core/)         Database / Models / i18n / Config / Tokenizer
    ↓
基础层 (infrastructure/)  Hardware Detect / ModuleRegistry / Boot / DataPreserve
```

**关键组件：**
- **ServiceContainer** (`container.py`) — 统一服务注册/惰性实例化/依赖注入，替代旧 getattr/hasattr 散落
- **CommandDispatcher** (`commands/dispatcher.py`) — 解析用户输入 → 查找命令 → 执行，cli.py 从 1940 行缩至 167 行
- **ApplicationBootstrap** (`bootstrap.py`) — 启动编排：核心服务 → 条件服务（feature flag 控制）→ 知识加载 → 返回容器
- **BaseService** (`base_service.py`) — 所有服务的基类，统一生命周期 (startup/shutdown)、可用性检查、状态查询
- **RuleEngine** (`services/rule_engine.py`) — 已收窄为纯决策引擎（assess + process_input），不再持有模块实例

**Docker 弹性部署：** 三级降级链 `INTEGRATION → DOCKER → PROCESS`，由 `DockerManager` 根据硬件自动选择。4GB 设备无 Docker 开销。

## 目录结构

```
allspark/
├── adapters/           # CLI (仅 REPL) + Web UI (FastAPI)
├── commands/           # 10 个命令模块 + 32 个 Command 类 + dispatcher + base
├── core/               # models, database, i18n, config, tokenizer
├── infrastructure/     # hardware, module_loader, boot_manager, data_preservation
├── services/           # ~25 个业务服务 (resource, knowledge, governance, llm, scheduler...)
├── docker/             # Dockerfile + docker-compose.yml
├── data/               # YAML 知识数据 + 翻译文件
├── locales/            # i18n YAML
├── templates/          # Web UI HTML 模板
├── container.py        # ServiceContainer
├── bootstrap.py        # ApplicationBootstrap
└── base_service.py     # 服务基类
```

## 编码规范

### i18n — 硬性规则
- **所有用户可见文本必须走 `t()` 函数**，禁止硬编码中英文
- config.py 仅放结构化数据（阈值、枚举），展示文本走 i18n key

### 日志
- 生产用 `logging`，展示层可用 `console.print`（Rich），**禁止裸 `print()`**

### 依赖注入
- 服务通过 `container.get()` 获取，**禁止** `from allspark.services.xxx import` 直接导入服务实例

### 命令注册
- 新命令：在 `commands/` 下创建 Command 类（继承 BaseCommand），系统自动发现注册

### 知识数据
- 新增知识内容放 `data/knowledge/*.yaml`，通过 `knowledge_loader.py` 加载，**不要**往 Python dict 里硬编码

## 设计风格

极客终端/航天仪表盘风格：冷峻精确、高信息密度。色彩体系 PRIMARY=#ff6b35 / CRITICAL=#ff4444 / WARNING=#ffaa00 / SUCCESS=#44cc44 / BG=#0a0a0a。CLI 用 Rich Table/Panel，状态标记用 ✓✗⚠◇。详见 `.trae/rules/`。

## 当前状态（v1.0.3）

- v1.0.3 稳定性收敛已完成，P1 类型债与 Web/回归高优先级问题已闭环
- 完整 tracked tests 已收集（以 `pytest tests/ -q` / CI 实际输出为准；CI 复现，SHA-28；覆盖率门禁 60% floor + 收集数门禁，SHA-151）
- Ruff lint 0 errors
- mypy 0 errors，`check_untyped_defs = true` 已启用
- `scripts/bench_import.py --check` 当前低于 600ms 门槛
- 知识数据已外置为 YAML（旧 Python dict 文件已删除）
- i18n 已外置为 `locales/zh.yaml` + `locales/en.yaml`（i18n.py 仅 96 行）
- Scheduler 已接入 bootstrap
- 命令自动发现注册已实现（10 个命令模块 / 32 个 Command 类）
- 剩余改进项：P2 真实环境集成验证（GPU/Docker/RPi/传感器/LLM 实机）、P3 视觉回归基线、bench `--hard-fail` 升级
