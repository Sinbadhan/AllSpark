# AllSpark 回归测试脚手架

> **位置：** `tests/regression/`
> **创建于：** 2026-06-14（v1.0.0 公开发布后第一轮全量回归）
> **首轮报告：** [`/BUGS_REGRESSION_2026-06-14.md`](../../BUGS_REGRESSION_2026-06-14.md)

这套脚手架是**面向人的探索性回归**，不是 CI 阻断器。它跑完后产出 JSONL + Markdown 给人 triage，而不是返回 0/1 的 pass/fail。一旦某个 bug 修完，把对应的具体检查从这里**毕业**到 `tests/test_*.py` 的真实 pytest 用例 —— 这是分层的：

- **pytest（CI 复现完整 tracked tests，SHA-28；以 `pytest tests/ -q` 实际输出为准）** = 单元/集成回归，每次提交都跑、必须绿
- **regression suites（本目录）** = e2e/UX 回归，发版前手动跑、给人看

## 何时跑

- 发版前（`v1.x` ready 之前）
- 大改 web/CLI/i18n/服务契约之后
- 修复了前一轮 BUG 报告里的项之后（确认没回归）
- PRD 加新模块时（先扩这里，再扩 pytest）

不要把它接到 CI——它需要起 uvicorn server / spawn subprocess，环境敏感且耗时，CI 能验的应已下沉到 pytest。

## 怎么跑

```bash
# 一键全部
python -m tests.regression.run_all

# 单独跑一个 suite
python -m tests.regression.suite_web_api
python -m tests.regression.suite_cli
python -m tests.regression.suite_boundary
python -m tests.regression.suite_html_render
```

报告全部落到 `tests/regression/reports/`（gitignored）：
- `INDEX.md` — 总览
- `<suite>.md` — 人读的汇总，按 flag 分组
- `<suite>.jsonl` — 原始记录，每行一条 probe，便于 grep/diff
- `cli_stdout.txt` / `cli_stderr.txt` — CLI 会话原始输出
- `html/{zh,en}/<page>.html` — 模板渲染快照

**跑前提：**
- `pip install -e ".[dev]"` 起码到位（httpx/uvicorn/fastapi 已是运行依赖）
- 不需要 LLM 模型 / 不需要硬件 / 不需要 Docker

## 覆盖矩阵（按 PRD §三 模块）

每个 ✅ 表示**至少一个 probe 触达**；不代表深度覆盖。看 suite 文件顶部 docstring 找具体路径。

| PRD 模块 | suite_web_api | suite_cli | suite_boundary | suite_html_render | 备注 |
|---|---|---|---|---|---|
| M1 生存评估 | ✅ `/api/status` | ✅ `status` | ✅ 紧急状态 | ✅ index | |
| M2 任务规划 | ✅ `/api/tasks*` | ✅ `tasks` | ⚪ | ⚪ | task 状态机不深 |
| M3 知识引擎 | ✅ `/api/knowledge/*` | ✅ `know`, `map`, `exp` | ⚪ | ⚪ | FTS5 走通；vector 未触 |
| M4 人格系统 | ✅ `/api/system/personality` | ⚪ | ⚪ | ⚪ | 仅 happy + invalid 值 |
| M5 权限治理 | Experimental：`/api/governance/*` 服务端 fail closed | `community` 明确不可用；`trade` 为 Experimental | ⚪ | repository 不宣称 RBAC 可用 | 无可验证成员身份前保持禁用 |
| M6 火种通信 | ✅ `/api/network/*` | ✅ `network` | ⚪ | ⚪ | **未跨进程握手** |
| M7 资源自管理 | ✅ `/api/resources` | ✅ `resource`, `set` | ✅ 资源衰减 | ✅ index | |
| M8 多语言 | ✅ `/api/system/language` | ✅ `lang` | ✅ 中途切换 | ✅ 双语渲染 | |
| M9 Web 层 | ✅ 5 个 HTML | ⚪ | ⚪ | ✅ 5 页 × 双语 | |
| M10 目标系统 | ✅ `/api/goals/*` | ✅ `goals` | ⚪ | ✅ executions | milestone 仅 GET |
| M11 重置 | ✅ `/api/reset/{level}` | ⚪ | ✅ L1+L2+L3 全周期 | ⚪ | force flag 已覆盖 |
| M12 简报 | ✅ `/api/briefing*` | ✅ `briefing` | ⚪ | ✅ index | |
| M13 时间线 | ✅ `/api/timeline*` | ✅ `timeline` | ⚪ | ✅ executions | |
| M14 天气 | ✅ `/api/weather*` | ✅ `weather` | ⚪ | ✅ system | |
| M15 心理 | ✅ `/api/psych*` | ✅ `psychology` | ⚪ | ✅ index | 自评仅 GET 题 |
| M16 日记 | ✅ `/api/diary*` | ✅ `diary` | ✅ 重复落库 | ✅ index | |
| 附 GPS / 环境 | ✅ `/api/gps*`, `/environment` | ✅ `gps`, `env` | ✅ 越界 | ✅ system | |
| 附 SKF / 验证 | ✅ `/api/skf/*`, `/verify/*` | ✅ `skf`, `verify` | ✅ 路径遍历 | ⚪ | |
| 附 视觉 | ✅ `/api/vision/status` | ✅ `vision` | ⚪ | ⚪ | **未真实推理** |
| 附 硬件 | ✅ `/api/power/*`, `/sensor/*` | ✅ `power`, `sensor` | ⚪ | ✅ system | **未接 GPIO 实机** |
| 附 数据固化 | ✅ `/api/preserve/*` | ✅ `preserve` | ⚪ | ✅ system | restore 流程未跑通 |
| 附 模块开关 | ✅ `/api/modules*` | ✅ `module` | ✅ 不存在模块 | ✅ system | |
| 附 LLM | ✅ `/api/llm/status` | ✅ `llm` | ⚪ | ⚪ | **未真实推理** |
| 附 Docker | ⚪ | ✅ `docker` | ⚪ | ⚪ | 本机无 docker 时已优雅降级 |

**⚪** = 该 suite 不负责覆盖这个交叉点（不是缺测，是分工）。

## 显式未覆盖（下一轮 / 专项 harness）

这些场景**已知未覆盖**，因为需要的环境本机没有，或者需要单独 harness。新增覆盖前先写好假设和门槛：

| 场景 | 缺什么 | 何时该补 | 建议位置 |
|---|---|---|---|
| LLM 真实推理 | `llama-cpp-python` + 已下载 GGUF | 任何 LLM 路径相关改动 | 新增 `suite_llm_live.py`，`pytest.skip` 默认跳过 |
| 语音 STT/TTS | `whisper.cpp` + 麦克风/扬声器 | 语音模块改动 | 新增 `suite_voice_live.py` |
| 多模态视觉 | 视觉 LLM + 真实图片 | 视觉模块改动 | 新增 `suite_vision_live.py` |
| AllSpark Network 跨进程握手 | 两个进程 + UDP 监听权限 | 网络协议改动 | 新增 `suite_network_p2p.py`（subprocess 双进程） |
| Docker 弹性部署 | Docker daemon | DockerManager 改动 | 已存在 `tests/test_docker.py`，扩展即可 |
| 长时调度器触发 | 等待 4h/12h | scheduler 改动 | 用 `freezegun` 或 monkeypatch time，写 pytest 用例 |
| 资源衰减真实推进 | 时间推进 | 预警协议改动 | 同上 |
| 重置快照 7 天保留 | 时间推进 | 重置/数据固化改动 | 同上 |
| 多人 commander/expert 冲突 | 多浏览器会话 | 治理改动 | playwright + 多 client，新 harness |
| 浏览器视觉/响应式 | headless browser | 模板视觉改动 | playwright，新增 `suite_browser.py` |

**约定：** 每个新 `suite_*.py` 顶部 docstring 必须列出"NOT covered here" — 让下一个人接手时不掉同样的坑。

## 已知漏测点（heuristic 局限）

`_harness.py` 里的检测都是启发式的，下面是已知**会漏报**或**会误报**的：

- **i18n 泄漏检测**（`detect_i18n_leaks`）只匹配 `xxx.yyy.zzz` 形态的 dotted key。如果代码里把 i18n 写成 `web_xxx_yyy`（下划线连接），它会逃过检测。要扩列表 → 改 `_LEAK_RE`。
- **CLI 跨语言检测**（`_EN_WORDS_IN_ZH_BAD`）只列了一批已知坏词。新模块的英文文案漏到 zh 上下文需要手动加规则。
- **HTML 静态扫描**只看 `<body>` 里的可见文本，扫不到运行时 JS 拼接的字符串（很多 alert / innerHTML 拼接的都不在快照里）。要彻底覆盖请加 playwright。
- **错误响应是 200 + status:"error" 还是 4xx** 是契约设计选择，不直接 flag —— 看 [BUGS_REGRESSION_2026-06-14.md B-6](../../BUGS_REGRESSION_2026-06-14.md)。要硬性禁止某种契约就给 `expect_ok=False` 加上 `flag=ok_unexpected` 然后约束。

## 扩展指南

### 加一个 probe

```python
from tests.regression._harness import http_probe

# 在 suite_web_api.py _run_lang() 里加一行：
H("GET", "/api/your/new/endpoint")
# expect_ok=False 标识这是"应该被拒绝"的边界探针
H("POST", "/api/your/new/endpoint", json={"bad": "shape"}, expect_ok=False)
```

### 加一个新 PRD 模块

1. 在 `suite_web_api.py` 顶部 docstring 的 coverage map 加一行
2. 在 `_run_lang()` 添加 probes，按 PRD 模块号注释
3. 同步扩 README 的覆盖矩阵
4. 如果是高交互模块（语音/视觉），新增独立 `suite_<name>_live.py` 而不是塞进现有 suite

### 把发现的 bug 升级为 pytest

发现的 bug 修了之后：

```python
# tests/test_<area>.py
def test_experience_post_rejects_bad_shape(client):
    """Regression for B-1: bad-shaped /api/experience must 4xx, not 5xx."""
    r = client.post("/api/experience", json={"category": "x"})
    assert r.status_code in (400, 422)
    assert "event" in r.json().get("detail", "").lower()
```

把 regression suite 里对应的那条 probe 也保留——它仍然是 e2e 烟雾测试的一部分，只是现在 pytest 也守着。

## 文件布局

```
tests/regression/
├── README.md                  ← 本文件
├── __init__.py                ← 入口注释
├── _harness.py                ← 共享脚手架（server boot / Recorder / detect_i18n_leaks / cli_drive ...）
├── suite_web_api.py           ← Web API 全量
├── suite_cli.py               ← CLI 命令全量
├── suite_boundary.py          ← 边界路径
├── suite_html_render.py       ← HTML 渲染
├── run_all.py                 ← 一键跑全部 + INDEX.md
└── reports/                   ← gitignored: 每次跑产出
    ├── INDEX.md
    ├── web_api.md / .jsonl
    ├── cli.md / .jsonl / cli_stdout.txt / cli_stderr.txt
    ├── boundary.md / .jsonl
    ├── html_render.md / .jsonl
    └── html/{zh,en}/*.html
```
