# housing-data-profiles

Housing data profiles for every U.S. state and county, and for the cities and towns in any
state you choose, built only from public Census Bureau and HUD files. **No API key, no
third-party packages, one Python file.**

Each profile covers the numbers a housing needs assessment usually starts with:

- **People and households:** population, owner and renter households, renter share
- **Stock and vacancy:** housing units, vacancy rate, rental and homeowner vacancy rates,
  seasonal/recreational units
- **Structure type and age:** single-family, 2-4 unit, 5+ unit and mobile-home shares;
  units built since 2010 and before 1980
- **Incomes, rents and values:** median household income (all, owners, renters), median
  gross rent, median home value
- **Affordability:** the income needed to rent at the median without cost burden, renter
  income against that need, value-to-income ratio, and the share of renters and owners who
  are cost-burdened (30%+) or severely cost-burdened (50%+)
- **Cost burden by income (new in 0.3.0):** from HUD's CHAS data, how many households in
  each income band (0-30%, 30-50%, 50-80%, 80-100% and over 100% of HUD Area Median Family
  Income) pay more than 30% or more than 50% of income for housing, with renters shown
  separately and a total for all households at or under 80% of area median income
- **New supply:** housing units authorized by building permits, by year and structure type,
  with an annual rate per 1,000 existing units, for states, counties and every city or town
  that issues its own permits

Every number shows the table cell it came from and its formula. ACS margins of error are
kept, and they are carried into derived shares with the Census Bureau's approximation
formulas, so nothing reads as more precise than the survey allows.

## Run it

Python 3.9+ and nothing else:

```sh
python housing_profile.py --states all --detail-states CO --out reports
python housing_profile.py --states UT,ID --detail-states UT --places-min-pop 2500
python -m unittest -v
```

The first run downloads the national ACS table files (about 500 MB) and HUD's CHAS zips into
`.cache/`. After that, any state runs in seconds.

| Option | Default | Meaning |
|---|---|---|
| `--states` | `all` | States in the CSV summaries (`CO,UT` or `08,49`) |
| `--detail-states` | none | States that also get one profile per county and place |
| `--places-min-pop` | 1000 | Smallest place included in detail states |
| `--acs-year` | 2024 | Last year of the ACS 5-year period (2024 = 2020-2024) |
| `--permit-years` | 2016-2025 | Building permit years; missing years are skipped |
| `--chas-period` | `2018thru2022` | HUD CHAS period; pass `""` to skip CHAS |
| `--chas-levels` | `040,050,160` | CHAS summary levels: states, counties, places |

If HUD's site refuses the scripted CHAS download, the run carries on without CHAS and says so.
You can then download the zips yourself from the
[CHAS page](https://www.huduser.gov/portal/datasets/cp.html) (2018-2022; State, County and
Place) and put them in `.cache/` under their original names, for example
`.cache/2018thru2022-050-csv.zip`.

Output (in `--out`):

- `states.csv` and `counties.csv`: one row per state and county, with every metric and its
  margin of error, plus the CHAS columns (`chas_<band>_<field>`, bands `le30`, `30_50`,
  `50_80`, `le80` and `all`)
- `<ST>/` for each detail state: a Markdown and JSON profile for the state, each county and
  each place above the population cutoff, plus `counties.csv`, `places.csv` and an index
  `README.md`

## Colorado first

Under SB24-174, Colorado local governments that meet the population thresholds must complete
a housing needs assessment by **December 31, 2026**, using the Department of Local Affairs
(DOLA) methodology. `--detail-states CO` gives a free, reproducible starting data set for
that work: the state, all 64 counties and every place with 1,000+ residents, including each
town's own building permits for 2016-2025 and cost burden by income band. These are **not** a
complete or DOLA-approved assessment. DOLA's guidance and the State Demography Office's data
are the official sources for compliance.

## Monthly report build

[`docs/refresh-workflow.yml`](docs/refresh-workflow.yml) is a GitHub Actions workflow that
runs the tests, rebuilds `reports/` for all states with Colorado in detail, and commits any
change, once a month. Copy it to `.github/workflows/refresh.yml` in your fork (or here) to
turn it on.

## Sources

| Data | File | Notes |
|---|---|---|
| American Community Survey 5-year, tables B01003, B19013, B25001-B25004, B25024, B25034, B25064, B25070, B25077, B25091, B25119 | `www2.census.gov/programs-surveys/acs/summary_file/<year>/table-based-SF/data/5YRData/` | Table-based summary files; no key needed |
| ACS geography names | `.../table-based-SF/documentation/Geos<year>5YR.txt` | |
| Building Permits Survey, annual county estimates | `www2.census.gov/econ/bps/County/co<year>a.txt` | Units by structure type (1, 2, 3-4, 5+) |
| Building Permits Survey, annual place estimates | `www2.census.gov/econ/bps/Place/<Region> Region/<ne,mw,so,we><year>a.txt` | One file per Census region; matched to ACS places by FIPS place code |
| HUD CHAS, Table 8 (tenure by income by cost burden) | `www.huduser.gov/portal/datasets/cp/<period>-<level>-csv.zip` | Special tabulation of the ACS; matched by FIPS code |

## Definitions and limits

- **Cost-burdened (ACS):** paying 30% or more of household income on gross rent (renters,
  B25070) or on selected monthly owner costs (owners, B25091). **Severely:** 50% or more.
  Households whose ratio cannot be computed are left out of the denominator.
- **Cost-burdened (CHAS):** HUD's definition, housing costs over 30% (severely, over 50%) of
  income. As in HUD's own CHAS summaries, the share's denominator is every household in the
  income band, including those whose cost burden is not computed. CHAS covers an earlier ACS
  period (2018-2022) than the other figures and HUD rounds its counts, so the CHAS and ACS
  shares will not match exactly. HAMFI is HUD Area Median Family Income.
- **CHAS Table 8 layout used:** owners start at column 2 and renters at column 68; the five
  income bands start at columns 3, 16, 29, 42, 55 (owners) and 69, 82, 95, 108, 121
  (renters); inside a band that starts at column s, s+4 is a cost burden over 30% to 50% and
  s+7 over 50%. This was checked against HUD's published field definitions and derived totals
  for Weld County, Colorado (for example, 20,990 cost-burdened and 11,110 severely
  cost-burdened households at or under 80% of HAMFI), which the tests reproduce.
- **Income needed for median rent:** median gross rent x 12 / 0.30.
- **Rental vacancy rate:** units for rent / (renter-occupied + rented, not occupied + for rent),
  the Census Bureau's definition. The homeowner rate is built the same way from for-sale units.
- ACS 5-year figures are period estimates from a sample survey. For small places, check the
  margins of error before drawing conclusions.
- Building permit counts are Census Bureau estimates (reported plus imputed) for permit-issuing
  offices only. A state's figure is the sum of its county estimates. Connecticut's planning
  regions replaced its counties in recent files, so its county permit history before 2022 does
  not line up, and CHAS 2018-2022 may still use the old Connecticut counties.
- **Place permits** come from the permit office whose FIPS place code matches the ACS place.
  Unincorporated county areas (FIPS place 99990) and county-wide offices (00000) are not
  places, so they only count toward their county. A town whose permits are issued by its
  county has no place permit section. In New England and other states where townships
  (minor civil divisions) issue permits, many offices have no FIPS place code and are skipped.
- These are informational data profiles. They are not legal, compliance or investment advice.

## Changes

- **0.3.0:** cost burden by household income band from HUD CHAS Table 8 (states, counties and
  places), in the Markdown, JSON and CSV outputs; a CHAS download that fails is skipped
  instead of stopping the run.
- **0.2.0:** building permits for cities and towns from the BPS annual place files; state
  permit totals now count county records only; the report workflow moved to
  `docs/refresh-workflow.yml`.
- **0.1.0:** first version (prepared, not published).

## About

Made by MV2 of Munim, Inc., with AI agents. The code is tested on fixtures that mirror the
real Census and HUD file layouts. Issues and corrections are welcome. MIT license.

This product uses Census Bureau data but is not endorsed or certified by the Census Bureau.
It also uses HUD CHAS data and is not endorsed by HUD.
