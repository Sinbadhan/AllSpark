# AllSpark v1.0.0 — 自动化回归测试 BUG 清单

> **测试日期：** 2026-06-14
> **测试范围：** Web API（~90 端点 × zh/en）+ CLI（30+ 命令 × zh/en）+ 模板静态体验巡检 + 边界路径（重置 L1/L2/L3、紧急状态、语言切换、错误参数）
> **测试方法：** httpx 顺序打 API + subprocess 喂 CLI 命令 + HTML 模板静态扫描，全部脚本与原始日志保留在 `/tmp/allspark-rt/`
> **基线版本：** `1.0.0` (commit 95c83d0)
>
> **总览：** 22 个 bug，🔴 阻塞或数据错误 5 / 🟠 功能不正常 9 / 🟡 体验粗糙 8

---

## 🔴 Critical（阻塞 / 数据错误 / 安全契约违背）

### B-1 [Web/契约] `POST /api/experience` 用 JSON body 调用时 500 崩溃

- **复现：** `curl -X POST /api/experience -d '{"category":"x","content":"y"}'`（错误的字段名）→ 后端 `event=None` 落到 `db.save_experience()` → `sqlite3.IntegrityError: NOT NULL constraint failed: experience_log.event` → 500 直接抛出。
- **期望：** 422/400 + 友好错误，告知字段必填。
- **根因：** `allspark/adapters/routes/core.py:234-247` —— Query 参数为 None 时回退读 body，未校验必填字段就直接落库。
- **修复：** 路由层对 `event/outcome` 做空值校验，返回 `error_response("Missing event/outcome", status=400)`。

### B-2 [服务/i18n] 任务/时间线/简报标题被持久化为某一语言的字符串，切换语言后不更新

- **复现：**
  1. 以中文初始化 → 系统生成"急需：寻找安全水源"等任务 → 数据库保存为彼时翻译字符串
  2. 切换 `lang en` → 该任务仍显示中文
  3. 反之以 en 初始化 → 切到 zh → 任务仍是 "URGENT: Find safe water source / Phase 0"
- **实测产物：** `cli.db.tasks` 行 `('task-urgent-water-224932', 'URGENT: Find safe water source', 0)`、timeline 同一条日记同时存了 "📝 日记：2026-06-14" 和 "📝 Diary: 2026-06-14"。
- **根因：** `allspark/services/mission_planner.py:122-125`、`goal_engine`、`timeline` 等 `t("…")` 调用结果直接 `save_task/save_timeline_event(title=t(…))`，未存 i18n key。
- **影响：** 任意切换语言后，UI 一半中文一半英文。直接违反 CLAUDE.md "硬性规则：所有用户可见文本必须走 t()"。
- **修复方案（任选一）：**
  - **A（推荐）：** 数据模型增加 `title_key` / `title_args` 字段，渲染时再 `t()`。迁移脚本反推已有数据。
  - **B（轻量）：** 显示层每次读出后做 key 反查 / 字面量映射；不彻底但代码改动小。

### B-3 [服务/契约] Reset API 把 "rejected"（被拒）当成成功路径返回，且不带原因

- **复现：**
  1. 调 `POST /api/reset/1 {confirm:true}` 成功
  2. 立刻再调 `POST /api/reset/2 {confirm:true}` → reset_manager 因 24h 冷却拒绝 → 返回 `{status:"rejected", reason:[...]}`
  3. 但路由 `survival.py:229` 返回 `{success: false, message: "rejected"}` —— **rejection reason 数组被丢弃**，前端只看到 message="rejected"
- **期望：** 把 `result["reason"]`（一个 i18n 后的数组）回填给前端，例如 `{success: false, error: "重置冷却中（剩余 23 小时）"}`
- **根因：** `allspark/adapters/routes/survival.py:229` 只取 `result.get("status")` 一个字段。
- **影响：** Web UI `system.html confirmReset` 在 alert 里看到 `RESET_I18N.failed + ': rejected'` —— 用户莫名其妙。

### B-4 [Web/契约] `repository.html addMember` 调用 `/api/governance/member/add` 用 JSON body，但后端是 Query —— 永远静默失败

- **复现：** Web UI Repository 页 → 社区 → 添加成员 → 输入名字+角色 → 点添加 → 看似无事发生 / 不刷新（实际 422，但前端 `await fetch` 不抛错，只看 catch）
- **根因：** `allspark/templates/repository.html:304-309` 用 `{name, role}` JSON body；`allspark/adapters/routes/governance.py:15-23` 用 `name: str = Query(...)`。
- **修复（任选）：**
  - 后端改成接受 JSON body（与其它 web 路由保持一致）
  - 前端改用 query string
  - **推荐：** 全局统一为 JSON body（governance.py 这一族 9 个端点都用 Query，与 system/survival 不一致）。

### B-5 [服务/数据语义] 电力续航估算 9999h 直接展示给用户

- **复现：** 任意状态下查看 status / briefing / power / 资源面板，只要 daily consumption=0 就出现：
  ```
  Power: 50.0Wh (416.6d)        ← briefing
  ⚡ Power: 50Wh | Est. 9999.0h  ← status
  Est. runtime: 9999.0h          ← power 命令
  ```
- **期望：** consumption=0 / unknown 时显示 `--` 或 "持续可用"，不应该把 sentinel 值原样泄漏。
- **影响：** 在 PRD 强调"电力驱动自适应模式"的产品里，这种数字直接误导用户对资源状态的判断。

---

## 🟠 Major（功能不正常 / 一致性破坏）

### B-6 [Web/契约] 全部 `error_response()` 返回 HTTP 200 + `{status:"error"}`，违背 REST 语义

- **复现：**
  - `POST /api/system/personality {mode: "evil"}` → 200 + `{status:"error", error:"Invalid personality mode"}`
  - `POST /api/system/operating-mode {mode:"ultra"}` → 同上
  - `GET /api/goals/__nonexistent__` → 200 + error
  - `POST /api/reset/9 {confirm:true}` → 200 + error_response("Invalid reset level")
  - `POST /api/system/personality {}` → 200 + error_response("Mode required")
- **后果：** 前端如果只判 `r.ok` / `response.status` 会以为成功；很多 UI 已经依赖 `data.status === "ok"` 但有的地方用 `data.success`，逻辑混乱。
- **根因：** `allspark/adapters/routes/helpers.py:7-19` `error_response()` 返回 dict 而非 `JSONResponse(status_code=400, ...)`。
- **修复：** 改为 `return JSONResponse({...}, status_code=status)`，覆盖 ~30 个调用点。

### B-7 [Web] `POST /api/modules/__nonexistent__/enable` 默默成功

- **复现：** 用一个根本不存在的模块名调 enable → 200 + `{status:"ok", module:"__nonexistent__", enabled:true}`
- **根因：** `infrastructure/module_loader.py:108` `enable()` 实现就是 `self._disabled.discard(name)` —— set.discard 对不存在 key 静默成功。
- **对比：** CLI `module enable __nope__` 返回"模块 __nope__ 当前硬件不支持，无法启用"（更好）—— 前端/后端行为不一致。
- **修复：** `enable()/disable()` 检查 `module_name in self._modules`，否则 raise / return False。

### B-8 [Web] `POST /api/system/language {lang: "en"}` 与 `{language: "en"}` 都接受，但其他端点不一致

- **现象：** language 路由用 `body.get("lang") or body.get("language")` 双 key 兼容；其他路由（如 personality 用 `mode`）只接受单一 key。
- **影响：** 文档不存在，前端开发者要靠读源码猜契约。
- **建议：** 任一选定 + 文档化 OpenAPI 描述。

### B-9 [Web/Init] 初始化向导默认显示英文，未根据浏览器/系统语言初选

- **复现：** 浏览器 `Accept-Language: zh-CN`，访问 `/` 但未初始化 → 看到 "Hardware Detection / Detecting hardware... / Next →"
- **根因：** `init.html:311` `const lang = selectedLang || "en";` —— 直接默认 en，未读 `navigator.language` 或 `Accept-Language` 头。
- **影响：** 火种宣传「中英双语原生支持」，但中文用户首屏全是英文，不能形成第一印象。

### B-10 [Web/i18n] `index.html` & `system.html` 多处 JS 内嵌硬编码英文（未走 t()）

| 文件:行 | 文本 |
|---|---|
| index.html:375 | 任务表头 `<th>PHASE</th><th>TASK</th><th>STATUS</th>` |
| index.html:390 | `'No results found'` |
| index.html:408,411 | `'Steps'`, `'Warnings'` 段标题 |
| index.html:454 | `'No experiences yet'` |
| index.html:485-487 | `'No modules loaded'`, `<th>MODULE</th><th>STATUS</th><th>VERSION</th>` |
| index.html:493,496-497 | `"Loading model..."`, `"Model loaded:"`, `"Error: ..."` |
| system.html:335 | 备份表头 `<th>LABEL</th><th>SIZE</th><th>WHEN</th>` |
| system.html:368 | `alert("OK: " + JSON.stringify(data))` |
| init.html:434,439,463,470 | `"Error: ..."`, `"Failed"`, `"Error checking progress"` |
| init.html:358-364 | tier 名 `"Phantom (2GB)" / "Minimum (4GB)" / "Recommended (8GB)" / "Comfortable (16GB)" / "Flagship (32GB+)" / "Unknown"` 全英文硬编码 |
| init.html:374 | `data.gpu_info \|\| "None"` |

- **修复：** 全部改为 `{{ t('xxx') }}` 或 `i18n("xxx")` 模式（按所在文件已有约定）。

### B-11 [体验] Web 多处 `alert(e)` 直接把 JS 异常对象 toString 给用户

- **位置：** executions.html:244,250 / repository.html:311 / system.html:441,504,510,528,556 / index.html:591,635,670
- **后果：** 用户看到 `alert("[object Error]")` 或 `alert("TypeError: Cannot read properties...")`。
- **修复：** 包装一个 `notify(error)` 工具，只展示用户友好文案。

### B-12 [服务] daily_briefing 在英文环境下夹中文知识标题（反之亦然）

- **实测：** `lang en` 模式下 briefing 输出包含 `💡 Daily Knowledge\n   山羊养殖` / `堆肥系统建设` —— 中文知识条目在英文上下文中突兀显示。
- **根因：** 知识库 `knowledge` 表里部分条目只有中文版本，briefing 选取时未按当前语言过滤或 fallback。
- **修复：** `daily_briefing.py` 选条目时加 `language=current_lang OR language="" (universal)` 过滤，没有就取 fallback 并在 UI 上加语言徽章。

### B-13 [服务] Diary 允许同日同情绪同内容重复落库

- **实测：** `cli.db.diary_entries` 行：
  ```
  ('diary-3eaff4b9', '2026-06-14', '今天我测试了系统', 'neutral', ...)
  ('diary-45f09a19', '2026-06-14', '今天我测试了系统', 'neutral', ...)
  ```
- **影响：** 双计入 timeline、CLI `diary` 列表里同一条出现两次。
- **修复：** 落库前查重（同日同 content+emotion 视为重复，提示用户）。

### B-14 [服务] Goal 允许同 title 重复创建

- **实测：** 重复 `POST /api/goals/add {title:"TR test goal"}` 数次，全部成功；`goals` 命令显示两条同名 `🟠 TR test goal (0%)`，briefing 里也是。
- **修复：** 同状态/同源/同 title 视为重复，返回提示或自动转为 stale。

---

## 🟡 Minor（体验粗糙 / 文案 / 一致性）

### B-15 心理状态 / 模式枚举值未本地化直出

- **实测：** `psychology` 命令在 zh / en 都显示 `Overall: lonely`、`Loneliness: 80%` —— "lonely" 是英文枚举，但提示文本是英文化。zh 模式下中文界面出现 "lonely" 字样。
- **修复：** `psych_state` 渲染层映射枚举到 i18n key。

### B-16 资源未输入时仍显示 "🟢"（OK）状态

- **实测：** Status / briefing 中 Water/Food/Fire/Storage 都是 `◇ OFFLINE`，但 ⚡ Power 因为初始化时给了默认 50Wh（且 daily consumption=0），状态显示为 🟢 SUFFICIENT。
- **问题：** 让用户误以为电力健康，实际是因为我们假设了 0 消耗。
- **修复：** consumption=0 时不应判定为 SUFFICIENT；显示 `◇ unknown` 更符合数据语义。

### B-17 Help 帮助文本格式不统一

- **实测：** CLI `help` 命令输出中：
  - 部分行用两空格缩进（"  status"）
  - 部分行用四空格（"    know <keyword>"）
  - 部分有 dash + space ("  status          — Full survival assessment")，部分用一长串空格
  - "lang <zh|en>" 与下方 "module" 缩进不一致
- **修复：** 用 Rich Table 或固定 column 宽度对齐；从 i18n YAML 整理一致的 markdown-like 格式。

### B-18 `gps_set` 接受任意经纬度不校验

- **实测：** `POST /api/gps/set {lat: 999, lng: -9999}` → 200 + `{status:"ok"}`
- **修复：** 校验 lat∈[-90,90], lng∈[-180,180]。

### B-19 Web SKF 路径错误信息未本地化

- **实测：** 调 `/api/skf/export?path=../../etc/passwd` → 400 `"SKF paths must stay under ~/.allspark/skf"` 英文硬编码。
- **修复：** 走 `t("skf_path_traversal_blocked")` 或类似 key。

### B-20 部分模块在 status 表里"🟢 Sufficient + 🟡 Pending"组合让人困惑

- **实测：** `module` 命令显示大量行 `Hardware: 🟢 Sufficient | Status: 🟡 Pending`。"Sufficient + Pending" 两个绿/黄并列没说明白：是硬件够但还没加载？还是被禁用？
- **修复：** 按 PROGRESS.md 的"available / loaded / disabled / unsupported"四态显示，加 legend。

### B-21 任务/目标列表无空行分隔，标题靠左加图标导致视觉拥挤

- **实测：** CLI goals 输出：
  ```
  🟠  TR test goal
     
     Progress: - (0%)
  🟠  TR test goal
     
     Progress: - (0%)
  ```
  连续两条目之间无横线/空白，进度行与标题行间一个空行让单条变成 3 行——既密又散。
- **修复：** 用 Rich Table 或 Panel；或在条目之间加 `─────` 分隔。

### B-22 Network/Vision 服务"未加载"在 web 返回 503，但 UI 没有渐进降级

- **实测：** `/api/network/status` 503 → repository.html network 区域 fetch 失败 → 用户看到空白 / 无文案
- **建议：** 用 `service_unavailable()` 同时返回 200 +`{available:false, reason:..., next_action:...}`，由前端展示「该模块未启用，硬件未达推荐配置 → 升级路径」式的卡片，而不是空白或弹错。

---

## 测试覆盖 & 工件

```
/tmp/allspark-rt/
├── web_smoke2.py        ←  Web API 全量回归脚本（90 端点 × 双语）
├── web2_results.jsonl   ←  170 条原始记录
├── cli_smoke.py         ←  CLI 命令回归脚本
├── cli_stdout.txt       ←  CLI 输出全量
├── cli_stderr.txt       ←  CLI stderr
├── cli_anomalies.json   ←  自动异常摘要
├── boundary.py          ←  边界路径（L1/L2/L3 重置 / 紧急状态 / 语言切换）
├── boundary_results.jsonl
├── render_visual.py     ←  HTML 模板渲染
└── html_samples/        ←  10 个页面 × 2 语言 共 20 个 HTML 静态样本
```

**未覆盖（可下一轮）：**
- LLM 真实调用（缺 llama-cpp-python，本机无 GPU）
- 语音 / 图像识别真实调用（缺模型）
- AllSpark Network 跨节点握手（需要两个进程）
- Docker 弹性部署（本机无 Docker）
- 长时跑（资源衰减、目标超时、调度器触发）

---

## 修复优先级建议

| 优先级 | Bug | 理由 |
|---|---|---|
| **P0** | B-1 | 500 崩溃，任何场景必修 |
| **P0** | B-3 | 用户重置失败但不知原因，影响数据决策 |
| **P0** | B-4 | 社区添加成员根本无法工作 |
| **P0** | B-2 | 违背 i18n 硬性规则；切换语言用户体验严重撕裂 |
| **P1** | B-5, B-6, B-12 | 数据语义 + 契约 + 双语夹杂 |
| **P1** | B-9, B-10, B-11 | 用户首屏 / Web 主流程 i18n |
| **P2** | B-7, B-8, B-13, B-14, B-15, B-16, B-19 | 边角行为 / 表面体验 |
| **P3** | B-17, B-18, B-20, B-21, B-22 | 视觉打磨 / 防御性增强 |

---

> **结论：** v1.0.0 已发布但工程化打磨距离 PRD 描述的"冷峻精确、高信息密度"还有距离，主要集中在两类：
>
> 1. **i18n 持久化 / 切换不彻底**（B-2 / B-10 / B-12 / B-15 / B-19 / B-9） —— 这是结构性问题，单点修不彻底，需要决策 i18n 数据是否进 DB 用 key。
> 2. **Web/CLI 行为不一致 + REST 契约不严**（B-1 / B-3 / B-4 / B-6 / B-7 / B-8） —— S1/S2/S3 三批 web 功能补齐时各路由风格不同，缺乏一遍统一 review。
>
> 建议先 P0 一批小修复发 v1.0.1，再用一个 sprint 做 i18n 与 REST 契约的横扫式 refactor。
