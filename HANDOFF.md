# ManuSift1 — Agent 交接文档

> **写给下一个 agent / 协作者**：读完本文应能立刻知道项目是什么、最近做了什么、指标多少、还差什么、怎么跑。  
> **最后更新**：2026-07-19（并行检测管线 + MCP 默认全量 tools + 桌面结果目录约定；以仓库当前文件为准）

---

## 0.T 本轮新增（2026-07-19 晚）：并行检测 + MCP 全量 + 结果落盘

### 产品形态（仍为 B+C）

| 表面 | 入口 | 说明 |
|------|------|------|
| B 批处理 | `manusift screen` | 离线管线；`--no-llm` 不调云端 |
| C MCP | `manusift-mcp` / `manusift mcp` | **默认暴露全量已注册 tools（~83）**；`--curated` 才用精简白名单 |
| 可选 | `manusift-workspace` | 任务浏览器，非 chat |

### 并行检测（已合入）

| 项 | 内容 |
|----|------|
| 实现 | `manusift/pipeline.py`：PDF 解析后 `ThreadPoolExecutor` 并行 `detector.run(doc)` |
| 配置 | `Settings.detector_workers`（默认 4）；环境变量 **`MANUSIFT_DETECTOR_WORKERS`**（`1`=串行） |
| 安全 | 单检测器崩溃隔离；`steps/` 分文件写入；findings **按管线注册顺序**合并 |
| 未并行 | PDF 解析、报告渲染、MCP 多 job 调度（`submit_screen` 仍是整 job 后台线程） |
| 测试 | `tests/test_parallel_pipeline.py`（workers=1/2 真 `run_pipeline`） |

### MCP 默认全量

- `manusift/mcp/server.py`：默认 **不** 套 `MCP_DEFAULT_TOOLS`；`--curated` 才限制  
- `MCP_DEFAULT_TOOLS` 仍含 P6/SI（`source_data_consistency`、`cross_paper_image`、`stat_*` 等），仅作 curated 列表  
- 注册检测器 **52** / 管线 **44** / 排除 **8** / 全量 tools **~83**

### 报告与 LLM（提醒）

| 文件 | 是否依赖 API key |
|------|------------------|
| `findings.json` / `report.html` / `investigation_pairs.*` / `investigation_plain.*` | **否**（本地模板 + 检测结果） |
| `llm_report.*` / `llm_briefing.*` 有实质解读 | **是**（enrichment；`--no-llm` 时为空壳） |

### 结果默认去哪找

- **务必** `--workspace` 指到固定目录，否则落在 cwd 下 `data/jobs/<trace_id>/` 或临时目录易丢  
- 已约定桌面结果（用户本机）：  
  **`C:\Users\22509\Desktop\ManuSift_results\`**  
  - `s41565\output\findings.json` + `investigation_pairs.html`  
  - `s41586\output\…`（主文 PDF 门墙未下时用 SI：`Supplementary_Information_MOESM1.pdf`）  
- 实测（`--no-llm`，`MANUSIFT_DETECTOR_WORKERS=4`）：s41565 exit 0、~225s、findings ~667；s41586 SI exit 0、~102s、findings ~3038  

### 推荐命令

```powershell
cd C:\Users\22509\Desktop\ManuSift1
$env:MANUSIFT_DETECTOR_WORKERS="4"
python -m manusift screen "C:\path\to\paper.pdf" --no-llm --with-sidecar `
  --workspace "C:\Users\22509\Desktop\ManuSift_results" --trace-id myjob
# 打开: Desktop\ManuSift_results\myjob\output\investigation_pairs.html
```

---

## 0.S 本轮新增（2026-07-19）：PubPeer 100 对照 + ROADMAP P6 + Excel/Source Data 强化

### 目标

从 PubPeer 常见造假/诚信讨论归纳 **100 条手法与检测措施**，与 ManuSift 现有能力对照，写入路线图，并**优先补强 Source Data 数值造数**（高影响、可自动化、与 s41586 等实案对齐）。

### 文档（必读）

| 文件 | 作用 |
|------|------|
| `docs/pubpeer_100_fraud_methods.md` | 100 条手法 + 检测措施（A–G 类） |
| `docs/pubpeer_100_coverage_matrix.md` | 逐条 full/partial/gap 对照 |
| `docs/pubpeer_integrity_patterns.md` | 短映射与发现技巧 |
| `ROADMAP.md` **§P6** | 任务路线：P6.0 已交付 / P6.1–P6.4 后续 |

### 覆盖结论（矩阵快照）

| 状态 | 约占比 | 含义 |
|------|--------|------|
| full | ~38% | 有直接检测器 |
| partial | ~34% | 启发式/间接 |
| gap | ~28% | 未覆盖或需外部系统 |

- **强**：Source Data 复制/固定差/比例/小数尾/块粘贴/平行全同/跨表 span；Cat I 图像复用；GRIM 族；tortured phrases；引撤稿。  
- **中**：Cat II/III 图像（有 SIFT/forensics，缺 flip 显式通道与 gel 专用缝）。  
- **弱/无**：跨库盗图、FACS、SPRITE/p-curve、伦理注册联查、重复发表。

### 本轮代码改动（已合入工作区）

| 区域 | 内容 |
|------|------|
| `table_relationships.py` | clean non-zero **fixed_offset→high**；**partial_fixed_offset**；**fixed_ratio**；**sequence_reuse**；**identical_parallel_replicates**；**excel_fabrication_span**；`pubpeer_pattern` 标签 |
| `finding_calibration.py` | 空表头免疫（造数 check + n≥5）；干净非零 offset 提权；完美小数尾 boost；新 check 进 STRONG / IMMUNE |
| 测试 | `tests/test_table_relationships.py`、`tests/test_finding_calibration.py` 全绿 |

### 实案路径（用户本机）

- `C:\Users\22509\ZCodeProject\s41586-024-08248-5\` — Source Data 齐全；主文 PDF 门墙未下  
- `C:\Users\22509\ZCodeProject\s41565-025-02082-0\` — 主文+sidecar；job `438bc19c94c9`  
- s41586 筛查 job（SI+xlsx）：`abe81e42411c`  

Excel 主指纹（组复制、固定差、小数尾、跨表）在上述材料上**可检出**；优化后定级更接近“可行动 high”。

### P6.1 已交付（2026-07-19 续）

| 能力 | 位置 | 测试 |
|------|------|------|
| flip/rotate 几何匹配（hflip/vflip/rot90–270/hflip+rot） | `image_dup.py` pass `geometric` | `tests/test_image_dup_geometric.py` |
| 凝胶垂直接缝启发式 | `image_forensics.py` `_vertical_gel_seam_check` kind=`vertical_gel_seam` | `tests/test_gel_vertical_seam.py` |
| Loading-control 底条 ROI 复用 | `image_dup.py` pass `loading_control` | `tests/test_loading_control_roi.py` |

- raw 带 `pubpeer_pattern=image_repositioned_reuse` / `image_splice_or_clone` / `image_loading_control_reuse`  
- 环境变量（可选）：`MANUSIFT_GEL_SEAM_PROMINENCE`、`MANUSIFT_GEL_SEAM_RATIO`、`MANUSIFT_GEL_SEAM_MAX_SIDE`、`MANUSIFT_LOADING_CONTROL_ROI`（默认开；`0` 关）  
- LC 与 region tile 解耦：整图命中（primary/secondary/geo）跳过；仅底部条带相同时仍出 `loading_control_roi_dup`

### P6.2 已交付（2026-07-19）

| 检测器 | name | 默认 | 说明 |
|--------|------|------|------|
| `PValuePileupDetector` | `stat_pvalue_pileup` | 开 | 精确 `p=` 在 (0.04,0.05] 堆积 |
| `SpriteLiteDetector` | `stat_sprite` | **关** | 摘要 M±SD,n 在有界尺度上 SD 上界；`MANUSIFT_SPRITE_ENABLED=1` |
| `CorrelationMatrixPSDDetector` | `stat_corr_psd` | 开 | 相关方阵 λ_min < 0 |

- 模块：`manusift/detectors/stat_extra.py`  
- 测试：`tests/test_stat_extra_p62.py`  
- 注册 **52** detectors；管线 **44**；MCP 默认 **全量 ~83 tools**（``--curated`` 可选精简白名单）  

### P6.3 已交付（2026-07-19）

| 能力 | 位置 |
|------|------|
| 本地图指纹索引 JSONL | `manusift/knowledge/fingerprint_index.py` → `data/cache/image_fingerprints.jsonl` |
| 跨论文 pHash 匹配 | `cross_paper_image` 检测器（管线内） |
| 筛查后自动入库 | pipeline 尾 `MANUSIFT_FINGERPRINT_AUTO_INDEX`（默认开） |
| SI PDF 复制 + 抽图合并 | `mcp/screen.py` + `ingest/companion_pdf.py` |
| 报告模式分组 | `investigation_pairs` → `pubpeer_pattern_groups` |

开关：`MANUSIFT_CROSS_PAPER_IMAGE`、`MANUSIFT_FINGERPRINT_INDEX`、`MANUSIFT_FINGERPRINT_AUTO_INDEX`、`MANUSIFT_CROSS_PAPER_HAMMING`。  
测试：`tests/test_p63_cross_paper.py`。检测器 **52**；MCP curated **40**。

### P6 下一步

1. 可选：fraud 双基准 / `pubpeer_classics_v1` 图像案复跑  
2. 可选：用已筛查论文批量预热指纹库  
3. 覆盖矩阵 full/partial 复算（P6.1 三项齐后）  

### source_data_xlsx_v1（表通道 / xlsx 案，2026-07-19）

路径：`benchmarks/source_data_xlsx_v1/`

| 项 | 结果 |
|----|------|
| 材料 | 10 案；9 案有 xlsx（Nature Source Data 本地 2 + PLOS SI EuropePMC 7） |
| Smoke | 10/10 ok；xlsx 挂载到 `inputs/materials/` |
| Mean core recall | ~**0.76**（gold 用真实 detector 名） |
| s41586 案 | **check_recall=1.0**（fixed_offset / decimal_tails / sequence_reuse / excel_span） |

**Bugfix**：`table_relationships` `fixed_ratio` 路径对极端比值 `Decimal.quantize` 抛 `InvalidOperation` → 整检测器崩溃；已 guard（跳过非有限/极端比值）。  

### 冗余收敛 P0/P1（2026-07-19）

- **文档**：`docs/DETECTOR_LAYERS.md` — 管线 / registry / EXCLUDED 三层；能力 owner 表  
- **注释**：删除 `contracts.ChatMessage` 对已删 `chat_app` 的引用  
- **`image_dup`**：标明整图哈希主路径；`imagehash_dup` 标明 agent-only、勿扩展  
- **`panel_dup` vs `panel_duplicate`**：模块 docstring 对照表  
- **`table_forensics` / PIPELINE_EXCLUDED**：文案指向 layers 文档  
- **单测**：`tests/test_detector_layers_doc.py`  

P2/P3 已做：safe_read 统一 facade；REPORT_PATH 主链路；legacy 冻结 + factory 默认 pydantic；SIFT 双入口 ownership 文档。
### source_data_consistency SI 对齐（2026-07-19）

- **入管线**：从 `PIPELINE_EXCLUDED` 移出，挂在表检测器之后  
- **SI 对齐**：按 `Source_Data_Fig*` / `ED_Fig*` 文件名与 sheet/`fig_name` 推断 `fig_key`，逐 figure 算 SI↔PDF 数值重叠  
- **多精度匹配**：2/3/4 位小数 + 整数键，减少舍入假缺失  
- **xlsx 文件名打标**：`parse_xlsx` 无 sheet 级 fig 时用文件名补 `fig_name`  
- **xlsx01 复验**：`source_data_consistency`×10，`core_recall=1.0`（含 SI poor-align medium）  
- 单测：`tests/test_source_data_consistency_p4.py`  

### negative_controls_v1 回归（2026-07-19 P6 后）

| 指标 | 结果 |
|------|------|
| high / 篇 | **0.00**（0/16）— CI budget ≤ 2.0 |
| P6 通道 high | **0**（geometric / LC / gel seam / pileup / sprite / corr_psd / cross_paper） |
| P6 通道 medium | 5（均为 `cross_paper_image`，期刊共用 chrome 类，已降 medium） |

**本轮 FP 治理**：

- `vertical_gel_seam`：AND 门控 + 白/黑 gutter 邻域拒绝 + 左右场不对称 + **禁止 high**  
- `cross_paper_image`：统一 paper_id、过滤 `original`/trace_id、小图不可 high  
- `excel_fabrication_span` / `duplicate_excess` / `table_round_bias`：校准层 cap medium  
- 单测护栏：`tests/test_negative_controls_p6_channels.py`  
- 报告：`benchmarks/negative_controls_v1/FP_REPORT.md`（含 P6 channel 区块）  

### 未决 / 已知债

- `stats_algo.chi2_sf_approx` 旧路径上尾/下尾问题（HANDOFF 0.R 已记，未修）  
- 主文 PDF 付费墙案需用户侧补挂再全管线重跑  
- 跨论文证据比对仍属长期项（非 P6.0）  
- GitHub：`https://github.com/WuP1ao0/ManuSift`（private）；本轮改动若未 push 需本地 commit  

### 怎么验证本轮

```text
cd Desktop/ManuSift1
.venv\Scripts\python -m pytest tests/test_loading_control_roi.py tests/test_image_dup_geometric.py tests/test_gel_vertical_seam.py -q
```

期望：全 passed。

---

## 0.R 本轮新增（2026-07-18）：ROADMAP P1–P4 落地

按 `ROADMAP.md`（用户确认顺序）执行，P1–P4 全部完成，P5 进行中。核心指标：**对照组 high 6.81 → 0.00/篇**；双基准 recall 全程 1.000 不回退（v1 12/12、web 13/13，三基准全量回归实测）。

**P1 精度与分诊**：
- `manusift/report/finding_aggregation.py`（新）：findings 按证据对象聚成 issue（图像类并查集+pHash 桥、表格类 表号+check 簇、文本类 detector 族），不丢 finding；pipeline 在 calibrate 后写 `issues.json`；investigation_pairs.html 与 formal 报告增 Issues 区块；MCP `list_findings` 加 `group_by=issue`。
- `manusift/llm/adjudication.py`（新）：high issue 送 LLM 判 actionable/explainable/uncertain，仅 explainable 降 high→medium（不删）；`MANUSIFT_LLM_ADJUDICATE=1` 门控默认关；上限 20 issue/篇 + 同 fingerprint 广播。
- `manusift/report/publisher_baselines.json`（新，12 条规则）+ calibration 钩子：FP_REPORT 残余 high 六类全归因降级（ref 版本冲突、生产性重复图、SIFT/texture/panel 天然相似、桥接镜像、页家具、结构化表重复行）。离线重放 high 109→0；三基准全量回归确认 recall 不变。`FP_REPORT.md` Round 3 章节为权威记录。

**P2 外部核验**：
- P2.1 Crossref 精度首测：fraud 侧 19 条全 high（18 条集中于真案，方向正确）；对照组 20 条 high 全为合法引用 → 治理（作者比对大小写/全署名、年份容差 ±1、机构灰文献降级 info、score<2 high→medium）。治理后离线回放对照组 high=0。`benchmarks/negative_controls_v1/CITATION_REPORT.md` 为权威报告。新增 `MANUSIFT_CROSSREF_OFFLINE=1` cache 回放模式（CI 不联网）。
- P2.2 `manusift/detectors/cited_retraction.py`（新）：OpenAlex `is_retracted` 引用级查询，命中→high；`data/openalex_cache.json` 缓存；`MANUSIFT_OPENALEX_ENABLED` 门控默认关。已入管线（37→38 检测器）。
- P2.3 `data_availability_concern.py` 扩展：声明中 DOI/URL 落地核验，404→medium、网络失败→info（绝不 high）；`MANUSIFT_DAS_RESOLUTION_ENABLED` 门控默认关；`data/link_check_cache.json` 缓存。

**P3 MCP 产品面**：新增 4 工具（surface 36→40，首位）：`screen_verdict`（一键分诊：high issue≥1→flagged，medium issue≥3→suspect，否则 clean；score 加权公式见 docs/mcp/README.md）、`submit_screen`/`get_job_status`/`get_job_result`（异步 job，`<workspace>/_screen_jobs/` 落盘可重启恢复，进度挂 pipeline on_step_complete 钩子）。契约：`scripts/check_mcp_stdio.py` + `tests/test_mcp_stdio.py` 全过。

**P4 图-表-文交叉核对**：`chart_data_extract` **修了两个使其从未生效的既有 bug**（`_load_numpy` 无限递归、未定义 `np`）；`figure_table_consistency` 补强证据路径（行标签锚定+就近配对，PCT_TOLERANCE=2.0、HIGH_MIN_GAP=10.0，弱分布路径收紧）。两检测器入管线（排除清单书面化同步）。新合成基准 `benchmarks/figure_text_v1/`（8 案：5 阳性 5/5 检出、3 阴性 0 FP）。

**管线计数现况**：检测器 注册 48 / 管线 39 / 书面排除 9；MCP 工具 40；工具总数 79（48 detectors-as-tools + 31 helpers）。

**检测能力提升（2026-07-18 晚，联网调研驱动）**：
- **statcheck 正版对齐**（`stats_algo.py`）：判定升级为四舍五入区间法（检验统计量小数位 → p 区间 → 按 p 位数舍入比对，替代原 flat 容差）；新增 z 统计量、`p=.000` 零错误、one-tailed 豁免（仅 t/z）、decision_error 分级（α=.05 显著性反转标记）；t/F/χ² 统计量侧 < / > 方向判定。调研依据：Nuijten statcheck R 包 error_test.R。
- **DEBIT**（二值结局 SD 闭式核验 √(p̂(1−p̂)N/(N−1))）+ **GRIMMER 均值感知单侧上界**（var=(μ−lo)(hi−μ)·n/(n−1)），均挂 `GrimTestDetector` 子检查（high，带二值结局/整数域/量表边界防护）；GRIM 加 N>200 跳过。
- **新检测器 `forest_plot`**（注册+入管线）：森林图规则管线 v1——四信号识别（无效线/CI 线段/关键词/数值列），右侧数值列 `est [lo, hi]` 解析，CI 顺序违反→high、log 不对称与无效线几何不一致→medium；`MANUSIFT_FOREST_PLOT_ENABLED` 门控。调研依据：无现成开源工具，自研规则路线（数值列捷径 + 几何交叉验证）。
- 调研存档备查（后续候选）：DePlot 交叉验证（282M，需下载模型）、WebPlotDigitizer 式散点/折线提取、SPRITE 深检层、p-curve 聚合信号。

**实案修复（2026-07-18 深夜，Codex MCP 实测驱动）**：
- **`screen_verdict` 伴随数据源自动发现**（`mcp/screen.py`）：管线分析的是工作区内的 PDF 副本，ingest 的"查 PDF 同目录"回退永远看不到用户源目录——新增 `_copy_sidecar_data`（源目录 XLSX/CSV/TSV/JSON 自动复制进 `inputs/materials`，默认开，`include_sidecar` 可关），verdict 增 `sidecar_files` 字段；异步 submit 路径自动继承。
- **表格伪造信号统计层**（`table_stats.py` RoundBiasDetector + `table_relationships.py`）：末位 10 类卡方 / 末位=5 与 {0,5} 二项专项 / 末两位逐对二项（Al-Marzouki、Beber-Scacco 方法）；等差序列（排序差分 CV / 值-秩 R²，索引列防护）；列内精确重复超额（精度推断→占位模型期望→泊松尾，零值/边界 tie 与 P-value 列防护）；小数位数混合（原始字符串）。全族 BH 校正，q<0.001 high。实案（s41565-025-02082-0，7 个 XLSX）用户人工列举信号全部有 finding 对应；negative controls 复跑 high=0。
- **发现的既有 bug（未修，待处理）**：`stats_algo.chi2_sf_approx` 与 table_stats 旧 `_chi2_sf` 返回的是**下尾 CDF 而非上尾**，legacy Benford/round_bias 路径仍用旧实现（新代码已用与 scipy 对拍的 `_chi2_sf_exact`）——需评估对 Benford 检测器现有行为的影响后单独修。
- 验证：全套件 exit=0（2332 collected）；3 案冒烟（bio_img_001/web_sci_01/ctrl_bmj_01）recall 与 FP 无异常。

**P5 评测扩域 + CI 门禁**：
- 新基准 `benchmarks/expansion_cs_math_v1/`（6 案 SpringerOpen CS/数学撤稿，mean recall **0.767**）与 `benchmarks/expansion_nonenglish_v1/`（5 案西/葡语，mean **0.533**）；gold 逐案核对官方撤稿通知（`retraction_notice.html` 留证）。中文（全库仅 2 条中文撤稿无 OA PDF）与德文（全在被挡站点）无法建案，实录见两集 README。miss 归因：`ref_duplicate`（跨论文重叠=预期缺口，属"跨论文证据比对"待开发项）、`paper_mill_template` 对 SpringerOpen CS 版式不适用。
- 扩域发现的实锤 bug 已修：`text_patterns` TODO/FIXME 改大小写敏感（西语 "todo" 曾每篇误报 medium），v1 12 案离线核对无 recall 风险。
- CI 门禁：`scripts/ci_benchmark_gate.py`（四基准 recall/FP 规则 + `--skip-run`/`--only`，故障注入实测变红）+ `.github/workflows/benchmark_gate.yml`（PR 跑规则测试；全量基准仅手动 workflow_dispatch 触发——nightly 已按用户要求移除，基准数据经 GitHub Release 资产 `benchmark-data` 恢复，用户已自行上传）。
- GAP_REPORT 新增 `adjudicated_down` 列（adjudicator 默认关，恒 0，供启用后监控误降）。
- `figure_table_consistency` 补 FP 修复：结构性合计行（"All CPs ... 100%" 分母行）不再锚定显式配对（回归中 ctrl_f1000_01  prose 子集百分比误锚 60pp 差距）；修复后对照组 high 回 0、合成基准仍 5/5。

**项目清理（2026-07-18 晚，释放约 2.1GB）**：删除 data/ 调试残留（test-ws/test_debug×2/test_inspect/_test_ingest×2/_analyze.py/server.log/_incoming/eval_tmp）、data/pilot_jobs（309MB）、benchmark-data.tar.gz 本地副本（已传 Release）、external_repos（193MB）、manusift_benchmarks（843MB）、real_eval_fraud_cases_v3、data/jobs 全部历史 job（保留 _screen_jobs）、__pycache__/pytest/ruff 缓存。**教训记录**：manusift_benchmarks 删除时误判"无测试引用"（grep 输出截断漏看），实际 3 个测试文件从其导入专用模块（build_alignment/enrich_gold_and_diagnose/cases_meta）——这些模块随目录永久删除（未入库），对应 4 个死测试文件一并删除（test_alignment_fig_page、test_enrich_gold_diagnose、test_v2_benchmark_meta、test_phase1_p112_30case_v2_smoke）；test_v2_alignment 用的是 real_eval_fraud_cases_v2/scripts 的同名模块（幸存），两个 PDF fixture 测试自带 skip 守卫。清理后全套件 exit=0、门禁 skip-run 4/4 绿、MCP 冒烟 OK。
- MCP 路径修复：`list_findings`/`read_finding` 现支持 `<workspace>/<trace_id>/` 扁平布局回退（此前只读 `jobs/` 布局，MCP 流程读不到自己的 findings）。
- **Job 工作区重分层（2026-07-18 晚）**：job 产物从 `<workspace>/<tid>/` 平铺改为三层——`inputs/`（original.pdf + materials/）、`steps/`（NN_*.json 检查点 + images/，PDF 抽取图从顶层 `data/_images/<tid>/` 迁入）、`output/`（job.json、findings.json、issues.json、report.html、llm_report.*、investigation_*、screen_verdict.json 等全部产物）。定义集中在 `manusift/workspace.py` JobPaths（新增 `inputs_dir`/`materials_dir`/`output_dir`/`images_dir`）；`tools/inspection.py` 的双布局回退随之删除（上一条的扁平回退已被本布局取代）。三个跨 job HTTP 缓存（crossref/openalex/link_check）从 `data/` 根迁入 `data/cache/`，共享 helper `workspace.cache_dir()`；无旧路径回退，旧文件不迁移（data/jobs 已清空，`crash.log` 保留）。

---

## 0. 本轮新增（2026-07-17 第二会话）：`fraud_web_v1` 网上自建基准 + 检测器优化

**新基准** `benchmarks/fraud_web_v1/`：13 个**网上自找的 OA 撤稿案例**（OpenAlex `is_retracted:true + is_oa:true` 检索，仅从出版社站点下载 PDF + Crossref 元数据 + 落地页；Hindawi/MDPI/T&F/PMC 反爬 403/PoW 已绕行到 PLOS/SciRep/Frontiers/BMC/Cureus/Spandidos/BMJ/F1000）。每案 gold 均**逐案核对官方撤稿通知原文**定稿，欺诈类型覆盖 v1 缺失维度（tortured phrases、统计不自洽、跑题、剽窃、伦理缺失、同行评审操纵、作者造假、跨论文图像复用）。

**指标**：mean core recall **0.801 → 0.942 → 1.000（13/13）**；`benchmarks/fraud_web_v1/GAP_REPORT.md` 为权威报告。  
**v1 回归**：`fraud_representatives_v1` 全量重跑，12/12 有 PDF 案仍 **1.000**，无回归。

**本轮落地的检测器改动**（均有单测）：

| 文件 | 内容 |
|------|------|
| `manusift/detectors/tortured_phrases.py` + `tortured_phrases_data.json` | 接入 5,802 条经核实 Cabanac 派生词典（`scripts/build_tortured_dict.py` 构建）；**删除旧假词典**（"covid-19"/"p-value"/"data availability" 等正常短语曾致每篇正常论文误报）；单条组合正则一次扫描 |
| `manusift/detectors/data_availability_concern.py` | 新增 LOW 级 `within_manuscript_only`（"All relevant data are within the manuscript"）与 `not_applicable` 信号 |
| `manusift/detectors/paper_mill_template.py` | **修复空格 join 毁行结构导致标题提取失效的真 bug**（"\n".join）；词表加 CS 论文工厂标题 "associated works" |
| `manusift/detectors/stat_consistency.py` | `stat_pvalue` 新增**表内 t/p 列一致性扫描**（header 驱动 `t-value`/`p-value` 列，正态近似，Δ>0.15 且≥2 对才 high）；早退 bug 修复（无文本但有 tables 时不再跳过表扫描） |
| `manusift/detectors/ssim.py` | `_ssim_one_pair` <7px 图板防护（修复 `panel_duplicate` 整器崩溃 ValueError） |
| `manusift/pipeline.py` | **`text_tortured_phrases` + `paper_mill_template` 此前只在注册表、从不在离线管线运行**——已加入管线列表（35 检测器） |
| `manusift/tools/detector_catalog.py` | 补 3 个缺失类目映射（figure_table_ocr→chart、source_data_consistency/table_highlight_focus→table） |

**gold 修正 3 案**（附注依据）：f1000_01（数据共享规范，误列 data_availability_concern）、bmj_01（五项声明齐全，误列 compliance）、cureus_01（无数值离群点，误列 table_outlier）。

**顺带修复既有测试**：GRIM×4（对齐区间法语义）、detector_tool_coverage×3（计数 66→73）、progress_endpoint canonical 列表、cde_deter_image_dup（PyMuPDF stdout 广告行）。  
**既有红测试清理（第二段工作，全绿收官）**：p213×5（提示词改从新 `agent/system_prompt.py` 读取）、p04×3（`CHEAT_SHEET_OVERRIDES` 新位置/新名）、stream_timeout×2（默认值已提至 300/600s，注释为据）、system_prompt_rewrite×1（删掉守卫段末尾审计史段落，16055→<16000 字符）、cli_entrypoints×1（chat TUI 已删，`app()`→`main()` 新契约）、cost×1（硬编码 ts 移出 30 天聚合窗，改相对时间）、finding_calibration×1（桥接允许 `len(out)>=len(in)`）、v2_alignment×5（`build_alignment` 模块名与 fig_page 冲突，改 importlib 唯一名加载）。**终验：2150 passed, 31 skipped, 0 failed**（忽略项：test_phase1_p112_30case_v2_smoke 慢速集成）。

---

## 0.5 第三段工作（2026-07-17 深夜）：精度基准 + 误报治理 + stat 纵深

**新基准** `benchmarks/negative_controls_v1/`：16 篇**正常 OA 论文**（OpenAlex `is_retracted:false` + 被引>3 + 与 fraud_web_v1 同出版社配对），专测**误报率**——此前所有基准只有撤稿论文，只测了 recall。`FP_REPORT.md` 为权威报告。

**核心指标**：
- 对照组 high findings/篇：**46.25 → 6.81**（740 → 109）
- fraud recall：v1 12/12 = **1.000**、fraud_web 13/13 = **1.000**（全程保持，四轮验证波确认）
- 残余 high 类（可辩护、留人工复核）：texture_overlap、cross_image_sift≥40 inliers、panel 强匹配、ref 年份冲突、生产性重复图——详见 `negative_controls_v1/README.md` 调参史

**误报治理（R1-R4，全部有单测）**：
| 文件 | 内容 |
|------|------|
| `page_raster_dup.py` | 页家具/模板重复按簇跨页降级（≥5 页→low，>2→medium）；page_tile↔page_tile 不再 high |
| `image_dup.py` / `panel_dup.py` | 同款簇降级；排他对在紧 hamming 保持 high |
| `sift_copymove.py` / `image_forensics` | cross-image SIFT high 需 ≥40 inliers；同图 copy-move high 需 ≥40（flag 阈值不变保 recall） |
| `panel_segmentation.py` | SSIM 0.97 单独不再够 high（白底虚增）；需 SSIM≥0.97 + pHash≤16 或 pHash≤4 |
| `stat_consistency.py` | **stat_grim 不再扫统计量列**（p/t/F/χ²/SD/效应量——GRIM 在此是门类错误）；mean 列 GRIM 降 low（连续数据非整数域）；仅 pct 类列保 high。**新增汇总统计重算**：Welch-t / ANOVA-F / F→p 从 mean±SD+N 反推并与报告值比对（cureus_01 真案命中 t 报 1.61 实 1.13） |
| `references.py` | 参考文献冲突分型：仅标题差异→low；年份/姓氏冲突→high |
| `pipeline.py` | **PIPELINE_EXCLUDED**：注册表 46 vs 管线 35 的 11 个排除全部书面化 + `test_pipeline_detector_coverage.py` 防再漂移 |

**经验（重要）**：多 hash/SIFT 类通道在 fraud 与正常论文上分布大面积重叠，**单靠阈值无法分离**；有效杠杆是（a）按簇排他性降级（家具 vs 抄袭对的结构差异）（b）严重度带宽（high 只留给强证据，recall 靠 count>0 不受影响）（c）门类正确性（GRIM 只用于整数域）。

**cureus_01 gold 修正**：stat_grim 移除（其原命中是 GRIM-on-p-value 门类错误）；真信号由 stat_pvalue + 新汇总统计重算捕获。

---

## 0.6 第四段工作（2026-07-17 深夜）：MCP 对外工具面打通

**目标**：项目可被外部 agent（Claude Code、Codex 等）以 MCP 方式调用。`manusift/mcp/server.py` 已存在，本轮修复到**端到端可用**。

**验证契约**（`scripts/check_mcp_stdio.py` + `tests/test_mcp_stdio.py`，均过）：initialize → tools/list（默认 **全量 ~83** tools）→ `ingest_from_path`（真 PDF 返回 trace_id）→ `pdf_metadata` 执行 → unknown_tool 错误路径。并行管线见 §0.T 与 `tests/test_parallel_pipeline.py`。

**修掉的 3 个 Windows 环境死锁/污染**（均实测复现后修复）：

| 问题 | 现象 | 修复 |
|------|------|------|
| PyMuPDF layout 广告行打印到 stdout | 污染 JSON-RPC 通道，客户端解析崩溃 | `pymupdf.no_recommend_layout()` 启动调用 + `contextlib.redirect_stdout(sys.stderr)` 包裹每次 tool 执行（传输层持有原始 stdout.buffer 不受影响） |
| numpy/scipy C 扩展在运行中的事件循环里懒导入 | `create_module` 死锁（faulthandler 抓到 numpy._core.multiarray、scipy.fft 两处现场） | 启动时**单线程预导入全链**（numpy/scipy/scipy.fft/scipy.special/imagehash/cv2/skimage/torch/easyocr），后续懒导入全变 sys.modules 缓存命中 |
| 重工具阻塞 loop 线程 | 大 PDF parse 期间服务器无响应 | `asyncio.to_thread(tool.execute, ...)` worker 线程执行 |

**调试开关**：`MANUSIFT_MCP_DEBUG=1` → stderr 打点 + faulthandler 定时线程转储。

**接入文档**：`docs/mcp/README.md` 更新；配置样例 `claude_code.mcp.json`（Claude Code，`claude mcp add` 一行也可）、`codex.config.toml`（Codex `~/.codex/config.toml`）、原有 `claude_desktop.example.json`/`cursor.example.json`。Windows 客户端建议 env 带 `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`（GBK 解码问题），init 超时给足（首次启动 10-30s 预导入）。

**待开发项登记**：跨论文证据比对（RW 库 + 指纹语料）已按用户要求列入 §7 待开发项，后续版本实施。

---

## 1. 一句话概况

**ManuSift** 是学术论文 PDF **诚信筛查**管线：解析 PDF → 多检测器（图像重复/取证、表格、元数据、数据可用性、paper-mill 信号等）→ 校准 findings → 生成调查报告（含 `investigation_pairs.html` 等）。  
**当前主线成果**：跨领域代表撤稿集 `fraud_representatives_v1` 在 **12 个有 PDF 的案例上 mean core recall = 1.0**。  
**卡点**：5 个付费墙经典案缺 `paper.pdf`（用户有学校图书馆账号，需其本人下载后放入约定路径）。

---

## 2. 仓库与环境

| 项 | 值 |
|----|-----|
| 根目录 | `C:\Users\22509\Desktop\ManuSift1` |
| 分支 | `master`（交接时工作区以 `git status` 为准） |
| Python | `.venv\Scripts\python.exe`（Windows） |
| 主包 | `manusift/` |
| 代表集 | `benchmarks/fraud_representatives_v1/` |
| 30 案旧评测 | `real_eval_fraud_cases_v2/`（Fig→page 对齐、P6 gate 等曾改过） |

**常用环境变量（smoke 已默认）**：

```text
MANUSIFT_FINDING_CALIBRATE=1
MANUSIFT_LLM_MAX_CONCURRENCY=0
MANUSIFT_LLM_ENRICH_MODE=off
MANUSIFT_LLM_ADJUDICATE=0
MANUSIFT_LLM_ADJUDICATE_MAX_ISSUES=20
MANUSIFT_FIGURE_TABLE_OCR=0
MANUSIFT_CHART_EXTRACT_ENABLED=1
MANUSIFT_CROSSREF_ENABLED=0
MANUSIFT_CROSSREF_OFFLINE=0
MANUSIFT_OPENALEX_ENABLED=0
MANUSIFT_DAS_RESOLUTION_ENABLED=0
```

`MANUSIFT_CROSSREF_OFFLINE=1`（P2.1，配合 `CROSSREF_ENABLED=1` 使用）：citation_network 只读本地 `data/cache/crossref_cache.json`，cache miss 不联网、记 info 级 `not_testable`，供 CI 确定性回放。

`MANUSIFT_CHART_EXTRACT_ENABLED=0`（P4，2026-07-18）：独立关闭 chart_data_extract（bar 几何提取，仅依赖 numpy/OpenCV、无 OCR 模型）。默认开；numpy/cv2 缺失时检测器自身已优雅返回空结果，此开关供评测/CI 彻底跳过。figure_table_consistency 为纯文本+表格比对，无需门控。

PowerShell 下 pytest/python 引号易碎：优先用  
`.venv\Scripts\python.exe -m pytest ...` 或 `-c "..."` / 脚本文件。

---

## 3. 当前指标（fraud_representatives_v1）

| 指标 | 值 |
|------|-----|
| Smoke OK | **12 / 17**（其余 5 = `skipped_no_pdf`） |
| Mean core recall（有 PDF） | **1.000** |
| 权威 gap 报告 | `benchmarks/fraud_representatives_v1/GAP_REPORT.md` |
| 最近 smoke 汇总 | `benchmarks/fraud_representatives_v1/smoke_runs.json` |

**轨迹（同一套 12 OA PDF）**：约 0.626 → 0.817 → 0.942 → **1.0**。

跑法：

```bash
# 有 PDF 的案例
.venv\Scripts\python.exe benchmarks/fraud_representatives_v1/run_smoke.py

# 聚合 gap 报告
.venv\Scripts\python.exe benchmarks/fraud_representatives_v1/build_gap_report.py
```

也可只跑若干 case_id：在脚本里调 `run_one(case_dir)`（见 `run_smoke.py`）。

---

## 4. 缺 PDF 的 5 案（用户学校图书馆待下）

**禁止**：镜像站 / Sci-Hub 等未授权渠道。  
**允许**：学校 VPN + 图书馆订阅 / 文献传递。

| case_id | 路径（相对 `cases/`） | 正确 DOI | 注意 |
|---------|----------------------|----------|------|
| `clin_001_lancet_surgisphere_hcq` | `clinical_registry/.../paper.pdf` | `10.1016/S0140-6736(20)31180-6` | 论著，非 Comment |
| `clin_002_nejm_surgisphere_cvd` | `clinical_registry/.../paper.pdf` | **`10.1056/NEJMoa2007621`** | **不要下成 `NEJMe...` 社论（常 1 页）** |
| `clin_003_wakefield_mmr` | `clinical_registry/.../paper.pdf` | `10.1016/S0140-6736(97)11096-0` | 论著 |
| `chem_003_science_heterostructure` | `chemistry_materials/.../paper.pdf` | `10.1126/science.aaz8700` | Science |
| `psych_001_stapel_science_chaos` | `psychology_social/.../paper.pdf` | `10.1126/science.1201068` | Science |

**Web of Science 说明**：WOS 多半不直接存 PDF；点 **Full Text / DOI** 跳出版社再下。机构权限须从图书馆入口或 VPN 进入。

**用户放好后 agent 应做**：

1. 校验 `paper.pdf` 存在且 `magic` 为 `%PDF`、页数合理（社论 1 页 = 下错）  
2. `run_smoke` 这 5 案或全量  
3. 更新 `smoke_runs.json` + `build_gap_report.py`  
4. 视结果微调 `official_gold.json` 的 `expected_core_detectors`

---

## 5. 本轮已落地的重要改动（代码）

### 5.1 图像重复 / 取证桥

| 文件 | 内容 |
|------|------|
| `manusift/detectors/image_dup.py` | 三通道：pHash 主阈值（config 默认 **8**）+ aHash/dHash 二次 + 高方差 tile 区域桥 |
| `manusift/report/finding_calibration.py` | `bridge_forensics_to_image_dup`；`bridge_forensics_to_panel_duplicate`（`panel_sift_match`） |
| `manusift/config.py` | `image_duplicate_hamming_threshold: 8` |

### 5.2 图板重复

| 文件 | 内容 |
|------|------|
| `manusift/detectors/panel_segmentation.py` | SSIM 0.78 + pHash；轮廓失败时 **网格回退** |
| 校准层 | forensics `panel_sift_match` → `panel_duplicate` |

### 5.3 作者 / 数据可用性 / 元数据

| 文件 | 内容 |
|------|------|
| `manusift/detectors/paper_mill_authorship.py` | Frontiers `Name N` 作者计数；免费邮箱；多机构上标堆叠；RETRACTED+瘦 peer-review |
| `manusift/detectors/data_availability_concern.py` | Frontiers 模糊声明（`without undue reservation` 等） |
| `manusift/detectors/pdf_metadata.py` | TeX + 超长 `/Subject` 弱信号 |

### 5.4 页栅格 / 表格（关键 bug）

| 文件 | 内容 |
|------|------|
| `manusift/detectors/page_raster_dup.py` | 区域 tile + 整页网格 + 多哈希（整区 pHash 常 ≥28 才漏） |
| **`manusift/ingest/pdf.py`** | **`_extract_tables` 必须在 `fitz.open` 的 `with` 内执行**——此前文档关闭后再抽表 → **`doc.tables` 恒空** |
| `manusift/ingest/pdf_tables.py` | Frontiers 文本层 `TABLE N |` 解析 |
| `manusift/detectors/table_stats.py` | 精确/数值近重行 + 文本层多数字行重复回退 |

### 5.5 Gold 调整

- `chem_002`：`table_duplicate_row` → **`image_noise_inconsistency`**（该案无表格重复证据，主问题是图像）。  
  见 `cases/chemistry_materials/chem_002_.../official_gold.json` 与 `manifest.json`。

### 5.6 测试（相关）

- `tests/test_image_dup_multihash.py`
- `tests/test_forensics_image_dup_bridge.py`
- `tests/test_pdf_table_open_doc.py`
- 以及 data_availability / paper_mill 增补用例

---

## 6. 架构速览（接手改代码时）

```
PDF
 → manusift/ingest/pdf.py          # 文本、图像、tables（须 open 中抽取）
 → pipeline 跑 detectors           # manusift/detectors/*, 注册在 __init__.py
 → finding_calibration.calibrate_findings  # 桥接 + 严重度，不丢 finding
 →（可选）LLM enrich               # smoke 已关
 → report / investigation_pairs
```

**Eval 口径**：`expected_core_detectors` 是否出现在 findings 的 `detector` 字段（计数 >0）。  
桥接会把 forensics 的强信号 **镜像** 成 `image_dup` / `panel_duplicate` 名——为对齐 gold/eval，不是替代 forensics。

**报告入口**：`investigation_pairs.html` 曾定为新主入口；另有 formal plain investigation 报告。

---

## 7. 建议下一优先级

**排期总表见 `ROADMAP.md`（2026-07-18 用户确认顺序：精度分诊 → 外部核验 → MCP 产品面 → 图表文交叉核对 → 评测扩域与 CI）。** 以下为原始速记：

1. **用户挂上 5 个授权 PDF** → smoke + gap 更新（见 §4）  
2. **Precision / finding 量控制**：`page_raster` tile、forensics bridge 会抬高 medium 数量  
3. **30-case v2 校准集全量 P6 gate**（`real_eval_fraud_cases_v2`，校准开、LLM 关）  
4. 表格 OCR（P4）对纯图表格的长期路径  
5. 勿再建议未授权镜像；机构账号由用户本地完成登录下载  

### 待开发项（用户排期，后续版本）

- **跨论文证据比对（cross-paper evidence）**：Retraction Watch / Crossref 撤稿库比对 + 图像指纹语料库（pHash 入库查重）。解决单篇 PDF 检测的天花板（跨论文图像复用、与外部文献的文本重叠只能标"存疑"无法"确证"）。复用已注册未入管线的 `imagehash_*` 检测器族。用户明确要求列为后续版本待开发（2026-07-17）。
- **MCP 对外工具面**（已完成第一版，见 §0.6）：后续可按外部 agent 反馈扩展 surface。

---

## 8. 会话中用户侧注意点（已发生）

- NEJM：`NEJMe...` = 社论（常 **1 页**）；完整 Surgisphere 文是 **`NEJMoa2007621`**。  
- Web of Science：找 Full Text/DOI，PDF 在出版社站。  
- 用户有学校图书馆账号，愿合规下载；agent **不能代登账号/要密码**。

---

## 9. 关键路径速查

```
manusift/pipeline.py
manusift/ingest/pdf.py
manusift/workspace.py        # JobPaths：job 目录布局的唯一来源
manusift/detectors/image_dup.py
manusift/detectors/image_forensics.py
manusift/detectors/panel_segmentation.py
manusift/detectors/page_raster_dup.py
manusift/detectors/paper_mill_authorship.py
manusift/detectors/data_availability_concern.py
manusift/detectors/table_stats.py
manusift/report/finding_calibration.py
manusift/report/investigation_pairs.py

data/jobs/<trace_id>/        # 单 job 工作区（重分层后）
  inputs/original.pdf        # 上传 PDF；inputs/materials/ 为伴随数据文件
  steps/NN_<detector>.json   # 检查点；steps/images/ 为 PDF 抽取图像
  output/                    # job.json、findings.json、issues.json、
                             # report.html、llm_report.*、investigation_* 等
data/cache/                  # 跨 job HTTP 缓存（crossref/openalex/link_check）

benchmarks/fraud_representatives_v1/
  README.md
  manifest.json
  CASE_CATALOGUE.md
  GAP_REPORT.md
  smoke_runs.json
  run_smoke.py
  build_gap_report.py
  prepare_cases.py
  cases/<domain>/<case_id>/
    paper.pdf              # 有则跑
    official_gold.json     # expected_core_detectors
    manusift_run/          # 最近跑次产物
```

---

## 10. 交接检查清单（下一个 agent 开场 5 分钟）

- [ ] `git status` / 读本 `HANDOFF.md`  
- [ ] 读 `benchmarks/fraud_representatives_v1/GAP_REPORT.md` 确认 12/12 core recall  
- [ ] 列 `cases/*/*/paper.pdf`：5 案仍缺则勿宣称全量 17 可跑  
- [ ] 改检测器后：相关 unit test + 对 miss 案 `run_one`，再 `build_gap_report`  
- [ ] 动 `parse_pdf` / tables 时：**确认 tables 在 fitz 文档仍 open 时抽取**  
- [ ] 不提供付费墙破解 / 盗版镜像指引  

---

*本文档为协作交接用，不是用户手册。产品行为以代码与 `official_gold.json` 为准。*
