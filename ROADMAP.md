# ManuSift 能力演进路线图（ROADMAP）

> **用途**：学术纠察 agent 的下一阶段任务规划。排期顺序经用户确认（2026-07-18）：**精度分诊 → 外部核验 → MCP 产品面 → 图表文交叉核对 → 评测扩域与 CI**。  
> **基线口径**：以 `HANDOFF.md` §0/§0.T/§0.S 为准；每项验收都要求双基准 recall 不回退。  
> **变更纪律**：凡动检测器/管线/校准层，必须同步单测 + 双基准回归 + 更新本文件与 HANDOFF。  
> **最后刷新**：2026-07-19 晚（并行检测 + MCP 默认全量 tools）。

---

## 0. 现状基线（2026-07-19 刷新；历史快照见 git）

| 维度 | 当前值 | 出处 |
|------|--------|------|
| fraud_representatives_v1 core recall | 1.000（12/12 有 PDF 案） | `benchmarks/fraud_representatives_v1/GAP_REPORT.md` |
| fraud_web_v1 core recall | 1.000（13/13） | `benchmarks/fraud_web_v1/GAP_REPORT.md` |
| negative_controls_v1 high findings/篇 | **0.00**（0/16；P6 入管线后回归仍 0，2026-07-19） | `benchmarks/negative_controls_v1/FP_REPORT.md` |
| figure_text_v1（合成，P4） | 阳性 5/5、阴性 0 FP | `benchmarks/figure_text_v1/GAP_REPORT.md` |
| expansion_cs_math_v1（P5.1） | mean core recall 0.767（6 案） | `benchmarks/expansion_cs_math_v1/GAP_REPORT.md` |
| expansion_nonenglish_v1（P5.1） | mean core recall 0.533（5 案，es/pt） | `benchmarks/expansion_nonenglish_v1/GAP_REPORT.md` |
| 检测器 | 注册 **52** / 管线 **44** / 书面排除 **8** | `pipeline.py` / `_DETECTOR_SPECS` |
| **检测并发** | 默认 **ThreadPool** `detector_workers=4`；`MANUSIFT_DETECTOR_WORKERS=1` 串行 | `pipeline.py`、`Settings.detector_workers`、`tests/test_parallel_pipeline.py` |
| MCP | 默认 **全量 ~83 tools**；`--curated` 精简白名单（含 P6/SI） | `mcp/server.py`、`MCP_DEFAULT_TOOLS` |
| 测试 | 本地全量可选；**GitHub CI** = 可复现子集 + evals | `.github/workflows/ci.yml` / `ci-fast.yml` |
| LLM enrich / adjudicate | 默认关；报告本体不依赖 API key | `enrichment.py`；见 HANDOFF §0.T |
| Crossref 引文核验 | 管线内，评测默认关；`MANUSIFT_CROSSREF_OFFLINE=1` 可回放 | `CITATION_REPORT.md` |
| CI 门禁 | `ci_benchmark_gate.py` + `benchmark_gate.yml` | ROADMAP P5.2 |
| 实案 smoke（本机） | s41565 主文 + s41586 SI：`--no-llm` 并行 screen 成功；结果建议落 `Desktop\ManuSift_results\` | HANDOFF §0.T |

**核心矛盾**：recall 已到顶，剩余价值在**精度、外部证据维度、产品化**；工程侧已补 **检测并行** 与 **MCP 全量暴露**，后续可做 ProcessPool 可选路径与 UI 进度在高并发下的体验。

---

## 1. 阶段总览

| # | 阶段 | 目标 | 关键验收指标 | 体量 |
|---|------|------|--------------|------|
| P1 | 精度与分诊：Finding 聚合 + LLM 二审 | 把人工复核量再压一个量级 | 对照组 high/篇 6.81 → **≤2.0**；recall 双基准 1.0 不回退 | L |
| P2 | 外部核验：Crossref 引文 + 数据可用性落地 | 新增独立证据维度 | 引文核验进评测基准且不引入误报风暴 | M |
| P3 | MCP 产品面：verdict 工具 + 异步任务 | 外部 agent 一键分诊、大 PDF 不超时 | stdio 契约扩展测试全过 | M |
| P4 | 图-表-文数值交叉核对 | 打通已注册未入管线的链路 | 新基准案（图文不一致）检出，入管线 | M |
| P5 | 评测扩域 + CI 门禁 | 防 recall/FP 回归自动化；补领域盲区 | benchmark 进 CI，recall 下降即红 | M |

**已登记并行项（不重复排期，见 HANDOFF §4/§7）**：5 个付费墙 PDF 补挂（用户侧）、30 案 v2 P6 gate、表格 OCR（P4 长期路径）、跨论文证据比对（RW 库 + 图像指纹语料，后续版本）。

---

## P1. 精度与分诊（Finding 聚合 + LLM 二审）

**现状依据**：对照组 6.81 个 high/篇，且 findings 平铺——同一图被 image_dup / panel_dup / forensics / SIFT 多通道命中时重复计数。`finding_calibration.py` 只做严重度校准、**不丢 finding**；`llm/enrichment.py` 只写 `llm_verdict` 叙述、**不动 severity**。两层之间缺"聚合"与"裁决"。

### P1.1 Finding 聚合器（issues 层）

- 新增 `manusift/report/finding_aggregation.py`：把 findings 按**证据对象**聚成 issue——
  - 图像类：按图像 identity（xref / 页+区域 / pHash 近邻）聚合 image_dup、panel_duplicate、image_forensics、sift_copymove、page_raster_dup 的同图命中；
  - 表格类：按 表号+check 簇 聚合（沿用 calibration 现有 table-pair cluster 逻辑上提）；
  - 文本/元数据类：按 detector 族聚合。
- issue 属性：`issue_id`、`severity = max(members)`、`detectors[]`、`evidence_refs[]`、`member_count`。
- **不丢 finding**：聚合层只加视图，原 findings 列表保留（与 calibration 同纪律）。
- 落点：pipeline 在 calibrate 之后调用；`investigation_pairs.html` 与 formal 报告增加 "Issues" 区块；`list_findings` MCP 工具可加 `group_by=issue` 参数。
- 测试：`tests/test_finding_aggregation.py`（同图多通道 → 1 issue；跨图不并案；severity 取 max；原 findings 数不变）。

### P1.2 LLM 二审裁决层（adjudicator）

- 新增 `manusift/llm/adjudication.py`（复用 `llm/client` 与 `prompt_cache`）：**只对 high issue** 送上下文（finding raw + 相关文本片段/图像说明）让 LLM 判 `actionable | explainable | uncertain`。
- 裁决结果写 `raw.adjudication`，severity 调整规则：`explainable` → high 降 medium（**不删**）；其余不动。
- 门控：`MANUSIFT_LLM_ADJUDICATE=1` 才启用，默认关；与 enrich 独立开关。成本护栏：每篇裁决 issue 上限（默认 20）、复用 cluster 广播逻辑（同 fingerprint 只问一次）。
- **recall 安全论证**：eval 口径是 `expected_core_detectors` 的 count>0，降 severity 不减计数，故双基准 recall 不受影响；但仍需在 GAP_REPORT 增加 "adjudicated-down" 列监控误降。
- 测试：`tests/test_llm_adjudication.py`（mock client：explainable→降级、actionable→不动、上限截断、off 时零调用）。

### P1.3 出版社/模板基线白名单

- 新增 per-publisher 降权表（`manusift/report/publisher_baselines.json` + calibration 钩子）：对已知良性模板信号（页家具簇、出版社固定声明句式）按出版社降 severity。
- 数据来源：`negative_controls_v1/FP_REPORT.md` 残余 high 类逐条归因（texture_overlap、SIFT≥40 inliers、panel 强匹配、ref 年份冲突、生产性重复图）。
- 测试：每加入一条白名单，必须在 negative_controls 上验证 FP 下降且在双基准上 recall 不变。

### P1 验收

- [x] 对照组 high/篇 ≤ 2.0（2026-07-18 三基准全量回归：**0.00/篇**，白名单 12 条规则全归因；adjudicator 默认关，未启用）
- [x] issue 聚合视图进报告，人工复核条目数（issue 数）有统计（investigation_pairs.html + formal 报告均有 Issues 区块；issues.json 落盘）
- [x] 双基准 recall 1.0 不回退；全套件 passed/0 failed（v1 12/12=1.000、web 13/13=1.000）
- [x] `FP_REPORT.md` 增补第三轮治理记录（Round 3 governance 章节）

---

## P2. 外部核验（Crossref 引文 + 数据可用性落地）

**现状依据**：`CitationNetworkDetector` 已在管线末尾（网络唯一依赖），做引文存在性/标题/年份/作者比对，带 `data/crossref_cache.json` 缓存与 `@remote_call` 重试；但评测环境一直 `MANUSIFT_CROSSREF_ENABLED=0`，**从未在基准上量过精度**。数据可用性目前只查声明措辞（`data_availability_concern.py`），不验证声明里的仓库链接是否真实存在。

### P2.1 引文核验进评测

- 在 fraud_web_v1 / negative_controls_v1 上开启 Crossref 重跑，统计：命中率、FP 率、耗时、缓存命中。
- 离线确定性：benchmark 运行以 cache 回放为准（cache miss 记 `not_testable` 而非联网），保证 CI 可复现。
- 误报治理：标题相似度/年份容差阈值按实测调；出版社预印本/版本差异场景分型降级。
- 测试：扩展 `tests/test_citation_network*.py`（cache 回放路径、离线模式不联网）。

### P2.2 引用撤稿轻量检查

- 用 OpenAlex `is_retracted`（免费、建基准时已用）按 DOI 批量查**被引文献**撤稿状态；命中即 high（"引用已撤稿文献"是独立强信号）。
- **边界声明**：不建 Retraction Watch 库、不做本文-撤稿库全文比对——那属于已登记的"跨论文证据比对"待开发项；本任务只做引用级在线查询，与后续 RW 库共享数据接入层。
- 测试：mock OpenAlex 响应；引用列表含撤稿 DOI → high finding。

### P2.3 数据可用性声明落地核验

- 解析声明中的 DOI/URL（Dryad/Zenodo/Figshare/OSF 常见域名），HEAD 请求验证可解析、非 404、仓库页面含数据文件条目。
- 网络失败一律 `info` 级存疑，不升级为 high（链接失效≠造假）。
- 测试：`tests/test_data_availability_resolution.py`（mock HTTP）。

### P2 验收

- [x] Crossref 在双基准 + 对照组完成精度测量并有书面报告（`benchmarks/negative_controls_v1/CITATION_REPORT.md`，2026-07-18；fraud_web 19 条全 high 方向正确，对照组治理后离线回放 high=0）
- [x] 引用撤稿检查上线且有真案或合成案验证（`cited_retraction` 检测器入管线，mock OpenAlex 8 测试全过）
- [x] 离线回放模式下 CI 可跑引文相关测试（`MANUSIFT_CROSSREF_OFFLINE=1` + 542 条缓存语料）
- [x] recall 1.0 不回退；对照组新增 FP 在 P1 白名单机制内消化（实际在检测器阈值层治理：大小写/全署名/年份±1/灰文献分型/score<2 降 medium）

---

## P3. MCP 产品面（verdict 工具 + 异步任务）

**现状依据（P3 + 2026-07-19 MCP 刷新）**：默认 MCP 暴露 **全量 ~83 tools**（含 `screen_verdict` / 异步 job / 全部检测器 tool）；`--curated` 才是精简面。大 PDF 仍可能分钟级（解析 + 重检测器主导；并行有助于重叠等待，不保证 N×）。

### P3.1 `screen_verdict` 一键分诊工具

- 新工具：输入 PDF 路径/trace_id → 跑管线（默认关 LLM）→ 返回 `{verdict: clean|suspect|flagged, score, top_issues[]（P1 聚合层输出）, counts_by_severity, report_path}`。
- verdict 判定规则书面化（high issue ≥1 → flagged；medium 聚簇 → suspect；阈值进 config 可配）。
- 加入 `surface.py` 首位；`docs/mcp/README.md` 增"三分钟接入"段落。

### P3.2 异步任务模型

- 新工具三件套：`submit_screen`（返回 job_id，立即返回）、`get_job_status`（进度/阶段）、`get_job_result`（完成后的 verdict JSON）。
- 复用 `data/jobs/` 已有目录机制；job 状态落盘（queued/running/done/failed + 进度百分比 + 当前阶段名）。
- 管线进度回调：pipeline 按检测器完成数推进度（分母 = `detector_names_for_progress()`，当前 **44**）。
- 保留同步 `screen_verdict` 给小 PDF/调试。

### P3.3 契约与文档

- `scripts/check_mcp_stdio.py` 扩展：submit → poll → result 全链路 + 进度单调性断言。
- `tests/test_mcp_stdio.py` 同步扩展；`docs/mcp/` 各客户端配置样例补异步调用示例。

### P3 验收

- [ ] Claude Code / Codex 实际接入走通 verdict 一键调用（stdio 契约已通，真实外部客户端接入待用户侧实测）
- [x] 异步链路 stdio 契约测试全过；大 PDF 不阻塞 initialize/list（`scripts/check_mcp_stdio.py` 全链过，进度单调）
- [x] 全套件 passed/0 failed

---

## P4. 图-表-文数值交叉核对

**现状依据**：`ChartDataExtractorDetector`、`FigureTextCrossCheckDetector` 已注册但被 `PIPELINE_EXCLUDED` 排除，理由原话是"no benchmark evidence yet"。本阶段补证据、再入管线。

### P4.1 基准证据建设

- 在 fraud_web_v1 增补或新建小集：≥5 个"图内数值与正文/表格报告值不一致"的案子（可从撤稿通知含 "figure does not match" 的 OA 案筛选，复用 `benchmarks/fraud_web_v1/prepare_cases.py` 流程）。
- 无足够真案时：用正常 OA 论文合成扰动（改图内数字）作阳性、原图作阴性。

### P4.2 链路打通与入管线

- `chart_data_extract`：柱状/散点/森林图数值提取的精度实测与阈值定档（ EasyOCR 路径已有，注意 Windows 预导入纪律——新增重依赖必须进 MCP 启动预导入链）。
- `FigureTextCrossCheckDetector`：图值 ↔ 正文/表格值比对（容差、单位归一、p 值/均值/百分比分型）。
- 从 `PIPELINE_EXCLUDED` 移除并加入管线列表 + 更新 `test_pipeline_detector_coverage.py` 计数。

### P4 验收

- [x] 新基准案检出率有报告；对照组无新增 FP 风暴（`benchmarks/figure_text_v1/` 合成 8 案：阳性 5/5、阴性 0 FP；对照组 3 案抽查 0 新增 high）
- [x] 排除清单书面化同步更新；双基准 recall 1.0（两检测器入管线，fraud_web 2 案抽查 core recall 1.0；chart_data_extract 两个失效 bug 一并修复）

---

## P5. 评测扩域 + CI 门禁

### P5.1 基准扩域

- CS/数学（TeX 源 PDF，版式与字体差异大——paper_mill_template、tortured_phrases 需验证适用性）；
- 非英文论文（至少中文/德文各数篇，文本类检测器的语言假设需审计）；
- 对抗样本：撤稿论文的"洗白版"（修掉表面信号后）测漏报。
- 每域先 5-8 案小步快跑，流程复用 fraud_web_v1（OpenAlex 检索 + 官方撤稿通知核对 gold）。

### P5.2 CI 回归门禁

- 新增 CI job（`.github/workflows/`）：跑三个 benchmark 的 recall/FP 聚合脚本（复用 `run_smoke.py` + `build_gap_report.py` + FP 统计），门禁规则——
  - core recall 任何基准 < 1.0 → 红；
  - 对照组 high/篇 超阈值（当前 6.81，P1 完成后改 2.0）→ 红；
  - 引文类走 cache 回放（P2.1），不联网。
- 慢速项（OCR、LLM）保持 CI 关，与 smoke 环境变量一致。

### P5 验收

- [x] 新域基准有 GAP_REPORT（`benchmarks/expansion_cs_math_v1/` 6 案 recall 0.767、`benchmarks/expansion_nonenglish_v1/` 5 案 recall 0.533，gold 逐案核对撤稿通知；中/德文无可下 OA 源未建案、对抗样本仅落方案——均书面化于两集 README）
- [x] CI 门禁 PR 上实际拦过一次回归（或故障注入验证）（`scripts/ci_benchmark_gate.py` 故障注入实测：recall 0.5 注入 → exit 1；`tests/test_ci_benchmark_gate.py` 14 例固化；workflow 两层：PR 跑规则测试 / 全量基准仅手动 workflow_dispatch 触发，基准数据经 Release 资产恢复）
- [x] HANDOFF 指标表更新（§0.R 段落 + ROADMAP §0 基线表已更新为收工快照）
---

---

## P6. PubPeer 100 手法对齐（覆盖补齐）

**依据文档**：

- `docs/pubpeer_100_fraud_methods.md` — 100 条手法 + 检测措施  
- `docs/pubpeer_100_coverage_matrix.md` — 与 ManuSift 逐条对照（full ~38% / partial ~34% / gap ~28%）  
- `docs/pubpeer_integrity_patterns.md` — 短映射与发现技巧  

**现状快照（2026-07-19）**：

| 簇 | 覆盖 | 代表能力 |
|----|------|----------|
| Source Data / Excel 造数 | **强** | fixed/partial offset、fixed_ratio、decimal tails、sequence_reuse、identical_parallel_replicates、excel_fabrication_span、Benford/round_bias |
| 图像 Cat I 复用 | **强** | image_dup / panel / page_raster / hashes |
| 图像 Cat II/III | **中** | SIFT/forensics/noise；缺 flip 显式通道、gel 泳道专用 |
| 统计 GRIM 族 | **中强** | GRIM/GRIMMER 路径、t/p 表一致性；无 p-curve/SPRITE |
| 文本/工厂 | **中** | tortured phrases、paper_mill_*、cited_retraction |
| 跨论文 / 外部库 | **弱** | 无亿级图库；无重复发表检索 |
| 流式 / 伦理注册 | **弱/无** | gap |

### P6.0 已交付（本轮，可勾选）

- [x] 100 条清单 + 覆盖矩阵文档落地  
- [x] Excel 提权：clean non-zero offset high、partial_fixed_offset、完美小数尾 high、空表头免疫  
- [x] `sequence_reuse`（块粘贴）、`identical_parallel_replicates`（零生物变异）  
- [x] `fixed_ratio`（A≈k·B 常数比例）  
- [x] `excel_fabrication_span` + `pubpeer_pattern` 标签  
- [x] 校准层与单测同步（`test_table_relationships` / `test_finding_calibration`）  
- [x] 实案 s41586 Source Data / s41565 路径上冒烟验证过 Excel 主指纹  

### P6.1 图像几何与凝胶（P1 级缺口）

| 任务 | 对应 # | 验收 | 状态 |
|------|--------|------|------|
| `image_dup` 显式 flip/rotate 二次匹配通道（0/90/180/270 + H/V flip） | 11–12, 10 | 合成翻转/旋转复用案 core 命中 | **done 2026-07-19**（pass geometric；`tests/test_image_dup_geometric.py`） |
| Gel 垂直接缝启发式（列向梯度断裂 + 背景噪声跳变） | 23–24 | 合成拼接 blot 阳性；平滑梯度阴性 | **done 2026-07-19**（`_vertical_gel_seam_check`；`tests/test_gel_vertical_seam.py`） |
| Loading-control ROI 启发式（底部条带区优先比对） | 5–6 | 可选门控；有/无 loading 案分型 | **done 2026-07-19**（pass `loading_control`；`tests/test_loading_control_roi.py`；`MANUSIFT_LOADING_CONTROL_ROI`） |

### P6.2 统计纵深

| 任务 | 对应 # | 验收 | 状态 |
|------|--------|------|------|
| p 值堆积（0.04–0.05）聚合信号 | 67 | 合成 p-hack 文 medium+；稀疏 p 阴性 | **done 2026-07-19** `stat_pvalue_pileup`（默认开） |
| SPRITE-lite 摘要可行性（默认关） | 73 | 门控默认关；不可能 SD → high | **done 2026-07-19** `stat_sprite` / `MANUSIFT_SPRITE_ENABLED` |
| 相关矩阵半正定检查 | 79 | 非 PSD → high/medium | **done 2026-07-19** `stat_corr_psd`（默认开） |

实现：`manusift/detectors/stat_extra.py`；入注册表 + 管线；测试 `tests/test_stat_extra_p62.py`。

### P6.3 跨论文与产品化

| 任务 | 对应 # | 验收 | 状态 |
|------|--------|------|------|
| 跨论文图像指纹语料（本地 pHash JSONL 索引） | 4, 90 | 小库召回可测；不依赖商业 API | **done 2026-07-19** `fingerprint_index` + `cross_paper_image` |
| SI PDF 与主文同 job 合并抽图 | 7 | materials 中 SI PDF 图并入 `doc.images` | **done 2026-07-19** `companion_pdf.merge_*` + screen 复制 SI PDF |
| 报告按 `pubpeer_pattern` 分组 | 报告 UX | investigation_pairs HTML/MD/JSON 新区块 | **done 2026-07-19** |

实现要点：

- 索引：`data/cache/image_fingerprints.jsonl`（或 `MANUSIFT_FINGERPRINT_INDEX`）  
- 管线结束后默认 `MANUSIFT_FINGERPRINT_AUTO_INDEX=1` 写入本篇指纹  
- 检测器 `cross_paper_image`（默认开，`MANUSIFT_CROSS_PAPER_IMAGE=0` 关）  
- screen 复制 `*Supplementary*` / `*MOESM*` 等 PDF 进 materials  
- 测试：`tests/test_p63_cross_paper.py`

### P6.4 明确不做（本版本）

- 商业级全库盗图（Imagetwin 1.6 亿）  
- 伦理批号/试剂型号权威库联查  
- 审稿人操纵网络（无编辑部数据）  
- 多语翻译洗稿全量  

### P6 验收（阶段级）

- [ ] 覆盖矩阵 **full ≥ 45%** 或 partial+full ≥ 80%（现 ~72%）  
- [x] P6.1 至少 2 项入管线 + 单测 + 对照组抽查（flip/rotate + gel seam + loading-control 均已入）
- [ ] 双基准 recall 不回退（fraud_web / representatives 待复跑）  
- [x] 对照组 high/篇 不恶化（P6 后 negative_controls high=0.00）  
- [x] HANDOFF 同步本阶段指标与未决项  

**推荐执行顺序**：P6.1 flip/rotate → P6.1 gel seam → P6.2 p-堆积 → P6.3 报告分组 → 其余。

---

## 2. 依赖关系与风险

```text
P1.1 聚合 ──► P1.2 裁决（吃 issue 输入）──► P3.1 verdict（top_issues 来自聚合层）
P2.1 cache 回放 ──► P5.2 CI（离线确定性前提）
P4.1 证据 ──► P4.2 入管线
P6.0 Excel 已交付 ──► P6.1 图像 ──► P6.2 统计 ──► P6.3 跨论文
```

| 风险 | 缓解 |
|------|------|
| LLM 裁决误降真问题 | 只降 severity 不删 finding；GAP_REPORT 增 adjudicated-down 列；阈值保守（仅 explainable 才降） |
| 网络依赖引入评测不确定性 | cache 回放 + 离线 not_testable 口径；CI 不联网 |
| 聚合误并案导致证据稀释 | 并案只加视图不删原始 findings；单测覆盖跨图不并案 |
| 白名单过拟合对照组 | 每条白名单必须双基准验证 recall 不变；白名单条目书面归因 |
| 新重依赖（OCR/图表解析）破坏 MCP | 进启动预导入链 + `tests/test_mcp_stdio.py` 回归 |
| P6 提权 Excel 抬高 high 数 | cluster Top-K + max_high；对照组回归必跑 |

## 3. 每阶段收尾清单（统一）

1. 单测新增/更新，全套件 0 failed  
2. 双基准 + 对照组重跑，更新 GAP_REPORT / FP_REPORT  
3. 本 ROADMAP 勾选验收项；HANDOFF.md 新增对应段落  
4. 环境变量/配置新增项写入 HANDOFF §2 常用环境变量表  
5. 若触及 100 条覆盖：更新 `docs/pubpeer_100_coverage_matrix.md`

---

*本文档为排期规划，执行细节以各阶段开工时的代码现状为准。*
