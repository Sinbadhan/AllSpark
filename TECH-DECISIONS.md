# AllSpark 技术决策文档

> **版本：** v1.0.3
> **最后更新：** 2026-06-24
> 本文档从 PRD §14 提取，记录内部技术选型与论证。
> PRD 聚焦"产品做什么"，技术决策单独维护。

---

## 一、参考项目：Project N.O.M.A.D.

**Project N.O.M.A.D.** = Node for Offline Media, Archives, and Data
GitHub: https://github.com/Crosstalk-Solutions/project-nomad

### 1.1 目标对比

| 维度 | NOMAD | 火种 | 重叠度 |
|------|-------|------|--------|
| **核心目标** | 离线知识获取与教育 | 极端环境生存决策 + 文明重建 | 30% |
| **架构** | Docker 容器化 + Web UI | 弹性架构（进程 → Docker 自适应） | 部分 |
| **AI** | Ollama + Qdrant (RAG) | 自适应 LLM + 分级 RAG | 部分 |
| **硬件** | 最低 4GB，推荐 32GB + GPU | 最低 4GB → 旗舰 32GB+，弹性分级 | 部分 |
| **定位关系** | 离线知识超市 | 废墟中的移动餐车 | 互补，非竞争 |

### 1.2 借鉴决策

**✅ 必须借鉴：**
- Kiwix + ZIM（离线百科/医学参考）
- ProtoMaps（离线地图）
- Kolibri（教育课程，舒适配置可选）
- 浏览器访问（多人共享 Web UI）
- 零遥测

**⚠️ 参考但自行实现：**
- RAG 管线（分级实现：4GB sqlite-vss → 16GB+ Qdrant）
- 初始化向导（8 步离线引导）
- 硬件评分（与资源管理联动）

**❌ 不借鉴：**
- 强制 Docker（火种 4GB 不适合容器开销）
- 零认证（火种有权限治理体系）
- 纯知识导向（火种有确定性规则引擎）

### 1.3 为什么火种不强制用 Docker

| 火种目标 | Docker 是否帮助？ | 评估 |
|---------|-----------------|------|
| 不同硬件运行 | ⚠️ 部分 | Docker 守护进程 ~100-200MB，4GB 上吃 5% |
| 模块化/可插拔 | ✅ 是 | 容器天然隔离 |
| 快速启动 | ❌ 否 | Docker 启动慢于直接进程 |
| 最低 4GB 运行 | ❌ 否 | 开销占比过高 |

**决策：弹性架构**
- 4GB → 进程模式（无 Docker 开销）
- 8GB+ → Docker 模式（享受隔离优势）
- 32GB+ → NOMAD 集成模式（完整生态）

### 1.4 与 NOMAD 的互操作性

- **知识包交换**：火种可读取 NOMAD 的 ZIM 文件作为知识源
- **Web UI 共存**：同硬件上可并行运行，通过不同端口访问
- **LLM 共享**：Ollama 实例可被两者共用

---

## 二、技术选型

### 2.1 编程语言

| 语言 | 优势 | 劣势 |
|------|------|------|
| **Python（选择）** | 生态丰富，llama-cpp-python/Whisper/FastAPI 成熟 | 性能/内存不如 Rust |
| Rust | 高性能/内存安全 | 生态不成熟，开发效率低 |
| C++ | 性能最优 | 开发成本高，跨平台复杂 |

### 2.2 LLM 模型选型

| 模型 | 参数 | 量化后体积 | 评估 |
|------|------|-----------|------|
| **Qwen3-1.7B** | 1.7B | ~1 GB | 最低可用，2GB 设备首选（PHANTOM） |
| **Qwen3-4B** | 4B | ~2.5 GB | 最低配置推荐（MINIMUM） |
| **Qwen3-8B** | 8B | ~5 GB | 推荐配置首选，性价比最高（RECOMMENDED） |
| **Qwen3-14B** | 14B | ~9 GB | 舒适配置推荐（COMFORTABLE） |
| **Qwen3-32B** | 32B | ~20 GB | 旗舰配置（FLAGSHIP） |

> v1.0.3 当前默认 LLM 选型为 Qwen3 系列，模型清单外置为 `allspark/data/models.yaml`（单一数据源：recommendations + catalog + override 入口）。上表对应 `models.yaml` 中各硬件 tier 的默认推荐；`deepseek-r1-distill-qwen-14b` 作为推理模式备选保留在 catalog 中。

### 2.3 RAG 技术选型

| 硬件级别 | 向量库 | 嵌入模型 |
|---------|--------|---------|
| 4GB | sqlite-vss | BGE-small |
| 8GB | sqlite-vss / Qdrant | BGE-base |
| 16GB+ | Qdrant | BGE-large + 重排序 |

---

## 三、已决策事项

- [x] Web UI 前端迁移到独立 HTML 模板（`allspark/templates/init.html` + `allspark/templates/index.html`）
- [x] 自动化测试框架选择 pytest（用例数以 `pytest tests/ -q` 实际输出为准）
- [x] 默认部署策略选择弹性架构（PROCESS → DOCKER → INTEGRATION，按硬件能力降级）

## 四、待决策事项

详见 `docs/adr/`：

- [ADR 001 — 火种间通信加密](docs/adr/001-spark-network-encryption.md)（v1.0 暂不实现，v2.0 评估 X25519 + ChaCha20-Poly1305 + TOFU）
- [ADR 002 — Tier 3 知识专家审核流程](docs/adr/002-tier3-knowledge-review.md)（v1.0 维护者人工 review + 强制引用，v2.0 评估双签机制）
- [ADR 003 — 知识包签名验证](docs/adr/003-skf-package-signing.md)（v1.0 仅 SHA256 完整性，v2.0 评估 Ed25519 签名 + 受信发行者列表）
