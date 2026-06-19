"""MICS Health Dashboard — single-page Streamlit app.

Run:
    streamlit run src/dashboard/app.py
"""
import streamlit as st
import plotly.express as px
import pandas as pd

from db import (
    TABLE_CONFIG,
    get_variable_list,
    get_dataset_summary,
    detect_var_kind,
    get_map_data,
    get_sample_data,
    get_freq_data,
    get_row_counts,
)
from utils import extract_country, extract_round, ALL_ROUNDS

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MICS Health Dashboard",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Apply any pending table double-click before sidebar renders
if "_table_var_pending" in st.session_state:
    st.session_state["_var_selectbox"] = st.session_state.pop("_table_var_pending")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🌍 MICS Explorer")
    st.caption("UNICEF Multiple Indicator Cluster Surveys · MICS2–MICS6")
    st.divider()

    dataset_label = st.selectbox(
        "**Dataset**",
        list(TABLE_CONFIG.keys()),
        help="Select the questionnaire module",
    )
    cfg = TABLE_CONFIG[dataset_label]

    selected_rounds = st.multiselect(
        "**MICS Round (Wave)**",
        ALL_ROUNDS,
        default=ALL_ROUNDS,
        help="Leave all selected to include every wave",
    )
    if not selected_rounds:
        st.warning("Select at least one round.")
        selected_rounds = ALL_ROUNDS

    var_df = get_variable_list(cfg["data"], cfg["index"])
    var_displays = var_df["display"].tolist()

    # Reset table-driven var when dataset switches
    _DS_KEY  = "_active_dataset"
    _VAR_KEY = "_var_selectbox"
    if st.session_state.get(_DS_KEY) != dataset_label:
        st.session_state[_DS_KEY] = dataset_label
        st.session_state.pop(_VAR_KEY, None)

    selected_display = st.selectbox(
        "**Variable (for map)**",
        var_displays,
        key=_VAR_KEY,
        help="Type to search, or click a row in the Overview tab to select",
    )
    sel_row = var_df[var_df["display"] == selected_display].iloc[0]
    selected_varname: str = sel_row["column_name"]

    st.divider()

    apply_btn = st.button(
        "▶  Apply / Compute Map",
        type="primary",
        use_container_width=True,
    )

# ── Session state ─────────────────────────────────────────────────────────────
_MAP_KEY = "map_params"
if apply_btn:
    st.session_state[_MAP_KEY] = {
        "dataset_label": dataset_label,
        "data_table":    cfg["data"],
        "index_table":   cfg["index"],
        "varname":       selected_varname,
        "var_label":     sel_row["label"],
        "measure_type":  sel_row["measure_type"],
        "rounds":        list(selected_rounds),
    }

# ── Page title ────────────────────────────────────────────────────────────────
st.markdown("## 🌍 MICS Women & Children Health Dashboard")
st.caption("UNICEF Multiple Indicator Cluster Surveys · MICS2–MICS6 · Global coverage")
st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# Tab navigation
# ═══════════════════════════════════════════════════════════════════════════════
tab_overview, tab_map = st.tabs(["📋 Dataset Overview", "🗺️ Variable Map"])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Dataset Overview  (auto-loads on dataset selection)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_overview:
    st.subheader(f"📋 Dataset Overview — {dataset_label}")

    with st.spinner("Loading variable summary…"):
        summary_df, total_rows, is_approx = get_dataset_summary(
            cfg["data"], cfg["index"]
        )

    approx_note = " *(estimated from system statistics)*" if is_approx else ""

    c1, c2, c3 = st.columns(3)
    c1.metric("Total rows" + (" (est.)" if is_approx else ""), f"{total_rows:,}")
    c2.metric("Analytic variables", f"{len(summary_df):,}")
    c3.metric(
        "Median coverage",
        f"{summary_df['Coverage %'].median():.1f}%",
        help="Median % of non-null rows across all variables",
    )
    st.caption(
        f"Coverage % = non-null rows / total rows{approx_note}.  "
        "Variables with low coverage are typically only asked of a sub-group "
        "(e.g. women who gave birth recently)."
    )

    sort_c1, sort_c2 = st.columns([3, 1])
    with sort_c1:
        sort_by = st.selectbox(
            "Sort by",
            ["Variable", "Category", "Description", "Valid N", "Coverage %", "Type"],
            index=4,
            label_visibility="collapsed",
        )
    with sort_c2:
        sort_asc = st.radio(
            "Order", ["↓ Desc", "↑ Asc"],
            horizontal=True,
            label_visibility="collapsed",
        ) == "↑ Asc"

    sorted_df = summary_df.sort_values(sort_by, ascending=sort_asc).reset_index(drop=True)

    def _highlight_selected(row):
        if row["Variable"] == selected_varname:
            return ["background-color: #fffacd"] * len(row)
        return [""] * len(row)

    table_sel = st.dataframe(
        sorted_df.style.apply(_highlight_selected, axis=1),
        use_container_width=True,
        height=520,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Variable": st.column_config.TextColumn(
                "Variable",
                help="Canonical variable name (as in the database)",
                width="medium",
            ),
            "Category": st.column_config.TextColumn("Category", width="medium"),
            "Description": st.column_config.TextColumn("Description", width="large"),
            "Valid N": st.column_config.NumberColumn(
                "Valid N", format="%d",
                help="Number of non-null observations",
            ),
            "Coverage %": st.column_config.ProgressColumn(
                "Coverage %",
                min_value=0, max_value=100, format="%.1f%%",
                help="Share of rows with a non-null value",
            ),
            "Type": st.column_config.TextColumn(
                "Type", width="small",
                help="Database storage type: float / integer / text",
            ),
        },
    )

    # Double-click simulation: first click selects row (visual), second click confirms
    if table_sel.selection.rows:
        clicked_col = sorted_df.iloc[table_sel.selection.rows[0]]["Variable"]
        if st.session_state.get("_pending_click") == clicked_col:
            # Second click on same row → sync to sidebar via pending key
            match = var_df[var_df["column_name"] == clicked_col]
            if not match.empty:
                new_display = match["display"].iloc[0]
                st.session_state.pop("_pending_click", None)
                if st.session_state.get("_var_selectbox") != new_display:
                    st.session_state["_table_var_pending"] = new_display
                    st.rerun()
        else:
            # First click → mark as pending
            st.session_state["_pending_click"] = clicked_col
    else:
        st.session_state.pop("_pending_click", None)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Variable Map  (loads on Apply)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_map:
    if _MAP_KEY not in st.session_state:
        st.info(
            "**Select a variable in the sidebar and click ▶ Apply / Compute Map** "
            "to display the choropleth map."
        )
    else:
        p = st.session_state[_MAP_KEY]
        data_table:   str       = p["data_table"]
        varname:      str       = p["varname"]
        var_label:    str       = p["var_label"]
        measure_type: str       = p["measure_type"]
        rounds:       list[str] = p["rounds"]
        ds_label:     str       = p["dataset_label"]

        st.subheader(f"`{varname}` — {var_label}")
        st.caption(
            f"Category: *{measure_type}* · Dataset: *{ds_label}* · "
            f"Rounds: *{', '.join(rounds)}*"
        )

        var_kind = detect_var_kind(data_table, varname)

        if var_kind == "categorical":
            st.info(
                f"**`{varname}`** contains non-numeric text values — "
                "choropleth map is not available.  "
                "The histogram below shows value frequency distribution."
            )
            with st.spinner("Loading value frequencies…"):
                freq_df = get_freq_data(data_table, varname, rounds)
            if freq_df.empty:
                st.warning("No data available for this variable.")
            else:
                fig_freq = px.bar(
                    freq_df,
                    x="val", y="freq",
                    labels={"val": varname, "freq": "Count"},
                    color_discrete_sequence=["#3498db"],
                    text_auto=True,
                )
                fig_freq.update_layout(
                    height=380,
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis_title="Value",
                    yaxis_title="Count",
                    showlegend=False,
                )
                fig_freq.update_traces(
                    marker_line_width=0.5, marker_line_color="white"
                )
                st.plotly_chart(fig_freq, use_container_width=True)
                st.caption(
                    f"Top {len(freq_df)} most frequent values · "
                    f"total non-null: {freq_df['freq'].sum():,}"
                )
        else:
            metric_label = (
                "Proportion of 'Yes' responses (%)"
                if var_kind == "binary"
                else f"Mean value of {varname}"
            )

            with st.spinner("Running country-level aggregation…"):
                raw_df = get_map_data(data_table, varname, rounds, var_kind)

            if raw_df.empty:
                st.error("No data returned — try different rounds or variable.")
            else:
                raw_df = raw_df.copy()
                raw_df["metric"]  = raw_df["metric"].astype(float)
                raw_df["n_valid"] = raw_df["n_valid"].astype(float)
                raw_df["country"] = raw_df["dataset_name"].apply(extract_country)
                raw_df["round"]   = raw_df["dataset_name"].apply(extract_round)
                raw_df = raw_df.dropna(subset=["country"])

                country_df = (
                    raw_df.groupby("country")
                    .apply(lambda g: pd.Series({
                        "metric":  (g["metric"] * g["n_valid"]).sum() / g["n_valid"].sum(),
                        "n_valid": g["n_valid"].sum(),
                        "rounds":  ", ".join(sorted(g["round"].unique())),
                    }))
                    .reset_index()
                )

                if var_kind == "binary":
                    country_df["metric_display"] = (country_df["metric"] * 100).round(1)
                    color_label = "% Yes"
                else:
                    country_df["metric_display"] = country_df["metric"].round(4)
                    color_label = "Mean"

                fig_map = px.choropleth(
                    country_df,
                    locations="country",
                    locationmode="country names",
                    color="metric_display",
                    hover_name="country",
                    hover_data={
                        "n_valid":        ":,",
                        "metric_display": ":.3f",
                        "rounds":         True,
                        "country":        False,
                    },
                    color_continuous_scale="RdYlGn_r",
                    labels={
                        "metric_display": color_label,
                        "n_valid":        "N valid",
                        "rounds":         "Rounds",
                    },
                    title=f"{varname}  —  {metric_label}",
                )
                fig_map.update_layout(
                    geo=dict(
                        showframe=False,
                        showcoastlines=True,
                        projection_type="natural earth",
                        bgcolor="rgba(0,0,0,0)",
                    ),
                    height=500,
                    margin=dict(l=0, r=0, t=40, b=0),
                    paper_bgcolor="rgba(0,0,0,0)",
                    coloraxis_colorbar=dict(title=color_label, thickness=14, len=0.6),
                )
                st.plotly_chart(fig_map, use_container_width=True)

                with st.spinner("Counting valid observations…"):
                    counts = get_row_counts(data_table, varname, rounds, var_kind)

                total_r     = counts["total"]
                valid_r     = counts["valid"]
                cov_pct     = 100 * valid_r / total_r if total_r else 0
                n_countries = country_df["country"].nunique()

                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Total rows (selected waves)", f"{total_r:,}")
                k2.metric("Valid observations",          f"{valid_r:,}")
                k3.metric("Data coverage",               f"{cov_pct:.1f}%")
                k4.metric("Countries on map",            f"{n_countries}")
                if var_kind == "binary":
                    k5.metric("Global avg % Yes",
                              f"{country_df['metric_display'].mean():.1f}%")
                else:
                    k5.metric("Mean across countries",
                              f"{country_df['metric_display'].mean():.3f}")

                st.divider()

                col_hist, col_tbl = st.columns([3, 2], gap="large")

                with col_hist:
                    st.subheader("Distribution")
                    with st.spinner("Sampling data…"):
                        sample_df = get_sample_data(
                            data_table, varname, rounds, var_kind
                        )

                    if sample_df.empty:
                        st.info("No distribution data available.")
                    elif var_kind == "binary":
                        sample_df["Response"] = sample_df["val"].map(
                            {1: "1 — Yes", 2: "2 — No"}
                        )
                        fig_hist = px.bar(
                            sample_df,
                            x="Response", y="freq",
                            color="Response",
                            color_discrete_map={
                                "1 — Yes": "#27ae60", "2 — No": "#e74c3c"
                            },
                            labels={"freq": "Count"},
                            text_auto=True,
                        )
                        fig_hist.update_traces(textfont_size=13)
                    else:
                        fig_hist = px.histogram(
                            sample_df, x="val", nbins=40,
                            labels={"val": varname, "count": "Count"},
                            color_discrete_sequence=["#3498db"],
                            opacity=0.85,
                        )
                        fig_hist.update_traces(
                            marker_line_width=0.5, marker_line_color="white"
                        )

                    if not sample_df.empty:
                        fig_hist.update_layout(
                            showlegend=False,
                            height=300,
                            margin=dict(l=0, r=0, t=10, b=0),
                            xaxis_title=varname,
                            yaxis_title="Count",
                        )
                        st.plotly_chart(fig_hist, use_container_width=True)

                    if var_kind == "numeric" and not sample_df.empty:
                        s = sample_df["val"]
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Min",    f"{s.min():.3f}")
                        m2.metric("Median", f"{s.median():.3f}")
                        m3.metric("Mean",   f"{s.mean():.3f}")
                        m4.metric("Max",    f"{s.max():.3f}")

                with col_tbl:
                    st.subheader("Country Rankings")
                    disp = (
                        country_df[["country", "metric_display", "n_valid", "rounds"]]
                        .sort_values("metric_display", ascending=False)
                        .head(20)
                        .rename(columns={
                            "country":        "Country",
                            "metric_display": color_label,
                            "n_valid":        "N Valid",
                            "rounds":         "Rounds",
                        })
                    )
                    st.dataframe(
                        disp,
                        use_container_width=True,
                        hide_index=True,
                        height=340,
                        column_config={
                            "N Valid": st.column_config.NumberColumn(
                                "N Valid", format="%d"
                            ),
                        },
                    )
                    st.caption(f"Top 20 of {len(country_df)} countries")
