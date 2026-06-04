"""
Generate English data report for hl.parquet → docs/hl_EN.md
Charts saved to etc/hl/ (with _en suffix)
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
DOC_PATH = ROOT / "docs" / "hl_EN.md"

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
    "HH1", "HH2", "HL1", "HL4", "HL5", "HL6", "HL9", "HL11",
    "ED1", "ED2", "ED3A", "HLMS", "FLINE",
]
print("Reading parquet schema ...")
schema = pq.read_schema(PARQUET)
available = [c for c in NEEDED_COLS if c in schema.names]
df = pq.read_table(PARQUET, columns=available).to_pandas()
n_total_cols = len(schema.names)
print(f"Loaded: {len(df):,} rows x {len(df.columns)} cols (total cols: {n_total_cols})")

n_rows = len(df)
n_countries = df["country"].nunique()
rows_per_round = df.groupby("mics_round").size().reindex(ROUNDS).fillna(0).astype(int)
ctry_per_round = df.groupby("mics_round")["country"].nunique().reindex(ROUNDS).fillna(0).astype(int)

# ── Fig 1 ─────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
ax = axes[0]
bars = ax.bar(ROUNDS, rows_per_round.values,
              color=[ROUND_COLORS[r] for r in ROUNDS], edgecolor="white")
ax.bar_label(bars, fmt=lambda x: f"{int(x):,}", padding=3, fontsize=9)
ax.set_title("Household Member Records by Round", fontsize=13)
ax.set_ylabel("Number of Records")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(
    lambda x, _: f"{x/1e6:.1f}M" if x >= 1e6 else f"{int(x):,}"))
ax.spines[["top", "right"]].set_visible(False)

ax = axes[1]
bars = ax.bar(ROUNDS, ctry_per_round.values,
              color=[ROUND_COLORS[r] for r in ROUNDS], edgecolor="white")
ax.bar_label(bars, padding=3, fontsize=10)
ax.set_title("Countries/Areas Covered by Round", fontsize=13)
ax.set_ylabel("Number of Countries/Areas")
ax.spines[["top", "right"]].set_visible(False)

plt.tight_layout()
fig.savefig(OUT_DIR / "fig1_round_overview_en.png", dpi=150, bbox_inches="tight")
plt.close(); print("Saved fig1")

# ── Fig 2 ─────────────────────────────────────────────────────────────────────
if "HL4" in df.columns:
    sex_rows = []
    for rnd in ROUNDS:
        sub = df[df["mics_round"] == rnd]["HL4"].dropna()
        sub = pd.to_numeric(sub, errors="coerce").dropna()
        total = len(sub)
        if total == 0: continue
        sex_rows.append({
            "round": rnd,
            "male_pct": (sub == 1).sum() / total * 100,
            "female_pct": (sub == 2).sum() / total * 100,
        })
    if sex_rows:
        sex_df = pd.DataFrame(sex_rows)
        fig, ax = plt.subplots(figsize=(8, 4))
        x = range(len(sex_df))
        ax.bar(x, sex_df["male_pct"], label="Male (1)", color="#2980b9", alpha=0.8)
        ax.bar(x, sex_df["female_pct"], bottom=sex_df["male_pct"],
               label="Female (2)", color="#e74c3c", alpha=0.8)
        ax.set_xticks(list(x)); ax.set_xticklabels(sex_df["round"])
        ax.set_ylabel("%")
        ax.set_title("HL4 Sex Distribution by Round", fontsize=13)
        ax.axhline(50, color="gray", linewidth=0.8, linestyle="--")
        ax.legend()
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        fig.savefig(OUT_DIR / "fig2_sex_distribution_en.png", dpi=150, bbox_inches="tight")
        plt.close(); print("Saved fig2")

# ── Fig 3 ─────────────────────────────────────────────────────────────────────
if "HL5" in df.columns:
    age_m6 = pd.to_numeric(
        df[(df["mics_round"] == "MICS6") & df["HL5"].notna()]["HL5"], errors="coerce"
    ).dropna()
    age_m6 = age_m6[(age_m6 >= 0) & (age_m6 <= 100)]
    if len(age_m6) > 0:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.hist(age_m6, bins=range(0, 101, 1), color="#159895", edgecolor="none", alpha=0.85)
        ax.set_xlabel("Age (years)")
        ax.set_ylabel("Count")
        ax.set_title("Age Distribution of Household Members — MICS6 (HL5)", fontsize=13)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        fig.savefig(OUT_DIR / "fig3_age_distribution_en.png", dpi=150, bbox_inches="tight")
        plt.close(); print("Saved fig3")

# ── Fig 4 ─────────────────────────────────────────────────────────────────────
key_vars = ["HL1", "HL4", "HL5", "HL6", "HL9", "HL11", "ED1", "ED2", "ED3A", "HLMS", "FLINE"]
key_vars = [v for v in key_vars if v in df.columns]
miss_rate = df[key_vars].isna().mean().sort_values(ascending=True) * 100

fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.barh(miss_rate.index, miss_rate.values, color="#117a65", edgecolor="white")
ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
ax.set_xlabel("Missing Rate (%)")
ax.set_title("Missing Rate of Key Variables — hl Module", fontsize=13)
ax.spines[["top", "right"]].set_visible(False)
plt.tight_layout()
fig.savefig(OUT_DIR / "fig4_missing_rate_en.png", dpi=150, bbox_inches="tight")
plt.close(); print("Saved fig4")

# ── Summary table ─────────────────────────────────────────────────────────────
avg_per = (rows_per_round / ctry_per_round.replace(0, np.nan)).round(0).fillna(0).astype(int)
summary_table = pd.DataFrame({
    "Round": ROUNDS,
    "Countries/Areas": ctry_per_round.values,
    "Records": rows_per_round.values,
    "Avg. Records/Country": avg_per.values,
})

rel = lambda p: f"../etc/hl/{p}"

md = f"""# hl Module Data Report

> Generation script: `MICS/etc/hl/report_en.py`

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Total rows | {n_rows:,} |
| Total columns | {n_total_cols:,} |
| Countries/areas covered | {n_countries} |
| Rounds covered | MICS2 – MICS6 |

The **hl module** (household listing) contains one row per household member. Key topic areas: individual demographics (age, sex, relationship to head), education (ED*), and intra-household links (mother/father line numbers).

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

## 3. Sex Distribution (HL4)

HL4 codes: 1 = Male, 2 = Female. The sex ratio is stable across rounds.

![Sex distribution]({rel("fig2_sex_distribution_en.png")})

---

## 4. Age Distribution (HL5, MICS6)

The MICS6 age distribution follows a typical population pyramid, with a relatively high share of children under 5.

![Age distribution]({rel("fig3_age_distribution_en.png")})

---

## 5. Missing Rate of Key Variables

![Missing rate]({rel("fig4_missing_rate_en.png")})

| Variable | Description | Missing Rate |
|----------|-------------|-------------|
| HL1  | Member line number | {df["HL1"].isna().mean()*100:.1f}% |
| HL4  | Sex | {df["HL4"].isna().mean()*100:.1f}% |
| HL5  | Age | {df["HL5"].isna().mean()*100:.1f}% |
| ED2  | Ever attended school | {df["ED2"].isna().mean()*100 if "ED2" in df.columns else float("nan"):.1f}% |
| ED3A | Highest level of education attended | {df["ED3A"].isna().mean()*100 if "ED3A" in df.columns else float("nan"):.1f}% |

---

## 6. Standard Core Variables

{standard_vars_table("hl")}

---

## 7. Usage Notes

- **Link keys**: `country` + `mics_round` + `HH1` (cluster) + `HH2` (household) + `HL1` (member line number)
- **Join with hh**: via `HH1` + `HH2`
- **Join with wm**: via `HH1` + `HH2` + `HL1` (woman's line number = `LN` in wm)
- **Join with ch**: via `HH1` + `HH2` + `HL1` (child's line number = `LN` in ch)
- **Note**: In MICS2, HL3 (sex) has been renamed to HL4 and HL4 (age) to HL5 to align with the MICS3–6 convention
"""

DOC_PATH.write_text(md, encoding="utf-8")
print(f"\nReport written to {DOC_PATH}")
