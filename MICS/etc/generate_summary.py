"""
Generate summary reports (CN + EN) covering all 7 MICS modules.
Output: docs/SUMMARY_CN.md  and  docs/SUMMARY_EN.md
Charts: etc/summary/
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

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "etc" / "summary"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED = Path("/Volumes/MikesDataBackup/MICS/processed")

ROUNDS = ["MICS2", "MICS3", "MICS4", "MICS5", "MICS6"]
ROUND_COLORS = {
    "MICS2": "#a8d8ea", "MICS3": "#57c5b6", "MICS4": "#159895",
    "MICS5": "#1a5276", "MICS6": "#117a65",
}

MODULE_INFO = {
    "hh": {
        "cn": ("家庭问卷", "每行一个家庭。涵盖家庭基本信息、饮水卫生（WS*）、居住条件（HC*）。"),
        "en": ("Household Questionnaire", "One row per household. Covers household info, water & sanitation (WS*), housing characteristics (HC*)."),
        "link_key_cn": "HH1 + HH2",
        "link_key_en": "HH1 + HH2",
    },
    "hl": {
        "cn": ("家庭成员清单", "每行一名家庭成员。涵盖年龄、性别、教育（ED*）及成员间关联。"),
        "en": ("Household Listing", "One row per household member. Covers age, sex, education (ED*), intra-household links."),
        "link_key_cn": "HH1 + HH2 + HL1",
        "link_key_en": "HH1 + HH2 + HL1",
    },
    "wm": {
        "cn": ("女性问卷（15–49岁）", "每行一名女性。涵盖教育、生育史摘要（CM*）、避孕（CP*）、孕产保健（MN*）。"),
        "en": ("Women's Questionnaire (15–49)", "One row per woman. Covers education, birth history summary (CM*), contraception (CP*), maternal health (MN*)."),
        "link_key_cn": "HH1 + HH2 + LN",
        "link_key_en": "HH1 + HH2 + LN",
    },
    "ch": {
        "cn": ("5岁以下儿童问卷", "每行一名5岁以下儿童。涵盖出生登记（BR*）、疫苗接种（VA*）、营养（AN*）、腹泻（CA*）。"),
        "en": ("Under-5 Children's Questionnaire", "One row per child under 5. Covers birth registration (BR*), vaccination (VA*), nutrition (AN*), diarrhoea (CA*)."),
        "link_key_cn": "HH1 + HH2 + LN",
        "link_key_en": "HH1 + HH2 + LN",
    },
    "bh": {
        "cn": ("生育史模块", "每行一次出生记录（一名女性可有多行）。涵盖出生日期、存活状态（BH5）、死亡年龄，用于计算儿童死亡率。"),
        "en": ("Birth History Module", "One row per birth (multiple per woman). Covers birth date, survival status (BH5), age at death. Used for child mortality estimates."),
        "link_key_cn": "HH1 + HH2 + LN + BHLN",
        "link_key_en": "HH1 + HH2 + LN + BHLN",
    },
    "fs": {
        "cn": ("基础技能模块（7–14岁）", "每行一名7–14岁儿童。涵盖读写、计算能力及认知发展（CB*）。仅MICS5/6。"),
        "en": ("Foundational Skills Module (7–14)", "One row per child 7–14. Covers literacy, numeracy, cognitive development (CB*). MICS5/6 only."),
        "link_key_cn": "HH1 + HH2 + LN",
        "link_key_en": "HH1 + HH2 + LN",
    },
    "gm": {
        "cn": ("全球移民模块", "每行一名受访者。涵盖移民经历（MG*）及财富指数（windex*）。仅MICS6，样本量较小。"),
        "en": ("Global Migration Module", "One row per respondent. Covers migration experience (MG*) and wealth index (windex*). MICS6 only, small sample."),
        "link_key_cn": "HH1 + HH2",
        "link_key_en": "HH1 + HH2",
    },
}

# ── Collect stats for all modules ─────────────────────────────────────────────
print("Collecting stats ...")
stats = {}
for mod in MODULE_INFO:
    schema = pq.read_schema(PROCESSED / f"{mod}.parquet")
    df_meta = pq.read_table(
        PROCESSED / f"{mod}.parquet",
        columns=["country", "mics_round"]
    ).to_pandas()
    rows_pr = df_meta.groupby("mics_round").size().reindex(ROUNDS).fillna(0).astype(int)
    ctry_pr = df_meta.groupby("mics_round")["country"].nunique().reindex(ROUNDS).fillna(0).astype(int)
    stats[mod] = {
        "n_rows": len(df_meta),
        "n_cols": len(schema.names),
        "n_countries": df_meta["country"].nunique(),
        "rows_pr": rows_pr,
        "ctry_pr": ctry_pr,
        "rounds": [r for r in ROUNDS if rows_pr[r] > 0],
    }
    print(f"  {mod}: {len(df_meta):,} rows, {len(schema.names)} cols, {df_meta['country'].nunique()} countries")

# ── Fig 1: Total rows per module ──────────────────────────────────────────────
for lang in ["cn", "en"]:
    font = "Arial Unicode MS" if lang == "cn" else "Arial"
    plt.rcParams["font.family"] = font

    modules = list(MODULE_INFO.keys())
    n_rows = [stats[m]["n_rows"] for m in modules]
    labels_cn = [f"{m}\n({MODULE_INFO[m]['cn'][0]})" for m in modules]
    labels_en = [f"{m}\n({MODULE_INFO[m]['en'][0][:20]})" for m in modules]
    labels = labels_cn if lang == "cn" else labels_en

    fig, ax = plt.subplots(figsize=(12, 5))
    colors = ["#159895", "#1a5276", "#117a65", "#2471a3", "#a8d8ea", "#57c5b6", "#c0392b"]
    bars = ax.bar(range(len(modules)), n_rows, color=colors, edgecolor="white")
    ax.bar_label(bars, fmt=lambda x: f"{int(x/1e6):.1f}M" if x >= 1e6 else f"{int(x):,}",
                 padding=4, fontsize=9)
    ax.set_xticks(range(len(modules)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_title("各模块总记录数" if lang == "cn" else "Total Records per Module", fontsize=13)
    ax.set_ylabel("记录数" if lang == "cn" else "Records")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{x/1e6:.0f}M" if x >= 1e6 else f"{int(x):,}"))
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    suf = "" if lang == "cn" else "_en"
    fig.savefig(OUT_DIR / f"fig1_rows_per_module{suf}.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  [{lang.upper()}] fig1 saved")

# ── Fig 2: Country coverage heatmap (all modules × rounds) ───────────────────
for lang in ["cn", "en"]:
    font = "Arial Unicode MS" if lang == "cn" else "Arial"
    plt.rcParams["font.family"] = font

    modules = list(MODULE_INFO.keys())
    data = np.array([[stats[m]["ctry_pr"][r] for r in ROUNDS] for m in modules])

    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(data, aspect="auto", cmap="YlGnBu")
    ax.set_xticks(range(len(ROUNDS))); ax.set_xticklabels(ROUNDS, fontsize=11)
    ax.set_yticks(range(len(modules))); ax.set_yticklabels(modules, fontsize=11)
    for i in range(len(modules)):
        for j in range(len(ROUNDS)):
            val = data[i, j]
            if val > 0:
                ax.text(j, i, str(val), ha="center", va="center",
                        fontsize=9, color="white" if val > 40 else "black")
    ax.set_title("各模块×轮次 覆盖国家数" if lang == "cn"
                 else "Countries Covered per Module × Round", fontsize=13)
    ax.xaxis.tick_top(); ax.xaxis.set_label_position("top")
    plt.colorbar(im, ax=ax, label="国家数" if lang == "cn" else "Countries")
    plt.tight_layout()
    suf = "" if lang == "cn" else "_en"
    fig.savefig(OUT_DIR / f"fig2_coverage_heatmap{suf}.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  [{lang.upper()}] fig2 saved")

# ── Build Markdown ────────────────────────────────────────────────────────────
def build_summary(lang):
    is_cn = lang == "cn"
    suf = "" if is_cn else "_en"
    rel = lambda p: f"../etc/summary/{p}"

    if is_cn:
        lines = [
            "# MICS 数据集汇总报告", "",
            "> 生成脚本：`MICS/etc/generate_summary.py`", "",
            "---", "", "## 1. 数据来源", "",
            "本数据集来自 [UNICEF MICS（多指标集群调查）](https://mics.unicef.org/surveys)，",
            "涵盖 MICS2 至 MICS6 五个轮次，覆盖全球 155 个国家/地区。",
            "原始数据为 SPSS（.sav）格式，已按标准变量映射字典统一处理后合并为 7 个 Parquet 文件。",
            "", "---", "", "## 2. 数据集结构", "",
            "MICS 调查包含 7 个相互关联的问卷模块，通过共同的链接键可横向关联：", "",
        ]
    else:
        lines = [
            "# MICS Dataset Summary Report", "",
            "> Generation script: `MICS/etc/generate_summary.py`", "",
            "---", "", "## 1. Data Source", "",
            "This dataset is derived from [UNICEF MICS (Multiple Indicator Cluster Surveys)](https://mics.unicef.org/surveys),",
            "covering MICS rounds 2–6 across 155 countries and areas.",
            "Raw data were in SPSS (.sav) format and have been standardised using a variable mapping dictionary",
            "and merged into 7 Parquet files.", "",
            "---", "", "## 2. Dataset Structure", "",
            "MICS surveys comprise 7 interrelated questionnaire modules linked by common keys:", "",
        ]

    # Module overview table
    if is_cn:
        lines += [
            "| 模块 | 名称 | 分析单元 | 总行数 | 总列数 | 覆盖国家数 | 覆盖轮次 | 链接键 |",
            "|------|------|----------|--------|--------|------------|----------|--------|",
        ]
        for mod, info in MODULE_INFO.items():
            s = stats[mod]
            rnd_str = " ".join(s["rounds"])
            name, unit = info["cn"][0], info["cn"][1].split("。")[0]
            lines.append(
                f"| [{mod}]({mod}_CN.md) | {name} | {unit} | {s['n_rows']:,} | "
                f"{s['n_cols']:,} | {s['n_countries']} | {rnd_str} | `{info['link_key_cn']}` |"
            )
    else:
        lines += [
            "| Module | Name | Unit of Analysis | Total Rows | Total Cols | Countries | Rounds | Link Key |",
            "|--------|------|-----------------|------------|------------|-----------|--------|----------|",
        ]
        for mod, info in MODULE_INFO.items():
            s = stats[mod]
            rnd_str = " ".join(s["rounds"])
            name = info["en"][0]
            unit = info["en"][1].split(".")[0]
            lines.append(
                f"| [{mod}]({mod}_EN.md) | {name} | {unit} | {s['n_rows']:,} | "
                f"{s['n_cols']:,} | {s['n_countries']} | {rnd_str} | `{info['link_key_en']}` |"
            )

    # Fig 1
    lines += ["", "---", "",
              "## 3. 各模块记录数" if is_cn else "## 3. Records per Module", ""]
    lines.append(f"![{'各模块总记录数' if is_cn else 'Records per module'}]({rel(f'fig1_rows_per_module{suf}.png')})")

    # Fig 2
    lines += ["", "---", "",
              "## 4. 各模块×轮次 覆盖国家数" if is_cn else "## 4. Country Coverage per Module × Round", ""]
    if is_cn:
        lines.append("数字为各格子覆盖的国家/地区数，0 表示该轮次不包含此模块。")
    else:
        lines.append("Each cell shows the number of countries covered. 0 means the module was not fielded in that round.")
    lines.append(f"![{'覆盖热力图' if is_cn else 'Coverage heatmap'}]({rel(f'fig2_coverage_heatmap{suf}.png')})")

    # Module descriptions
    lines += ["", "---", "",
              "## 5. 各模块说明" if is_cn else "## 5. Module Descriptions", ""]
    for mod, info in MODULE_INFO.items():
        s = stats[mod]
        name, desc = info["cn"] if is_cn else info["en"]
        link_key = info["link_key_cn"] if is_cn else info["link_key_en"]
        report_link = f"{mod}_{'CN' if is_cn else 'EN'}.md"
        lines += [
            f"### {mod} — {name}", "",
            f"{desc}", "",
            f"- **{'记录数' if is_cn else 'Records'}**: {s['n_rows']:,}",
            f"- **{'列数' if is_cn else 'Columns'}**: {s['n_cols']:,}",
            f"- **{'覆盖国家' if is_cn else 'Countries'}**: {s['n_countries']}",
            f"- **{'覆盖轮次' if is_cn else 'Rounds'}**: {' '.join(s['rounds'])}",
            f"- **{'链接键' if is_cn else 'Link key'}**: `{link_key}`",
            f"- **{'详细报告' if is_cn else 'Full report'}**: [{report_link}]({report_link})",
            "",
        ]

    # Join diagram
    lines += ["---", "",
              "## 6. 模块间关联关系" if is_cn else "## 6. Module Relationships", ""]
    if is_cn:
        lines += [
            "```",
            "hh (家庭) ──┬── hl (成员)  ←→  wm (女性) ──→ bh (生育史)",
            "            │                ↓",
            "            │               ch (5岁以下儿童)",
            "            │",
            "            ├── fs (7-14岁儿童基础技能)",
            "            └── gm (移民)",
            "",
            "关联键: hh ↔ hl ↔ wm/ch 均通过 HH1 + HH2 连接",
            "        wm ↔ bh 通过 HH1 + HH2 + LN 连接",
            "```",
        ]
    else:
        lines += [
            "```",
            "hh (Household) ──┬── hl (Members)  ←→  wm (Women) ──→ bh (Birth History)",
            "                 │                   ↓",
            "                 │                  ch (Under-5 Children)",
            "                 │",
            "                 ├── fs (Children 7-14, Foundational Skills)",
            "                 └── gm (Migration)",
            "",
            "Join keys: hh ↔ hl ↔ wm/ch via HH1 + HH2",
            "           wm ↔ bh via HH1 + HH2 + LN",
            "```",
        ]

    return "\n".join(lines) + "\n"


for lang in ["cn", "en"]:
    md = build_summary(lang)
    suffix = "CN" if lang == "cn" else "EN"
    doc_path = ROOT / "docs" / f"SUMMARY_{suffix}.md"
    doc_path.write_text(md, encoding="utf-8")
    print(f"[{lang.upper()}] Summary → {doc_path}")

print("\nAll done.")
