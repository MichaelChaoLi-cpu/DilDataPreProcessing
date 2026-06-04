"""
Generate data report for hh.parquet → docs/hh_CN.md
Charts saved to etc/hh/
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import pyarrow.parquet as pq

import sys
ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "src"))
from report_utils import standard_vars_table

PARQUET = Path("/Volumes/MikesDataBackup/MICS/processed/hh.parquet")
OUT_DIR = ROOT / "etc" / "hh"
DOC_PATH = ROOT / "docs" / "hh_CN.md"

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
    "HH1", "HH2",
    "HH6", "HH7", "HH9", "HH11", "HH12", "HH13", "HH14", "HH15",
    "HC2", "HC3", "WS1", "WS7",
]

print("Reading parquet schema …")
schema = pq.read_schema(PARQUET)
available = [c for c in NEEDED_COLS if c in schema.names]

print(f"Loading {len(available)} columns from hh.parquet …")
df = pq.read_table(PARQUET, columns=available).to_pandas()
n_total_cols = len(schema.names)
print(f"Loaded: {len(df):,} rows × {len(df.columns)} cols (total cols in file: {n_total_cols})")

# ── Basic stats ───────────────────────────────────────────────────────────────
n_rows = len(df)
n_cols = n_total_cols
n_countries = df["country"].nunique()
round_counts = df.groupby("mics_round")["country"].nunique().reindex(ROUNDS).fillna(0).astype(int)
survey_counts = df.groupby("mics_round").size().reindex(ROUNDS).fillna(0).astype(int)

# ── Fig 1: 各轮次调查数 & 国家数 ──────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

ax = axes[0]
bars = ax.bar(ROUNDS, survey_counts.values,
              color=[ROUND_COLORS[r] for r in ROUNDS], edgecolor="white", linewidth=0.5)
ax.bar_label(bars, padding=3, fontsize=10)
ax.set_title("各轮次家庭问卷行数", fontsize=13)
ax.set_ylabel("行数")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
ax.spines[["top", "right"]].set_visible(False)

ax = axes[1]
bars = ax.bar(ROUNDS, round_counts.values,
              color=[ROUND_COLORS[r] for r in ROUNDS], edgecolor="white", linewidth=0.5)
ax.bar_label(bars, padding=3, fontsize=10)
ax.set_title("各轮次覆盖国家/地区数", fontsize=13)
ax.set_ylabel("国家/地区数")
ax.spines[["top", "right"]].set_visible(False)

plt.tight_layout()
fig.savefig(OUT_DIR / "fig1_round_overview.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig1")

# ── Fig 2: 国家-轮次覆盖热力图 ────────────────────────────────────────────────
pivot = df.groupby(["country", "mics_round"]).size().unstack(fill_value=0)
pivot = pivot.reindex(columns=ROUNDS, fill_value=0)
pivot_bin = (pivot > 0).astype(int)

top_n = 60
pivot_plot = pivot_bin.sort_values(ROUNDS, ascending=False).head(top_n)

fig, ax = plt.subplots(figsize=(8, 14))
import numpy as np
colors = np.where(pivot_plot.values == 1, 1.0, 0.0)
ax.imshow(colors, aspect="auto", cmap="Blues", vmin=0, vmax=1)
ax.set_xticks(range(len(ROUNDS)))
ax.set_xticklabels(ROUNDS, fontsize=10)
ax.set_yticks(range(len(pivot_plot)))
ax.set_yticklabels(pivot_plot.index, fontsize=7)
ax.set_title(f"国家-轮次覆盖情况（前{top_n}个国家）", fontsize=12)
ax.xaxis.tick_top()
ax.xaxis.set_label_position("top")
plt.tight_layout()
fig.savefig(OUT_DIR / "fig2_country_round_coverage.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig2")

# ── Fig 3: 关键变量缺失率 ─────────────────────────────────────────────────────
key_vars = ["HH6", "HH7", "HH9", "HH11", "HH12", "HH13", "HH14", "HH15",
            "HC2", "HC3", "WS1", "WS7"]
key_vars = [v for v in key_vars if v in df.columns]
miss_rate = df[key_vars].isna().mean().sort_values(ascending=True) * 100

fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.barh(miss_rate.index, miss_rate.values,
               color="#159895", edgecolor="white")
ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
ax.set_xlabel("缺失率 (%)")
ax.set_title("hh 模块关键变量缺失率", fontsize=13)
ax.spines[["top", "right"]].set_visible(False)
plt.tight_layout()
fig.savefig(OUT_DIR / "fig3_missing_rate.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig3")

# ── Fig 4: HH6 城乡分布（MICS6）─────────────────────────────────────────────
if "HH6" in df.columns:
    m6 = df[df["mics_round"] == "MICS6"]["HH6"].dropna()
    val_counts = m6.value_counts().head(5)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(val_counts.index.astype(str), val_counts.values,
           color="#1a5276", edgecolor="white")
    ax.set_title("MICS6 HH6（城乡）分布", fontsize=12)
    ax.set_xlabel("编码值（1=城市, 2=农村）")
    ax.set_ylabel("家庭数")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUT_DIR / "fig4_hh6_urban_rural.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("Saved fig4")

# ── Table: 各轮次基本统计 ─────────────────────────────────────────────────────
rows_per_round = df.groupby("mics_round").size().reindex(ROUNDS).fillna(0).astype(int)
hh_per_round = df.groupby("mics_round")["country"].nunique().reindex(ROUNDS).fillna(0).astype(int)
avg_hh = (rows_per_round / hh_per_round.replace(0, float("nan"))).round(0).fillna(0).astype(int)

summary_table = pd.DataFrame({
    "轮次": ROUNDS,
    "国家/地区数": hh_per_round.values,
    "家庭问卷行数": rows_per_round.values,
    "平均每国行数": avg_hh.values,
})

# ── Write Markdown ────────────────────────────────────────────────────────────
rel = lambda p: f"../etc/hh/{p}"

md = f"""# hh 模块数据报告

> 生成脚本：`MICS/etc/hh/report.py`

---

## 1. 概览

| 指标 | 数值 |
|------|------|
| 总行数 | {n_rows:,} |
| 总列数 | {n_cols:,} |
| 覆盖国家/地区数 | {n_countries} |
| 覆盖轮次 | MICS2 ~ MICS6 |

**hh 模块**（家庭问卷）每行代表一个家庭。主要包含：家庭基本信息、调查结果、居住条件（HC*）、饮水与卫生设施（WS*）。

---

## 2. 各轮次分布

![各轮次概览]({rel("fig1_round_overview.png")})

| 轮次 | 国家/地区数 | 行数 | 平均每国行数 |
|------|------------|------|------------|
"""
for _, row in summary_table.iterrows():
    md += f"| {row['轮次']} | {row['国家/地区数']} | {row['家庭问卷行数']:,} | {row['平均每国行数']:,} |\n"

md += f"""
---

## 3. 国家-轮次覆盖

下图展示前60个国家在各轮次的覆盖情况（蓝色=有数据，白色=无数据）。

![国家-轮次覆盖]({rel("fig2_country_round_coverage.png")})

---

## 4. 关键变量缺失率

以下为常用分析变量的缺失情况。缺失主要来自早期轮次（MICS2/3）问卷未包含该题。

![关键变量缺失率]({rel("fig3_missing_rate.png")})

| 变量 | 含义 | 缺失率 |
|------|------|--------|
| HH6  | 城乡类型 | {df["HH6"].isna().mean()*100:.1f}% |
| HH9  | 家庭问卷结果 | {df["HH9"].isna().mean()*100:.1f}% |
| HH11 | 家庭成员数 | {df["HH11"].isna().mean()*100:.1f}% |
| HC2  | 睡眠用房间数 | {df["HC2"].isna().mean()*100:.1f}% |
| HC3  | 地板材质 | {df["HC3"].isna().mean()*100:.1f}% |
| WS1  | 饮用水主要来源 | {df["WS1"].isna().mean()*100:.1f}% |
"""

if "HH6" in df.columns:
    md += f"""
---

## 5. HH6 城乡分布（MICS6）

MICS6 中 HH6 的编码：1 = 城市，2 = 农村。

![HH6城乡分布]({rel("fig4_hh6_urban_rural.png")})
"""

std_table = standard_vars_table("hh")

md += f"""
---

## 6. 标准核心变量列表

{std_table}

---

## 7. 使用说明

- **链接键**：`country` + `mics_round` + `HH1`（cluster）+ `HH2`（household）
- **与 hl 模块关联**：通过 `HH1` + `HH2` 连接
- **与 wm/ch 模块关联**：通过 `HH1` + `HH2` 连接
- **注意**：MICS2 的变量已按映射字典标准化，部分早期轮次变量不存在时为 NaN
"""

DOC_PATH.write_text(md, encoding="utf-8")
print(f"\nReport written to {DOC_PATH}")
