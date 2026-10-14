import json
import os
import tempfile
import unittest
import zipfile

import housing_profile as hp

COUNTY = "0500000US08041"
STATE = "0400000US08"
PLACE = "1600000US0816000"

# Real line layout of co2024a.txt (Census BPS annual county file).
BPS_2024 = [
    "Survey,FIPS,FIPS,Region,Division,County,,1-unit,,,2-units,,,3-4 units,,,5+ units,,,"
    "1-unit rep,,,2-units rep,,,3-4 units rep,,,5+ units rep,,,\n",
    "Date,State,County,Code,Code,Name,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,"
    "Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value\n",
    " \n",
    "2024,01,001,3,6,Autauga County                ,221,221,82537210,0,0,0,0,0,0,0,0,0,"
    "221,221,82537210,0,0,0,0,0,0,0,0,0\n",
    "2024,08,041,4,8,El Paso County                ,2733,2733,1565916233,119,238,56713798,"
    "2,6,2509808,22,872,183362655,2733,2733,1565916233,119,238,56713798,2,6,2509808,22,872,183362655\n",
]
BPS_2025 = [
    "2025,08,041,4,8,El Paso County                ,2500,2500,1500000000,100,200,50000000,"
    "5,15,3000000,30,1151,200000000,2500,2500,1500000000,100,200,50000000,5,15,3000000,30,1151,200000000\n",
    "2025,08,043,4,8,Fremont County                ,100,100,30000000,0,0,0,0,0,0,1,10,1000000,"
    "100,100,30000000,0,0,0,0,0,0,1,10,1000000\n",
]

# Real line layout of we2025a.txt (Census BPS annual place file, West region): 17 identifying
# fields, then 24 permit columns. The identifying fields are copied from the live file; some
# permit numbers are made up.
DENVER_2025 = ("2025,08,173000,031,0320,20000 ,00000 ,735538 ,216,19740,2,1,80202      ,4,8,11,Denver,"
               "1027,1027,332552732,10,20,5000000,4,14,3000000,60,3500,600000000,"
               "1027,1027,332552732,10,20,5000000,4,14,3000000,60,3500,600000000\n")
PLACE_2025 = [
    "Survey,State,6-Digit,County,Census Place,FIPS Place,FIPS MCD,Pop,CSA,CBSA,Footnote,Central,Zip,"
    "Region,Division,Number of,Place,1-unit,,,2-units,,,3-4 units,,,5+ units,,,"
    "1-unit rep,,,2-units rep,,,3-4 units rep,,,5+ units rep,,,\n",
    "Date,Code,ID,Code,Code,Code,Code,  ,Code,Code,Code,City,Code,Code,Code,Months Rep,Name,"
    "Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,"
    "Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value\n",
    " \n",
    DENVER_2025,
    "2025,08,201000,041,    ,99990 ,00000 ,196856 ,999,17820,2, ,80910      ,4,8,12,"
    "El Paso County Unincorporated Area,2719,2719,900000000,0,0,0,0,0,0,0,0,0,"
    "2719,2719,900000000,0,0,0,0,0,0,0,0,0\n",
    "2025,08,231000,065,    ,00000 ,00000 ,7310 ,999,99999, , ,80461      ,4,8,12,Lake County,"
    "10,10,4000000,0,0,0,0,0,0,0,0,0,10,10,4000000,0,0,0,0,0,0,0,0,0\n",
    "2025,08,683000,125,1395,86750 ,00000 ,3497 ,999,99999, , ,80759      ,4,8,12,Yuma,"
    "0,0,0,1,2,124000,0,0,0,0,0,0,0,0,0,1,2,124000,0,0,0,0,0,0\n",
    "2025,49,067000,035,2335,67000 ,00000 ,181743 ,482,41620,2,1,84111      ,4,8,12,Salt Lake City,"
    "200,200,80000000,0,0,0,0,0,0,10,900,150000000,200,200,80000000,0,0,0,0,0,0,10,900,150000000\n",
]

# HUD CHAS Table 8 for Weld County, CO. The band totals and the over-50% cells (T8_est3, 16, 29,
# 69, 82, 95, 23, 36, 89, 102) are HUD's published values from its CHAS county layer; the
# over-30%-to-50% cells are split so that the sums equal HUD's published derived fields
# (T8_LE30_CB 6,745, T8_LE30_CB50 5,665, T8_LE80_CB 20,990, T8_LE80_CB50 11,110, T8_LE30_CB_R 4,025).
WELD_EST = {
    1: 99815, 2: 71450, 68: 28365,
    3: 3625, 7: 820, 10: 1900, 69: 5580, 73: 260, 76: 3765,
    16: 4980, 20: 1310, 23: 1800, 82: 5085, 86: 2155, 89: 1715,
    29: 8895, 33: 2775, 36: 1335, 95: 6740, 99: 2560, 102: 595,
}
WELD_MOE = {3: 100, 69: 200, 7: 30, 10: 40}


def chas_lines(rows, sumlevel="050"):
    """A CHAS Table8.csv in HUD's layout: source, sumlevel, geoid, name, st, cnty, then
    T8_est1..T8_est133 and T8_moe1..T8_moe133."""
    header = ["source", "sumlevel", "geoid", "name", "st", "cnty"]
    header += ["T8_est%d" % n for n in range(1, 134)] + ["T8_moe%d" % n for n in range(1, 134)]
    out = [",".join(header) + "\n"]
    for geoid, name, est, moe in rows:
        cells = ["2018thru2022", sumlevel, geoid, '"%s"' % name, geoid[7:9], geoid[9:12]]
        cells += [str(est.get(n, 0)) for n in range(1, 134)]
        cells += [str(moe.get(n, 0)) for n in range(1, 134)]
        out.append(",".join(cells) + "\n")
    return out


WELD_LINES = chas_lines([
    ("05000US08123", "Weld County, Colorado", WELD_EST, WELD_MOE),
    ("05000US35013", "Doña Ana County, New Mexico", {3: 10}, {}),
])


def row(table, estimates, moes=None):
    out = {}
    for line, value in estimates.items():
        out[hp.acs_column(table, line)] = float(value)
    for line, value in (moes or {}).items():
        out[hp.acs_column(table, line, moe=True)] = float(value)
    return out


def county_acs():
    tables = {
        "b01003": row("b01003", {1: 750000}, {1: 0}),
        "b25001": row("b25001", {1: 300000}, {1: 500}),
        "b25002": row("b25002", {1: 300000, 2: 285000, 3: 15000}, {1: 500, 2: 1500, 3: 1200}),
        "b25003": row("b25003", {1: 285000, 2: 180000, 3: 105000}, {1: 1500, 2: 2000, 3: 2100}),
        "b25004": row("b25004", {1: 15000, 2: 4000, 3: 1000, 4: 1500, 5: 500, 6: 3000}, {6: 400}),
        "b19013": row("b19013", {1: 90000}, {1: 900}),
        "b25119": row("b25119", {1: 90000, 2: 110000, 3: 60000}, {1: 900, 2: 1200, 3: 1500}),
        "b25064": row("b25064", {1: 1755}, {1: 46}),
        "b25077": row("b25077", {1: 450000}, {1: 4000}),
        "b25070": row("b25070", {1: 105000, 2: 10000, 3: 15000, 4: 15000, 5: 10000, 6: 10000,
                                 7: 8000, 8: 6000, 9: 7000, 10: 20000, 11: 4000},
                      {n: 300 for n in range(1, 12)}),
        "b25091": row("b25091", {**{n: 10000 for n in (3, 4, 5, 6, 7, 14, 15, 16, 17, 18)},
                                 1: 180000, 2: 120000, 12: 500, 13: 60000, 23: 1000,
                                 8: 5000, 9: 3000, 10: 3000, 11: 6000,
                                 19: 1000, 20: 500, 21: 500, 22: 1000},
                      {n: 200 for n in range(1, 24)}),
        "b25024": row("b25024", {1: 300000, 2: 200000, 3: 20000, 4: 10000, 5: 15000, 6: 10000,
                                 7: 10000, 8: 10000, 9: 15000, 10: 9000, 11: 1000},
                      {n: 400 for n in range(1, 12)}),
        "b25034": row("b25034", {1: 300000, 2: 15000, 3: 45000, 4: 50000, 5: 40000, 6: 75000,
                                 7: 30000, 8: 20000, 9: 15000, 10: 5000, 11: 5000},
                      {n: 400 for n in range(1, 12)}),
        # Gross rent: 9,000 units under $500, 36,000 under $1,250, 96,000 under $2,500;
        # lines 3-26 add up to line 2 (with cash rent), and line 2 + line 27 to line 1.
        "b25063": row("b25063", {**{n: 1000 for n in range(3, 12)}, **{n: 3000 for n in range(12, 21)},
                                 1: 105000, 2: 102000, 21: 20000, 22: 30000, 23: 10000,
                                 24: 3000, 25: 2000, 26: 1000, 27: 3000},
                      {n: 200 for n in range(1, 28)}),
        # Renter incomes (lines 15-25 add up to line 14): 22,000 under $20,000, 56,000 under
        # $50,000, 90,000 under $100,000.
        "b25118": row("b25118", {1: 285000, 2: 180000, 14: 105000, 15: 5000, 16: 5000, 17: 6000,
                                 18: 6000, 19: 7000, 20: 12000, 21: 15000, 22: 20000, 23: 14000,
                                 24: 10000, 25: 5000},
                      {n: 300 for n in range(1, 26)}),
    }
    return {t: {COUNTY: r} for t, r in tables.items()}


def jammed_acs():
    """county_acs() with open-ended medians, as the live 2020-2024 files publish them for
    Bow Mar, Colorado: rent 3501 and value 2000001, with no margin of error."""
    acs = county_acs()
    acs["b25064"][COUNTY] = row("b25064", {1: 3501})
    acs["b25077"][COUNTY] = row("b25077", {1: 2000001})
    return acs


def permits():
    return {2024: hp.read_bps_county(BPS_2024), 2025: hp.read_bps_county(BPS_2025)}


def permits_with_places():
    by_year = permits()
    by_year[2025].update(hp.read_bps_place(PLACE_2025))
    return by_year


def weld_chas():
    return hp.read_chas_table8(WELD_LINES)


class ParseTests(unittest.TestCase):
    def test_parse_value(self):
        self.assertEqual(hp.parse_value("1755"), 1755.0)
        self.assertEqual(hp.parse_value(" 12.5 "), 12.5)
        self.assertIsNone(hp.parse_value(""))
        self.assertIsNone(hp.parse_value("null"))
        self.assertIsNone(hp.parse_value("-666666666"))
        self.assertIsNone(hp.parse_value("-999999999", is_moe=True))
        self.assertEqual(hp.parse_value("-555555555", is_moe=True), 0.0)
        self.assertIsNone(hp.parse_value("-555555555"))
        self.assertIsNone(hp.parse_value("-333333333", is_moe=True))
        self.assertEqual(hp.parse_value("-5"), -5.0)

    def test_read_acs_table_filters(self):
        lines = [
            "﻿GEO_ID|B25064_E001|B25064_M001\n",
            "0100000US|1487|3\n",
            "0400000US08|1690|9\n",
            "0500000US08041|1755|46\n",
            "0500000US49035|1600|20\n",
            "1600000US0816000|1700|-555555555\n",
            "1400000US08041000100|1500|100\n",
        ]
        got = hp.read_acs_table(lines, ("0400000US08", "0500000US08", "1600000US08"))
        self.assertEqual(sorted(got), ["0400000US08", COUNTY, PLACE])
        self.assertEqual(got[COUNTY], {"B25064_E001": 1755.0, "B25064_M001": 46.0})
        self.assertEqual(got[PLACE]["B25064_M001"], 0.0)
        only = hp.read_acs_table(lines, ("0500000US",), wanted={COUNTY}, columns={"B25064_E001"})
        self.assertEqual(only, {COUNTY: {"B25064_E001": 1755.0}})
        self.assertEqual(hp.read_acs_table([], ("0500000US",)), {})

    def test_read_geos(self):
        header = ("FILEID|STUSAB|SUMLEVEL|COMPONENT|US|REGION|DIVISION|STATE|COUNTY|COUSUB|PLACE|"
                  "TRACT|BLKGRP|CONCIT|AIANHH|AIANHHFP|AIHHTLI|AITS|AITSFP|ANRC|CBSA|CSA|METDIV|"
                  "MACC|MEMI|NECTA|CNECTA|NECTADIV|UA|CDCURR|SLDU|SLDL|ZCTA5|SUBMCD|SDELM|SDSEC|"
                  "SDUNI|UR|PCI|PUMA5|GEO_ID|NAME|BTTR|BTBG|TL_GEO_ID\n")
        pad = "|" * 40
        lines = [header,
                 "ACSSF|CO|050" + pad[3:] + "|0500000US08041|El Paso County, Colorado|||08041\n",
                 "ACSSF|US|010" + pad[3:] + "|0100000US|United States|||\n"]
        # FILEID..PUMA5 are 40 columns, so GEO_ID is index 40 and NAME index 41.
        names = hp.read_geos(lines, ("0500000US",))
        self.assertEqual(names, {COUNTY: "El Paso County, Colorado"})

    def test_read_bps_county(self):
        got = hp.read_bps_county(BPS_2024)
        self.assertEqual(sorted(got), ["01001", "08041"])
        ep = got["08041"]
        self.assertEqual(ep["year"], 2024)
        self.assertEqual(ep["name"], "El Paso County")
        self.assertEqual((ep["units_1"], ep["units_2"], ep["units_3_4"], ep["units_5plus"]),
                         (2733, 238, 6, 872))
        self.assertEqual(ep["units_total"], 3849)
        self.assertEqual(ep["bldgs_5plus"], 22)
        self.assertEqual(ep["value"], 1565916233 + 56713798 + 2509808 + 183362655)
        self.assertEqual(sorted(hp.read_bps_county(BPS_2024, {"08"})), ["08041"])

    def test_read_bps_place(self):
        got = hp.read_bps_place(PLACE_2025)
        # Unincorporated (99990) and county-wide (00000) offices are skipped.
        self.assertEqual(sorted(got), ["0820000", "0886750", "4967000"])
        den = got["0820000"]
        self.assertEqual((den["year"], den["name"]), (2025, "Denver"))
        self.assertEqual((den["units_1"], den["units_2"], den["units_3_4"], den["units_5plus"]),
                         (1027, 20, 14, 3500))
        self.assertEqual(den["units_total"], 4561)
        self.assertEqual(den["bldgs_5plus"], 60)
        self.assertEqual(den["value"], 332552732 + 5000000 + 3000000 + 600000000)
        self.assertEqual(got["0886750"]["units_total"], 2)
        self.assertEqual(sorted(hp.read_bps_place(PLACE_2025, {"08"})), ["0820000", "0886750"])

    def test_read_bps_place_adds_duplicates(self):
        got = hp.read_bps_place([DENVER_2025, DENVER_2025])
        self.assertEqual(got["0820000"]["units_total"], 9122)
        self.assertEqual(got["0820000"]["units_5plus"], 7000)

    def test_place_permit_url(self):
        self.assertEqual(hp.place_permit_url("West", 2025),
                         "https://www2.census.gov/econ/bps/Place/West%20Region/we2025a.txt")
        self.assertEqual(hp.place_permit_url("Midwest", 2016),
                         "https://www2.census.gov/econ/bps/Place/Midwest%20Region/mw2016a.txt")
        self.assertEqual(len(hp.STATE_REGION), 51)
        self.assertEqual(hp.STATE_REGION["08"], "West")
        self.assertEqual(hp.STATE_REGION["11"], "South")
        self.assertEqual(set(hp.STATE_REGION) | {"72"}, set(hp.STATES))


class ChasParseTests(unittest.TestCase):
    def test_chas_fips_and_url(self):
        self.assertEqual(hp.chas_fips("05000US08123"), "08123")
        self.assertEqual(hp.chas_fips("04000US08"), "08")
        self.assertEqual(hp.chas_fips("16000US0820000"), "0820000")
        self.assertEqual(hp.chas_fips("08123"), "08123")
        self.assertEqual(hp.chas_fips("Weld"), "")
        self.assertEqual(hp.chas_url("2018thru2022", "050"),
                         "https://www.huduser.gov/portal/datasets/cp/2018thru2022-050-csv.zip")
        self.assertEqual(hp.chas_period_label("2018thru2022"), "2018-2022")

    def test_read_chas_table8(self):
        got = weld_chas()
        self.assertEqual(sorted(got), ["08123", "35013"])
        weld = got["08123"]
        self.assertEqual(weld["est"][3], 3625.0)
        self.assertEqual(weld["est"][133], 0.0)
        self.assertEqual(weld["moe"][69], 200.0)
        self.assertEqual(len(weld["est"]), 133)
        only = hp.read_chas_table8(WELD_LINES, {"08123"})
        self.assertEqual(sorted(only), ["08123"])
        self.assertEqual(hp.read_chas_table8([]), {})

    def test_read_chas_table8_any_case_and_blanks(self):
        lines = ["﻿SOURCE,SUMLEVEL,GEOID,NAME,T8_EST1,T8_MOE1,T8_EST2\n",
                 '2018thru2022,040,04000US08,"Colorado",2300000,5000,\n']
        got = hp.read_chas_table8(lines)
        self.assertEqual(got["08"]["est"], {1: 2300000.0, 2: None})
        self.assertEqual(got["08"]["moe"], {1: 5000.0})
        with self.assertRaises(ValueError):
            hp.read_chas_table8(["source,name,T8_est1\n"])

    def test_chas_zip_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "2018thru2022-050-csv.zip")
            with zipfile.ZipFile(good, "w") as zf:
                zf.writestr("050/Table1.csv", "source,geoid\n")
                # A Latin-1 file (Doña Ana), so the UTF-8 decode falls back.
                zf.writestr("050/Table8.csv", "".join(WELD_LINES).encode("latin-1"))
            got = hp.read_chas_table8(hp.chas_table8_lines(good))
            self.assertEqual(sorted(got), ["08123", "35013"])
            bad = os.path.join(tmp, "2018thru2022-040-csv.zip")
            with open(bad, "w") as fh:
                fh.write("<html>blocked</html>")
            logged = []
            chas, sources = hp.load_chas("2018thru2022", ["040", "050"], {"08123"}, tmp, logged.append)
            self.assertEqual(sorted(chas), ["08123"])
            self.assertEqual(sources, ["https://www.huduser.gov/portal/datasets/cp/2018thru2022-050-csv.zip"])
            self.assertFalse(os.path.exists(bad))
            skipped = [msg for msg in logged if msg.startswith("skip HUD CHAS 040")]
            self.assertEqual(len(skipped), 1)
            # The log line tells the user where to get the zip and where to save it.
            self.assertIn(hp.CHAS_PAGE, skipped[0])
            self.assertIn(bad, skipped[0])
            empty = os.path.join(tmp, "empty.zip")
            with zipfile.ZipFile(empty, "w") as zf:
                zf.writestr("050/Table9.csv", "x\n")
            with self.assertRaises(ValueError):
                hp.chas_table8_lines(empty)


class MathTests(unittest.TestCase):
    def test_moe_sum(self):
        self.assertAlmostEqual(hp.moe_sum([3, 4]), 5.0)
        self.assertIsNone(hp.moe_sum([3, None]))
        self.assertIsNone(hp.moe_sum([]))

    def test_moe_proportion(self):
        self.assertAlmostEqual(hp.moe_proportion(50, 100, 10, 20), 0.0)
        self.assertAlmostEqual(hp.moe_proportion(25, 100, 10, 20), 75 ** 0.5 / 100)
        # Negative radicand falls back to the ratio formula.
        self.assertAlmostEqual(hp.moe_proportion(80, 100, 5, 20), 281 ** 0.5 / 100)
        self.assertIsNone(hp.moe_proportion(1, 0, 1, 1))
        self.assertIsNone(hp.moe_proportion(1, 2, None, 1))

    def test_moe_ratio(self):
        # sqrt(30^2 + 2^2 * 10^2) / 50 = sqrt(1300) / 50
        self.assertAlmostEqual(hp.moe_ratio(100, 50, 30, 10), 1300 ** 0.5 / 50)
        self.assertIsNone(hp.moe_ratio(1, 0, 1, 1))
        self.assertIsNone(hp.moe_ratio(1, 2, 1, None))

    def test_acs_bound(self):
        self.assertEqual(hp.acs_bound("b25077", 2000001.0, None), (2000000.0, "at_least"))
        self.assertEqual(hp.acs_bound("b25077", 9999.0, None), (10000.0, "at_most"))
        self.assertEqual(hp.acs_bound("b25064", 3501.0, None), (3500.0, "at_least"))
        self.assertEqual(hp.acs_bound("b25064", 99.0, None), (100.0, "at_most"))
        self.assertEqual(hp.acs_bound("b19013", 250001.0, None), (250000.0, "at_least"))
        self.assertEqual(hp.acs_bound("b25119", 2499.0, None), (2500.0, "at_most"))
        # A value that happens to equal a jam value but has a margin of error is a real estimate.
        self.assertEqual(hp.acs_bound("b25064", 3501.0, 120.0), (3501.0, None))
        self.assertEqual(hp.acs_bound("b25064", 1755.0, None), (1755.0, None))
        self.assertEqual(hp.acs_bound("b01003", 2000001.0, None), (2000001.0, None))
        self.assertEqual(hp.acs_bound("b25077", None, None), (None, None))

    def test_ratio_bound(self):
        self.assertIsNone(hp.ratio_bound(None, None))
        self.assertEqual(hp.ratio_bound("at_least", None), "at_least")
        self.assertEqual(hp.ratio_bound(None, "at_least"), "at_most")
        self.assertEqual(hp.ratio_bound(None, "at_most"), "at_least")
        self.assertEqual(hp.ratio_bound("at_least", "at_most"), "at_least")
        self.assertEqual(hp.ratio_bound("at_least", "at_least"), "unknown")
        self.assertEqual(hp.ratio_bound("at_most", "at_most"), "unknown")


class ChasSummaryTests(unittest.TestCase):
    def setUp(self):
        summary = hp.chas_summary(weld_chas()["08123"])
        self.summary = summary
        self.g = {g["key"]: g for g in summary["groups"]}

    def test_groups(self):
        self.assertEqual(self.summary["source"], "HUD CHAS 2018-2022, Table 8")
        self.assertEqual([g["key"] for g in self.summary["groups"]],
                         ["le30", "30_50", "50_80", "80_100", "gt100", "le80", "all"])

    def test_matches_hud_published_fields(self):
        le30 = self.g["le30"]
        self.assertEqual(le30["households"], 9205)               # T8_LE30
        self.assertEqual(le30["cost_burdened"], 6745)            # T8_LE30_CB
        self.assertEqual(le30["severely_cost_burdened"], 5665)   # T8_LE30_CB50
        self.assertEqual(le30["renter_cost_burdened"], 4025)     # T8_LE30_CB_R
        self.assertEqual(le30["renter_households"], 5580)
        self.assertAlmostEqual(le30["cost_burdened_share"], 0.7328)          # T8_LE30_CB_PCT 73.28
        self.assertAlmostEqual(le30["severely_cost_burdened_share"], 0.6154)  # T8_LE30_CB50_PCT 61.54
        self.assertEqual(self.g["30_50"]["cost_burdened"], 6980)             # T8_GT30_LE50_CB
        self.assertEqual(self.g["30_50"]["severely_cost_burdened"], 3515)    # T8_GT30_LE50_CB50
        self.assertEqual(self.g["50_80"]["cost_burdened"], 7265)             # T8_GT50_LE80_CB
        self.assertEqual(self.g["50_80"]["severely_cost_burdened"], 1930)    # T8_GT50_LE80_CB50
        le80 = self.g["le80"]
        self.assertEqual(le80["cost_burdened"], 20990)                       # T8_LE80_CB
        self.assertEqual(le80["severely_cost_burdened"], 11110)              # T8_LE80_CB50
        self.assertEqual(le80["households"], 34905)
        self.assertEqual(le80["renter_households"], 17405)

    def test_moe_and_empty_bands(self):
        le30 = self.g["le30"]
        self.assertEqual(le30["households_moe"], 224)       # sqrt(100^2 + 200^2)
        self.assertEqual(le30["cost_burdened_moe"], 50)     # sqrt(30^2 + 40^2)
        self.assertIsNotNone(le30["cost_burdened_share_moe"])
        self.assertLess(le30["cost_burdened_share_moe"], 0.05)
        self.assertEqual(self.g["80_100"]["households"], 0)
        self.assertIsNone(self.g["80_100"]["cost_burdened_share"])
        self.assertIsNone(hp.chas_summary(None))

    def test_missing_cells_give_none(self):
        summary = hp.chas_summary({"est": {3: 10.0}, "moe": {}})
        le30 = {g["key"]: g for g in summary["groups"]}["le30"]
        self.assertIsNone(le30["households"])
        self.assertIsNone(le30["households_moe"])


class RentLadderTests(unittest.TestCase):
    def setUp(self):
        self.ladder = hp.rent_ladder(county_acs(), COUNTY)
        self.r = {r["key"]: r for r in self.ladder["rungs"]}

    def test_layout(self):
        # Bracket edges as published in the Census Bureau's variable list for B25063 and B25118
        # (2024 ACS 5-year): B25063_011 is "$450 to $499", B25063_020 "$1,000 to $1,249",
        # B25063_023 "$2,000 to $2,499"; B25118_018 is renter "$15,000 to $19,999", B25118_021
        # "$35,000 to $49,999", B25118_023 "$75,000 to $99,999".
        self.assertEqual(sorted(hp.B25063_RENT_EDGES), list(range(3, 26)))
        self.assertEqual(sorted(hp.B25118_RENTER_EDGES), list(range(15, 25)))
        self.assertEqual(hp.NEEDED_LINES["b25063"], list(range(1, 28)))
        self.assertEqual(hp.NEEDED_LINES["b25118"], list(range(1, 26)))
        self.assertEqual(hp.lines_under(hp.B25063_RENT_EDGES, 500), list(range(3, 12)))
        self.assertEqual(hp.lines_under(hp.B25063_RENT_EDGES, 1250), list(range(3, 21)))
        self.assertEqual(hp.lines_under(hp.B25063_RENT_EDGES, 2500), list(range(3, 24)))
        self.assertEqual(hp.lines_under(hp.B25118_RENTER_EDGES, 20000), [15, 16, 17, 18])
        self.assertEqual(hp.lines_under(hp.B25118_RENTER_EDGES, 50000), list(range(15, 22)))
        self.assertEqual(hp.lines_under(hp.B25118_RENTER_EDGES, 100000), list(range(15, 24)))
        with self.assertRaises(ValueError):
            hp.lines_under(hp.B25063_RENT_EDGES, 625)
        for _, income in hp.RENT_LADDER:
            self.assertIn(income, hp.B25118_RENTER_EDGES.values())
            self.assertIn(income // 40, hp.B25063_RENT_EDGES.values())
            self.assertAlmostEqual(income * 0.30 / 12, income // 40)

    def test_rungs(self):
        self.assertEqual([r["key"] for r in self.ladder["rungs"]], ["lt20k", "lt50k", "lt100k"])
        lt20k = self.r["lt20k"]
        self.assertEqual((lt20k["income_limit"], lt20k["rent_limit"]), (20000, 500))
        self.assertEqual(lt20k["renter_households"], 22000)
        self.assertEqual(lt20k["renter_households_moe"], 600)   # sqrt(4) x 300
        self.assertEqual(lt20k["units"], 9000)
        self.assertEqual(lt20k["units_moe"], 600)               # sqrt(9) x 200
        self.assertEqual(lt20k["gap"], -13000)
        self.assertEqual(lt20k["gap_moe"], 849)                 # sqrt(600^2 + 600^2)
        self.assertAlmostEqual(lt20k["units_per_100"], 40.9)
        self.assertAlmostEqual(lt20k["units_per_100_moe"], 2.9)
        lt50k = self.r["lt50k"]
        self.assertEqual((lt50k["renter_households"], lt50k["units"], lt50k["gap"]), (56000, 36000, -20000))
        self.assertEqual((lt50k["renter_households_moe"], lt50k["units_moe"]), (794, 849))
        self.assertAlmostEqual(lt50k["units_per_100"], 64.3)
        lt100k = self.r["lt100k"]
        self.assertEqual((lt100k["rent_limit"], lt100k["renter_households"], lt100k["units"], lt100k["gap"]),
                         (2500, 90000, 96000, 6000))
        self.assertAlmostEqual(lt100k["units_per_100"], 106.7)
        self.assertEqual(self.ladder["renter_households"], 105000)
        self.assertEqual(self.ladder["units_with_cash_rent"], 102000)
        self.assertEqual((self.ladder["no_cash_rent_units"], self.ladder["no_cash_rent_units_moe"]), (3000, 200))

    def test_missing(self):
        self.assertIsNone(hp.rent_ladder({}, COUNTY))
        acs = county_acs()
        del acs["b25118"]
        self.assertIsNone(hp.rent_ladder(acs, COUNTY))
        acs = county_acs()
        acs["b25063"][COUNTY][hp.acs_column("b25063", 5)] = None
        ladder = hp.rent_ladder(acs, COUNTY)
        lt20k = ladder["rungs"][0]
        self.assertIsNone(lt20k["units"])
        self.assertIsNone(lt20k["gap"])
        self.assertIsNone(lt20k["units_per_100"])
        self.assertEqual(lt20k["renter_households"], 22000)

    def test_markdown(self):
        p = hp.build_profile(COUNTY, "El Paso County, Colorado", county_acs(), permits(), 2024)
        md = hp.render_markdown(p)
        self.assertIn("## Rents renters can afford (ACS)", md)
        self.assertIn("| Under $20,000 a year | 22,000 +/- 600 | Under $500 a month | 9,000 +/- 600 | 41 | "
                      "-13,000 |", md)
        self.assertIn("| Under $100,000 a year | 90,000 +/- 900 | Under $2,500 a month | 96,000 +/- 917 | 107 | "
                      "+6,000 |", md)
        self.assertIn("3,000 renter-occupied units pay no cash rent", md)
        self.assertLess(md.index("## Rents renters can afford"), md.index("## Cost burden by household income"))
        empty = hp.build_profile(PLACE, "X city, Colorado", {}, {}, 2024)
        self.assertIn("No ACS gross rent or renter income record for this geography.", hp.render_markdown(empty))


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = hp.build_profile(COUNTY, "El Paso County, Colorado", county_acs(), permits(), 2024)
        self.m = {k: v["value"] for k, v in self.profile["metrics"].items()}

    def test_identity(self):
        p = self.profile
        self.assertEqual((p["fips"], p["level"]), ("08041", "county"))
        self.assertEqual(p["acs"], "2020-2024 ACS 5-year estimates")
        self.assertEqual(list(p["metrics"]), hp.METRIC_KEYS)
        self.assertIsNone(p["chas"])
        self.assertIsNotNone(p["rent_ladder"])
        self.assertTrue(all(v["bound"] is None for v in p["metrics"].values()))

    def test_occupancy_and_vacancy(self):
        self.assertEqual(self.m["population"], 750000)
        self.assertAlmostEqual(self.m["vacancy_rate"], 0.05)
        self.assertAlmostEqual(self.m["renter_share"], 0.3684, places=4)
        self.assertAlmostEqual(self.m["rental_vacancy_rate"], 4000 / 110000, places=4)
        self.assertAlmostEqual(self.m["homeowner_vacancy_rate"], 1500 / 182000, places=4)
        self.assertAlmostEqual(self.m["seasonal_share_of_units"], 0.01)

    def test_structure(self):
        self.assertAlmostEqual(self.m["single_family_share"], 0.7333, places=4)
        self.assertAlmostEqual(self.m["two_to_four_share"], 0.0833, places=4)
        self.assertAlmostEqual(self.m["five_plus_share"], 0.15)
        self.assertAlmostEqual(self.m["mobile_home_share"], 0.03)
        self.assertAlmostEqual(self.m["built_2010_or_later_share"], 0.2)
        self.assertAlmostEqual(self.m["built_before_1980_share"], 0.25)

    def test_affordability(self):
        self.assertEqual(self.m["median_gross_rent"], 1755)
        self.assertEqual(self.m["income_needed_for_median_rent"], 70200)
        self.assertEqual(self.profile["metrics"]["income_needed_for_median_rent"]["moe"], 1840)
        self.assertAlmostEqual(self.m["renter_income_to_needed_ratio"], 0.85)
        self.assertAlmostEqual(self.m["value_to_income_ratio"], 5.0)
        self.assertEqual(self.m["rent_burdened_households"], 41000)
        self.assertAlmostEqual(self.m["rent_burdened_share"], 41000 / 101000, places=4)
        self.assertAlmostEqual(self.m["severely_rent_burdened_share"], 20000 / 101000, places=4)
        self.assertAlmostEqual(self.m["owner_burdened_share"], 20000 / 178500, places=4)
        self.assertAlmostEqual(self.m["severely_owner_burdened_share"], 7000 / 178500, places=4)

    def test_open_ended_medians(self):
        p = hp.build_profile(COUNTY, "El Paso County, Colorado", jammed_acs(), permits(), 2024)
        mt = p["metrics"]
        self.assertEqual((mt["median_gross_rent"]["value"], mt["median_gross_rent"]["bound"]),
                         (3500, "at_least"))
        self.assertIsNone(mt["median_gross_rent"]["moe"])
        self.assertEqual((mt["median_home_value"]["value"], mt["median_home_value"]["bound"]),
                         (2000000, "at_least"))
        self.assertEqual((mt["income_needed_for_median_rent"]["value"],
                          mt["income_needed_for_median_rent"]["bound"]), (140000, "at_least"))
        # Renter income (exact) over a need that is at least $140,000: at most 60,000 / 140,000.
        self.assertEqual(mt["renter_income_to_needed_ratio"]["bound"], "at_most")
        self.assertAlmostEqual(mt["renter_income_to_needed_ratio"]["value"], 0.43)
        self.assertEqual(mt["value_to_income_ratio"]["bound"], "at_least")
        self.assertAlmostEqual(mt["value_to_income_ratio"]["value"], 22.22)
        self.assertIsNone(mt["median_household_income"]["bound"])
        md = hp.render_markdown(p)
        self.assertIn("| Median gross rent (monthly) | $3,500+ |  | B25064_E001 |", md)
        self.assertIn("| Median home value (owner-occupied) | $2,000,000+ |  | B25077_E001 |", md)
        self.assertIn("| Median renter income / income needed for median rent | under 0.43 |", md)
        self.assertIn("open-ended top or bottom interval", md)
        self.assertNotIn("open-ended", hp.render_markdown(self.profile))

    def test_open_ended_ratio_unknown(self):
        acs = jammed_acs()
        acs["b19013"][COUNTY] = row("b19013", {1: 250001})
        p = hp.build_profile(COUNTY, "El Paso County, Colorado", acs, permits(), 2024)
        mt = p["metrics"]
        self.assertEqual((mt["median_household_income"]["value"], mt["median_household_income"]["bound"]),
                         (250000, "at_least"))
        # $2,000,000+ over $250,000+ could be anything.
        self.assertIsNone(mt["value_to_income_ratio"]["value"])
        self.assertIsNone(mt["value_to_income_ratio"]["bound"])

    def test_share_moe_present(self):
        moe = self.profile["metrics"]["rent_burdened_share"]["moe"]
        self.assertIsNotNone(moe)
        self.assertGreater(moe, 0)
        self.assertLess(moe, 0.05)

    def test_permits(self):
        p = self.profile["permits"]
        self.assertEqual(p["years"], [2024, 2025])
        self.assertEqual([r["units_total"] for r in p["by_year"]], [3849, 3866])
        self.assertEqual(p["by_year"][1]["units_2_4"], 215)
        self.assertEqual(p["total_units"], 7715)
        self.assertAlmostEqual(p["avg_annual_units"], 3857.5)
        self.assertAlmostEqual(p["multifamily_share"], 2482 / 7715, places=4)
        self.assertAlmostEqual(p["avg_annual_per_1000_units"], 12.86, places=2)

    def test_state_permits_sum_counties(self):
        series = hp.permit_series(permits(), "08")
        self.assertEqual([r["units_total"] for r in series], [3849, 3866 + 110])
        self.assertEqual(hp.permit_series(permits(), "0816000"), [])

    def test_state_permits_ignore_places(self):
        series = hp.permit_series(permits_with_places(), "08")
        self.assertEqual([r["units_total"] for r in series], [3849, 3866 + 110])

    def test_place_permits(self):
        self.assertEqual([r["units_total"] for r in hp.permit_series(permits_with_places(), "0820000")],
                         [4561])
        p = hp.build_profile("1600000US0820000", "Denver city, Colorado", {}, permits_with_places(), 2024)
        self.assertEqual(p["level"], "place")
        self.assertEqual(p["permits"]["years"], [2025])
        self.assertEqual(p["permits"]["total_units"], 4561)
        self.assertAlmostEqual(p["permits"]["multifamily_share"], 3534 / 4561, places=4)
        self.assertIsNone(p["permits"]["avg_annual_per_1000_units"])
        md = hp.render_markdown(p, {"permit_span": "2024-2025"})
        self.assertIn("| 2025 | 4,561 | 1,027 | 34 | 3,500 |", md)

    def test_missing_data_is_none(self):
        p = hp.build_profile(PLACE, "Colorado Springs city, Colorado", {}, permits(), 2024)
        self.assertEqual(p["level"], "place")
        self.assertTrue(all(v["value"] is None for v in p["metrics"].values()))
        self.assertIsNone(p["permits"])
        self.assertIsNone(p["rent_ladder"])
        md = hp.render_markdown(p, {"permit_span": "2024-2025"})
        self.assertIn("n/a", md)
        self.assertIn("No Building Permits Survey record for this geography", md)
        self.assertIn("No HUD CHAS record for this geography.", md)

    def test_chas_in_profile(self):
        p = hp.build_profile("0500000US08123", "Weld County, Colorado", {}, {}, 2024, weld_chas())
        self.assertEqual(p["chas"]["source"], "HUD CHAS 2018-2022, Table 8")
        md = hp.render_markdown(p)
        self.assertIn("## Cost burden by household income (HUD CHAS)", md)
        self.assertIn("| 0-30% of HAMFI (extremely low income) | 9,205 | 5,580 | 6,745 | 73.3% | 5,665 | 61.5% |",
                      md)
        self.assertIn("| **All households at or under 80% of HAMFI** | 34,905 | 17,405 | 20,990 | 60.1% | "
                      "11,110 | 31.8% |", md)
        self.assertIn("not endorsed by HUD", md)


class OutputTests(unittest.TestCase):
    def test_fmt_and_slug(self):
        self.assertEqual(hp.fmt(1234567.4, "count"), "1,234,567")
        self.assertEqual(hp.fmt(1755, "usd"), "$1,755")
        self.assertEqual(hp.fmt(0.4059, "share"), "40.6%")
        self.assertEqual(hp.fmt(5, "ratio"), "5.00")
        self.assertEqual(hp.fmt(None, "usd"), "n/a")
        self.assertEqual(hp.fmt(2000000, "usd", "at_least"), "$2,000,000+")
        self.assertEqual(hp.fmt(10000, "usd", "at_most"), "under $10,000")
        self.assertEqual(hp.fmt(None, "usd", "at_least"), "n/a")
        self.assertEqual(hp.fmt(-13000, "count"), "-13,000")
        self.assertEqual(hp.fmt_moe(22000, 600, "count"), "22,000 +/- 600")
        self.assertEqual(hp.fmt_moe(22000, None, "count"), "22,000")
        self.assertEqual(hp.fmt_moe(None, 600, "count"), "n/a")
        self.assertEqual(hp.slugify("Doña Ana County, New Mexico"), "dona-ana-county")
        self.assertEqual(hp.slugify("Colorado Springs city, Colorado"), "colorado-springs-city")

    def test_resolve_states_and_years(self):
        self.assertEqual(hp.resolve_states("CO, 49,co"), ["08", "49"])
        self.assertEqual(len(hp.resolve_states("all")), 52)
        self.assertEqual(hp.resolve_states(""), [])
        with self.assertRaises(ValueError):
            hp.resolve_states("ZZ")
        self.assertEqual(hp.parse_years("2016-2018,2020"), [2016, 2017, 2018, 2020])

    def test_markdown(self):
        p = hp.build_profile(COUNTY, "El Paso County, Colorado", county_acs(), permits(), 2024)
        md = hp.render_markdown(p, {"permit_span": "2024-2025"})
        self.assertIn("# Housing profile: El Paso County, Colorado", md)
        self.assertIn("| Median gross rent (monthly) | $1,755 | +/- $46 | B25064_E001 |", md)
        self.assertIn("| 2024 | 3,849 | 2,733 | 244 | 872 |", md)
        self.assertIn("MV2 of Munim, Inc.", md)
        self.assertIn("not endorsed or certified by the Census Bureau", md)

    def test_csv_row_matches_header(self):
        p = hp.build_profile(COUNTY, "El Paso County, Colorado", county_acs(), permits(), 2024)
        self.assertEqual(len(hp.csv_row(p)), len(hp.csv_header()))
        empty = hp.build_profile(PLACE, "X city, Colorado", {}, {}, 2024)
        self.assertEqual(len(hp.csv_row(empty)), len(hp.csv_header()))

    def test_csv_bound_columns(self):
        header = hp.csv_header()
        self.assertEqual(len([c for c in header if c.endswith("_bound")]), len(hp.BOUND_KEYS))
        self.assertEqual(header.index("median_home_value_bound"), header.index("median_home_value_moe") + 1)
        p = hp.build_profile(COUNTY, "El Paso County, Colorado", jammed_acs(), permits(), 2024)
        got = dict(zip(header, hp.csv_row(p)))
        self.assertEqual(got["median_home_value"], 2000000)
        self.assertEqual(got["median_home_value_bound"], "at_least")
        self.assertEqual(got["median_household_income_bound"], "")

    def test_csv_chas_columns(self):
        p = hp.build_profile("0500000US08123", "Weld County, Colorado", {}, {}, 2024, weld_chas())
        header, values = hp.csv_header(), hp.csv_row(p)
        self.assertEqual(len(values), len(header))
        got = dict(zip(header, values))
        self.assertEqual(got["chas_le80_cost_burdened"], 20990)
        self.assertEqual(got["chas_le80_cost_burdened_share"], 0.6013)
        self.assertEqual(got["chas_le30_severely_cost_burdened"], 5665)
        self.assertEqual(len([c for c in header if c.startswith("chas_")]),
                         len(hp.CHAS_CSV_GROUPS) * len(hp.CHAS_CSV_FIELDS))
        self.assertEqual(got["rent_ladder_lt20k_units"], "")

    def test_csv_rent_ladder_columns(self):
        p = hp.build_profile(COUNTY, "El Paso County, Colorado", county_acs(), permits(), 2024)
        header, values = hp.csv_header(), hp.csv_row(p)
        got = dict(zip(header, values))
        self.assertEqual(len([c for c in header if c.startswith("rent_ladder_")]),
                         len(hp.RENT_LADDER) * len(hp.RENT_LADDER_CSV_FIELDS))
        self.assertEqual(got["rent_ladder_lt20k_renter_households"], 22000)
        self.assertEqual(got["rent_ladder_lt20k_units"], 9000)
        self.assertAlmostEqual(got["rent_ladder_lt20k_units_per_100"], 40.9)
        self.assertEqual(got["rent_ladder_lt50k_gap"], -20000)
        self.assertEqual(got["rent_ladder_lt100k_gap"], 6000)
        # Existing columns keep their places; the new ones come last.
        self.assertEqual(header[-1], "rent_ladder_lt100k_gap")

    def test_write_outputs(self):
        acs = county_acs()
        for table, rows in list(acs.items()):
            rows[STATE] = dict(rows[COUNTY])
        profiles = [
            hp.build_profile(STATE, "Colorado", acs, permits(), 2024),
            hp.build_profile(COUNTY, "El Paso County, Colorado", acs, permits(), 2024),
            hp.build_profile(PLACE, "Colorado Springs city, Colorado", {}, permits(), 2024),
            hp.build_profile("1600000US0820000", "Denver city, Colorado", {}, permits_with_places(), 2024),
        ]
        meta = {"permit_span": "2024-2025", "generated_at": "2026-10-13T00:00Z", "places_min_pop": 1000}
        with tempfile.TemporaryDirectory() as tmp:
            hp.write_outputs(profiles, tmp, ["08"], meta)
            for rel in ["states.csv", "counties.csv", "manifest.json", "CO/README.md", "CO/counties.csv",
                        "CO/places.csv", "CO/08-colorado.md", "CO/counties/08041-el-paso-county.json",
                        "CO/counties/08041-el-paso-county.md",
                        "CO/places/0816000-colorado-springs-city.md",
                        "CO/places/0820000-denver-city.json"]:
                self.assertTrue(os.path.exists(os.path.join(tmp, rel)), rel)
            with open(os.path.join(tmp, "CO", "counties", "08041-el-paso-county.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["metrics"]["median_gross_rent"]["value"], 1755)
            self.assertIsNone(data["metrics"]["median_gross_rent"]["bound"])
            self.assertEqual(data["rent_ladder"]["rungs"][0]["gap"], -13000)
            with open(os.path.join(tmp, "CO", "README.md"), encoding="utf-8") as fh:
                index = fh.read()
            self.assertIn("[El Paso County](counties/08041-el-paso-county.md)", index)
            self.assertIn("Places with 1,000+ residents (2)", index)
            self.assertIn("| [Denver city](places/0820000-denver-city.md) | n/a | n/a | n/a | n/a | n/a | 4,561 |",
                          index)
            self.assertIn("its permits are counted in its county's figures", index)
            with open(os.path.join(tmp, "counties.csv"), encoding="utf-8") as fh:
                self.assertEqual(len(fh.read().strip().splitlines()), 2)

    def test_state_index_open_ended(self):
        state = hp.build_profile(STATE, "Colorado", {}, {}, 2024)
        county = hp.build_profile(COUNTY, "El Paso County, Colorado", jammed_acs(), permits(), 2024)
        index = hp.render_state_index(state, [county], [], {"places_min_pop": 1000})
        self.assertIn("| $3,500+ | $2,000,000+ |", index)
        self.assertNotIn("counted in its county's figures", index)


if __name__ == "__main__":
    unittest.main()
