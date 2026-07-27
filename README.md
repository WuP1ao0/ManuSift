# ManuSift

<p align="center">
  <img src="docs/assets/manusift.png" alt="ManuSift" width="920" />
</p>

<p align="center">
  <strong>学术论文诚信纠察 agent · 离线检测内核 · pi SDK 独立 TUI</strong><br/>
  <a href="README.en.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/WuP1ao0/ManuSift/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/WuP1ao0/ManuSift/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue.svg"></a>
  <a href="CHANGELOG.md"><img alt="Status" src="https://img.shields.io/badge/status-beta-yellow.svg"></a>
  <a href="docs/pi-agent.md"><img alt="pi agent" src="https://img.shields.io/badge/pi-agent-purple.svg"></a>
</p>

## 这是个啥？

ManuSift 是一个**学术论文诚信筛查 agent**：扔给它一篇 PDF（外加 Source Data
表格更好），它会用 52 个检测器扫一遍——图像复用、表格造数痕迹、统计对不上、
扭曲措辞、引用异常……然后给你一份带证据的报告。

两种用法：

| 用法 | 一句话 |
|------|--------|
| **交互 agent**（推荐） | 敲 `manusift` 进品牌 TUI，聊着把论文查了；`/screen <pdf>` 一键跑全管线 |
| **批处理 CLI** | `manusift screen paper.pdf --no-llm`，完全离线、不要任何 API key，适合脚本和批量 |

架构上它是「oh-my-pi 式」的独立 agent：交互层用
[pi](https://github.com/earendil-works/pi) SDK 搭（没 fork），检测内核还是
Python——中间靠一条 JSON-lines stdio 桥（`manusift toolserver`）把 **~82 个领域
工具**全部喂给 agent。

> **先说清楚**：ManuSift 只给「筛查信号」，不下「学术不端」的结论。
> 该人来判断的还是得人来判断。

---

## 快速上手

需要 Python ≥ 3.10（推荐 3.11），Windows / Linux / macOS 都行。

```bash
git clone https://github.com/WuP1ao0/ManuSift.git
cd ManuSift

python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -e .

# 装完先冒个烟
python scripts/install_smoke.py

# 离线筛一篇（不用任何 key）
manusift screen evals/fixtures/clean_academic.pdf --no-llm --suites fast --workspace ./my_jobs
```

### 交互 agent（要 Node.js ≥ 20 + 一个 LLM key）

```bash
cd agent && npm install --ignore-scripts && cd ..   # 一次性
manusift                                            # 进 TUI，随便聊
```

TUI 里能干的事：

- 直接说人话：`对 C:\papers\paper.pdf 做诚信筛查`、`图 3 是不是重复了？`
- `/screen <pdf>` —— 全管线后台跑，进度挂在底栏，跑完自动给你 5 段式结论
- `/manusift status` / `restart` —— 看/重启 Python 工具桥
- 一次性问答：`manusift agent -p "对 xxx.pdf 做诚信筛查"`

agent 的 LLM key 走 pi 的认证（首次启动会引导登录，或设
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 环境变量）。**批处理模式不需要这些**。

### 结果在哪

```text
<workspace>/<trace_id>/
├── inputs/       # 原始 PDF（+伴随数据）
├── steps/        # 每个检测器的检查点
└── output/
    ├── findings.json            # 校准后的原始发现
    ├── issues.json              # 聚合后的复核条目（更少、更好读）
    ├── report.html              # HTML 总结
    └── investigation_pairs.*    # 主调查视图（先开这个）
```

建议永远带 `--workspace`，不然结果落在 `data/jobs/` 里容易找不着。

### 可选增强

```bash
pip install -e ".[dev]"   # pytest + ruff（贡献者）
pip install -e ".[ocr]"   # EasyOCR + torch（约 2GB），解锁图内表格 OCR 类检测器
```

批处理想要 LLM 润色报告？复制 `.env.example` → `.env`，填
`MANUSIFT_OPENAI_API_KEY` 或 `MANUSIFT_ANTHROPIC_API_KEY`，然后去掉
`--no-llm` 就行。没 key 也能跑完，只是 `llm_report.*` 是空壳。
报告默认中文，`--lang en` 切英文。

---

## 能查什么

| 方向 | 具体查什么 |
|------|-----------|
| **图像取证** | 多哈希复用（pHash/aHash/dHash）、SIFT copy-move、翻转/旋转匹配、凝胶接缝、panel+SSIM、页面栅格、噪声/ELA、AI 生成图探针 |
| **表格与统计** | Benford、重复行/近重复行、跨表复制、固定差/固定比、小数尾偏置、GRIM/GRIMMER、DEBIT、statcheck 式 t/F/χ²/z/r vs p 复算 |
| **图文交叉** | 柱状图几何提取 vs 正文数值、森林图 CI 规则 |
| **文本与元数据** | 扭曲措辞（5802 条词典）、论文工厂信号、PDF 元数据、参考文献重复/冲突 |
| **外部核验**（选配） | Crossref / OpenAlex 撤稿库 / 数据可用性链接落地检查（带缓存，CI 可离线回放） |
| **分诊** | 校准 + issue 聚合，high/medium/low 三档，宁可保守不乱扣帽子 |

数字口径（免得糊涂）：检测器注册 **52** 个，离线管线跑其中 **44** 个（8 个
agent 按需调用）；agent 工具面 **~82** 个 = 检测器工具 + ingest/报告/任务等
辅助工具。`manusift toolserver --list-tools` 可以自己数。

---

## 它是怎么拼起来的

```text
你 ──> manusift（品牌 TUI，pi SDK，agent/bin/manusift-agent.mjs）
         │  自带诚信纠察系统提示词；默认只读工具面（--dev 才开 bash/edit/write）
         ▼
       .pi/extensions/manusift/   桥扩展（/screen、去重护栏、82 工具注册）
         ▼
       python -m manusift.toolserver   JSON-lines stdio 桥
         ▼
       Python 检测内核：ingest → 44 检测器并行 → 校准/聚合 → 报告
```

批处理 `manusift screen` 直接走最下面那层，不经过 agent。

其它入口：`manusift-workspace`（本地任务浏览器）、
`python -m uvicorn manusift.web.app:app`（本地回环 HTTP API，不是云服务）。

### 加一个自己的检测器

```python
# manusift/detectors/my_detector.py
from .base import DetectorResult
from ..contracts import ParsedDoc

class MyDetector:
    """一句话描述（也会出现在 agent 工具列表里）。"""
    name = "my_detector"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        return DetectorResult(detector=self.name, ok=True, findings=[], duration_ms=1)
```

在 `manusift/detectors/__init__.py` 注册，或者用 entry_points 做成第三方插件——
注册完自动变成 agent 工具，一分钱手续费不收。

---

## 常用配置

前缀都是 `MANUSIFT_`，全量清单看 `manusift/config.py`。

| 变量 | 默认 | 干嘛的 |
|------|------|--------|
| `MANUSIFT_WORKSPACE_DIR` | `./data/jobs` | 任务根目录（等价 `--workspace`） |
| `MANUSIFT_DETECTOR_WORKERS` | `4` | 检测器并行数（`1` = 串行） |
| `MANUSIFT_REPORT_LANGUAGE` | `zh` | 报告语言 `zh` / `en` |
| `MANUSIFT_OPENAI_API_KEY` 等 | 未设 | 批处理 LLM 润色（可选） |
| `MANUSIFT_PYTHON` | 自动找 `.venv` | agent 桥用哪个 Python |
| `MANUSIFT_PI` | 未设 | 强制用裸 pi 启动而非独立 agent |

---

## 文档

| 文档 | 讲什么 |
|------|--------|
| [`docs/pi-agent.md`](docs/pi-agent.md) | agent 安装、/screen、排障 |
| [`docs/DETECTOR_LAYERS.md`](docs/DETECTOR_LAYERS.md) | 检测器三层归属（管线/注册表/排除） |
| [`docs/REPORT_PATH.md`](docs/REPORT_PATH.md) | 报告主链路（investigation_pairs） |
| [`docs/pubpeer_100_fraud_methods.md`](docs/pubpeer_100_fraud_methods.md) | PubPeer 100 种手法与检测对照 |
| [`docs/SECURITY.md`](docs/SECURITY.md) | 安全注意事项 |

---

## 开发

```bash
pip install -e ".[dev]"
python -m pytest -q          # 全量测试
python -m ruff check manusift tests

python scripts/ci_benchmark_gate.py --skip-run   # 基准门禁（查已存产物）
```

基准套件在 `benchmarks/`：真实撤稿案 recall 全程 1.0，负对照 high 误报 0——
改检测器前先看 `docs/DETECTOR_LAYERS.md`，改完跑门禁。

---

## 许可与社区

MIT 许可（[LICENSE](LICENSE)）· [贡献指南](CONTRIBUTING.md) ·
[行为准则](CODE_OF_CONDUCT.md) · [安全政策](SECURITY.md) ·
[更新日志](CHANGELOG.md) · [引用格式](CITATION.cff)

## 免责声明

ManuSift 是**筛查辅助工具**，输出的是「值得人工复核的信号」，不是学术不端的
法律或制度性认定，也替代不了编辑、机构和领域专家的人工审查。
