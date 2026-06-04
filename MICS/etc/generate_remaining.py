"""
Generate CN and EN data reports for wm, ch, bh, fs, gm modules.
Charts saved to etc/<module>/  |  Reports written to docs/<module>_CN.md and _EN.md
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
sys.path.insert(0, str(ROOT / "src"))
from report_utils import standard_vars_table

PROCESSED = Path("/Volumes/MikesDataBackup/MICS/processed")
ROUNDS = ["MICS2", "MICS3", "MICS4", "MICS5", "MICS6"]
ROUND_COLORS = {
    "MICS2": "#a8d8ea", "MICS3": "#57c5b6", "MICS4": "#159895",
    "MICS5": "#1a5276", "MICS6": "#117a65",
}

# ── Module configuration ──────────────────────────────────────────────────────
MODULE_CFG = {
    "wm": {
        "name_cn": "女性问卷", "name_en": "Women's Questionnaire",
        "desc_cn": "每行代表一名15–49岁女性。主要包含：访谈信息、出生日期与年龄、教育、生育史摘要（CM*）、避孕（CP*）、孕产保健（MN*）等。",
        "desc_en": "One row per woman aged 15–49. Key topics: interview info, birth date and age, education, summary birth history (CM*), contraception (CP*), maternal health (MN*).",
        "needed_cols": ["country", "mics_round", "HH1", "HH2", "LN",
                        "WM7", "WM9", "WM8M", "WM8Y", "WM10", "WM11", "WM12",
                        "CM1", "CM3", "CEB", "CDEAD"],
        "key_vars_cn": [("WM7", "访谈结果"), ("WM9", "年龄"), ("WM10", "是否上过学"),
                        ("WM11", "最高教育程度"), ("CM1", "是否生育过"), ("CEB", "累计生育数")],
        "key_vars_en": [("WM7", "Result of interview"), ("WM9", "Age"),
                        ("WM10", "Ever attended school"), ("WM11", "Highest level of education"),
                        ("CM1", "Ever given birth"), ("CEB", "Children ever born")],
        "join_cn": "HH1 + HH2 + LN（女性行号）",
        "join_en": "HH1 + HH2 + LN (woman's line number)",
        "age_col": "WM9", "age_max": 50, "age_title_cn": "MICS6 受访女性年龄分布（WM9）",
        "age_title_en": "Age Distribution of Women — MICS6 (WM9)",
    },
    "ch": {
        "name_cn": "5岁以下儿童问卷", "name_en": "Under-5 Children's Questionnaire",
        "desc_cn": "每行代表一名5岁以下儿童。主要包含：访谈信息、出生日期与年龄、出生登记（BR*）、疫苗接种（VA*）、急性呼吸道感染（ARI*）、腹泻（CA*）、营养（AN*）等。",
        "desc_en": "One row per child under 5. Key topics: interview info, birth date and age, birth registration (BR*), vaccination (VA*), ARI, diarrhoea (CA*), nutrition (AN*).",
        "needed_cols": ["country", "mics_round", "HH1", "HH2", "LN",
                        "UF4", "UF9", "UF11", "UF8D", "UF8M", "UF8Y",
                        "AG1D", "AG1M", "AG1Y", "AG2", "BR1", "BR2"],
        "key_vars_cn": [("UF9", "访谈结果"), ("UF4", "性别"), ("UF11", "年龄"),
                        ("BR1", "有出生证明"), ("BR2", "已登记")],
        "key_vars_en": [("UF9", "Result of interview"), ("UF4", "Sex"),
                        ("UF11", "Age"), ("BR1", "Has birth certificate"), ("BR2", "Registered")],
        "join_cn": "HH1 + HH2 + LN（儿童行号）",
        "join_en": "HH1 + HH2 + LN (child's line number)",
        "age_col": "UF11", "age_max": 6, "age_title_cn": "MICS6 受访儿童年龄分布（UF11，岁）",
        "age_title_en": "Age Distribution of Children — MICS6 (UF11, years)",
    },
    "bh": {
        "name_cn": "生育史模块", "name_en": "Birth History Module",
        "desc_cn": "每行代表一次出生记录（一名女性可有多行）。主要包含：出生日期（BH4*）、存活状态（BH5）、死亡年龄（BH9*）等。用于计算儿童死亡率指标。",
        "desc_en": "One row per birth (a woman may have multiple rows). Key topics: birth date (BH4*), survival status (BH5), age at death (BH9*). Used to compute child mortality indicators.",
        "needed_cols": ["country", "mics_round", "HH1", "HH2", "LN", "BHLN",
                        "BH2", "BH3", "BH4D", "BH4M", "BH4Y", "BH5", "BH6",
                        "BH9U", "BH9N", "BH10"],
        "key_vars_cn": [("BH2", "出生性别"), ("BH5", "当前存活状态"), ("BH6", "年龄（存活儿）"),
                        ("BH9U", "死亡年龄单位"), ("BH9N", "死亡年龄数值")],
        "key_vars_en": [("BH2", "Sex of birth"), ("BH5", "Survival status"),
                        ("BH6", "Current age (alive)"), ("BH9U", "Age at death unit"),
                        ("BH9N", "Age at death value")],
        "join_cn": "HH1 + HH2 + LN（母亲行号）+ BHLN（出生序号）",
        "join_en": "HH1 + HH2 + LN (mother's line number) + BHLN (birth order)",
        "age_col": None,
    },
    "fs": {
        "name_cn": "基础技能模块（7–14岁儿童）", "name_en": "Foundational Skills Module (Children 7–14)",
        "desc_cn": "每行代表一名7–14岁儿童。主要包含：读写能力、计算能力、学习基础技能评估（FS*）、认知发展（CB*）等。仅存在于MICS5和MICS6。",
        "desc_en": "One row per child aged 7–14. Key topics: literacy, numeracy, foundational learning skills (FS*), cognitive development (CB*). Present in MICS5 and MICS6 only.",
        "needed_cols": ["country", "mics_round", "HH1", "HH2", "LN",
                        "FS4", "FS5", "FS6", "FS9", "FS7D", "FS7M", "FS7Y",
                        "CB2M", "CB2Y"],
        "key_vars_cn": [("FS9", "访谈结果"), ("FS5", "年龄"), ("FS6", "性别")],
        "key_vars_en": [("FS9", "Result of interview"), ("FS5", "Age"), ("FS6", "Sex")],
        "join_cn": "HH1 + HH2 + LN（儿童行号）",
        "join_en": "HH1 + HH2 + LN (child's line number)",
        "age_col": "FS5", "age_max": 16, "age_title_cn": "MICS6 儿童年龄分布（FS5）",
        "age_title_en": "Age Distribution of Children — MICS6 (FS5)",
    },
    "gm": {
        "name_cn": "全球移民模块", "name_en": "Global Migration Module",
        "desc_cn": "每行代表一名受访者（样本量较小）。主要包含：移民相关信息（MG*）、财富指数（windex*）等。仅存在于MICS6。",
        "desc_en": "One row per respondent (small sample). Key topics: migration-related variables (MG*), wealth index (windex*). Present in MICS6 only.",
        "needed_cols": ["country", "mics_round", "HH1", "HH2",
                        "MG3", "MG5", "MG6", "MG9", "MG10",
                        "HH6", "HH7", "windex5", "windex10"],
        "key_vars_cn": [("MG3", "移民状态"), ("MG5", "出发国"), ("MG9", "离开原因"),
                        ("windex5", "财富指数五分位")],
        "key_vars_en": [("MG3", "Migration status"), ("MG5", "Country of departure"),
                        ("MG9", "Reason for leaving"), ("windex5", "Wealth index quintile")],
        "join_cn": "HH1 + HH2",
        "join_en": "HH1 + HH2",
        "age_col": None,
    },
}


def make_fig1(df, module, out_dir, lang):
    rows_pr = df.groupby("mics_round").size().reindex(ROUNDS).fillna(0).astype(int)
    ctry_pr = df.groupby("mics_round")["country"].nunique().reindex(ROUNDS).fillna(0).astype(int)
    cfg = MODULE_CFG[module]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, vals, title in [
        (axes[0], rows_pr, ("各轮次记录数" if lang == "cn" else "Records by Round")),
        (axes[1], ctry_pr, ("各轮次覆盖国家数" if lang == "cn" else "Countries by Round")),
    ]:
        bars = ax.bar(ROUNDS, vals.values,
                      color=[ROUND_COLORS[r] for r in ROUNDS], edgecolor="white")
        ax.bar_label(bars, fmt=lambda x: f"{int(x):,}", padding=3, fontsize=9)
        ax.set_title(title, fontsize=13)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"{x/1e6:.1f}M" if x >= 1e6 else f"{int(x):,}"))
        ax.spines[["top", "right"]].set_visible(False)

    plt.tight_layout()
    path = out_dir / f"fig1_round_overview{'_en' if lang == 'en' else ''}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return rows_pr, ctry_pr


def make_fig2(df, module, out_dir, lang):
    pivot = df.groupby(["country", "mics_round"]).size().unstack(fill_value=0)
    pivot = pivot.reindex(columns=ROUNDS, fill_value=0)
    pivot_bin = (pivot > 0).astype(int)
    top_n = min(50, len(pivot_bin))
    pivot_plot = pivot_bin.sort_values(ROUNDS, ascending=False).head(top_n)

    h = max(6, top_n * 0.22)
    fig, ax = plt.subplots(figsize=(7, h))
    ax.imshow(np.where(pivot_plot.values == 1, 1.0, 0.0),
              aspect="auto", cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(ROUNDS))); ax.set_xticklabels(ROUNDS, fontsize=10)
    ax.set_yticks(range(len(pivot_plot))); ax.set_yticklabels(pivot_plot.index, fontsize=7)
    title = (f"国家-轮次覆盖（前{top_n}个国家）" if lang == "cn"
             else f"Country × Round Coverage (Top {top_n})")
    ax.set_title(title, fontsize=12)
    ax.xaxis.tick_top(); ax.xaxis.set_label_position("top")
    plt.tight_layout()
    path = out_dir / f"fig2_coverage{'_en' if lang == 'en' else ''}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()


def make_fig3_missing(df, module, out_dir, lang):
    cfg = MODULE_CFG[module]
    key_vars = [v for v, _ in cfg[f"key_vars_{lang}"]]
    key_vars = [v for v in key_vars if v in df.columns]
    if not key_vars:
        return
    miss = df[key_vars].isna().mean().sort_values(ascending=True) * 100
    fig, ax = plt.subplots(figsize=(8, max(3, len(key_vars) * 0.55)))
    bars = ax.barh(miss.index, miss.values, color="#159895", edgecolor="white")
    ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
    ax.set_xlabel("Missing Rate (%)" if lang == "en" else "缺失率 (%)")
    ax.set_title(f"{'Key Variable Missing Rate' if lang == 'en' else '关键变量缺失率'} — {module}",
                 fontsize=13)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    path = out_dir / f"fig3_missing{'_en' if lang == 'en' else ''}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()


def make_fig4_age(df, module, out_dir, lang):
    cfg = MODULE_CFG[module]
    age_col = cfg.get("age_col")
    if not age_col or age_col not in df.columns:
        return False
    age = pd.to_numeric(
        df[(df["mics_round"] == "MICS6") & df[age_col].notna()][age_col], errors="coerce"
    ).dropna()
    age_max = cfg.get("age_max", 100)
    age = age[(age >= 0) & (age <= age_max)]
    if len(age) == 0:
        return False
    fig, ax = plt.subplots(figsize=(10, 4))
    bins = range(0, age_max + 2)
    ax.hist(age, bins=bins, color="#1a5276", edgecolor="none", alpha=0.85)
    ax.set_xlabel("Age (years)" if lang == "en" else "年龄（岁）")
    ax.set_ylabel("Count" if lang == "en" else "人数")
    ax.set_title(cfg[f"age_title_{lang}"], fontsize=13)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    path = out_dir / f"fig4_age{'_en' if lang == 'en' else ''}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return True


def build_md(module, lang, df, rows_pr, ctry_pr, n_total_cols, has_age_fig):
    cfg = MODULE_CFG[module]
    is_cn = lang == "cn"
    suf = "" if is_cn else "_en"
    rel = lambda p: f"../etc/{module}/{p}"
    n_rows = len(df)
    n_countries = df["country"].nunique()
    avg_pr = (rows_pr / ctry_pr.replace(0, np.nan)).round(0).fillna(0).astype(int)

    # Header
    if is_cn:
        title = f"# {module} 模块数据报告"
        script = f"> 生成脚本：`MICS/etc/generate_remaining.py`"
        h1 = "## 1. 概览"
        overview_rows = [
            ("总行数", f"{n_rows:,}"),
            ("总列数", f"{n_total_cols:,}"),
            ("覆盖国家/地区数", str(n_countries)),
            ("覆盖轮次", "MICS2 ~ MICS6"),
        ]
        desc = cfg["desc_cn"]
        h2 = "## 2. 各轮次分布"
        tbl_hdr = "| 轮次 | 国家/地区数 | 记录数 | 平均每国记录数 |"
        tbl_sep = "|------|------------|--------|--------------|"
        h3 = "## 3. 国家-轮次覆盖"
        cov_desc = "蓝色=有数据，白色=无数据。"
        h4 = "## 4. 关键变量缺失率"
        miss_desc = "缺失主要来自早期轮次问卷未包含该题。"
        miss_hdr = "| 变量 | 含义 | 缺失率 |"
        miss_sep = "|------|------|--------|"
        h5 = "## 5. 年龄分布（MICS6）" if has_age_fig else None
        h6 = "## 6. 标准核心变量列表" if has_age_fig else "## 5. 标准核心变量列表"
        h7 = "## 7. 使用说明" if has_age_fig else "## 6. 使用说明"
        join_label = "链接键"
        note_label = "注意"
    else:
        title = f"# {module} Module Data Report"
        script = f"> Generation script: `MICS/etc/generate_remaining.py`"
        h1 = "## 1. Overview"
        overview_rows = [
            ("Total rows", f"{n_rows:,}"),
            ("Total columns", f"{n_total_cols:,}"),
            ("Countries/areas covered", str(n_countries)),
            ("Rounds covered", "MICS2 – MICS6"),
        ]
        desc = cfg["desc_en"]
        h2 = "## 2. Distribution by Round"
        tbl_hdr = "| Round | Countries/Areas | Records | Avg. Records/Country |"
        tbl_sep = "|-------|----------------|---------|----------------------|"
        h3 = "## 3. Country × Round Coverage"
        cov_desc = "Blue = data available, White = no data."
        h4 = "## 4. Missing Rate of Key Variables"
        miss_desc = "Missingness mainly reflects questions absent in earlier rounds."
        miss_hdr = "| Variable | Description | Missing Rate |"
        miss_sep = "|----------|-------------|-------------|"
        h5 = "## 5. Age Distribution (MICS6)" if has_age_fig else None
        h6 = "## 6. Standard Core Variables" if has_age_fig else "## 5. Standard Core Variables"
        h7 = "## 7. Usage Notes" if has_age_fig else "## 6. Usage Notes"
        join_label = "Link keys"
        note_label = "Note"

    key_vars = cfg[f"key_vars_{lang}"]
    join_str = cfg[f"join_{lang}"]
    name_str = cfg[f"name_{lang}"]

    lines = [title, "", script, "", "---", "", h1, ""]
    lines += ["| " + r[0] + " | " + r[1] + " |" for r in overview_rows]
    lines = [title, "", script, "", "---", "", h1, ""]
    lines.append(f"| {'指标' if is_cn else 'Metric'} | {'数值' if is_cn else 'Value'} |")
    lines.append("|--------|-------|")
    for k, v in overview_rows:
        lines.append(f"| {k} | {v} |")
    lines += ["", f"**{module} 模块**（{name_str}）{desc}" if is_cn
              else f"The **{module} module** ({name_str}) — {desc}", "", "---", "", h2, ""]
    lines.append(f"![{'各轮次概览' if is_cn else 'Round overview'}]({rel(f'fig1_round_overview{suf}.png')})")
    lines += ["", tbl_hdr, tbl_sep]
    for rnd in ROUNDS:
        r = rows_pr.get(rnd, 0)
        c = ctry_pr.get(rnd, 0)
        a = avg_pr.get(rnd, 0)
        lines.append(f"| {rnd} | {c} | {r:,} | {a:,} |")

    lines += ["", "---", "", h3, ""]
    lines.append(cov_desc)
    lines.append(f"![{'国家-轮次覆盖' if is_cn else 'Country-round coverage'}]({rel(f'fig2_coverage{suf}.png')})")

    lines += ["", "---", "", h4, ""]
    lines.append(miss_desc)
    lines.append(f"![{'关键变量缺失率' if is_cn else 'Missing rate'}]({rel(f'fig3_missing{suf}.png')})")
    lines += ["", miss_hdr, miss_sep]
    for var, lbl in key_vars:
        if var in df.columns:
            rate = df[var].isna().mean() * 100
            lines.append(f"| {var} | {lbl} | {rate:.1f}% |")

    if has_age_fig and h5:
        lines += ["", "---", "", h5, ""]
        lines.append(f"![{'年龄分布' if is_cn else 'Age distribution'}]({rel(f'fig4_age{suf}.png')})")

    std = standard_vars_table(module)
    lines += ["", "---", "", h6, "", std]

    lines += ["", "---", "", h7, ""]
    lines.append(f"- **{join_label}**: `country` + `mics_round` + {join_str}")
    lines.append(f"- **{note_label}**: {'MICS2 变量已按映射字典标准化，早期轮次缺失字段显示为 NaN' if is_cn else 'MICS2 variables have been standardised; fields absent in early rounds appear as NaN'}")

    return "\n".join(lines) + "\n"


# ── Main ──────────────────────────────────────────────────────────────────────
for module, cfg in MODULE_CFG.items():
    print(f"\n{'='*50}")
    print(f"Module: {module}")
    out_dir = ROOT / "etc" / module
    out_dir.mkdir(parents=True, exist_ok=True)

    schema = pq.read_schema(PROCESSED / f"{module}.parquet")
    n_total_cols = len(schema.names)
    available = [c for c in cfg["needed_cols"] if c in schema.names]
    print(f"  Loading {len(available)} cols ...")
    df = pq.read_table(PROCESSED / f"{module}.parquet", columns=available).to_pandas()
    print(f"  Loaded: {len(df):,} rows")

    for lang in ["cn", "en"]:
        font = "Arial Unicode MS" if lang == "cn" else "Arial"
        plt.rcParams["font.family"] = font
        plt.rcParams["axes.unicode_minus"] = False

        rows_pr, ctry_pr = make_fig1(df, module, out_dir, lang)
        make_fig2(df, module, out_dir, lang)
        make_fig3_missing(df, module, out_dir, lang)
        has_age = make_fig4_age(df, module, out_dir, lang)

        md = build_md(module, lang, df, rows_pr, ctry_pr, n_total_cols, has_age)
        suffix = "CN" if lang == "cn" else "EN"
        doc_path = ROOT / "docs" / f"{module}_{suffix}.md"
        doc_path.write_text(md, encoding="utf-8")
        print(f"  [{lang.upper()}] Report → {doc_path}")

    del df

print("\nAll done.")
