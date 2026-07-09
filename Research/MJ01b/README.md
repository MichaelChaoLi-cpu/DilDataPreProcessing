# MJ01b — WASH 改善的因果效应对儿童发育迟缓与消瘦的影响

## 研究问题

改善饮用水供给与卫生设施是否能降低儿童发育迟缓（HAZ < −2）和消瘦（WHZ < −2）？
效应是否经由腹泻/肠道感染传导？

## 识别策略

利用 2000–2023 年各国/地区 WASH 覆盖率的持续扩张，以 **cluster 级改善饮水/卫生设施覆盖率**（`cluster_water_coverage`、`cluster_sanit_coverage`）作为核心处理变量，采用 saturation/phase-in 设计（类 Duflo 式基础设施推广研究）。cluster 覆盖率通过跨 cluster 的逐年扩张提供准随机变异，控制家庭自选择进入 WASH 的内生性。

腹泻（`diarrhea`）作为中介变量，可在机制检验中分解总效应的经由路径：

```
WASH → 腹泻减少 → 营养吸收改善 → HAZ / WHZ 提升
```

## 数据

### 来源

MICS（Multiple Indicator Cluster Surveys）MICS2–MICS6，1999–2023 年，覆盖 100+ 国家。

- **CH 模块**（`final_CH_MICS`）：儿童结局、患病、基础背景变量
- **HH 模块**（`final_HH_MICS`）：WASH 设施变量

合并键：`(dataset_name, cluster_number, household_number)`

### 输出

`data/mj01b_analysis.parquet` — **1,684,203 行 × 29 列**

HH 模块匹配率 74.8%（1,259,020 行）；未匹配主要来自早期 MICS2 数据集无对应 HH 问卷，或 cluster/household 编码不一致。

## 变量字典

### 标识符

| 变量 | 说明 | 覆盖率 |
|------|------|--------|
| `dataset_name` | 原始数据集名称 | 100% |
| `country` | 国家名（从 dataset_name 解析） | 100% |
| `survey_year` | 调查年份（正则解析，fallback 用 MICS 轮次推算） | 100% |
| `cluster_number` | 抽样 cluster 编号 | 95.0% |
| `household_number` | 家庭编号 | 98.7% |
| `child_line_number` | 儿童行号 | 98.4% |

### 结局变量

| 变量 | 说明 | 覆盖率 |
|------|------|--------|
| `haz_clean` | 年龄别身高 Z-score；过滤 flag≠0 及超出 ±6 范围的值 | 56.6% |
| `whz_clean` | 身高别体重 Z-score；过滤 flag≠0 及超出 ±6 范围的值 | 57.5% |
| `stunting` | 发育迟缓：`haz_clean < −2`（0/1）⚠️ 见注1 | — |
| `wasting` | 消瘦：`whz_clean < −2`（0/1）⚠️ 见注1 | — |

### 中介 / 机制变量

| 变量 | 说明 | 覆盖率 |
|------|------|--------|
| `diarrhea` | 过去两周腹泻（0=No, 1=Yes，已统一编码）| 80.6% |
| `fever_last_2_weeks` | 过去两周发烧（1=Yes, 2=No）⚠️ 见注2 | 66.7% |

### WASH 处理变量（来自 HH 模块）

| 变量 | 说明 | 覆盖率 |
|------|------|--------|
| `improved_water` | JMP 改善饮水（0/1）：管道/管井/受保护水源/雨水/瓶装水 | 74.8% |
| `improved_sanitation` | JMP 改善卫生设施且**非共用**（0/1） | 84.9% |
| `handwashing_soap_water` | 洗手处同时有肥皂+水（0/1）| 52.4% |
| `basic_water_access` | 改善水源且取水来回时间 ≤30 分钟（0/1）| 76.2% |
| `water_on_premises` | 水源在住所内（取水时间=0）（0/1）| 92.8% |
| `water_time_min` | 来回取水时间（分钟）| 33.4% |
| `treat_water_to_make_safer` | 对水进行净化处理（0/1）| 60.1% |
| `cluster_water_coverage` | **Cluster 级改善饮水覆盖率均值 ← Saturation IV** | 77.2% |
| `cluster_sanit_coverage` | Cluster 级改善卫生设施覆盖率均值 | 85.8% |

### 控制变量

| 变量 | 说明 | 覆盖率 |
|------|------|--------|
| `child_age_years` | 儿童年龄（年，0–4；P07 修复，全数据集可用）| 97.2% |
| `child_age_months` | 儿童月龄（0–59；仅月编码数据集，42/251 个）| 16.6% |
| `sex_of_child` | 性别（1=男, 2=女）⚠️ 见注2 | 98.9% |
| `area` | 城乡（1=城市, 2=农村）⚠️ 见注3 | 80.0% |
| `region` | 地区/省级行政区 | 54.8% |
| `wealth_index_quintile` | 财富五分位（1–5）⚠️ 见注2 | 79.4% |
| `mother_education_harmonized` | 母亲受教育程度 ISCED 四分类（0=无, 1=小学, 2=中学, 3=高等；P03 校正）| 89.6% |
| `child_sample_weight` | 抽样权重 | 55.0% |

## 数据质量说明

### 注1 — stunting / wasting 的 NaN 传播问题

旧版 pandas 中 `pd.Series(NaN) < -2` 返回 `False` 而非 `NA`，导致 `stunting`/`wasting` 对 `haz_clean`/`whz_clean` 缺失行误标为 0（未矮化）。**分析时必须加 mask**：

```python
df_valid = df[df["haz_clean"].notna()]
stunting_rate = df_valid["stunting"].mean()
```

### 注2 — Sentinel 值未清除

以下变量含异常编码，分析前须过滤：

```python
df = df[df["sex_of_child"].isin([1, 2])]
df = df[df["wealth_index_quintile"].between(1, 5)]
df = df[df["fever_last_2_weeks"].isin([1, 2])]  # 最大值=100，sentinel 未清
```

### 注3 — area 编码跨数据集不一致

大多数数据集：1=城市，2=农村；少数数据集使用其他编码（最大值=17）。直接用于跨国回归前需验证各数据集标签。

### 注4 — improved_sanitation 定义严格

应用了 JMP 完整定义：**改善设施类型 + 非共用**，均值覆盖率 13.5%（偏低）。若仅按设施类型分类（不管是否共用），覆盖率会显著提升。两种定义可作为稳健性检验对比。

### 注5 — diarrhea 跨轮次编码差异

MICS2 时代数据集（31 个，按 dataset_name 正则识别）使用 0=No/1=Yes；其余数据集使用 1=Yes/2=No。`pull_data.py` 已统一转换为 0/1。

## 复现

```bash
cd /Users/lichao/Development/DilDataPreProcessing
source MasterDataAlignmentWithMike/.venv/bin/activate
python Research/MJ01b/pull_data.py
# 输出: Research/MJ01b/data/mj01b_analysis.parquet
```

**前置条件**：PostgreSQL `localhost:5432/mda` 已应用 P03（`mother_education_harmonized`）和 P07（`child_age_years`）patch，详见 `DATA_PATCH_LOG.md`。
