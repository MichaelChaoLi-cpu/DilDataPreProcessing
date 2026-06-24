# MJ01: Determinants of Child Stunting — Maternal, Socioeconomic, and Urban-Rural Inequality

## Research Question

What are the socioeconomic and maternal determinants of child stunting (HAZ < −2), and how do urban-rural disparities and country development levels shape these outcomes across the globe?

## Background

Child stunting (low height-for-age) is a long-run marker of chronic undernutrition and cumulative deprivation. It reflects not only dietary inadequacy but also access to healthcare, sanitation, maternal human capital, and household resources. From a development economics perspective, stunting encodes the intergenerational transmission of poverty: a mother's education, access to antenatal care, and household wealth all shape the nutritional trajectory of her child.

MICS (Multiple Indicator Cluster Surveys) provides harmonised cross-sectional data across 60+ countries spanning MICS2–MICS6, covering both high- and low-income settings, making it well-suited for cross-country inequality analysis.

## Data Sources

| Table | Module | Key |
|-------|--------|-----|
| `final_CH_MICS2MICS6` | Children (CH) | `dataset_name`, `cluster_number`, `household_number`, `child_line_number` |
| `final_WM_MICS2MICS6` | Women (WM) | `dataset_name`, `cluster_number`, `hh_number`, `woman_line_number` |

**Linkage:** `CH.dataset_name = WM.dataset_name AND CH.cluster_number = WM.cluster_number AND CH.household_number = WM.hh_number AND CH.mother_caretaker_line_number = WM.woman_line_number`

## Variable List

### Outcome (from CH)
| Variable | Description |
|----------|-------------|
| `height_for_age_zscore` | HAZ score (continuous); stunting = HAZ < −2 |
| `weight_for_age_zscore` | WAZ score (underweight = WAZ < −2) |
| `weight_for_height_zscore` | WHZ score (wasting = WHZ < −2) |

### Child Controls (from CH)
| Variable | Description |
|----------|-------------|
| `sex_of_child` | Sex |
| `child_age_months` | Age in months |
| `child_sample_weight` | Survey sample weight |
| `interview_year` | Survey year |
| `area` | Urban / rural |
| `region` | Subnational region |
| `wealth_index_quintile` | Household wealth quintile |
| `mother_education` | Mother's education level (from CH) |
| `ever_breastfed` | Child ever breastfed |
| `still_breastfeeding` | Currently breastfeeding |

### Maternal Characteristics (from WM)
| Variable | Description |
|----------|-------------|
| `education_level` | Mother's highest education level |
| `woman_age` | Mother's age |
| `literacy` | Literacy (reads part of sentence) |
| `currently_married_or_cohabiting` | Marital status |
| `received_anc` | Received any antenatal care |
| `anc_visits` | Number of ANC visits |
| `ever_breastfed` | Mother ever breastfed (WM module) |
| `media_tv_frequency` | TV watching frequency (information access proxy) |
| `wealth_quintile` | Wealth quintile from WM |
| `women_sample_weight` | Women's sample weight |

## Analytical Framework

1. **Descriptive inequality**: Stunting prevalence by wealth quintile, urban/rural, education level, and country income group (using `dataset_name` to map to country-level development status).
2. **Regression analysis**: OLS on HAZ (continuous) and logistic regression on stunting dummy (HAZ < −2), with mother's education, wealth, and urban/rural as key exposures; child age/sex, ANC, breastfeeding as controls. Survey weights applied.
3. **Cross-country heterogeneity**: Examine whether the education–stunting gradient differs between low-income and middle/high-income countries.

## Notes

- HH and HL modules are excluded from this initial analysis. Most household-level controls are already available within WM and CH.
- Future extension (MJ02): Link with CMIP6 climate variables at cluster level to examine climate stress as an additional exposure (heat, drought, precipitation anomaly).
- The pull script (`pull_data.py`) outputs a single merged Parquet file to `data/mj01_analysis.parquet`.
