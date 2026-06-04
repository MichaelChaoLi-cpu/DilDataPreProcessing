"""
Generate English data report for hh.parquet → docs/hh_EN.md
Charts saved to etc/hh/ (with _en suffix)
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "src"))
from report_utils import standard_vars_table

PARQUET = Path("/Volumes/MikesDataBackup/MICS/processed/hh.parquet")
OUT_DIR = ROOT / "etc" / "hh"
DOC_PATH = ROOT / "docs" / "hh_EN.md"

plt.rcParams["font.family"] = "Arial"
plt.rcParams["axes.unicode_minus"] = False

ROUNDS = ["MICS2", "MICS3", "MICS4", "MICS5", "MICS6"]
ROUND_COLORS = {
    "MICS2": "#a8d8ea", "MICS3": "#57c5b6", "MICS4": "#159895",
    "MICS5": "#1a5276", "MICS6": "#117a65",
}

# ── Load ──────────────────────────────────────────────────────────────────────
NEEDED_COLS = [
    "country", "mics_round",
    "HH1", "HH2", "HH6", "HH7", "HH9", "HH11", "HH12", "HH13", "HH14", "HH15",
    "HC2", "HC3", "WS1", "WS7",
]
print("Reading parquet schema ...")
schema = pq.read_schema(PARQUET)
available = [c for c in NEEDED_COLS if c in schema.names]
df = pq.read_table(PARQUET, columns=available).to_pandas()
n_total_cols = len(schema.names)
print(f"Loaded: {len(df):,} rows x {len(df.columns)} cols (total cols: {n_total_cols})")

n_rows = len(df)
n_countries = df["country"].nunique()
round_counts = df.groupby("mics_round")["country"].nunique().reindex(ROUNDS).fillna(0).astype(int)
survey_counts = df.groupby("mics_round").size().reindex(ROUNDS).fillna(0).astype(int)

# ── Fig 1 ─────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
ax = axes[0]
bars = ax.bar(ROUNDS, survey_counts.values,
              color=[ROUND_COLORS[r] for r in ROUNDS], edgecolor="white")
ax.bar_label(bars, fmt=lambda x: f"{int(x):,}", padding=3, fontsize=10)
ax.set_title("Household Questionnaire Records by Round", fontsize=13)
ax.set_ylabel("Number of Records")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
ax.spines[["top", "right"]].set_visible(False)

ax = axes[1]
bars = ax.bar(ROUNDS, round_counts.values,
              color=[ROUND_COLORS[r] for r in ROUNDS], edgecolor="white")
ax.bar_label(bars, padding=3, fontsize=10)
ax.set_title("Countries/Areas Covered by Round", fontsize=13)
ax.set_ylabel("Number of Countries/Areas")
ax.spines[["top", "right"]].set_visible(False)

plt.tight_layout()
fig.savefig(OUT_DIR / "fig1_round_overview_en.png", dpi=150, bbox_inches="tight")
plt.close(); print("Saved fig1")

# ── Fig 2 ─────────────────────────────────────────────────────────────────────
import numpy as np
pivot = df.groupby(["country", "mics_round"]).size().unstack(fill_value=0)
pivot = pivot.reindex(columns=ROUNDS, fill_value=0)
pivot_bin = (pivot > 0).astype(int)
top_n = 60
pivot_plot = pivot_bin.sort_values(ROUNDS, ascending=False).head(top_n)

fig, ax = plt.subplots(figsize=(8, 14))
ax.imshow(np.where(pivot_plot.values == 1, 1.0, 0.0),
          aspect="auto", cmap="Blues", vmin=0, vmax=1)
ax.set_xticks(range(len(ROUNDS))); ax.set_xticklabels(ROUNDS, fontsize=10)
ax.set_yticks(range(len(pivot_plot))); ax.set_yticklabels(pivot_plot.index, fontsize=7)
ax.set_title(f"Country × Round Coverage (Top {top_n} Countries)", fontsize=12)
ax.xaxis.tick_top(); ax.xaxis.set_label_position("top")
plt.tight_layout()
fig.savefig(OUT_DIR / "fig2_country_round_coverage_en.png", dpi=150, bbox_inches="tight")
plt.close(); print("Saved fig2")

# ── Fig 3 ─────────────────────────────────────────────────────────────────────
key_vars = ["HH6", "HH7", "HH9", "HH11", "HH12", "HH13", "HH14", "HH15",
            "HC2", "HC3", "WS1", "WS7"]
key_vars = [v for v in key_vars if v in df.columns]
miss_rate = df[key_vars].isna().mean().sort_values(ascending=True) * 100

fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.barh(miss_rate.index, miss_rate.values, color="#159895", edgecolor="white")
ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
ax.set_xlabel("Missing Rate (%)")
ax.set_title("Missing Rate of Key Variables — hh Module", fontsize=13)
ax.spines[["top", "right"]].set_visible(False)
plt.tight_layout()
fig.savefig(OUT_DIR / "fig3_missing_rate_en.png", dpi=150, bbox_inches="tight")
plt.close(); print("Saved fig3")

# ── Fig 4 ─────────────────────────────────────────────────────────────────────
if "HH6" in df.columns:
    m6 = df[df["mics_round"] == "MICS6"]["HH6"].dropna()
    val_counts = m6.value_counts().head(5)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(val_counts.index.astype(str), val_counts.values,
           color="#1a5276", edgecolor="white")
    ax.set_title("HH6 Distribution (MICS6) — 1=Urban, 2=Rural", fontsize=12)
    ax.set_xlabel("Code Value")
    ax.set_ylabel("Number of Households")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUT_DIR / "fig4_hh6_urban_rural_en.png", dpi=150, bbox_inches="tight")
    plt.close(); print("Saved fig4")

# ── Summary table ─────────────────────────────────────────────────────────────
rows_per_round = df.groupby("mics_round").size().reindex(ROUNDS).fillna(0).astype(int)
ctry_per_round = df.groupby("mics_round")["country"].nunique().reindex(ROUNDS).fillna(0).astype(int)
avg_hh = (rows_per_round / ctry_per_round.replace(0, float("nan"))).round(0).fillna(0).astype(int)
summary_table = pd.DataFrame({
    "Round": ROUNDS,
    "Countries/Areas": ctry_per_round.values,
    "Records": rows_per_round.values,
    "Avg. Records/Country": avg_hh.values,
})

rel = lambda p: f"../etc/hh/{p}"

md = f"""# hh Module Data Report

> Generation script: `MICS/etc/hh/report_en.py`

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Total rows | {n_rows:,} |
| Total columns | {n_total_cols:,} |
| Countries/areas covered | {n_countries} |
| Rounds covered | MICS2 – MICS6 |

The **hh module** (household questionnaire) contains one row per household. Key topic areas: household identification, interview result, housing characteristics (HC*), water and sanitation (WS*).

---

## 2. Distribution by Round

![Round overview]({rel("fig1_round_overview_en.png")})

| Round | Countries/Areas | Records | Avg. Records/Country |
|-------|----------------|---------|----------------------|
"""
for _, row in summary_table.iterrows():
    md += f"| {row['Round']} | {row['Countries/Areas']} | {row['Records']:,} | {row['Avg. Records/Country']:,} |\n"

md += f"""
---

## 3. Country × Round Coverage

Blue = data available, White = no data. Top 60 countries shown.

![Country-round coverage]({rel("fig2_country_round_coverage_en.png")})

---

## 4. Missing Rate of Key Variables

Missingness is mainly driven by earlier rounds (MICS2/3) where certain questions were not included.

![Missing rate]({rel("fig3_missing_rate_en.png")})

| Variable | Description | Missing Rate |
|----------|-------------|-------------|
| HH6  | Area (urban/rural) | {df["HH6"].isna().mean()*100:.1f}% |
| HH9  | Result of HH interview | {df["HH9"].isna().mean()*100:.1f}% |
| HH11 | Number of household members | {df["HH11"].isna().mean()*100:.1f}% |
| HC2  | Number of sleeping rooms | {df["HC2"].isna().mean()*100:.1f}% |
| HC3  | Main material of floor | {df["HC3"].isna().mean()*100:.1f}% |
| WS1  | Main source of drinking water | {df["WS1"].isna().mean()*100:.1f}% |
"""

if "HH6" in df.columns:
    md += f"""
---

## 5. HH6 Urban/Rural Distribution (MICS6)

HH6 codes: 1 = Urban, 2 = Rural.

![HH6 distribution]({rel("fig4_hh6_urban_rural_en.png")})
"""

std_table = standard_vars_table("hh")

md += f"""
---

## 6. Standard Core Variables

{std_table}

---

## 7. Usage Notes

- **Link keys**: `country` + `mics_round` + `HH1` (cluster) + `HH2` (household)
- **Join with hl**: via `HH1` + `HH2`
- **Join with wm/ch**: via `HH1` + `HH2`
- **Note**: MICS2 variables have been standardised using the variable mapping dictionary; fields absent in early rounds appear as NaN
"""

DOC_PATH.write_text(md, encoding="utf-8")
print(f"\nReport written to {DOC_PATH}")
