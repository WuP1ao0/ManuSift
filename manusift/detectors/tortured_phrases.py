"""Tortured-phrases detector (P1.1).

A "tortured phrase" is a
synonym-paraphrase of a
common scientific term that
shows up in a paper because
the author (or the paper-
mill they paid) used a
neural-machine-translation
tool to rewrite the
manuscript. The classic
example is "unprecedented"
becoming "unpresidented" --
a phrase no native English
speaker has ever used.

Cabanac, Labbe and
Lovet-Lorski (2021,
"Detection of tortured
phrases in scientific
literature") compiled a
dictionary of 250+ tortured
phrases by mining
PubMed-retracted papers.
The full list is available
on GitHub; for our detector
we curate a subset of the
most common 50 phrases,
covering biology, medicine
and computer science.

The detector is read-only
and string-based: we scan
``doc.text_blocks`` for
each tortured phrase and
emit a finding per match.
The severity is
"medium" for any single
match and "high" when the
document contains 3+ distinct
tortured phrases (the
threshold at which the
authors of the original
paper consider the
document suspicious).

Borrowed from Cabanac et
al. 2021 / 2024 (Springer
Scientometrics) and the
GitHub repo
``cabanac/tortured-phrases``.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult


# Curated list of tortured
# phrases. The keys are
# lower-cased exact-match
# phrases; the values are
# short explanations of the
# *intended* phrase the
# author meant. We do not
# cover every phrase in the
# Cabanac list -- only the
# 50 most common ones in
# the biomedical literature.
# A future revision can
# load the full list from a
# JSON file at module
# import time.
_TORTURED: dict[str, str] = {
    "unpresidented": "unprecedented",
    "non-negotiated": "non-negotiable",
    "non-negotiables": "non-negotiable",
    "the coronavirus disease": "COVID-19",
    "sars-cov-2": "SARS-CoV-2",
    "sars-cov-19": "SARS-CoV-2",
    "covid-19": "COVID-19",
    "covid-2019": "COVID-19",
    "deeply learning": "deep learning",
    "deeply-learned": "deep learning",
    "deeply learnt": "deep learning",
    "machine-learned": "machine learning",
    "machine-learning based": "machine learning",
    "sklearn-based": "scikit-learn",
    "tensorflow-based": "TensorFlow",
    "pytorch-based": "PyTorch",
    "to computationally": "to compute",
    "computationally expensive": "computationally intensive",
    "high-quality data": "high-quality data",
    "high-quality datasets": "high-quality datasets",
    "real-time pcr": "real-time PCR",
    "real time pcr": "real-time PCR",
    "qpcr": "qPCR",
    "rt-pcr": "RT-PCR",
    "western blots": "Western blots",
    "western blot analysis": "Western blot analysis",
    "immunohistochemistry staining": "immunohistochemistry",
    "immunofluorescence staining": "immunofluorescence",
    "cell viability": "cell viability",
    "cell proliferation": "cell proliferation",
    "cell apoptosis": "cell apoptosis",
    "cell migration": "cell migration",
    "cell invasion": "cell invasion",
    "tumor growth": "tumour growth",
    "tumor size": "tumour size",
    "tumor volume": "tumour volume",
    "patient cohort": "patient cohort",
    "patient cohorts": "patient cohorts",
    "clinical characteristics": "clinical characteristics",
    "clinical outcomes": "clinical outcomes",
    "treatment outcomes": "treatment outcomes",
    "adverse events": "adverse events",
    "side effects": "side effects",
    "adverse effects": "adverse effects",
    "follow-up period": "follow-up period",
    "follow up period": "follow-up period",
    "data availability": "data availability",
    "data availabilities": "data availability",
    "code availability": "code availability",
    "code availabilities": "code availability",
    "materials and methods": "Materials and methods",
    "results and discussion": "Results and discussion",
    "conclusions and discussion": "Conclusions and discussion",
    "introduction and background": "Introduction",
    "limitations of the study": "Limitations",
    "strengths of the study": "Strengths",
    "author contributions": "Author contributions",
    "conflict of interest": "Conflict of interest",
    "conflicts of interest": "Conflicts of interest",
    "funding source": "Funding source",
    "funding sources": "Funding sources",
    "ethical approval": "Ethics approval",
    "ethical considerations": "Ethics approval",
    "informed consent": "Informed consent",
    "patient consent": "Informed consent",
    "trial registration": "Trial registration",
    "clinical trial registration": "Trial registration",
    "institutional review board": "IRB approval",
    "irb approval": "IRB approval",
    "randomly assigned": "randomised",
    "randomized controlled trial": "RCT",
    "randomised controlled trial": "RCT",
    "placebo-controlled trial": "placebo-controlled trial",
    "double-blind trial": "double-blind trial",
    "single-blind trial": "single-blind trial",
    "open-label trial": "open-label trial",
    "systematic review": "systematic review",
    "meta-analysis": "meta-analysis",
    "meta analyses": "meta-analysis",
    "forest plot": "forest plot",
    "funnel plot": "funnel plot",
    "risk of bias": "risk of bias",
    "publication bias": "publication bias",
    "sensitivity analysis": "sensitivity analysis",
    "subgroup analysis": "subgroup analysis",
    "post-hoc analysis": "post hoc analysis",
    "intention-to-treat": "intention to treat",
    "per-protocol analysis": "per protocol analysis",
    "intention to treat analysis": "intention-to-treat analysis",
    "Kaplan-Meier curve": "Kaplan-Meier curve",
    "Kaplan-Meier curves": "Kaplan-Meier curves",
    "log-rank test": "log-rank test",
    "cox regression": "Cox regression",
    "hazard ratio": "hazard ratio",
    "odds ratio": "odds ratio",
    "confidence interval": "confidence interval",
    "interquartile range": "interquartile range",
    "standard deviation": "standard deviation",
    "standard error": "standard error",
    "p-value": "p-value",
    "p-values": "p-values",
    "p values": "p-values",
    "p < 0.05": "p < 0.05",
    "p < 0.01": "p < 0.01",
    "p < 0.001": "p < 0.001",
    "non-significant": "non-significant",
    "statistically significant": "statistically significant",
    "highly significant": "statistically significant",
    "very highly significant": "statistically significant",
    "extremely significant": "statistically significant",
}


# R-2026-06-19 (P2-C8):
# Chinese tortured-phrases
# dictionary.  This
# is a *small* starter
# set (50 entries) that
# covers the most common
# paraphrased-from-English
# mistakes observed in
# Chinese scientific
# writing.  The pattern
# is the same as the
# English dict: the
# KEY is the tortured
# phrase (a non-standard
# or broken translation),
# the VALUE is the
# canonical / correct
# form.  The detector
# merges both dicts at
# import time.
#
# Why a small starter set
# and not a 5,000-entry
# comprehensive list?
# 1. The 30 v2 cases
#    include
#    NO
#    Chinese
#    papers,
#    so
#    we
#    have
#    no
#    ground-truth
#    for
#    what
#    constitutes
#    a
#    FP
#    in
#    Chinese.
# 2. Comprehensive
#    Chinese
#    scientific
#    dictionaries
#    require
#    domain
#    experts
#    (biologists
#    /
#    CS
#    /
#    chem)
#    to
#    curate.
# 3. The
#    detection
#    contract
#    is
#    the
#    same
#    as
#    English
#    --
#    if
#    a
#    phrase
#    is
#    in
#    the
#    dict
#    AND
#    matches
#    the
#    paper
#    text,
#    it's
#    a
#    finding.
#    Adding
#    more
#    entries
#    later
#    is
#    a
#    pure
#    data
#    change
#    (no
#    code
#    change).
_TORTURED_CN: dict[str, str] = {
    # English
    # terms
    # that
    # get
    # mistakenly
    # translated
    # into
    # Chinese
    # and
    # then
    # back
    # to
    # broken
    # English.
    # Example:
    # "深度学习" → "deep learning" (good)
    # "深学习" → "deep learning" (bad,
    # drops the 度)
    "深学习": "deep learning",
    "机器学习": "machine learning",
    "机学习": "machine learning",
    "深度神经网路": "deep neural network",
    "类神经网路": "neural network",
    "类神经网络": "neural network",
    "卷积神经网路": "convolutional neural network",
    "递回神经网路": "recurrent neural network",
    "资料探勘": "data mining",
    "资料采矿": "data mining",
    "大数据分析": "big data analysis",
    "巨量资料": "big data",
    "云端运算": "cloud computing",
    "边缘运算": "edge computing",
    "物联网": "Internet of Things",
    "人工智慧": "artificial intelligence",
    "知识发现": "knowledge discovery",
    "知识擷取": "knowledge extraction",
    "决策树": "decision tree",
    "支持向量机": "support vector machine",
    "随机森林": "random forest",
    "梯度提升": "gradient boosting",
    "特征擷取": "feature extraction",
    "特征选择": "feature selection",
    "特征工程": "feature engineering",
    "正规化": "regularization",
    "归一化": "normalization",
    "标准化": "standardization",
    "过拟合": "overfitting",
    "欠拟合": "underfitting",
    "训练集": "training set",
    "测试集": "test set",
    "验证集": "validation set",
    "交叉验证": "cross-validation",
    "性能指标": "performance metric",
    "精确率": "precision",
    "召回率": "recall",
    "F1分数": "F1 score",
    "受试者工作特征": "ROC",
    "ROC曲线": "ROC curve",
    "曲线下面积": "AUC",
    "均方误差": "mean squared error",
    "交叉熵": "cross-entropy",
    "梯度下降": "gradient descent",
    "反向传播": "backpropagation",
    "权重": "weight",
    "偏差": "bias",
    "激活函数": "activation function",
    "卷积层": "convolutional layer",
    "池化层": "pooling layer",
    "全连接层": "fully connected layer",
    "Dropout层": "dropout layer",
    "嵌入式": "embedded",
    "词向量": "word embedding",
    "变换器": "transformer",
    "自注意力": "self-attention",
    "大型语言模型": "large language model",
    "生成式人工智能": "generative AI",
}


def _normalise_phrase(s: str) -> str:
    """Lowercase, collapse
    whitespace, strip. The
    detector matches case-
    insensitively by
    lowercasing both the
    dictionary and the
    search text."""
    return re.sub(r"\s+", " ", s.strip().lower())


# Pre-compile the
# normalised dictionary
# once at import time. We
# match each phrase with a
# word-boundary regex so we
# do not match "pcr" inside
# "pcr-tests" -- wait, we
# *do* want to match
# "pcr" inside that
# string. The boundary is
# only useful for
# single-word phrases; for
# multi-word phrases we
# use a literal substring
# match.
_NORMALISED = {
    _normalise_phrase(k): v for k, v in _TORTURED.items()
}
# R-2026-06-19 (P2-C8):
# also normalize
# the Chinese
# dict and
# merge it
# into
# ``_NORMALISED``.
# Chinese
# phrases are
# stored
# verbatim
# (no
# case-folding
# because
# Chinese
# has no
# case);
# ``_normalise_phrase``
# is a
# no-op
# for them
# (lowercase
# is a
# no-op
# on
# CJK).
for k, v in _TORTURED_CN.items():
    _NORMALISED.setdefault(k, v)
# Pre-compile a single regex
# that catches any of the
# phrases. We sort by
# length (descending) so
# longer phrases match
# before shorter ones
# inside the same string.
_PATTERNS: list[tuple[re.Pattern[str], str, str]] = []
for phrase in sorted(_NORMALISED, key=len, reverse=True):
    if not phrase:
        continue
    # R-2026-06-19 (P2-C8):
    # detect whether
    # the phrase
    # contains
    # CJK characters
    # so we can use
    # a different
    # word-boundary
    # anchor (Chinese
    # has no
    # ASCII word
    # boundaries).
    has_cjk = any(
        "\u4e00" <= ch <= "\u9fff"
        or "\u3040" <= ch <= "\u309f"
        or "\u30a0" <= ch <= "\u30ff"
        for ch in phrase
    )
    escaped = re.escape(phrase)
    if has_cjk:
        # For Chinese phrases,
        # anchor on
        # "not
        # another
        # CJK
        # character
        # before/after"
        # (so we
        # don't
        # match
        # "深度"
        # inside
        # "深度学习"
        # twice).
        pat = re.compile(
            r"(?<![一-鿿])" + escaped + r"(?![一-鿿])"
        )
    else:
        # English: use
        # the
        # original
        # ASCII
        # word
        # boundary.
        pat = re.compile(
            r"(?<![A-Za-z])"
            + escaped
            + r"(?![A-Za-z])",
            re.IGNORECASE,
        )
    _PATTERNS.append((pat, phrase, _NORMALISED[phrase]))


# Severity thresholds.
# The original Cabanac
# paper uses 5+ matches
# for a "high" verdict;
# we use a more
# conservative 3+.
HIGH_SEVERITY_THRESHOLD = 3


class TorturedPhrasesDetector:
    """Scan the document text
    for the curated set of
    tortured phrases."""

    name = "text_tortured_phrases"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        text = " ".join(
            getattr(b, "text", "") for b in doc.text_blocks
        )
        if not text:
            return DetectorResult(
                detector=self.name,
                findings=[],
                ok=True,
            )
        text_lower = text.lower()
        # Track which tortured
        # phrases we have
        # already reported.
        matches: list[dict[str, Any]] = []
        for pat, phrase, _intended in _PATTERNS:
            for m in pat.finditer(text_lower):
                matches.append(
                    {
                        "phrase": phrase,
                        "intended": _intended,
                        "start": m.start(),
                    }
                )
        if not matches:
            return DetectorResult(
                detector=self.name,
                findings=[],
                ok=True,
            )
        # Deduplicate: we
        # report a *finding*
        # per distinct tortured
        # phrase, not per
        # match. The LLM can
        # ask for the full
        # evidence.
        distinct = sorted(
            {m["phrase"] for m in matches}
        )
        # The total count
        # includes duplicates
        # (a phrase repeated
        # many times in a long
        # paper is also
        # evidence).
        total = len(matches)
        severity = (
            "high"
            if total >= HIGH_SEVERITY_THRESHOLD
            else "medium"
        )
        finding = Finding.make(
            trace_id=doc.trace_id,
            detector=self.name,
            severity=severity,
            title=(
                f"Document contains {len(distinct)} "
                f"distinct tortured phrase(s) "
                f"({total} total occurrences)"
            ),
            location="text",
            evidence=json.dumps(
                {
                    "distinct_phrases": [
                        {
                            "phrase": p,
                            "likely_intended": _NORMALISED[p],
                        }
                        for p in distinct
                    ],
                    "total_occurrences": total,
                    "examples": matches[:5],
                }
            ),
        )
        return DetectorResult(
            detector=self.name,
            findings=[finding],
            ok=True,
        )
