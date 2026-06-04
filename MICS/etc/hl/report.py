"""
Generate data report for hl.parquet → docs/hl_CN.md
Charts saved to etc/hl/
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "src"))
from report_utils import standard_vars_table

PARQUET = Path("/Volumes/MikesDataBackup/MICS/processed/hl.parquet")
OUT_DIR = ROOT / "etc" / "hl"
DOC_PATH = ROOT / "docs" / "hl_CN.md"

plt.rcParams["font.family"] = "Arial Unicode MS"
plt.rcParams["axes.unicode_minus"] = False

ROUNDS = ["MICS2", "MICS3", "MICS4", "MICS5", "MICS6"]
ROUND_COLORS = {
    "MICS2": "#a8d8ea",
    "MICS3": "#57c5b6",
    "MICS4": "#159895",
    "MICS5": "#1a5276",
    "MICS6": "#117a65",
}

# ── Load (only columns needed for the report) ─────────────────────────────────
NEEDED_COLS = [
    "country", "mics_round",
    "HH1", "HH2", "HL1",
    "HL4", "HL5", "HL6", "HL9", "HL11",
    "ED1", "ED2", "ED3A", "HLMS", "FLINE",
]

print("Reading parquet schema …")
schema = pq.read_schema(PARQUET)
available = [c for c in NEEDED_COLS if c in schema.names]

print(f"Loading {len(available)} columns from hl.parquet …")
df = pq.read_table(PARQUET, columns=available).to_pandas()
n_total_cols = len(schema.names)
print(f"Loaded: {len(df):,} rows × {len(df.columns)} cols (total cols in file: {n_total_cols})")

n_rows = len(df)
n_cols = n_total_cols
n_countries = df["country"].nunique()

# ── Fig 1: 各轮次行数 & 国家数 ────────────────────────────────────────────────
rows_per_round = df.groupby("mics_round").size().reindex(ROUNDS).fillna(0).astype(int)
ctry_per_round = df.groupby("mics_round")["country"].nunique().reindex(ROUNDS).fillna(0).astype(int)

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
ax = axes[0]
bars = ax.bar(ROUNDS, rows_per_round.values,
              color=[ROUND_COLORS[r] for r in ROUNDS], edgecolor="white")
ax.bar_label(bars, fmt=lambda x: f"{int(x):,}", padding=3, fontsize=9)
ax.set_title("各轮次家庭成员记录数", fontsize=13)
ax.set_ylabel("行数")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x/1e6):.1f}M" if x >= 1e6 else f"{int(x):,}"))
ax.spines[["top", "right"]].set_visible(False)

ax = axes[1]
bars = ax.bar(ROUNDS, ctry_per_round.values,
              color=[ROUND_COLORS[r] for r in ROUNDS], edgecolor="white")
ax.bar_label(bars, padding=3, fontsize=10)
ax.set_title("各轮次覆盖国家/地区数", fontsize=13)
ax.set_ylabel("国家/地区数")
ax.spines[["top", "right"]].set_visible(False)

plt.tight_layout()
fig.savefig(OUT_DIR / "fig1_round_overview.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig1")

# ── Fig 2: 性别分布（HL4）────────────────────────────────────────────────────
if "HL4" in df.columns:
    sex_by_round = []
    for rnd in ROUNDS:
        sub = df[df["mics_round"] == rnd]["HL4"].dropna()
        if len(sub) == 0:
            continue
        male = (sub == 1).sum()
        female = (sub == 2).sum()
        total = male + female
        if total > 0:
            sex_by_round.append({
                "round": rnd,
                "male_pct": male / total * 100,
                "female_pct": female / total * 100,
            })

    if sex_by_round:
        sex_df = pd.DataFrame(sex_by_round)
        fig, ax = plt.subplots(figsize=(8, 4))
        x = range(len(sex_df))
        ax.bar(x, sex_df["male_pct"], label="男性（1）", color="#2980b9", alpha=0.8)
        ax.bar(x, sex_df["female_pct"], bottom=sex_df["male_pct"],
               label="女性（2）", color="#e74c3c", alpha=0.8)
        ax.set_xticks(list(x))
        ax.set_xticklabels(sex_df["round"])
        ax.set_ylabel("%")
        ax.set_title("HL4 性别比例（各轮次）", fontsize=13)
        ax.axhline(50, color="gray", linewidth=0.8, linestyle="--")
        ax.legend()
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        fig.savefig(OUT_DIR / "fig2_sex_distribution.png", dpi=150, bbox_inches="tight")
        plt.close()
        print("Saved fig2")

# ── Fig 3: 年龄分布（HL5，MICS6 样本）────────────────────────────────────────
if "HL5" in df.columns:
    age_m6 = df[(df["mics_round"] == "MICS6") & df["HL5"].notna()]["HL5"]
    age_m6 = pd.to_numeric(age_m6, errors="coerce").dropna()
    age_m6 = age_m6[(age_m6 >= 0) & (age_m6 <= 100)]

    if len(age_m6) > 0:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.hist(age_m6, bins=range(0, 101, 1), color="#159895", edgecolor="none", alpha=0.85)
        ax.set_xlabel("年龄（岁）")
        ax.set_ylabel("人数")
        ax.set_title("MICS6 家庭成员年龄分布（HL5）", fontsize=13)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        fig.savefig(OUT_DIR / "fig3_age_distribution.png", dpi=150, bbox_inches="tight")
        plt.close()
        print("Saved fig3")

# ── Fig 4: 关键变量缺失率 ─────────────────────────────────────────────────────
key_vars = ["HL1", "HL4", "HL5", "HL6", "HL9", "HL11", "ED1", "ED2", "ED3A", "HLMS", "FLINE"]
key_vars = [v for v in key_vars if v in df.columns]
miss_rate = df[key_vars].isna().mean().sort_values(ascending=True) * 100

fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.barh(miss_rate.index, miss_rate.values, color="#117a65", edgecolor="white")
ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
ax.set_xlabel("缺失率 (%)")
ax.set_title("hl 模块关键变量缺失率", fontsize=13)
ax.spines[["top", "right"]].set_visible(False)
plt.tight_layout()
fig.savefig(OUT_DIR / "fig4_missing_rate.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig4")

# ── Summary table ─────────────────────────────────────────────────────────────
avg_per_hh = (rows_per_round / ctry_per_round.replace(0, np.nan)).round(0).fillna(0).astype(int)
summary_table = pd.DataFrame({
    "轮次": ROUNDS,
    "国家/地区数": ctry_per_round.values,
    "成员记录数": rows_per_round.values,
    "平均每国记录数": avg_per_hh.values,
})

# ── Write Markdown ────────────────────────────────────────────────────────────
rel = lambda p: f"../etc/hl/{p}"

md = f"""# hl 模块数据报告

> 生成脚本：`MICS/etc/hl/report.py`

---

## 1. 概览

| 指标 | 数值 |
|------|------|
| 总行数 | {n_rows:,} |
| 总列数 | {n_cols:,} |
| 覆盖国家/地区数 | {n_countries} |
| 覆盖轮次 | MICS2 ~ MICS6 |

**hl 模块**（家庭成员清单）每行代表一个家庭成员。主要包含：个人基本信息（年龄、性别、与户主关系）、教育信息（ED*）、家庭成员间的关联（母亲/父亲行号）。

---

## 2. 各轮次分布

![各轮次概览]({rel("fig1_round_overview.png")})

| 轮次 | 国家/地区数 | 成员记录数 | 平均每国记录数 |
|------|------------|-----------|--------------|
"""
for _, row in summary_table.iterrows():
    md += f"| {row['轮次']} | {row['国家/地区数']} | {row['成员记录数']:,} | {row['平均每国记录数']:,} |\n"

md += f"""
---

## 3. 性别分布（HL4）

HL4 编码：1 = 男性，2 = 女性。各轮次性别比例基本稳定。

![性别分布]({rel("fig2_sex_distribution.png")})

---

## 4. 年龄分布（HL5，MICS6）

MICS6 家庭成员年龄呈典型的人口金字塔分布，0-5 岁儿童占比较高。

![年龄分布]({rel("fig3_age_distribution.png")})

---

## 5. 关键变量缺失率

![关键变量缺失率]({rel("fig4_missing_rate.png")})

| 变量 | 含义 | 缺失率 |
|------|------|--------|
| HL1  | 成员行号 | {df["HL1"].isna().mean()*100:.1f}% |
| HL4  | 性别 | {df["HL4"].isna().mean()*100:.1f}% |
| HL5  | 年龄 | {df["HL5"].isna().mean()*100:.1f}% |
| ED2  | 是否上过学 | {df["ED2"].isna().mean()*100 if "ED2" in df.columns else float("nan"):.1f}% |
| ED3A | 最高教育程度 | {df["ED3A"].isna().mean()*100 if "ED3A" in df.columns else float("nan"):.1f}% |

---

## 6. 标准核心变量列表

{standard_vars_table("hl")}

---

## 7. 使用说明

- **链接键**：`country` + `mics_round` + `HH1`（cluster）+ `HH2`（household）+ `HL1`（成员行号）
- **与 hh 模块关联**：通过 `HH1` + `HH2`
- **与 wm 模块关联**：通过 `HH1` + `HH2` + `HL1`（女性行号 = `LN` in wm）
- **与 ch 模块关联**：通过 `HH1` + `HH2` + `HL1`（儿童行号 = `LN` in ch）
- **注意**：MICS2 的 HL3（原性别）已重命名为 HL4，HL4（原年龄）已重命名为 HL5，与 MICS3-6 一致
"""

DOC_PATH.write_text(md, encoding="utf-8")
print(f"\nReport written to {DOC_PATH}")
