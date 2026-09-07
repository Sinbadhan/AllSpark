# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

AllSpark（火种）— 离线人工智能生存系统，面向极客/生存主义者。极端环境下提供生存决策、资源管理、知识检索、多人治理。Python 3.10+，当前版本 v1.0.3。

## 优化计划权威入口（2026-09-07 切换）

- 本轮高 ROI 优化的目标、范围、验收和决策统一维护在[飞书知识库正式计划](https://my.feishu.cn/docx/Ps4mdBreKojEIMx3W15cJVBOnc0)。
- AS-01 至 AS-16 及后续工作的 TODO、负责人、下一步、状态和完成证据统一维护在[AllSpark 飞书任务清单](https://applink.feishu.cn/client/todo/task_list?guid=4c10dae7-8a5b-4808-a1ae-09a78b13458c)；本地计划只保留切换前快照，不再维护第二套进度。
- 原始计划、审计报告和机器证据保存在 [AS-01 任务附件](https://applink.feishu.cn/client/todo/detail?guid=ced39300-24df-4635-be36-e882789e0672)及本地证据目录；后续代码、机器契约和必要执行证据继续在本地持久保留。
- 2026-09-07 用户明确停用 Linear；后续正式文档、任务、审计与发布决策全部使用上述飞书入口。SHA-* 仅保留历史追溯标识，不再读取、写入或要求恢复 Linear；缺失历史签核标为未核实，不推导为已通过。发布决策统一归 AS-15。
- 用户已授权本轮候选推送、PR、主分支保护与合并；发布必须另有用户明确要求，合并和 CI 通过不等于 tag、GitHub Release、PyPI 发布或 Stable。专家、真人、指定浏览器和干净设备门禁不变。

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
python3 scripts/bench_import.py --check --hard-fail

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

## 当前状态（v1.0.3 Release Candidate）

- v1.0.3 尚未 tag 或发布；飞书 AS-15 是实时发布决策权威入口，M4 产品门禁与外部复核未完成，因此 Stable 结论仍为 No-Go；以下 SHA-* 为历史证据标识
- 2026-07-15 发现的 8 个 High/P1、本轮 CLI/Repository/CI P2、执行中心入口、CSP enforcing、发布事务一致性与最终 RC 跨流程复验均已闭环
- 完整 tracked tests 已收集（以 `pytest tests/ -q` / CI 实际输出为准；CI 在 Python 3.10/3.11/3.12 复现，SHA-28）
- AS-08 / SHA-151 质量门禁：Python 3.12 为主覆盖环境，3.10 覆盖仍作为兼容基线强制保留；两者均要求总行覆盖率 ≥75%、10 个关键路径模块分支覆盖率 ≥90%；3.10/3.11/3.12 均运行完整测试与收集数防回退门禁，不扩大至 3.13/3.14
- Ruff lint 0 errors
- mypy 0 errors，`check_untyped_defs = true` 已启用
- `scripts/bench_import.py --check --hard-fail` 强制执行 600ms sum-of-means 与 2000ms cold-wall 门禁；导入失败、空测量和非法预算也必须失败。是否通过以当前候选输出为准
- 知识数据已外置为 YAML（旧 Python dict 文件已删除）
- i18n 已外置为 `locales/zh.yaml` + `locales/en.yaml`（i18n.py 157 行）
- Scheduler 已接入 bootstrap
- 命令自动发现注册已实现（10 个命令模块 / 32 个 Command 类）
- Web 脚本使用逐请求 nonce，`script-src-attr 'none'` 禁止内联事件处理器；七页面真实 Chrome CSP violation 门禁为 0
- M4 信息架构、支持状态语义与 Stable 声明已闭环；Apple Silicon macOS 离线 RC 构建、完整性校验、安装/回滚和无模型启动已在本机通过，SHA-245 仍需干净断网设备验收；Developer ID/公证仅适用于可选官方 App/DMG 渠道
- SHA-262 已闭环；SHA-264 的未发布首启草稿、原子发布、CLI/Web 失败恢复、并发与覆盖率门禁已在本机通过，真实 Chrome 恢复/放弃验收因当前配置缺少 ChatGPT Chrome Extension 保持 `not_run`
- 2026-07-20 内部复审已补齐知识操作内容双门禁、危机支持子句作用域与联系方式真实性、即时危险热/冷/中毒/窒息分支及 20 个可执行对抗变体，并收敛首启、Dashboard、Repository、Executions、任务结果与计划证据的错误/无障碍契约；外部专业签核、五人试点、干净断网设备与隔离浏览器证据仍不得由自动化替代
- Stable 仍受飞书 AS-10/11 专业与知识复核、AS-14 五人试点、AS-13 干净断网交付及 AS-12 指定浏览器/VoiceOver 证据阻断；真实硬件、Docker daemon、独立介质与 v2+ 能力保持 Testing/Experimental 或未来版本边界
- 当前开放轨道与实时计数以飞书任务原生状态为准
- 当前基线的精确 commit、测试计数、GitHub Actions 与发布证据维护在飞书正式成果及 AS-09/AS-15，仓库文档不复制易漂移的 run 编号
