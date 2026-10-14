#!/usr/bin/env python3
"""housing_profile.py - housing data profiles for U.S. states, counties and places,
built only from public Census Bureau and HUD files. No API key, no third-party packages.

Sources:
  * American Community Survey (ACS) 5-year table-based summary files
    https://www2.census.gov/programs-surveys/acs/summary_file/<year>/table-based-SF/
  * Building Permits Survey (BPS) annual county files
    https://www2.census.gov/econ/bps/County/co<year>a.txt
  * Building Permits Survey (BPS) annual place files, one per Census region
    https://www2.census.gov/econ/bps/Place/<Region> Region/<ne|mw|so|we><year>a.txt
  * HUD Comprehensive Housing Affordability Strategy (CHAS) data, Table 8
    https://www.huduser.gov/portal/datasets/cp.html

Every metric carries its source table and formula, and ACS margins of error are kept
(and propagated for derived shares, using the Census Bureau's approximation formulas).

By MV2 of Munim, Inc. Made with AI agents. MIT license.
This product uses Census Bureau data but is not endorsed or certified by the Census Bureau.
It also uses HUD CHAS data and is not endorsed by HUD.
"""

import argparse
import csv
import datetime
import json
import math
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile

__version__ = "0.3.1"

REPO_URL = "https://github.com/munimv2/housing-data-profiles"
USER_AGENT = "housing-data-profiles/%s (MV2 of Munim, Inc.; %s)" % (__version__, REPO_URL)

ACS_BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/{year}/table-based-SF/"
ACS_TABLE_URL = ACS_BASE + "data/5YRData/acsdt5y{year}-{table}.dat"
ACS_GEOS_URL = ACS_BASE + "documentation/Geos{year}5YR.txt"
BPS_COUNTY_URL = "https://www2.census.gov/econ/bps/County/co{year}a.txt"
BPS_PLACE_URL = "https://www2.census.gov/econ/bps/Place/{region}%20Region/{prefix}{year}a.txt"
CHAS_URL = "https://www.huduser.gov/portal/datasets/cp/{period}-{level}-csv.zip"
CHAS_PAGE = "https://www.huduser.gov/portal/datasets/cp.html"

DEFAULT_ACS_YEAR = 2024
DEFAULT_PERMIT_YEARS = "2016-2025"
DEFAULT_CHAS_PERIOD = "2018thru2022"
DEFAULT_CHAS_LEVELS = "040,050,160"   # states, counties, places

# ACS table -> the line numbers this tool reads from it.
NEEDED_LINES = {
    "b01003": [1],                  # total population
    "b25001": [1],                  # housing units
    "b25002": [1, 2, 3],            # occupancy status
    "b25003": [1, 2, 3],            # tenure
    "b25004": [1, 2, 3, 4, 5, 6],   # vacancy status
    "b19013": [1],                  # median household income
    "b25119": [1, 2, 3],            # median household income by tenure
    "b25064": [1],                  # median gross rent
    "b25077": [1],                  # median value (owner-occupied)
    "b25070": list(range(1, 12)),   # gross rent as a percentage of household income
    "b25091": list(range(1, 24)),   # mortgage status by owner costs as a percentage of income
    "b25024": list(range(1, 12)),   # units in structure
    "b25034": list(range(1, 12)),   # year structure built
}
ACS_TABLES = list(NEEDED_LINES)

# ACS medians that fall in the open-ended bottom or top interval are published as these "jam"
# values, with no margin of error: a median home value of 2000001 means "$2,000,000 or more".
# (bottom, top) per table.
ACS_JAM_VALUES = {
    "b19013": (2499, 250001),
    "b25119": (2499, 250001),
    "b25064": (99, 3501),
    "b25077": (9999, 2000001),
}

SUMLEVEL_PREFIX = {"state": "0400000US", "county": "0500000US", "place": "1600000US"}
LEVEL_ORDER = {"state": 0, "county": 1, "place": 2}

STATES = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT",
    "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL",
    "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD",
    "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE",
    "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
    "55": "WI", "56": "WY", "72": "PR",
}
ABBR_TO_FIPS = {abbr: fips for fips, abbr in STATES.items()}

# Census regions, which is how the BPS place files are split. Puerto Rico has no place file.
CENSUS_REGIONS = {
    "Northeast": "09 23 25 33 34 36 42 44 50",
    "Midwest": "17 18 19 20 26 27 29 31 38 39 46 55",
    "South": "01 05 10 11 12 13 21 22 24 28 37 40 45 47 48 51 54",
    "West": "02 04 06 08 15 16 30 32 35 41 49 53 56",
}
STATE_REGION = {fips: region for region, codes in CENSUS_REGIONS.items() for fips in codes.split()}
BPS_REGION_PREFIX = {"Northeast": "ne", "Midwest": "mw", "South": "so", "West": "we"}

# (section title, [metric keys]) in display order.
SECTIONS = [
    ("People and households", [
        "population", "occupied_units", "owner_households", "renter_households", "renter_share",
    ]),
    ("Housing stock and vacancy", [
        "housing_units", "vacant_units", "vacancy_rate", "rental_vacancy_rate",
        "homeowner_vacancy_rate", "seasonal_vacant_units", "seasonal_share_of_units",
    ]),
    ("Structure type and age", [
        "single_family_share", "two_to_four_share", "five_plus_share", "mobile_home_share",
        "built_2010_or_later_share", "built_before_1980_share",
    ]),
    ("Incomes, rents and values", [
        "median_household_income", "median_owner_income", "median_renter_income",
        "median_gross_rent", "median_home_value",
    ]),
    ("Affordability", [
        "income_needed_for_median_rent", "renter_income_to_needed_ratio", "value_to_income_ratio",
        "rent_burdened_households", "rent_burdened_share", "severely_rent_burdened_share",
        "owner_burdened_share", "severely_owner_burdened_share",
    ]),
]
METRIC_KEYS = [key for _, keys in SECTIONS for key in keys]
# Metrics that are medians, or built from medians, and so can be open-ended bounds.
BOUND_KEYS = [
    "median_household_income", "median_owner_income", "median_renter_income", "median_gross_rent",
    "median_home_value", "income_needed_for_median_rent", "renter_income_to_needed_ratio",
    "value_to_income_ratio",
]

PERMIT_FIELDS = ["units_1", "units_2", "units_3_4", "units_5plus", "bldgs_5plus", "value"]

# HUD CHAS Table 8 is tenure by household income (as a share of HUD Area Median Family Income,
# HAMFI) by housing cost burden by complete kitchen and plumbing facilities. Owners start at
# column 2 and renters at column 68; each income band takes 13 columns. Inside a band that
# starts at column s, columns s+4 and s+7 are the households with a cost burden over 30% to 50%
# and over 50% (s+1 and s+10 are 30% or less and not computed).
# (key, label, owner band start, renter band start)
CHAS_BANDS = [
    ("le30", "0-30% of HAMFI (extremely low income)", 3, 69),
    ("30_50", "30-50% of HAMFI (very low income)", 16, 82),
    ("50_80", "50-80% of HAMFI (low income)", 29, 95),
    ("80_100", "80-100% of HAMFI", 42, 108),
    ("gt100", "Over 100% of HAMFI", 55, 121),
]
CHAS_CB_30_50, CHAS_CB_50 = 4, 7
# (key, label, band keys) in display order.
CHAS_GROUPS = [(key, label, [key]) for key, label, _, _ in CHAS_BANDS] + [
    ("le80", "All households at or under 80% of HAMFI", ["le30", "30_50", "50_80"]),
    ("all", "All households", [key for key, _, _, _ in CHAS_BANDS]),
]
CHAS_CSV_GROUPS = ["le30", "30_50", "50_80", "le80", "all"]
CHAS_CSV_FIELDS = ["households", "renter_households", "cost_burdened", "cost_burdened_share",
                   "severely_cost_burdened", "severely_cost_burdened_share"]


# ---------------------------------------------------------------- parsing

def parse_value(raw, is_moe=False):
    """One summary-file cell -> float or None. Census uses large negative codes for
    'not available'; -555555555 on a margin of error means the estimate is controlled
    (no sampling error), which is treated as a margin of error of 0."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= -100000000:
        if is_moe and int(value) == -555555555:
            return 0.0
        return None
    return value


def iter_text_lines(path):
    """Yield the lines of a text file, decoding each as UTF-8 and falling back to Latin-1."""
    with open(path, "rb") as fh:
        for raw in fh:
            try:
                yield raw.decode("utf-8")
            except UnicodeDecodeError:
                yield raw.decode("latin-1")


def acs_column(table, line, moe=False):
    return "%s_%s%03d" % (table.upper(), "M" if moe else "E", line)


def read_acs_table(lines, prefixes, wanted=None, columns=None):
    """Parse one ACS table-based summary file (pipe-delimited, header row first).
    Keeps rows whose GEO_ID starts with one of `prefixes` (and is in `wanted`, if given),
    and only the columns in `columns`, if given. Returns {GEO_ID: {column: value}}."""
    it = iter(lines)
    try:
        header = next(it).rstrip("\r\n").lstrip("﻿").split("|")
    except StopIteration:
        return {}
    keep = [(i, col, "_M" in col) for i, col in enumerate(header)
            if i > 0 and (columns is None or col in columns)]
    out = {}
    for line in it:
        if not line.startswith(prefixes):
            continue
        parts = line.rstrip("\r\n").split("|")
        geo_id = parts[0]
        if wanted is not None and geo_id not in wanted:
            continue
        out[geo_id] = {col: parse_value(parts[i] if i < len(parts) else "", is_moe)
                       for i, col, is_moe in keep}
    return out


def read_geos(lines, prefixes, wanted=None):
    """Parse the ACS geography file (pipe-delimited) -> {GEO_ID: NAME}."""
    it = iter(lines)
    try:
        header = next(it).rstrip("\r\n").lstrip("﻿").split("|")
    except StopIteration:
        return {}
    i_geo, i_name = header.index("GEO_ID"), header.index("NAME")
    out = {}
    for line in it:
        parts = line.rstrip("\r\n").split("|")
        if len(parts) <= max(i_geo, i_name):
            continue
        geo_id = parts[i_geo]
        if not geo_id.startswith(prefixes):
            continue
        if wanted is not None and geo_id not in wanted:
            continue
        out[geo_id] = parts[i_name].strip()
    return out


def _permit_record(year, name, nums):
    """Twelve BPS estimate columns (buildings, units and value for 1-unit, 2-unit, 3-4 unit
    and 5+ unit structures) -> one permit record."""
    rec = {
        "year": year,
        "name": name,
        "units_1": nums[1],
        "units_2": nums[4],
        "units_3_4": nums[7],
        "units_5plus": nums[10],
        "bldgs_5plus": nums[9],
        "value": nums[2] + nums[5] + nums[8] + nums[11],
    }
    rec["units_total"] = rec["units_1"] + rec["units_2"] + rec["units_3_4"] + rec["units_5plus"]
    return rec


def read_bps_county(lines, states=None):
    """Parse a Building Permits Survey annual county file -> {5-digit FIPS: record}.
    Columns: survey date, state FIPS, county FIPS, region, division, county name, then
    buildings/units/value for 1-unit, 2-unit, 3-4 unit and 5+ unit structures (estimates),
    then the same twelve columns for reported-only counts (ignored here)."""
    out = {}
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 18 or not parts[0].isdigit() or len(parts[0]) not in (4, 6):
            continue
        try:
            nums = [int(float(p or 0)) for p in parts[6:18]]
        except ValueError:
            continue
        state, county = parts[1].zfill(2), parts[2].zfill(3)
        if states is not None and state not in states:
            continue
        out[state + county] = _permit_record(int(parts[0][:4]), parts[5], nums)
    return out


def read_bps_place(lines, states=None):
    """Parse a Building Permits Survey annual place file -> {state FIPS + 5-digit FIPS place: record}.
    Columns: survey date, state FIPS, BPS ID, county FIPS, Census place code, FIPS place, FIPS MCD,
    population, CSA, CBSA, footnote, central city, zip, region, division, months reported, name,
    then the same 24 permit columns as the county file. Permit offices with no FIPS place (county
    unincorporated areas use 99990, some county-wide offices 00000) are skipped, and rows that
    share a place code are added together."""
    out = {}
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 29 or not parts[0].isdigit() or len(parts[0]) not in (4, 6):
            continue
        place = parts[5]
        if not place.isdigit() or place in ("00000", "99990"):
            continue
        state = parts[1].zfill(2)
        if states is not None and state not in states:
            continue
        try:
            nums = [int(float(p or 0)) for p in parts[17:29]]
        except ValueError:
            continue
        rec = _permit_record(int(parts[0][:4]), parts[16], nums)
        key = state + place.zfill(5)
        prev = out.get(key)
        if prev is None:
            out[key] = rec
            continue
        for field in PERMIT_FIELDS + ["units_total"]:
            prev[field] += rec[field]
    return out


def chas_fips(geoid):
    """CHAS geoid ('05000US08123', '16000US0820000') -> FIPS code ('08123', '0820000')."""
    geoid = (geoid or "").strip()
    if "US" in geoid:
        return geoid.split("US", 1)[1]
    return geoid if geoid.isdigit() else ""


def read_chas_table8(lines, wanted=None):
    """Parse a CHAS Table8.csv (comma-delimited, header row first, columns source, sumlevel,
    geoid, name, ... then T8_est<n> and T8_moe<n>) -> {FIPS: {"est": {n: value}, "moe": {n: value}}},
    keeping only FIPS codes in `wanted`, if given. Column names are matched in any case."""
    reader = csv.reader(lines)
    try:
        header = [h.strip().lstrip("﻿").lower() for h in next(reader)]
    except StopIteration:
        return {}
    if "geoid" not in header:
        raise ValueError("CHAS Table 8 file has no geoid column")
    i_geo = header.index("geoid")
    cols = []
    for i, name in enumerate(header):
        match = re.match(r"t8_(est|moe)(\d+)$", name)
        if match:
            cols.append((i, match.group(1), int(match.group(2))))
    out = {}
    for parts in reader:
        if len(parts) <= i_geo:
            continue
        fips = chas_fips(parts[i_geo])
        if not fips or (wanted is not None and fips not in wanted):
            continue
        row = {"est": {}, "moe": {}}
        for i, kind, n in cols:
            row[kind][n] = parse_value(parts[i] if i < len(parts) else "")
        out[fips] = row
    return out


def chas_table8_lines(zip_path):
    """The lines of Table8.csv inside a CHAS download zip (any folder inside the zip)."""
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.replace("\\", "/").rsplit("/", 1)[-1].lower() == "table8.csv"]
        if not names:
            raise ValueError("no Table8.csv in %s" % zip_path)
        data = zf.read(names[0])
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.splitlines()


# ---------------------------------------------------------------- arithmetic

def _sum(values):
    values = list(values)
    if not values or any(v is None for v in values):
        return None
    return float(sum(values))


def _diff(a, *rest):
    if a is None or any(v is None for v in rest):
        return None
    return float(a - sum(rest))


def _ratio(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


def moe_sum(moes):
    """Margin of error of a sum or difference of estimates: square root of the sum of squares."""
    moes = list(moes)
    if not moes or any(m is None for m in moes):
        return None
    return math.sqrt(sum(m * m for m in moes))


def moe_proportion(num, den, moe_num, moe_den):
    """Margin of error of a proportion num/den (Census Bureau ACS handbook formula). If the
    value under the square root is negative, the ratio formula is used instead, as advised."""
    if None in (num, den, moe_num, moe_den) or den == 0:
        return None
    p = num / den
    radicand = moe_num ** 2 - p * p * moe_den ** 2
    if radicand < 0:
        radicand = moe_num ** 2 + p * p * moe_den ** 2
    return math.sqrt(radicand) / den


def acs_bound(table, value, moe):
    """An ACS median -> (value, bound). A median published at its table's jam value with no
    margin of error is in an open-ended interval: it becomes the interval's edge, with bound
    'at_least' (top) or 'at_most' (bottom). Any other value is returned with bound None."""
    jam = ACS_JAM_VALUES.get(table)
    if jam is None or value is None or moe is not None:
        return value, None
    if value == jam[1]:
        return value - 1, "at_least"
    if value == jam[0]:
        return value + 1, "at_most"
    return value, None


def ratio_bound(num_bound, den_bound):
    """The bound of num/den when either is an open-ended median: 'at_least', 'at_most', None
    (exact) or 'unknown' (the two pull in opposite directions, so the ratio is not known)."""
    flipped = {"at_least": "at_most", "at_most": "at_least"}.get(den_bound)
    if num_bound and flipped and num_bound != flipped:
        return "unknown"
    return num_bound or flipped


# ---------------------------------------------------------------- profiles

def level_of(geo_id):
    for level, prefix in SUMLEVEL_PREFIX.items():
        if geo_id.startswith(prefix):
            return level
    return "other"


def fips_of(geo_id):
    return geo_id.split("US", 1)[1] if "US" in geo_id else geo_id


def permit_series(permits_by_year, fips):
    """Yearly permit records for a county (5-digit FIPS), a place (7-digit FIPS) or a state
    (2-digit FIPS; the sum of its county estimates only, so places are not counted twice).
    Geographies with no record get an empty list."""
    series = []
    for year in sorted(permits_by_year):
        recs = permits_by_year[year]
        if len(fips) in (5, 7):
            rec = recs.get(fips)
            if rec is None:
                continue
            row = {field: rec[field] for field in PERMIT_FIELDS}
        elif len(fips) == 2:
            matching = [rec for code, rec in recs.items() if len(code) == 5 and code[:2] == fips]
            if not matching:
                continue
            row = {field: sum(rec[field] for rec in matching) for field in PERMIT_FIELDS}
        else:
            continue
        row["year"] = year
        row["units_total"] = row["units_1"] + row["units_2"] + row["units_3_4"] + row["units_5plus"]
        series.append(row)
    return series


def summarize_permits(series, housing_units):
    if not series:
        return None
    total = sum(r["units_total"] for r in series)
    multi = sum(r["units_2"] + r["units_3_4"] + r["units_5plus"] for r in series)
    avg = total / len(series)
    per_1000 = _ratio(avg * 1000, housing_units)
    return {
        "years": [r["year"] for r in series],
        "by_year": [{
            "year": r["year"],
            "units_total": r["units_total"],
            "units_1": r["units_1"],
            "units_2_4": r["units_2"] + r["units_3_4"],
            "units_5plus": r["units_5plus"],
        } for r in series],
        "total_units": total,
        "avg_annual_units": round(avg, 1),
        "multifamily_share": round(multi / total, 4) if total else None,
        "avg_annual_per_1000_units": round(per_1000, 2) if per_1000 is not None else None,
    }


def chas_period_label(period):
    return (period or "").replace("thru", "-")


def chas_group(row, band_keys):
    """Households, renters and cost-burdened counts and shares for some CHAS income bands.
    As in HUD's own CHAS summaries, the shares' denominator is all households in the bands,
    including those whose cost burden could not be computed."""
    starts = {key: (owner, renter) for key, _, owner, renter in CHAS_BANDS}
    owner_starts = [starts[k][0] for k in band_keys]
    renter_starts = [starts[k][1] for k in band_keys]
    all_starts = owner_starts + renter_starts

    def total(cols):
        return (_sum(row["est"].get(c) for c in cols), moe_sum(row["moe"].get(c) for c in cols))

    households, households_moe = total(all_starts)
    renters, renters_moe = total(renter_starts)
    burdened, burdened_moe = total([s + off for s in all_starts for off in (CHAS_CB_30_50, CHAS_CB_50)])
    severe, severe_moe = total([s + CHAS_CB_50 for s in all_starts])
    renter_burdened, _ = total([s + off for s in renter_starts for off in (CHAS_CB_30_50, CHAS_CB_50)])
    return {
        "households": _clean(households, "count"),
        "households_moe": _clean(households_moe, "count"),
        "renter_households": _clean(renters, "count"),
        "renter_households_moe": _clean(renters_moe, "count"),
        "cost_burdened": _clean(burdened, "count"),
        "cost_burdened_moe": _clean(burdened_moe, "count"),
        "cost_burdened_share": _clean(_ratio(burdened, households), "share"),
        "cost_burdened_share_moe": _clean(
            moe_proportion(burdened, households, burdened_moe, households_moe), "share"),
        "severely_cost_burdened": _clean(severe, "count"),
        "severely_cost_burdened_moe": _clean(severe_moe, "count"),
        "severely_cost_burdened_share": _clean(_ratio(severe, households), "share"),
        "severely_cost_burdened_share_moe": _clean(
            moe_proportion(severe, households, severe_moe, households_moe), "share"),
        "renter_cost_burdened": _clean(renter_burdened, "count"),
    }


def chas_summary(row, period=DEFAULT_CHAS_PERIOD):
    """One geography's CHAS Table 8 row -> cost burden by income band, or None."""
    if not row:
        return None
    groups = []
    for key, label, band_keys in CHAS_GROUPS:
        group = {"key": key, "label": label}
        group.update(chas_group(row, band_keys))
        groups.append(group)
    return {"source": "HUD CHAS %s, Table 8" % chas_period_label(period), "groups": groups}


def _clean(value, unit):
    if value is None:
        return None
    if unit in ("count", "usd"):
        return int(round(value))
    if unit == "share":
        return round(value, 4)
    return round(value, 2)


def build_profile(geo_id, name, acs, permits_by_year=None, acs_year=DEFAULT_ACS_YEAR, chas=None,
                  chas_period=DEFAULT_CHAS_PERIOD):
    """One geography's housing profile as a plain dict (JSON-ready). `chas` maps FIPS codes to
    CHAS Table 8 rows (see read_chas_table8)."""

    def e(table, line):
        row = acs.get(table, {}).get(geo_id)
        return None if row is None else row.get(acs_column(table, line))

    def m(table, line):
        row = acs.get(table, {}).get(geo_id)
        return None if row is None else row.get(acs_column(table, line, moe=True))

    def median(table, line):
        return acs_bound(table, e(table, line), m(table, line))

    metrics = {}

    def add(key, label, value, source, unit, moe=None, bound=None):
        if bound == "unknown":
            value, bound = None, None
        metrics[key] = {"label": label, "value": _clean(value, unit), "moe": _clean(moe, unit),
                        "unit": unit, "source": source, "bound": bound}

    def share(key, label, num_lines, den_lines, table, source, den_minus=()):
        num = _sum(e(table, n) for n in num_lines)
        den = _diff(_sum(e(table, n) for n in den_lines), *[e(table, n) for n in den_minus])
        moe = moe_proportion(num, den, moe_sum(m(table, n) for n in num_lines),
                             moe_sum([m(table, n) for n in den_lines] + [m(table, n) for n in den_minus]))
        add(key, label, _ratio(num, den), source, "share", moe)

    units = e("b25001", 1)
    owner, renter = e("b25003", 2), e("b25003", 3)

    add("population", "Population", e("b01003", 1), "B01003_E001", "count", m("b01003", 1))
    add("occupied_units", "Households (occupied housing units)", e("b25002", 2), "B25002_E002",
        "count", m("b25002", 2))
    add("owner_households", "Owner households", owner, "B25003_E002", "count", m("b25003", 2))
    add("renter_households", "Renter households", renter, "B25003_E003", "count", m("b25003", 3))
    share("renter_share", "Renter share of households", [3], [1], "b25003", "B25003_E003 / B25003_E001")

    add("housing_units", "Housing units", units, "B25001_E001", "count", m("b25001", 1))
    add("vacant_units", "Vacant housing units", e("b25002", 3), "B25002_E003", "count", m("b25002", 3))
    share("vacancy_rate", "Vacancy rate (all vacant units)", [3], [1], "b25002", "B25002_E003 / B25002_E001")
    add("rental_vacancy_rate", "Rental vacancy rate",
        _ratio(e("b25004", 2), _sum([renter, e("b25004", 3), e("b25004", 2)])),
        "B25004_E002 / (B25003_E003 + B25004_E003 + B25004_E002)", "share")
    add("homeowner_vacancy_rate", "Homeowner vacancy rate",
        _ratio(e("b25004", 4), _sum([owner, e("b25004", 5), e("b25004", 4)])),
        "B25004_E004 / (B25003_E002 + B25004_E005 + B25004_E004)", "share")
    add("seasonal_vacant_units", "Vacant: seasonal, recreational or occasional use", e("b25004", 6),
        "B25004_E006", "count", m("b25004", 6))
    add("seasonal_share_of_units", "Seasonal/recreational share of all housing units",
        _ratio(e("b25004", 6), units), "B25004_E006 / B25001_E001", "share",
        moe_proportion(e("b25004", 6), units, m("b25004", 6), m("b25001", 1)))

    share("single_family_share", "Single-family (detached or attached) share of units", [2, 3], [1],
          "b25024", "(B25024_E002 + B25024_E003) / B25024_E001")
    share("two_to_four_share", "2-4 unit buildings share of units", [4, 5], [1],
          "b25024", "(B25024_E004 + B25024_E005) / B25024_E001")
    share("five_plus_share", "5+ unit buildings share of units", [6, 7, 8, 9], [1],
          "b25024", "(B25024_E006 .. B25024_E009) / B25024_E001")
    share("mobile_home_share", "Mobile home share of units", [10], [1],
          "b25024", "B25024_E010 / B25024_E001")
    share("built_2010_or_later_share", "Share of units built 2010 or later", [2, 3], [1],
          "b25034", "(B25034_E002 + B25034_E003) / B25034_E001")
    share("built_before_1980_share", "Share of units built before 1980", [7, 8, 9, 10, 11], [1],
          "b25034", "(B25034_E007 .. B25034_E011) / B25034_E001")

    income, income_bound = median("b19013", 1)
    owner_income, owner_income_bound = median("b25119", 2)
    renter_income, renter_income_bound = median("b25119", 3)
    rent, rent_bound = median("b25064", 1)
    value, value_bound = median("b25077", 1)
    add("median_household_income", "Median household income", income, "B19013_E001", "usd",
        m("b19013", 1), income_bound)
    add("median_owner_income", "Median income, owner households", owner_income, "B25119_E002",
        "usd", m("b25119", 2), owner_income_bound)
    add("median_renter_income", "Median income, renter households", renter_income, "B25119_E003",
        "usd", m("b25119", 3), renter_income_bound)
    add("median_gross_rent", "Median gross rent (monthly)", rent, "B25064_E001", "usd", m("b25064", 1),
        rent_bound)
    add("median_home_value", "Median home value (owner-occupied)", value, "B25077_E001", "usd",
        m("b25077", 1), value_bound)

    needed = None if rent is None else rent * 12 / 0.30
    needed_moe = None if m("b25064", 1) is None else m("b25064", 1) * 12 / 0.30
    add("income_needed_for_median_rent", "Income needed to rent at the median without cost burden",
        needed, "B25064_E001 x 12 / 0.30", "usd", needed_moe, rent_bound)
    add("renter_income_to_needed_ratio", "Median renter income / income needed for median rent",
        _ratio(renter_income, needed), "B25119_E003 / (B25064_E001 x 12 / 0.30)", "ratio",
        bound=ratio_bound(renter_income_bound, rent_bound))
    add("value_to_income_ratio", "Median home value / median household income",
        _ratio(value, income), "B25077_E001 / B19013_E001", "ratio",
        bound=ratio_bound(value_bound, income_bound))

    burdened_lines = [7, 8, 9, 10]
    add("rent_burdened_households", "Renter households paying 30%+ of income on rent",
        _sum(e("b25070", n) for n in burdened_lines), "B25070_E007 .. B25070_E010", "count",
        moe_sum(m("b25070", n) for n in burdened_lines))
    share("rent_burdened_share", "Rent-burdened share (30%+ of income)", burdened_lines, [1],
          "b25070", "(B25070_E007 .. B25070_E010) / (B25070_E001 - B25070_E011)", den_minus=[11])
    share("severely_rent_burdened_share", "Severely rent-burdened share (50%+ of income)", [10], [1],
          "b25070", "B25070_E010 / (B25070_E001 - B25070_E011)", den_minus=[11])
    share("owner_burdened_share", "Cost-burdened owner share (30%+ of income)",
          [8, 9, 10, 11, 19, 20, 21, 22], [1], "b25091",
          "(B25091_E008 .. E011 + B25091_E019 .. E022) / (B25091_E001 - E012 - E023)",
          den_minus=[12, 23])
    share("severely_owner_burdened_share", "Severely cost-burdened owner share (50%+ of income)",
          [11, 22], [1], "b25091", "(B25091_E011 + B25091_E022) / (B25091_E001 - E012 - E023)",
          den_minus=[12, 23])

    fips = fips_of(geo_id)
    permits = summarize_permits(permit_series(permits_by_year or {}, fips), units)
    return {
        "geo_id": geo_id,
        "fips": fips,
        "level": level_of(geo_id),
        "name": name,
        "acs": "%d-%d ACS 5-year estimates" % (acs_year - 4, acs_year),
        "metrics": {key: metrics[key] for key in METRIC_KEYS},
        "permits": permits,
        "chas": chas_summary((chas or {}).get(fips), chas_period),
    }


# ---------------------------------------------------------------- output

def fmt(value, unit, bound=None):
    """A value for display; an open-ended median reads '$2,000,000+' or 'under $10,000'."""
    if value is None:
        return "n/a"
    if unit == "count":
        text = "{:,}".format(int(round(value)))
    elif unit == "usd":
        text = "${:,}".format(int(round(value)))
    elif unit == "share":
        text = "{:.1f}%".format(value * 100)
    else:
        text = "{:.2f}".format(value)
    if bound == "at_least":
        return text + "+"
    if bound == "at_most":
        return "under " + text
    return text


def fmt_metric(metric):
    return fmt(metric["value"], metric["unit"], metric.get("bound"))


def slugify(text):
    text = unicodedata.normalize("NFKD", text.split(",")[0]).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "geo"


def file_stem(profile):
    return "%s-%s" % (profile["fips"], slugify(profile["name"]))


def render_chas(chas):
    lines = ["## Cost burden by household income (HUD CHAS)", ""]
    if not chas:
        return lines + ["No HUD CHAS record for this geography.", ""]
    lines += [
        "From %s. Income bands are shares of HUD Area Median Family Income (HAMFI). Cost-burdened "
        "means housing costs over 30%% of income; severely, over 50%%." % chas["source"],
        "",
        "| Household income | Households | Renter households | Cost-burdened | Share | "
        "Severely cost-burdened | Share |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for g in chas["groups"]:
        label = g["label"] if g["key"] not in ("le80", "all") else "**%s**" % g["label"]
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            label, fmt(g["households"], "count"), fmt(g["renter_households"], "count"),
            fmt(g["cost_burdened"], "count"), fmt(g["cost_burdened_share"], "share"),
            fmt(g["severely_cost_burdened"], "count"), fmt(g["severely_cost_burdened_share"], "share")))
    return lines + [""]


def render_markdown(profile, meta=None):
    meta = meta or {}
    lines = ["# Housing profile: %s" % profile["name"], ""]
    lines.append("FIPS %s, %s. %s%s." % (
        profile["fips"], profile["level"], profile["acs"],
        "; building permits %s" % meta["permit_span"] if meta.get("permit_span") else ""))
    lines.append("")
    metrics = profile["metrics"]
    for title, keys in SECTIONS:
        lines += ["## %s" % title, "", "| Measure | Value | Margin of error (90%) | Source |",
                  "|---|---:|---:|---|"]
        for key in keys:
            mt = metrics[key]
            moe = "+/- " + fmt(mt["moe"], mt["unit"]) if mt["moe"] is not None else ""
            lines.append("| %s | %s | %s | %s |" % (mt["label"], fmt_metric(mt), moe, mt["source"]))
        lines.append("")
    lines += render_chas(profile.get("chas"))
    permits = profile.get("permits")
    lines += ["## New housing authorized by building permits", ""]
    if permits:
        lines.append("Annual average: **%s units**, %s per 1,000 existing housing units; "
                     "%s of permitted units were in buildings with 2 or more units." % (
                         fmt(permits["avg_annual_units"], "count"),
                         fmt(permits["avg_annual_per_1000_units"], "ratio"),
                         fmt(permits["multifamily_share"], "share")))
        lines += ["", "| Year | Total units | 1-unit | 2-4 units | 5+ units |", "|---|---:|---:|---:|---:|"]
        for r in permits["by_year"]:
            lines.append("| %d | %s | %s | %s | %s |" % (
                r["year"], fmt(r["units_total"], "count"), fmt(r["units_1"], "count"),
                fmt(r["units_2_4"], "count"), fmt(r["units_5plus"], "count")))
    else:
        lines.append("No Building Permits Survey record for this geography. A place that does not "
                     "issue its own building permits is covered by its county's figures.")
    lines += [
        "",
        "## Notes",
        "",
        "- ACS figures are 5-year period estimates from a sample survey. Margins of error are at the "
        "90% confidence level; for derived shares they use the Census Bureau's approximation formulas. "
        "Share margins are in percentage points.",
    ]
    if any(metrics[key].get("bound") for key in BOUND_KEYS):
        lines.append("- A value shown with \"+\" or \"under\" is a median in the ACS's open-ended top or "
                     "bottom interval (for example, a median home value of \"$2,000,000+\"). The Census "
                     "Bureau publishes only that edge, and ratios built from it are bounds too.")
    lines += [
        "- \"Cost-burdened\" means paying 30% or more of household income on housing; \"severely\" means "
        "50% or more. Households whose cost ratio cannot be computed are left out of the denominator.",
        "- The HUD CHAS figures are a special tabulation of an earlier ACS period, rounded by HUD, and use "
        "HUD's definitions: over 30% and over 50% of income, with households whose cost burden is not "
        "computed kept in the denominator, as in HUD's own summaries. They will not match the ACS "
        "shares above exactly.",
        "- Building permit counts are Census Bureau estimates (reported plus imputed) for permit-issuing "
        "offices only; housing built where no permit is required is not counted. A state's figure is the "
        "sum of its counties. A place's figure is its own permit office's, keyed by FIPS place code.",
        "- This profile is a starting point for a housing needs assessment, not a complete one, and is not "
        "legal, compliance or investment advice.",
        "",
        "Generated by [housing-data-profiles](%s) %s, by MV2 of Munim, Inc. (made with AI agents). "
        "This product uses Census Bureau data but is not endorsed or certified by the Census Bureau. "
        "HUD CHAS data are from HUD User; this product is not endorsed by HUD." % (REPO_URL, __version__),
        "",
    ]
    return "\n".join(lines)


def csv_header():
    cols = ["geo_id", "fips", "level", "name"]
    for key in METRIC_KEYS:
        cols += [key, key + "_moe"]
        if key in BOUND_KEYS:
            cols.append(key + "_bound")
    cols += ["permit_years", "permits_total_units", "permits_avg_annual_units",
             "permits_multifamily_share", "permits_avg_annual_per_1000_units"]
    cols += ["chas_%s_%s" % (g, field) for g in CHAS_CSV_GROUPS for field in CHAS_CSV_FIELDS]
    return cols


def csv_row(profile):
    row = [profile["geo_id"], profile["fips"], profile["level"], profile["name"]]
    for key in METRIC_KEYS:
        mt = profile["metrics"][key]
        row += ["" if mt["value"] is None else mt["value"], "" if mt["moe"] is None else mt["moe"]]
        if key in BOUND_KEYS:
            row.append(mt.get("bound") or "")
    p = profile.get("permits")
    if p:
        span = "%d-%d" % (p["years"][0], p["years"][-1])
        row += [span, p["total_units"], p["avg_annual_units"],
                "" if p["multifamily_share"] is None else p["multifamily_share"],
                "" if p["avg_annual_per_1000_units"] is None else p["avg_annual_per_1000_units"]]
    else:
        row += ["", "", "", "", ""]
    chas = profile.get("chas")
    groups = {g["key"]: g for g in chas["groups"]} if chas else {}
    for key in CHAS_CSV_GROUPS:
        g = groups.get(key, {})
        row += ["" if g.get(field) is None else g[field] for field in CHAS_CSV_FIELDS]
    return row


def write_csv(path, profiles):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(csv_header())
        for profile in profiles:
            writer.writerow(csv_row(profile))


def write_profile_files(directory, profile, meta):
    os.makedirs(directory, exist_ok=True)
    stem = os.path.join(directory, file_stem(profile))
    with open(stem + ".json", "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(stem + ".md", "w", encoding="utf-8") as fh:
        fh.write(render_markdown(profile, meta))
    return stem


def render_state_index(state_profile, counties, places, meta):
    abbr = STATES.get(state_profile["fips"], state_profile["fips"])
    lines = ["# Housing profiles: %s" % state_profile["name"], "",
             "%s; building permits %s. Generated %s by housing-data-profiles %s." % (
                 state_profile["acs"], meta.get("permit_span") or "n/a", meta.get("generated_at", ""),
                 __version__), "",
             "Statewide: [%s](%s.md)" % (state_profile["name"], file_stem(state_profile)), ""]

    def table(title, folder, rows):
        out = ["## %s (%d)" % (title, len(rows)), "",
               "| Name | Population | Housing units | Median rent | Median value | Rent-burdened |"
               " Permitted units / yr |",
               "|---|---:|---:|---:|---:|---:|---:|"]
        for p in rows:
            mt = p["metrics"]
            cells = [
                "[%s](%s/%s.md)" % (p["name"].split(",")[0], folder, file_stem(p)),
                fmt_metric(mt["population"]), fmt_metric(mt["housing_units"]),
                fmt_metric(mt["median_gross_rent"]), fmt_metric(mt["median_home_value"]),
                fmt_metric(mt["rent_burdened_share"]),
                fmt(p["permits"]["avg_annual_units"], "count") if p.get("permits") else "n/a",
            ]
            out.append("| " + " | ".join(cells) + " |")
        return out + [""]

    lines += table("Counties", "counties", counties)
    if places:
        lines += table("Places with %s+ residents" % "{:,}".format(meta.get("places_min_pop", 0)),
                       "places", places)
        lines += ["Permitted units / yr is n/a for a place with no permit office of its own in the "
                  "Building Permits Survey (for example, where a county or regional building department "
                  "issues its permits); its permits are counted in its county's figures.", ""]
    lines += ["Machine-readable: `counties.csv`, `places.csv` and one `.json` per profile. "
              "State abbreviation: %s." % abbr, ""]
    return "\n".join(lines)


def write_outputs(profiles, out_dir, detail_states, meta):
    """Write CSV summaries for every profile and per-geography files for the detail states."""
    os.makedirs(out_dir, exist_ok=True)
    by_level = {"state": [], "county": [], "place": []}
    for p in profiles:
        by_level.setdefault(p["level"], []).append(p)
    write_csv(os.path.join(out_dir, "states.csv"), by_level["state"])
    write_csv(os.path.join(out_dir, "counties.csv"), by_level["county"])
    written = []
    for st in detail_states:
        abbr = STATES.get(st, st)
        st_dir = os.path.join(out_dir, abbr)
        state = [p for p in by_level["state"] if p["fips"] == st]
        if not state:
            continue
        counties = [p for p in by_level["county"] if p["fips"][:2] == st]
        places = [p for p in by_level["place"] if p["fips"][:2] == st]
        written.append(write_profile_files(st_dir, state[0], meta))
        for p in counties:
            written.append(write_profile_files(os.path.join(st_dir, "counties"), p, meta))
        for p in places:
            written.append(write_profile_files(os.path.join(st_dir, "places"), p, meta))
        write_csv(os.path.join(st_dir, "counties.csv"), counties)
        write_csv(os.path.join(st_dir, "places.csv"), places)
        with open(os.path.join(st_dir, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(render_state_index(state[0], counties, places, meta))
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
        fh.write("\n")
    return written


# ---------------------------------------------------------------- download and run

def fetch(url, cache_dir, log=None):
    """Download `url` into `cache_dir` once and return the local path."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, url.rsplit("/", 1)[1])
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    if log:
        log("download %s" % url)
    tmp = path + ".part"
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out, 1 << 20)
            os.replace(tmp, path)
            return path
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last = exc
        except (urllib.error.URLError, OSError) as exc:
            last = exc
        time.sleep(5 * (attempt + 1))
    raise last


def place_permit_url(region, year):
    return BPS_PLACE_URL.format(region=region, prefix=BPS_REGION_PREFIX[region], year=year)


def chas_url(period, level):
    return CHAS_URL.format(period=period, level=level)


def resolve_states(spec):
    """'all' -> every state, DC and Puerto Rico; 'CO,49' -> ['08', '49']; '' -> []."""
    spec = (spec or "").strip()
    if not spec:
        return []
    if spec.lower() == "all":
        return sorted(STATES)
    out = []
    for part in spec.split(","):
        part = part.strip().upper()
        if not part:
            continue
        if part in ABBR_TO_FIPS:
            fips = ABBR_TO_FIPS[part]
        elif part.isdigit() and part.zfill(2) in STATES:
            fips = part.zfill(2)
        else:
            raise ValueError("unknown state: %r" % part)
        if fips not in out:
            out.append(fips)
    return out


def parse_years(spec):
    """'2016-2025' or '2019,2021-2023' -> sorted list of years."""
    years = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            years.update(range(int(a), int(b) + 1))
        else:
            years.add(int(part))
    return sorted(years)


def load_chas(period, levels, wanted_fips, cache, log=print):
    """Read CHAS Table 8 for the given summary levels -> ({FIPS: row}, [source URLs]).
    A level that cannot be downloaded or read is skipped with a log line; a cached file that is
    not a zip (HUD's site serves scripts a web page instead) is deleted so the next run tries
    again, and the log says where to save the zip after downloading it in a browser."""
    chas, sources = {}, []
    for level in levels:
        url = chas_url(period, level)
        try:
            path = fetch(url, cache, log)
        except (urllib.error.URLError, OSError) as exc:
            log("skip HUD CHAS %s: %s" % (level, exc))
            continue
        try:
            rows = read_chas_table8(chas_table8_lines(path), wanted_fips)
        except (zipfile.BadZipFile, ValueError, csv.Error) as exc:
            if isinstance(exc, zipfile.BadZipFile):
                os.remove(path)
                log("skip HUD CHAS %s: HUD sent a web page, not the zip. Download %s in a browser "
                    "(from %s) and save it as %s, then run again." % (level, url, CHAS_PAGE, path))
            else:
                log("skip HUD CHAS %s: %s" % (level, exc))
            continue
        log("read HUD CHAS %s: %d geographies" % (level, len(rows)))
        chas.update(rows)
        sources.append(url)
    return chas, sources


def run(args, log=print):
    states = resolve_states(args.states)
    detail = resolve_states(args.detail_states)
    for st in detail:
        if st not in states:
            states.append(st)
    year = args.acs_year
    prefixes = tuple(SUMLEVEL_PREFIX[level] + st for st in states for level in ("state", "county"))
    prefixes += tuple(SUMLEVEL_PREFIX["place"] + st for st in detail)

    def table_url(table):
        return ACS_TABLE_URL.format(year=year, table=table)

    columns = {t: {acs_column(t, n, moe) for n in lines for moe in (False, True)}
               for t, lines in NEEDED_LINES.items()}
    pop = read_acs_table(iter_text_lines(fetch(table_url("b01003"), args.cache, log)), prefixes,
                         columns=columns["b01003"])
    wanted = {g for g, row in pop.items()
              if level_of(g) != "place" or (row.get("B01003_E001") or 0) >= args.places_min_pop}
    acs = {"b01003": {g: pop[g] for g in wanted}}
    for table in ACS_TABLES[1:]:
        acs[table] = read_acs_table(iter_text_lines(fetch(table_url(table), args.cache, log)), prefixes,
                                    wanted=wanted, columns=columns[table])
        log("read %s: %d geographies" % (table, len(acs[table])))
    names = read_geos(iter_text_lines(fetch(ACS_GEOS_URL.format(year=year), args.cache, log)),
                      prefixes, wanted)

    permits_by_year, sources = {}, [ACS_BASE.format(year=year)]
    for py in parse_years(args.permit_years):
        url = BPS_COUNTY_URL.format(year=py)
        try:
            path = fetch(url, args.cache, log)
        except urllib.error.HTTPError as exc:
            log("skip permits %d: HTTP %s" % (py, exc.code))
            continue
        permits_by_year[py] = read_bps_county(iter_text_lines(path), set(states))
        sources.append(url)
    loaded = sorted(permits_by_year)

    # Place permits (7-digit keys) share each year's dict with the county records (5-digit keys).
    regions = sorted({STATE_REGION[st] for st in detail if st in STATE_REGION})
    for py in loaded:
        for region in regions:
            url = place_permit_url(region, py)
            try:
                path = fetch(url, args.cache, log)
            except urllib.error.HTTPError as exc:
                log("skip place permits %s %d: HTTP %s" % (region, py, exc.code))
                continue
            permits_by_year[py].update(read_bps_place(iter_text_lines(path), set(detail)))
            sources.append(url)

    chas, chas_period = {}, (args.chas_period or "").strip()
    if chas_period:
        levels = [lv.strip() for lv in (args.chas_levels or "").split(",") if lv.strip()]
        if not detail:
            levels = [lv for lv in levels if lv != "160"]
        chas, chas_sources = load_chas(chas_period, levels, {fips_of(g) for g in wanted}, args.cache, log)
        sources += chas_sources

    profiles = [build_profile(g, names.get(g, g), acs, permits_by_year, year, chas, chas_period)
                for g in sorted(wanted, key=lambda g: (LEVEL_ORDER.get(level_of(g), 9), g))]
    meta = {
        "tool": "housing-data-profiles",
        "version": __version__,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "acs": "%d-%d ACS 5-year estimates (table-based summary file)" % (year - 4, year),
        "permit_years": loaded,
        "permit_span": "%d-%d" % (loaded[0], loaded[-1]) if loaded else "",
        "chas": "HUD CHAS %s, Table 8" % chas_period_label(chas_period) if chas else "",
        "chas_profiles": sum(1 for p in profiles if p["chas"]),
        "states": [STATES[s] for s in states],
        "detail_states": [STATES[s] for s in detail],
        "places_min_pop": args.places_min_pop,
        "profiles": len(profiles),
        "sources": sources,
        "made_by": "MV2 of Munim, Inc., with AI agents",
    }
    write_outputs(profiles, args.out, detail, meta)
    log("wrote %d profiles to %s" % (len(profiles), args.out))
    return profiles


def main(argv=None):
    ap = argparse.ArgumentParser(description="Housing data profiles from public Census Bureau and HUD files "
                                             "(ACS 5-year, Building Permits Survey, HUD CHAS). No API key needed.")
    ap.add_argument("--states", default="all",
                    help="states for the CSV summaries: 'all' or a list like CO,UT or 08,49 (default all)")
    ap.add_argument("--detail-states", default="",
                    help="states that also get one Markdown + JSON profile per county and place")
    ap.add_argument("--places-min-pop", type=int, default=1000,
                    help="smallest place population to include for detail states (default 1000)")
    ap.add_argument("--acs-year", type=int, default=DEFAULT_ACS_YEAR,
                    help="last year of the ACS 5-year period (default %d)" % DEFAULT_ACS_YEAR)
    ap.add_argument("--permit-years", default=DEFAULT_PERMIT_YEARS,
                    help="building permit years, e.g. 2016-2025 (default %s)" % DEFAULT_PERMIT_YEARS)
    ap.add_argument("--chas-period", default=DEFAULT_CHAS_PERIOD,
                    help="HUD CHAS period, e.g. 2018thru2022 (default); an empty value skips CHAS")
    ap.add_argument("--chas-levels", default=DEFAULT_CHAS_LEVELS,
                    help="CHAS summary levels to read (default %s: states, counties, places)"
                         % DEFAULT_CHAS_LEVELS)
    ap.add_argument("--out", default="reports", help="output folder (default reports)")
    ap.add_argument("--cache", default=".cache", help="download cache folder (default .cache)")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)
    run(args, log=lambda msg: print(msg, file=sys.stderr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
