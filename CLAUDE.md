# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

A Python rebuild of the old Excel cash-flow forecast `assets/alternativer_prognosemodel.xlsm` for one investor across P&P's six feeder funds (Private Equity I/II, Private Credit I/II, Maritime, FoF). It produces an editable PowerPoint deck on the PPIM slide master (same look as `../pe-fund-report`) plus a `_data.xlsx` audit workbook.

## Commands

```
pip install -e .[dev]
python -m prognosemodel "CR ApS"                       # deck pr. i dag -> exports/
python -m prognosemodel "cr"                           # omtrentligt navn: spørger ved tvivl (--ja: kun ved ét fund)
python -m prognosemodel "CR ApS" --dato 2026-10-18 --motor excel --scenarie svag --uden-data
pytest                                                 # no DB needed
pytest tests/test_prognose_excel.py::test_gentager_arket -q
ruff check .
python scripts/afstem.py ["CR ApS" ...]                # reconcile against the legacy procedures (DB)
python scripts/kalibrer.py [--dato ...] ["CR ApS" ...]  # calibrate TA profiles to the internal method (DB)
```

`exports/` and `log/` are git-ignored: they contain investor data.

## Database: read-only, always

- The `PE` database on `sql1\ppim` (Windows auth, ODBC Driver 18) feeds other systems and must never be written to. Its schema can't change.
- `prognosemodel/db.py:read_sql` accepts only a single `SELECT`/`WITH`. It rejects write/DDL keywords, `INTO`, `EXEC` and `;` batches, connects with `ApplicationIntent=ReadOnly` and always rolls back.
- `tests/test_db.py` checks every file in `sql/` against that guard.
- New queries go in `sql/<name>.sql` with `:param` binding and are run with `db.sql_fil("<name>", ...)`.
- The only `EXEC` path is `db.koer_procedure`. It is restricted to `AFSTEMNINGSPROCEDURER`, legacy procedures that were read in `docs/legacy_sql/` and only touch `#temp` tables, and is used solely by `scripts/afstem.py`.
- The Excel model used the legacy `dbo` layer. This project reads the same raw tables with its own SELECTs:
  - `tbl_pe_transactions`, `tbl_pe_fund_nav`, `tbl_pe_stamdata`, `tbl_pe_stamdata_fund`, `fx_rates_nationalbanken`.
  - The newer `fund`/`rpt` schema used by pe-fund-report describes P&P's own vehicles, not client holdings in the feeders.
  - `tbl_pe_stamdata` has a `PASSWORD` column, so never `SELECT *` from it.
- The legacy procedure and view definitions are dumped in `docs/legacy_sql/` (re-dump with `sql/00_discovery/definitioner.sql`).

## Data facts (non-obvious, verified)

- `tbl_pe_fund_nav.EGENKAPITAL_VAERDI` is the fund's NAV in **DKK**; dividing by `VALUTA_KURS` gives fund currency.
- Investor NAV = ownership × fund NAV. Ownership = investor shares / fund shares (`ANTAL_AKTIER`, DRAWDOWN/CLOSING/KØB minus SALG) on the NAV date.
  - FoF is a K/S with NULL shares, so the fallback is the investor's share of total `OPKRÆVET`. The legacy procedures return no FoF NAV.
- `BELOEB`/`BETALT_DKK` are cash paid, including closing true-up interest and net of discount. `OPKRÆVET` is the amount drawn against commitment and drives paid-in %. Unfunded commitment = latest `TILSAGN_PR_DAGS_DATO` − Σ`OPKRÆVET`.
- `VALUTA_KURS` on transactions is nvarchar and may use a decimal comma.
- Signs are stored positive, except SALG, which is negative. `data.betalinger` applies the investor's sign: outflow < 0.
- There are no `DISTRIBUTION` events yet.
- KØB/SALG are trades between investors. They count here as cash flows and as transfers of paid-in amount; the legacy procedures ignore them, which explains every KØB/SALG difference in `scripts/afstem.py`.
- Fund currency comes from `tbl_pe_stamdata_fund.VALUTA`; FoF is EUR. The old VBA wrongly passed USD for FoF.

## Architecture

The pipeline is `report.byg` → `data.hent` → `beregning.prognose` → `slides.*` → `report.byg_deck`.

- **`data.py`**
  - `hent(navn, dato)` runs the SQL files and builds one dict per fund via pure functions: `position`, `nav_pr`, `aarstal`, `kvartaler`.
  - Market value = latest NAV + net flows since the NAV date (at cost), converted at spot. The DKK IRR uses market value at spot; the legacy model used cost.
  - Fully sold positions go to `r["solgte"]` and count only in portfolio totals and IRR.
- **`prognose_excel.py`** reproduces the sheet's yearly RC/RD/G method exactly.
  - It is reconciled cell by cell against the workbook's cached values in `tests/test_prognose_excel.py`, which reads the xlsm with openpyxl `read_only`, `data_only`.
  - `excel_kompatibel=False` fixes the sheet's known flaws: contributions capped at unfunded commitment, terminal NAV included in IRR, RC no longer overriding RD.
- **`prognose_ta.py`** is the Takahashi-Alexander engine, copied from `pe-fund-report/pe_fund_report/prognose.py`. It runs quarterly in fund currency from the as-of date and is the deck default.
- **`beregning.py`** gives both engines one output shape per fund: yearly `linjer` with actual years, then the current year (YTD + rest), then forecast years.
  - It also produces horizon IRR/TVPI, totals and the base/weak/strong scenarios.
  - The Excel engine always runs too, for the comparison slide.
- **`forudsaetninger.py` + `config/forudsaetninger.yaml`** hold all assumptions: per-fund growth, life, TA profile and Excel RC/RD per calendar year, TA profiles, scenarios and per-investor overrides.
  - Validation is strict: unknown keys or rates outside 0..1 raise an error.
  - The Excel RC/RD rates are per calendar year and must be rolled forward yearly.
  - Each fund has its own TA profile (named after the fund), plus a `loebetid_aar` that `kalibrering.py` calibrated to the internal method. The generic profiles are kept for switching back.
    - The calibration sums all investors per fund (both engines are linear).
    - It fits the yearly calls/distributions plus TVPI/IRR, and sets the life so that TA exits in the internal method's Exit year.
    - Rerun `scripts/kalibrer.py` and paste its output whenever RC/RD change.
    - The remaining IRR gap (≤ ~0.7 pp) is structural: the internal method grows from NAV at 31.12 of last year, while TA grows from today's market value.
  - The `excel` engine is shown on slides as "Intern metode". Its RC/RD rates reflect the liquidity expectations the funds have communicated, so slide text describes it that way and not as "the old Excel sheet".
- **Deck order (`report.byg_deck`):**
  - Shared status slides (summary, per fund, quarterly returns) use the engine from `generelt.motor` / `--motor`.
  - Then two forecast sections, each with the calls/distributions, NAV/liquidity and per-fund slides: first the baseline ("Intern metode", engine `excel`), then the new method (Takahashi-Alexander, scenario from `--scenarie`). Each slide's subtitle names its method.
  - Then the appendix.
- **`slides.py`** has one function per slide.
  - Its building blocks (`_tabel`, `Fodnoter`, `_diagramakser`, `_linjeplot` for column+line combos, `sidefod`, Danish number formats) are lifted from pe-fund-report's `slides.py`.
  - `deck.py` and `style.py` are byte-identical copies shared across the PE repos; don't edit them.

## Conventions

- Identifiers, docstrings, comments and slide text are in Danish, as in the sibling PE repos.
- Amounts on slides are in mio. with one decimal (`beloeb`). A missing value shows as `n/a`.
- Slide notes cite sources and method only.
