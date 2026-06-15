# DilDataPreProcessing

> For English version, see [README.md](README.md)

本仓库对 UNICEF 多指标类集调查（MICS）的微观调查数据进行预处理，生成适合分析的标准化数据集。目标是将每轮调查、每个国家的每道问题映射到一个稳定的标准变量名，实现跨调查的横向可比。

---

## 第一章 — MICS 家庭问卷（MICS-HH）

### 概述

MICS 家庭问卷（`hh.sav`）涵盖六轮调查（MICS2–MICS6）、100 余个国家。同一个概念在不同国家和轮次中可能出现几十种不同的列名，或以不同语言记录。本模块生成一个合并后的单一数据集，每一列对应一个标准变量。

**当前规模**

| 项目 | 数量 |
|------|------|
| 已处理数据集 | 255 |
| 标准变量数 | 298 |
| 对齐条目数 | 25,748 |
| 合并数据集行数 | 2,774,775 |

---

### 处理流程

```
原始 .sav 文件
      │
      ▼
1. extract_hh_columns.py        提取列元数据
      │
      ▼
2. translate_hh_yaml.py         将非英文标签翻译为英文  [LLM]
      │
      ▼
3. canonicalize_hh_columns.py   用规则引擎分配标准变量名  [规则]
      │
      ▼
4. dedup_hh_columns_v2.py       标记同一问卷内的重复列
      │
      ▼
5. align_hh_columns_v2.py       跨数据集对齐标准变量
      │
      ▼
6. analyze_unmapped_hh_columns.py   聚类未映射变量（可选）
      │
      ▼
7. merge_hh_to_parquet.py       将所有 .sav 合并为单一 parquet
      │
      ▼
8. upload_hh_to_postgres.py     上传至 PostgreSQL
```

---

### 各步骤说明

#### 第1步 — 提取列元数据
**脚本：** `MICS-HH/src/extract_hh_columns.py`  
**输入：** `{RAW_DATA_DIR}/{dataset}/hh.sav`  
**输出：** `MICS-HH/data/HH/raw/{dataset}/hh.yaml`

用 `pyreadstat` 读取每个 `hh.sav`，将列名、列标签、值标签和变量类型写入 YAML 文件。

#### 第2步 — 翻译标签
**脚本：** `MICS-HH/src/translate_hh_yaml.py`  
**输入：** `data/HH/raw/{dataset}/hh.yaml`  
**输出：** `data/HH/translate/{dataset}/hh.yaml`、`data/HH/translate_embedding/{dataset}/hh.csv`

调用 LLM 将非英文列标签翻译为英文，同时生成用于后续聚类的嵌入向量。已是英文的数据集直接透传。

#### 第3步 — 标准化
**脚本：** `MICS-HH/src/canonicalize_hh_columns.py`  
**规则引擎：** `MICS-HH/src/canonical_hh.py`  
**输入：** `data/HH/translate/{dataset}/hh.yaml`  
**输出：** `data/HH/canonical/{dataset}/hh.yaml`

用确定性规则为每列分配 `canonical_varname`。主要规则：
- 家庭问卷中的独立 `Age`/`Sex` 列映射为 `age_of_household_head` / `sex_of_household_head`。
- 完整日期列可拆分为派生变量 `interview_year`、`interview_month`、`interview_day`。
- 复合资产标签（如 `washing machine / dryer`）不合并为更简单的名称。
- 纯选项标签（`other`、`dk`、`none`）不分配标准变量名。

#### 第4步 — 问卷内去重
**脚本：** `MICS-HH/src/dedup_hh_columns_v2.py`  
**输入：** `data/HH/canonical/{dataset}/hh.yaml`  
**输出：** `data/HH/questionnaire_dedup_v2/{dataset}/dup.yaml`

识别同一问卷内映射到同一标准变量的重复列，标记 `primary_source` 和候选来源。不删除原始列，仅记录决策供下游步骤使用。

#### 第5步 — 跨数据集对齐
**脚本：** `MICS-HH/src/align_hh_columns_v2.py`  
**输入：** `data/HH/canonical/{dataset}/hh.yaml`  
**输出：** `data/HH/alignment_v2.yaml`、`data/HH/alignment_summary_v2.csv`

将所有数据集的标准变量映射汇总为一个跨问卷对齐字典。每个标准变量列出所有贡献该变量的（数据集，原始列名）对。

#### 第6步 — 检查未映射变量（可选）
**脚本：** `MICS-HH/src/analyze_unmapped_hh_columns.py`  
**输出：** `data/HH/unmapped_clusters.csv`、`data/HH/unmapped_cluster_examples.yaml`

对未分配标准变量的翻译标签用嵌入向量进行聚类，不调用 LLM。用于指导新规则的制定。

#### 第7步 — 合并为 parquet
**脚本：** `MICS-HH/src/merge_hh_to_parquet.py`  
**输入：** 原始 `.sav` + `alignment_v2.yaml` + `questionnaire_dedup_v2/`  
**输出：** `data/HH/processed_data/hh_merged.parquet`

读取每个 `hh.sav`，将列重命名为标准变量名，合并重复列（优先使用 primary source，NaN 由备用列填充），应用日期派生函数，最后纵向拼接所有数据集。第一列为 `dataset_name`。

#### 第8步 — 上传至 PostgreSQL
**脚本：** `MICS-HH/src/upload_hh_to_postgres.py`  
**数据库：** `localhost:5432 / mda`

| 表名 | 说明 |
|------|------|
| `final_MICS2MICS6` | 合并后的家庭数据（2,774,775 行 × 299 列） |
| `ind_que_MICSMICS` | 变量索引：标准名、数据集、原始列名、英文标签 |

---

### 运行命令

```bash
# 完整流程（从仓库根目录执行）
uv run MICS-HH/src/extract_hh_columns.py
uv run MICS-HH/src/translate_hh_yaml.py
uv run MICS-HH/src/canonicalize_hh_columns.py
uv run MICS-HH/src/dedup_hh_columns_v2.py
uv run MICS-HH/src/align_hh_columns_v2.py
uv run MICS-HH/src/merge_hh_to_parquet.py
uv run MICS-HH/src/upload_hh_to_postgres.py
```

---

### 数据流向

```
RAW_DATA_DIR/                        （外部存储，在 .env 中配置）
  {dataset}/hh.sav

MICS-HH/data/HH/
  raw/{dataset}/hh.yaml              列元数据
  translate/{dataset}/hh.yaml        英文翻译后的标签
  translate_embedding/{dataset}/     聚类用嵌入向量
  canonical/{dataset}/hh.yaml        标准变量分配结果
  questionnaire_dedup_v2/{dataset}/  去重决策
  alignment_v2.yaml                  跨数据集对齐字典
  alignment_summary_v2.csv           汇总统计
  unmapped_clusters.csv              未映射变量聚类结果
  processed_data/hh_merged.parquet   最终合并数据集

PostgreSQL mda/
  final_MICS2MICS6                   合并数据表
  ind_que_MICSMICS                   变量索引表
```

---
