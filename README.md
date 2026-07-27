# ManuSift

<p align="center">
  <img src="docs/assets/manusift.png" alt="ManuSift" width="920" />
</p>

<p align="center">
  <strong>学术论文诚信筛查 agent · 离线检测内核 · 基于 pi SDK 的独立 TUI</strong><br/>
  <a href="README.en.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/WuP1ao0/ManuSift/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/WuP1ao0/ManuSift/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue.svg"></a>
  <a href="CHANGELOG.md"><img alt="Status" src="https://img.shields.io/badge/status-beta-yellow.svg"></a>
  <a href="docs/pi-agent.md"><img alt="pi agent" src="https://img.shields.io/badge/pi-agent-purple.svg"></a>
</p>

## 概述

ManuSift 对论文 PDF 及其 Source Data 表格执行诚信筛查：52 个检测器覆盖图像复用、
表格伪造指纹、统计不一致、扭曲措辞、引用异常等方向，输出带证据定位的
findings / issues / HTML 报告。

两个产品面：

| 入口 | 说明 |
|------|------|
| **交互 agent** | `manusift` 启动独立 TUI；对话式筛查，`/screen <pdf>` 触发全管线 |
| **批处理 CLI** | `manusift screen paper.pdf --no-llm`；完全离线、无需 API key，适合脚本与批量 |

架构：交互层基于 [pi](https://github.com/earendil-works/pi) SDK 构建独立 agent
（非 fork），检测内核为 Python；两者经 JSON-lines stdio 桥
（`manusift toolserver`）对接，agent 侧可调用全部 **~82 个领域工具**。

> ManuSift 输出的是筛查信号（screening signals），不构成学术不端认定。

---

## 安装与使用

要求 Python ≥ 3.10（推荐 3.11）；Windows / Linux / macOS。

```bash
git clone https://github.com/WuP1ao0/ManuSift.git
cd ManuSift

python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -e .

python scripts/install_smoke.py    # 安装自检

# 离线批处理（无需 key）
manusift screen evals/fixtures/clean_academic.pdf --no-llm --suites fast --workspace ./my_jobs
```

### 交互 agent

依赖 Node.js ≥ 20 及一个 LLM provider key（经 pi 认证体系，首次启动引导登录，
或设置 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`；批处理模式不依赖）。

```bash
cd agent && npm install --ignore-scripts && cd ..   # 一次性
manusift                                            # 交互 TUI
manusift agent -p "对 path/to/paper.pdf 做诚信筛查"  # 单次打印模式
```

TUI 内：

- 自然语言指令：`对 C:\papers\paper.pdf 做诚信筛查`、`图 3 是否重复`
- `/screen <pdf>`：全管线异步执行，进度显示于底栏，完成后按 5 段式输出结论
- `/manusift status | restart`：工具桥状态管理
- 默认只读工具面（无 bash/edit/write），`--dev` 解除限制

### 产物布局

```text
<workspace>/<trace_id>/
├── inputs/       # 原始 PDF 与伴随数据
├── steps/        # 逐检测器检查点
└── output/
    ├── findings.json            # 校准后 findings
    ├── issues.json              # 聚合后的复核条目
    ├── report.html              # HTML 总结
    └── investigation_pairs.*    # 主调查视图
```

建议显式指定 `--workspace`；缺省时产物位于 `data/jobs/<trace_id>/`。

### 可选依赖

```bash
pip install -e ".[dev]"   # pytest + ruff
pip install -e ".[ocr]"   # EasyOCR + torch（约 2GB）：图内表格 OCR 类检测器
```

批处理 LLM 润色：复制 `.env.example` → `.env`，配置
`MANUSIFT_OPENAI_API_KEY` 或 `MANUSIFT_ANTHROPIC_API_KEY` 后省略 `--no-llm`。
无 key 时管线仍完整执行，`llm_report.*` 为空壳。报告默认中文，`--lang en`
切换英文。

---

## 检测能力

| 方向 | 检测项 |
|------|--------|
| **图像取证** | 多哈希复用（pHash/aHash/dHash）、SIFT copy-move、翻转/旋转匹配、凝胶接缝、panel + SSIM、页面栅格、噪声/ELA、AI 生成图探针 |
| **表格与统计** | Benford、重复/近重复行、跨表复制、固定差/固定比、小数尾偏置、GRIM/GRIMMER、DEBIT、statcheck 式 t/F/χ²/z/r 与 p 值复算 |
| **图文交叉** | 柱状图几何提取与正文数值比对、森林图 CI 规则 |
| **文本与元数据** | 扭曲措辞（5,802 条词典）、论文工厂信号、PDF 元数据、参考文献重复/冲突 |
| **外部核验**（选配） | Crossref / OpenAlex 撤稿查询 / 数据可用性链接核验（带缓存，支持 CI 离线回放） |
| **分诊** | 校准 + issue 聚合，high/medium/low 分级，严格控制误报 |

计数口径：注册检测器 **52**，离线管线运行 **44**（其余 8 个由 agent 按需调用）；
agent 工具面 **~82** = 检测器工具 + ingest / 报告 / 任务管理等辅助工具。
可通过 `manusift toolserver --list-tools` 查验。

---

## 架构

```text
manusift  (独立 TUI，pi SDK，agent/bin/manusift-agent.mjs)
   │  定制系统提示词；默认只读工具面（--dev 开放 bash/edit/write）
   ▼
.pi/extensions/manusift/          桥扩展：/screen、调用去重护栏、~82 工具注册
   ▼
python -m manusift.toolserver     JSON-lines stdio 桥
   ▼
Python 检测内核：ingest → 44 检测器并行 → 校准/聚合 → 报告
```

批处理 `manusift screen` 直接调用检测内核，不经过 agent 层。

其它入口：`manusift-workspace`（本地任务浏览器）、
`python -m uvicorn manusift.web.app:app`（仅回环地址的本地 HTTP API）。

### 扩展检测器

```python
# manusift/detectors/my_detector.py
from .base import DetectorResult
from ..contracts import ParsedDoc

class MyDetector:
    """一句话描述（同时用于 agent 工具列表）。"""
    name = "my_detector"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        return DetectorResult(detector=self.name, ok=True, findings=[], duration_ms=1)
```

在 `manusift/detectors/__init__.py` 注册，或通过 entry_points 以第三方插件
形式发布；注册后自动进入 agent 工具面。

---

## 配置

统一前缀 `MANUSIFT_`，完整清单见 `manusift/config.py`。

| 变量 | 默认 | 说明 |
|------|------|------|
| `MANUSIFT_WORKSPACE_DIR` | `./data/jobs` | 任务根目录（等价 `--workspace`） |
| `MANUSIFT_DETECTOR_WORKERS` | `4` | 检测器并行度（`1` = 串行） |
| `MANUSIFT_REPORT_LANGUAGE` | `zh` | 报告语言 `zh` / `en` |
| `MANUSIFT_OPENAI_API_KEY` 等 | 未设 | 批处理 LLM 润色（可选） |
| `MANUSIFT_PYTHON` | 自动探测 `.venv` | agent 桥使用的 Python 解释器 |
| `MANUSIFT_PI` | 未设 | 强制以裸 pi 方式启动（跳过独立 agent） |

---

## 文档

| 文档 | 内容 |
|------|------|
| [`docs/pi-agent.md`](docs/pi-agent.md) | agent 安装、/screen、排障 |
| [`docs/DETECTOR_LAYERS.md`](docs/DETECTOR_LAYERS.md) | 检测器三层归属（管线/注册表/排除） |
| [`docs/REPORT_PATH.md`](docs/REPORT_PATH.md) | 报告主链路（investigation_pairs） |
| [`docs/pubpeer_100_fraud_methods.md`](docs/pubpeer_100_fraud_methods.md) | PubPeer 100 类手法与检测对照 |
| [`docs/SECURITY.md`](docs/SECURITY.md) | 安全说明 |

---

## 开发

```bash
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check manusift tests

python scripts/ci_benchmark_gate.py --skip-run   # 基准门禁（校验已存产物）
```

基准位于 `benchmarks/`：真实撤稿案 core recall 保持 1.0，负对照 high 误报为 0。
修改检测器前请阅读 `docs/DETECTOR_LAYERS.md`，改动后运行门禁回归。

---

## 许可与社区

MIT（[LICENSE](LICENSE)）· [CONTRIBUTING](CONTRIBUTING.md) ·
[CODE_OF_CONDUCT](CODE_OF_CONDUCT.md) · [SECURITY](SECURITY.md) ·
[CHANGELOG](CHANGELOG.md) · [CITATION](CITATION.cff)

## 免责声明

ManuSift 为筛查辅助工具，输出供人工复核的信号，不构成对学术不端的法律或
制度性认定，不能替代编辑、机构与领域专家的审查。
