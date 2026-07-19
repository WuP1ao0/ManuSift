# PubPeer 100 手法 × ManuSift 覆盖矩阵

> 对照 `docs/pubpeer_100_fraud_methods.md` 与当前检测器/管线。  
> **状态**：`full` 强覆盖 · `partial` 启发式/间接 · `gap` 未覆盖或依赖外部系统  
> **日期**：2026-07-19

## 汇总

| 状态 | 条数（约） | 占比 |
|------|-----------|------|
| full | 39 | 39% |
| partial | 33 | 33% |
| gap | 28 | 28% |

**结论**：Source Data / 统计 / 文本工厂主路径已强；图像 Cat III 专用、跨库盗图、流式、伦理/注册外部联查仍是主缺口。

## 矩阵（#1–100）

| # | 手法摘要 | 状态 | ManuSift 入口 |
|---|----------|------|----------------|
| 1 | 简单整图复制 | full | `image_dup`, hashes, `page_raster_dup` |
| 2 | 同图多 panel 复用 | full | `panel_dup`, `panel_duplicate` |
| 3 | 跨 figure 整图 | full | `image_dup` 全对全 |
| 4 | 跨论文盗图 | partial | 本地 `cross_paper_image` 索引（非商业全库） |
| 5 | Loading control 复用 | full | `image_dup` pass `loading_control` 底条 ROI aHash |
| 6 | control 泳道重复标注 | partial | 跨图底条有；同图泳道标注语义仍弱 |
| 7 | SI vs 主文图 | full | materials SI PDF 抽图合并进同一 `doc.images` |
| 8 | 示意图冒充数据 | **gap** | 无语义分类 |
| 9 | 不同放大倍率同视野 | partial | 多尺度弱 |
| 10 | 灰度/彩色转换 | partial | SIFT/哈希部分 |
| 11 | 翻转复用 | full | `image_dup` geometric pass (hflip/vflip) |
| 12 | 旋转复用 | full | `image_dup` geometric pass (rot90/180/270) |
| 13 | 裁剪 ROI | partial | tile / forensics |
| 14 | 缩放拉伸 | partial | 归一化有限 |
| 15 | 亮度对比掩盖 | partial | 归一化后比 |
| 16 | 伪彩改变 | partial | 亮度通道 |
| 17 | 视野平移重叠 | partial | texture / SIFT |
| 18 | 拼接瓷砖重复 | partial | copy-move |
| 19 | 同玻片多条件 | partial | 噪声指纹弱 |
| 20 | 曝光差异 | partial | 有限 |
| 21 | Copy-move 条带 | full | `image_sift_copymove`, forensics |
| 22 | Clone-stamp 抹除 | partial | noise / forensics |
| 23 | 泳道垂直拼接 | partial→加强 | `image_forensics` `vertical_gel_seam` 启发式 |
| 24 | 水平拼接曝光 | partial | noise inconsistency |
| 25 | 选择性擦除背景 | partial | 噪声平坦度 |
| 26 | 局部锐化不一致 | partial | 频域弱 |
| 27 | 局部 beautification | partial | ELA 类 |
| 28 | 添加虚假条带 | **gap** | 语义难 |
| 29 | 删泳道不声明 | **gap** | 需 raw 胶 |
| 30 | 不均一增强 | partial | forensics |
| 31 | 细胞内克隆 | partial | copy-move 小块 |
| 32 | 菌落复制 | partial | 同上 |
| 33 | FACS 点云操纵 | **gap** | 无流式专用 |
| 34 | 直方图手改 | partial | 图-表一致性 |
| 35 | IHC 补丁 | partial | 边缘/分辨率 |
| 36 | TEM 美化 | partial | 频谱弱 |
| 37 | marker 错乱 | **gap** | |
| 38 | 荧光通道错配 | **gap** | |
| 39 | AI 生成图 | partial | `ai_generated_figure`（弱/fixture） |
| 40 | 分辨率混贴 | partial | 局部锐度弱 |
| 41 | 组间整列复制 | full | `fixed_offset`=0, repeated |
| 42 | 固定差值 | full | `fixed_offset` / partial |
| 43 | 固定比例 | full | **`fixed_ratio`（本轮）** |
| 44 | 部分固定差 | full | `partial_fixed_offset` |
| 45 | 平行重复全同 | full | `identical_parallel_replicates` |
| 46 | 小数尾全同 | full | matching decimal tails |
| 47 | 整数移 + 尾同 | full | integer-shift tail |
| 48 | 连续块粘贴 | full | `sequence_reuse` |
| 49 | 跨 sheet 粘贴 | full | cross_table_* |
| 50 | 重复行 | full | `table_duplicate_row` |
| 51 | 近重复行 | full | `table_near_duplicate_row` |
| 52 | 末位 0/5 偏 | full | `table_round_bias` |
| 53 | 末两位集中 | full | terminal pair |
| 54 | Benford | full | `table_benford` |
| 55 | 等差填数 | full | arithmetic_progression |
| 56 | SD 全同 | full | constant SD |
| 57 | SD=0 | full | zero SD |
| 58 | 误差棒不合理 | partial | 启发式弱 |
| 59 | 图≠Source Data | full | `source_data_consistency` |
| 60 | 选择性公开数据 | partial | DAS 措辞+链接 |
| 61 | 0 填缺失 | partial | 零膨胀弱 |
| 62 | 多图同指纹 | full | `excel_fabrication_span` |
| 63 | 列加减互推 | full | three-column ± |
| 64 | 镜面对称列 | full | mirror_symmetry |
| 65 | 伪独立 n | partial | 需方法-表 n 对齐 |
| 66 | 捏造原始点 | partial | 末端数字等 |
| 67 | p-hacking | partial→加强 | `stat_pvalue_pileup`（近 .05 堆积；非完整 p-curve） |
| 68 | HARKing | **gap** | 需预注册 |
| 69 | 选择性结局 | **gap** | 需试验注册 |
| 70 | 删离群不声明 | **gap** | 需 raw |
| 71 | 不可能均值 | full | GRIM |
| 72 | 不可能 SD | full | GRIMMER 路径 + sprite-lite max SD |
| 73 | SPRITE 反推 | partial | `stat_sprite` lite（默认关；非全枚举） |
| 74 | 统计量/df 矛盾 | partial | t/p 列一致性 |
| 75 | 百分比与 n | full | `stat_percent` |
| 76 | 多重比较 | **gap** | 方法学 |
| 77 | 基线不平衡 | **gap** | |
| 78 | 极端效应量 | partial | 弱 |
| 79 | 相关矩阵非正定 | full | `stat_corr_psd` |
| 80 | 伪造问卷 | partial | 末端数字 |
| 81 | 文本剽窃 | partial | 无跨库查重 |
| 82 | Tortured phrases | full | `text_tortured_phrases` |
| 83 | 模板方法 | partial | `paper_mill_template` |
| 84 | 引用卡特尔 | partial | `citation_network` |
| 85 | 引撤稿 | full | `cited_retraction` |
| 86 | 虚假参考文献 | partial | Crossref 存在性 |
| 87 | free-mail 作者 | full | paper_mill_authorship |
| 88 | 卖挂名 | partial | 启发式 |
| 89 | 审稿操纵 | **gap** | 编辑部数据 |
| 90 | 重复发表 | **gap** | 跨论文 |
| 91 | 翻译洗稿 | **gap** | 多语 |
| 92 | AI 代写 | partial | 文本启发式弱 |
| 93 | 假伦理号 | **gap** | 无机构库 |
| 94 | 假试剂型号 | **gap** | |
| 95 | 时间线不可能 | **gap** | |
| 96 | n 前后矛盾 | partial | 弱抽取 |
| 97 | PDF 元数据 | full | pdf_metadata |
| 98 | 声称 SI 无文件 | full | supplementary |
| 99 | 压缩/编辑历史 | partial | 有限 |
| 100 | 选择性 raw | partial | DAS |

## 优先级（路线图用）

| 优先级 | 缺口簇 | 对应 # |
|--------|--------|--------|
| **P0** | Source Data 比例关系、块粘贴、平行全同（已做/本轮补完） | 43–48, 62 |
| **P1** | 图像 flip/rotate；gel 垂直接缝；loading-control ROI（已做） | 11–12, 23, 5–6 |
| **P2** | 同图泳道级 / 标注语义（#6 残差） | 6 |
| **P3** | SPRITE、p-curve、相关矩阵（P6.2 已交付） | 67, 73, 79 |
| **P4** | 跨论文图库 / 重复发表 | 4, 90 |
| **P5** | FACS、伦理/注册/试剂外部联查 | 33, 68–69, 93–95 |
