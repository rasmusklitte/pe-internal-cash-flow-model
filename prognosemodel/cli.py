"""python -m prognosemodel "CR ApS" [--dato 2026-10-18] [--motor ta|excel] [--scenarie basis]

Investornavnet må gerne være omtrentligt ("cr", "kristan rasmusen"): ligner flere navne det,
spørges der, hvilken investor der menes."""
import argparse
import sys
from datetime import date
from pathlib import Path

from . import data, report

KLART_FORAN = 0.15   # så langt foran nr. 2, at kun det bedste navn foreslås


def _vaelg_investor(soeg, ja=False):
    """Det præcise investornavn ud fra en omtrentlig søgning; spørger ved tvivl."""
    navne = list(data.investorer()["navn"])
    fund = data.find_investor(soeg, navne)
    if fund and fund[0][1] == 1.0:
        return fund[0][0]
    if not fund:
        forslag = "\n".join(f"  {n}" for n in data.naermeste_investorer(soeg, navne))
        raise SystemExit(f"Ingen investor ligner {soeg!r}. Mente du en af disse?\n{forslag}")
    if ja or not sys.stdin.isatty():
        if len(fund) == 1:
            return fund[0][0]
        liste = "\n".join(f"  {n}" for n, _ in fund)
        raise SystemExit(f"Flere investorer ligner {soeg!r} - skriv navnet mere præcist:\n{liste}")
    if len(fund) == 1 or fund[0][1] - fund[1][1] >= KLART_FORAN:
        svar = input(f"Mente du {fund[0][0]!r}? [J/n] ").strip().casefold()
        if svar not in ("", "j", "ja", "y", "yes"):
            raise SystemExit("Afbrudt.")
        return fund[0][0]
    print(f"Investorer, der ligner {soeg!r}:")
    for i, (n, _) in enumerate(fund, 1):
        print(f"  {i}. {n}")
    while True:
        svar = input("Vælg nummer (Enter = 1, q = afbryd): ").strip().casefold()
        if svar in ("q", "afbryd"):
            raise SystemExit("Afbrudt.")
        if svar == "":
            return fund[0][0]
        if svar.isdigit() and 1 <= int(svar) <= len(fund):
            return fund[int(svar) - 1][0]
        print(f"Skriv et tal fra 1 til {len(fund)}.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="prognosemodel",
                                 description="Status og cash flow-prognose for én investor")
    ap.add_argument("investor", help="investorens navn (hele eller dele af navnet; ved tvivl "
                                     "spørges der)")
    ap.add_argument("--dato", type=date.fromisoformat, default=None,
                    help="opgørelsesdato (standard: i dag)")
    ap.add_argument("--motor", choices=("ta", "excel"), default=None,
                    help="motoren bag de fælles statusslides (standard fra forudsaetninger.yaml); "
                         "decket viser altid begge metoder i hvert sit afsnit")
    ap.add_argument("--scenarie", default=None,
                    help="scenariet for den nye metode: basis | svag | staerk")
    ap.add_argument("--out", type=Path, default=None, help="sti til decket")
    ap.add_argument("--uden-data", action="store_true", help="gem ikke _data.xlsx")
    ap.add_argument("--ja", action="store_true",
                    help="spørg ikke: brug navnet, hvis kun én investor ligner det")
    a = ap.parse_args(argv)
    investor = _vaelg_investor(a.investor, a.ja)
    if investor != a.investor:
        print(f"investor: {investor}")
    report.byg(investor, a.dato, a.motor, a.scenarie, a.out, med_data=not a.uden_data)


if __name__ == "__main__":
    main()
