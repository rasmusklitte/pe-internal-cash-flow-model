"""python -m prognosemodel "CR ApS" [--dato 2026-10-18] [--motor ta|excel] [--scenarie basis]"""
import argparse
from datetime import date
from pathlib import Path

from . import report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="prognosemodel",
                                 description="Status og cash flow-prognose for én investor")
    ap.add_argument("investor", help="investorens navn som i tbl_pe_stamdata.NAVN")
    ap.add_argument("--dato", type=date.fromisoformat, default=None,
                    help="opgørelsesdato (standard: i dag)")
    ap.add_argument("--motor", choices=("ta", "excel"), default=None,
                    help="prognosemotor (standard fra forudsaetninger.yaml)")
    ap.add_argument("--scenarie", default=None, help="basis | svag | staerk")
    ap.add_argument("--out", type=Path, default=None, help="sti til decket")
    ap.add_argument("--uden-data", action="store_true", help="gem ikke _data.xlsx")
    a = ap.parse_args(argv)
    report.byg(a.investor, a.dato, a.motor, a.scenarie, a.out, med_data=not a.uden_data)


if __name__ == "__main__":
    main()
