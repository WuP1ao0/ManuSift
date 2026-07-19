# 100 种学术造假/诚信异常手法与检测措施

> **来源定位**：以 [PubPeer](https://pubpeer.com) 常见讨论为中心，结合 Bik et al. 图像分类、COPE/期刊图像规范、统计取证（GRIM 等）、论文工厂文献与 Source Data 案例。  
> **性质**：筛查线索清单，**不是**法律或期刊对不端的最终认定。许多“手法”亦可能是无心失误。  
> **编制日期**：2026-07

---

## A. 图像：整体复用（Bik Category I 及变体）

| # | 手法 | 典型场景 | 发现/检测措施 |
|---|------|----------|----------------|
| 1 | 简单整图复制 | 同一 blot/显微图用于不同条件 | 并排对比；perceptual hash / SSIM；ImageTwin、Proofig |
| 2 | 同图多 panel 复用 | 一图拆成 a/b 标不同处理 | 面板级哈希与几何配准 |
| 3 | 跨 figure 整图复用 | Fig.2 与 Fig.5 同一图 | 全 PDF 抽图 + 全对全相似度 |
| 4 | 跨论文图像复用 | 同实验室多文同一图 | 外部图库比对（Imagetwin 1.6 亿级） |
| 5 | Loading control 复用 | β-actin 等多实验共用 | 专门比对 loading 条带 ROI |
| 6 | 同一 control 泳道重复标注 | 对照泳道复制后改标签 | 泳道分割 + 条带指纹 |
| 7 | 补充材料与主文图重复却不同结论 | SI vs 主文 | SI 与主文联合索引 |
| 8 | 封面/示意图冒充数据图 | 装饰图当结果 | 元数据+是否可计量检查 |
| 9 | 不同放大倍率声称同一视野 | 缩放后当不同实验 | 多尺度匹配 |
| 10 | 灰度/彩色转换掩盖同一图 | 改色道当新实验 | 通道无关特征（SIFT/ORB） |

## B. 图像：重定位与几何变换（Bik Category II）

| # | 手法 | 典型场景 | 发现/检测措施 |
|---|------|----------|----------------|
| 11 | 水平/垂直翻转复用 | 镜像 blot 或显微 | 翻转增强匹配；keypoint 镜像检验 |
| 12 | 旋转 90°/180° 复用 | 旋转后当新图 | 多角度模板匹配 |
| 13 | 裁剪不同 ROI | 同玻片不同裁切 | 大图滑动窗口 / 重叠区域检测 |
| 14 | 缩放/拉伸后复用 | 各向异性拉伸 | 仿射归一化后比对 |
| 15 | 亮度对比度调整掩盖 | “美化”后重复 | 归一化直方图后再比 |
| 16 | 颜色映射/伪彩改变 | 假彩后当通道不同 | 去伪彩/亮度通道比对 |
| 17 | 重叠视野 partial overlap | 同视野平移 | 相位相关 / 模板滑动 |
| 18 | 拼接图中重复瓷砖 | 全景图内部重复 | 块哈希 / copy-move |
| 19 | 显微镜“平移后重复拍摄”造多条件 | 实为同一玻片 | 背景噪点指纹 |
| 20 | 不同曝光当不同样品 | 曝光变化 | 曝光归一化 + 结构相似度 |

## C. 图像：篡改与局部克隆（Bik Category III）

| # | 手法 | 典型场景 | 发现/检测措施 |
|---|------|----------|----------------|
| 21 | Copy-move 克隆条带 | 同一 blot 内复制条带 | SIFT/copy-move；ELA；背景连续性 |
| 22 | Clone-stamp 抹去条带 | 消除不利条带 | 纹理不连续；噪声层突变 |
| 23 | 泳道垂直拼接 | 不同胶条硬拼 | 垂直接缝、背景梯度断裂 |
| 24 | 水平拼接不同曝光 | 左右曝光不一致 | 块噪声方差差 |
| 25 | 选择性擦除背景 | “干净”背景 | 局部噪声平坦度异常 |
| 26 | 条带锐化/模糊不一致 | 局部锐化 | 频域能量不均 |
| 27 | 对比度局部增强（beautification） | 只增强某区域 | 分区直方图；COPE 关注点 |
| 28 | 添加虚假条带 | 绘制或粘贴 | 边缘锐利度与胶噪声不匹配 |
| 29 | 删除不利泳道不声明 | 裁掉泳道 | 与 raw 胶图比对；接缝 |
| 30 | 不均一增强（non-uniform enhancement） | ORI 关注 | 分区 ELA / 亮度曲线 |
| 31 | 显微视野内细胞克隆 | 同一细胞贴多次 | 小块 copy-move |
| 32 | 菌落/斑点复制 | 平板照片 | 斑点形状模板重复 |
| 33 | FACS 图点云复制/改比例 | 流式图 | 点模式重复；坐标统计 |
| 34 | 直方图柱高手改 | 流式/柱状 | 与 source data 不一致 |
| 35 | IHC/病理切片“补丁” | 局部贴补 | 边缘光晕、分辨率突变 |
| 36 | TEM/SEM 图美化擦除 | 电镜伪影擦除 | 背景频谱 |
| 37 | 凝胶分子量标记不一致 | 拼接后 marker 错乱 | 几何对齐检查 |
| 38 | 多通道荧光通道错配拼接 | 通道来自不同实验 | 通道间配准残差 |
| 39 | AI 生成显微/blot 图 | 合成图 | AI-image 检测器；异常纹理 |
| 40 | 分辨率混贴（高低清拼接） | 局部更糊/更清 | 局部锐度图 |

## D. Source Data / Excel 数值造数

| # | 手法 | 典型场景 | 发现/检测措施 |
|---|------|----------|----------------|
| 41 | 实验组数值整列复制 | A 组=B 组 | 列对完全相等；fixed_offset=0 |
| 42 | 固定差值造组 | A=B+常数 | fixed_offset；散点完美直线 |
| 43 | 固定比例造组 | A=k·B | 比值方差≈0 |
| 44 | 部分行固定差 | 多数行同 offset | partial_fixed_offset |
| 45 | 平行重复（n=3）完全相同 | 零生物变异 | identical_parallel_replicates |
| 46 | 小数点后两位跨组全同 | “Excel 敲的数” | matching_decimal_tails |
| 47 | 整数部分改、小数尾保留 | 12.37→13.37 | integer-shift decimal-tail reuse |
| 48 | 多 cell 连续块粘贴 | 一串数再出现 | sequence_reuse（滑动窗口） |
| 49 | 跨 sheet 整表粘贴 | SI 多表相同 | 跨表 repeated values |
| 50 | 重复行大块粘贴 | 表格行复制 | table_duplicate_row |
| 51 | 近重复行（改一两个数） | 伪独立样本 | near_duplicate_row |
| 52 | 末位数字偏向 0/5 | 编造圆整 | terminal digit / round_bias |
| 53 | 末两位过度集中 | 同一 xx 反复 | last-two-digit pair test |
| 54 | Benford 律严重偏离 | 首位数字异常 | Benford χ² |
| 55 | 等差数列填数 | 剂量完美等差 | arithmetic_progression |
| 56 | 标准差全相同 | 假 SEM/SD | constant SD 列检测 |
| 57 | 报告 SD=0 却 n>1 | 不可能重复 | zero SD entries |
| 58 | 过大/过小误差棒 | 图与 n 不匹配 | 效应量与 SE 合理性 |
| 59 | 图数字与 Source Data 不符 | 美化后的图 | source_data_consistency |
| 60 | 只公开部分源数据 | 选择性公开 | data availability 检查 |
| 61 | 用 0 填缺失当真实 0 | 宽表填零 | 零膨胀 + 与 n 对照 |
| 62 | 跨图 Source Data 同一指纹 | 多图同手法 | excel_fabrication_span |
| 63 | 相关列可加减互推 | C=A+B | three-column additive |
| 64 | 镜面对称列 | A+B=常数 | mirror_symmetry |
| 65 | 重复测量伪造独立 n | 伪重复 | 方法学 n 与表列数核对 |

## E. 统计与报告造假/扭曲

| # | 手法 | 典型场景 | 发现/检测措施 |
|---|------|----------|----------------|
| 66 | 捏造原始数据点 | 完全虚构 | 末端数字均匀性；分布检验 |
| 67 | p-hacking / 可选停止 | p 刚好 <0.05 | p-curve；p 值堆积在 0.04–0.05 |
| 68 | HARKing | 事后假设装事先 | 预注册对照；叙事时间线 |
| 69 | 选择性报告结局 | 只报显著终点 | 结局转换检测；试验注册比对 |
| 70 | 剔除不利离群不声明 | 删点 | 敏感性分析；原始 vs 发表 n |
| 71 | 不可能的均值（整数数据） | 均值与 n 不兼容 | **GRIM** |
| 72 | 不可能的 SD | SD 与均值/n 不兼容 | **GRIMMER** |
| 73 | 从摘要反推不可能样本 | 摘要数字 | **SPRITE** |
| 74 | 错报自由度 / 检验统计量 | t/F 与 df 矛盾 | 统计量反算 |
| 75 | 百分比与计数不兼容 | 12.3% of n=10 | percent-consistency |
| 76 | 多重比较不校正却宣称 | 假阳性膨胀 | 方法学审查 |
| 77 | 基线不平衡却随机化声称 | 组间基线 | 基线表检验 |
| 78 | 过大效应量不合理 | 小样本超大 d | 极端效应量筛查 |
| 79 | 相关矩阵非正定 | 编造相关 | 矩阵特征值检查 |
| 80 | 伪造问卷/量表得分 | 心理测量 | 末端数字；反应时模式 |

## F. 文本、引用与论文工厂

| # | 手法 | 典型场景 | 发现/检测措施 |
|---|------|----------|----------------|
| 81 | 文本剽窃 / 改写 | 大段复制 | 查重；相似度 |
| 82 | Tortured phrases | 机器改写术语 | tortured-phrase 词典 |
| 83 | 模板化摘要/方法 | 工厂稿 | 模板指纹；n-gram |
| 84 | 引用卡特尔 / 强迫引用 | 互引灌水 | 引用网络异常 |
| 85 | 引用已撤稿而不披露 | 不实支撑 | Crossref/Retraction Watch |
| 86 | 虚假参考文献 | DOI/题名不存在 | Crossref 校验 |
| 87 | 作者邮箱免费邮箱扎堆 | 工厂特征 | free-mail + 单位堆叠启发式 |
| 88 | 影子作者 / 卖挂名 | 挂名 | 贡献声明异常；通讯模式 |
| 89 | 同行评审操纵 | 假审稿人 | 编辑部流程；邮箱域 |
| 90 | 一稿多投 / 重复发表 | 同数据多刊 | 标题/摘要/图库查重 |
| 91 | 翻译洗稿 | 跨语言洗稿 | 多语查重 |
| 92 | AI 代写不披露 | LLM 痕迹 | AI 文本检测（慎用）+ 披露政策 |

## G. 方法、伦理与元数据

| # | 手法 | 典型场景 | 发现/检测措施 |
|---|------|----------|----------------|
| 93 | 虚构伦理批号 | 伦理号造假 | 机构核查；格式启发式 |
| 94 | 试剂/仪器型号不存在 | 方法造假 | 目录核对 |
| 95 | 时间线不可能 | 实验周期 vs 投稿 | 日期逻辑 |
| 96 | 样品 n 前后矛盾 | 方法 n≠图表 n | 全文 n 抽取一致性 |
| 97 | PDF 元数据异常 / 嵌入文件 | 版本混乱 | pdf_metadata |
| 98 | 声称有 SI 却无文件 | 材料缺失 | supplementary 检测 |
| 99 | 图像 EXIF/压缩历史异常 | 多次导出编辑 | 文件取证 |
| 100 | 选择性公开 raw 仅“好看”批次 | 数据可用性作秀 | 可用性声明 vs 实际可复现 |

---

## 检测措施速查（工具层）

| 层次 | 代表工具/方法 |
|------|----------------|
| 人工 | PubPeer 贴图框选；翻转/反相/叠图；打开 Source Data 散点 |
| 图像商业 | ImageTwin、Proofig、ORI 指南工作流 |
| 开源/启发式 | pHash/aHash、SIFT copy-move、ELA、SSIM、面板分割 |
| 数值 | 列相关/固定差、序列窗口、Benford、末端数字、GRIM/GRIMMER |
| 文本/引用 | 查重、tortured phrases、Crossref、撤稿库 |
| 统计审稿 | p-curve、效应量、自由度反算 |

### ManuSift 已覆盖的重点（不完全）

- 图像：`image_dup`、`panel_dup`、`image_forensics`、`image_sift_copymove`、page raster  
- 数值：`table_relationships`（fixed/partial offset、decimal tails、sequence_reuse、identical_parallel_replicates、excel_fabrication_span）、`table_round_bias`、`table_benford`、duplicate rows  
- 统计：`stat_grim`、`stat_pvalue`、`stat_percent`  
- 文本：`text_tortured_phrases`、`paper_mill_*`、`cited_retraction`  
- 细节映射见：`docs/pubpeer_integrity_patterns.md`

### 明确缺口（相对 PubPeer 顶级人工）

1. 跨全库图像抄袭（需外部亿级索引）  
2. Western blot **泳道级专用**拼接模型（通用 forensics 有限）  
3. 流式点云/门控操纵专用检测  
4. 与试验注册/伦理系统自动联查  
5. 跨语言洗稿与审稿操纵网络

---

## 主要参考文献（公开）

1. Bik EM, Casadevall A, Fang FC. *The Prevalence of Inappropriate Image Duplication in Biomedical Research Publications.* mBio 2016. Category I–III.  
2. PubPeer — 发表后评议与图像/数据问题讨论平台.  
3. COPE / 期刊图像完整性实践（beautification、non-uniform enhancement 等）.  
4. Brown & Heathers — GRIM；Anaya — GRIMMER；SPRITE.  
5. Beber & Scacco 等 — 末端数字与选举/数据取证传统（迁移到科学数据）.  
6. Cabanac 等 — tortured phrases / 论文工厂信号.  
7. 出版商图像预筛试点（如 ASM + Imagetwin）.  
8. 统计取证综述：Crone et al. 等关于 data fabrication 检测工具的评论.

---

## 使用建议

1. **先 Source Data，后图像**：许多高影响案例先在 Excel 暴露。  
2. **先可自动化高召回，再人工低误报**：哈希/固定差/序列复用 → 叠图与实验室记录。  
3. **区分失误与故意**：Cat I 更常为失误；Cat III、系统性 Excel 指纹、跨文复用更需升级调查。  
4. **所有自动结果仅作线索**，最终以机构/期刊调查为准。
