"""
Variable mapping for MICS data harmonisation.

Standard: MICS4/5/6 variable names.

Usage:
  ROUND_RENAME[round][module] = {old_name: standard_name}

Rules:
  - MICS3-6: names are consistent; only 2 linking-key renames needed.
  - MICS2: linking keys + admin + substantive variables mapped below.
  - Any MICS2 variable absent from both this dict and the MICS3-6 standard
    set is dropped during merging.
  - When both PSU and HI1 are present in the same file, HI1 takes precedence
    (they carry the same cluster ID; PSU is dropped).
"""

# ---------------------------------------------------------------------------
# MICS3: two linking-key renames only
# ---------------------------------------------------------------------------
_MICS3: dict[str, dict[str, str]] = {
    "wm": {"WMID": "LN"},
    "ch": {"UFID": "LN"},
}

# ---------------------------------------------------------------------------
# MICS2 — hh module
# HI* structural variables → HH*/HC* standard names
# ---------------------------------------------------------------------------
_MICS2_HH: dict[str, str] = {
    # Linking keys
    "PSU":    "HH1",   # cluster (fallback; overridden by HI1 when both present)
    "HI1":    "HH1",   # cluster number
    "HOUSE":  "HH2",   # household (fallback; overridden by HI2 when both present)
    "HI2":    "HH2",   # household number
    # Interview administration
    "HI3D":   "HH5D",  # day of interview
    "HI3M":   "HH5M",  # month of interview
    "HI3Y":   "HH5Y",  # year of interview
    "HI4":    "HH3",   # interviewer number
    # Interview result and household counts
    "HI10":   "HH9",   # result of HH interview
    "HIMEM":  "HH11",  # number of household members
    "HI11":   "HH12",  # total eligible women 15-49
    "HI12":   "HH13",  # women interviews completed
    "HI13":   "HH14",  # total children under 5
    "HI14":   "HH15",  # child interviews completed
    # Housing characteristics
    "HI8":    "HC3",   # main material of floor
    "HI9":    "HC2",   # number of rooms used for sleeping
}

# ---------------------------------------------------------------------------
# MICS2 — hl module
# Linking keys + systematic variable-number offset vs MICS3+
# ---------------------------------------------------------------------------
_MICS2_HL: dict[str, str] = {
    # Linking keys
    "PSU":   "HH1",
    "HI1":   "HH1",
    "HOUSE": "HH2",
    "HI2":   "HH2",
    # Household member characteristics (offset by 1 vs MICS3+)
    "HL3":   "HL4",    # sex  (MICS3+ HL3 = relationship to head)
    "HL4":   "HL5",    # age  (MICS3+ HL4 = sex, HL5 = age)
    "HL5":   "HL6",    # line number of eligible woman
    "HL6":   "HL7",    # line number of mother — child labour module
    "HL7":   "HL8",    # line number of mother — child health module
    "HL9":   "HLMS",   # marital status
    "HL10":  "HL9",    # mother alive
    "HL11":  "HL10",   # mother's line number in HH
    "HL12":  "HL11",   # father alive
    "HL13":  "HL12",   # father's line number in HH
    # Education (ED14-ED19 → ED1-ED5/ED3A/ED3B)
    "ED14":  "ED1",    # person line number
    "ED15":  "ED2",    # ever attended school
    "ED16A": "ED3A",   # highest level of school attended
    "ED16B": "ED3B",   # highest grade at that level
    "ED17":  "ED4",    # currently attending school
    "ED19":  "ED5",    # days attended school in last week
}

# ---------------------------------------------------------------------------
# MICS2 — wm module
# ---------------------------------------------------------------------------
_MICS2_WM: dict[str, str] = {
    # Linking keys
    "WICLNO": "HH1",   # cluster number
    "WIHHNO": "HH2",   # household number
    "WILNNO": "LN",    # woman's line number
    # Interview administration
    "WI3AM":  "WM8M",  # month of birth
    "WI3AY":  "WM8Y",  # year of birth
    "WI3B":   "WM9",   # age (completed years)
    # Substantive variables below share names with MICS3+ (no rename needed
    # but listed here as documentation):
    # CM1, CM2AD, CM2AM, CM2AY, CM2B, CM3, CM4A, CM4B, CM5, CM6A, CM6B → same
}

# ---------------------------------------------------------------------------
# MICS2 — ch module
# Child ID info shifted from BR* to UF* in MICS3+; BR* numbering also offset
# ---------------------------------------------------------------------------
_MICS2_CH: dict[str, str] = {
    # Linking keys
    "CHCLNO": "HH1",   # cluster number (most countries)
    "CHHHNO": "HH2",   # household number (most countries)
    "HI1":    "HH1",   # cluster (Albania-style countries)
    "HI2":    "HH2",   # household (Albania-style countries)
    "CHLNNO": "LN",    # child line number
    "CHCTNO": "UF6",   # caretaker line number
    # Child demographic info (MICS2 BR* → MICS3+ UF*)
    "BR2":    "UF11",  # age of child
    "BR3D":   "UF10D", # day of birth
    "BR3M":   "UF10M", # month of birth
    "BR3Y":   "UF10Y", # year of birth
    # Birth registration (MICS2 BR4+ offset by 3 vs MICS3+ BR1+)
    "BR4":    "BR1",   # child has birth certificate
    "BR5":    "BR2",   # child registered
    "BR6":    "BR3",   # reason birth not registered
    "BR7":    "BR4",   # know how to register birth
    # Early childhood education (MICS2 BR8-BR9 → MICS3+ BR6-BR7)
    "BR8":    "BR6",   # child attends early childhood education
    "BR9":    "BR7",   # hours attended ECE in last 7 days
}

# ---------------------------------------------------------------------------
# MICS2 — bh module (birth history)
# Linking keys follow wm pattern
# ---------------------------------------------------------------------------
_MICS2_BH: dict[str, str] = {
    "WICLNO": "HH1",
    "WIHHNO": "HH2",
    "WILNNO": "LN",
}

# ---------------------------------------------------------------------------
# Combined lookup: ROUND_RENAME[round][module][old] → standard
# ---------------------------------------------------------------------------
ROUND_RENAME: dict[str, dict[str, dict[str, str]]] = {
    "MICS2": {
        "hh": _MICS2_HH,
        "hl": _MICS2_HL,
        "wm": _MICS2_WM,
        "ch": _MICS2_CH,
        "bh": _MICS2_BH,
    },
    "MICS3": _MICS3,
}
