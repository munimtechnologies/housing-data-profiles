# Published reports

These are the outputs of one real run of `housing_profile.py`, kept here so anyone can read
them without running anything.

- **[Colorado](CO/README.md):** the state, all 64 counties and the 220 places with 1,000 or
  more residents. Run on 2026-10-14 with `--states CO --detail-states CO` by version 0.3.0,
  from the 2020-2024 ACS 5-year estimates, Building Permits Survey estimates for 2016-2025 and
  HUD CHAS 2018-2022. [`manifest.json`](manifest.json) lists every source file used.

What this snapshot includes and leaves out:

- It holds the Markdown profiles and the `counties.csv` / `places.csv` tables. The per-profile
  JSON files are left out to keep the repository light; running the tool produces them.
- It was made by 0.3.0, which prints medians in the ACS's open-ended top interval as the
  Census Bureau's raw code: "$2,000,001" means $2,000,000 or more, "$3,501" means $3,500 or
  more, and "$250,001" means $250,000 or more. This touches a few small, high-cost places
  (Bow Mar, Castle Pines Village, Cherry Hills Village, Columbine Valley, Mountain Village
  and Sterling Ranch). Version 0.3.1 shows these as bounds.
- It does not yet have the "Rents renters can afford" table added in 0.4.0. The next refresh
  is made with the current version and replaces these files.
- Towns whose permits come from a county or regional building department (for example
  Colorado Springs, Pueblo and Grand Junction) show no permit figures of their own; their
  permits are in their county's figures.

These are a free starting data set for Colorado's SB24-174 housing needs assessments, not a
complete or DOLA-approved assessment, and not legal, compliance or investment advice.

Made by MV2 of Munim, Inc., with AI agents. Corrections are welcome as GitHub issues.
This product uses Census Bureau data but is not endorsed or certified by the Census Bureau.
It also uses HUD CHAS data and is not endorsed by HUD.
