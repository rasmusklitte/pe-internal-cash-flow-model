"""Kalibrér TA-profilerne til den interne metode pr. fond (læser kun databasen).

    python scripts/kalibrer.py                      # alle investorer pr. i dag
    python scripts/kalibrer.py --dato 2026-10-29 "CR ApS"

Alle investorers positioner lægges sammen pr. fond (se kalibrering.samlet). Udskriver TVPI og
IRR for den interne metode og TA før og efter, og et YAML-udsnit til
config/forudsaetninger.yaml (indsættes i hånden, så kommentarerne i filen bevares).
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prognosemodel import data, forudsaetninger, kalibrering  # noqa: E402
from prognosemodel.data import FONDSORDEN  # noqa: E402


def _pct(v):
    return "n/a" if v is None else f"{v * 100:5.1f} %"


def _x(v):
    return "n/a" if v is None else f"{v:4.2f}x"


def _tal(v):
    return f"{v:g}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("investorer", nargs="*", help="standard: alle investorer")
    ap.add_argument("--dato", type=date.fromisoformat, default=date.today())
    a = ap.parse_args()
    cfg = forudsaetninger.indlaes()
    slut_aar = a.dato.year + (cfg.get("generelt") or {}).get("horisont_aar", 10) - 1
    navne = a.investorer or list(data.investorer()["navn"])
    pr_fond = {}
    for navn in navne:
        try:
            r = data.hent(navn, a.dato)
        except ValueError as e:
            print(f"{navn}: {e}", file=sys.stderr)
            continue
        for f in r["fonde"]:
            pr_fond.setdefault(f["fond"], []).append(f)

    resultater = {}
    print(f"{len(navne)} investorer pr. {a.dato:%d.%m.%Y}, horisont {slut_aar}\n")
    print(f"{'Fond':18} {'n':>3}  {'TVPI intern':>11} {'TA før':>7} {'TA efter':>8}   "
          f"{'IRR intern':>10} {'TA før':>8} {'TA efter':>8}")
    for fond in sorted(pr_fond, key=lambda x: FONDSORDEN.index(x) if x in FONDSORDEN else 99):
        f = kalibrering.samlet(pr_fond[fond])
        res = kalibrering.kalibrer(f, forudsaetninger.for_fond(cfg, fond), a.dato, slut_aar)
        resultater[fond] = res
        i, fo, e = res["intern"], res["foer"], res["efter"]
        print(f"{fond:18} {len(pr_fond[fond]):>3}  {_x(i['tvpi']):>11} {_x(fo['tvpi']):>7} "
              f"{_x(e['tvpi']):>8}   {_pct(i['irr']):>10} {_pct(fo['irr']):>8} "
              f"{_pct(e['irr']):>8}")

    print("\n# profiler: (kalibreret til den interne metode "
          f"pr. {a.dato:%d.%m.%Y})")
    for fond, res in resultater.items():
        p = res["profil"]
        rater = ", ".join(_tal(x) for x in p["kaldsrater"])
        print(f"  {fond + ':':17} {{kaldsrater: [{rater}], kald_til_aar: "
              f"{_tal(p['kald_til_aar'])}, bow: {_tal(p['bow'])}, udbytte: {_tal(p['udbytte'])}}}")
    print("\n# fonde.<fond>.loebetid_aar:")
    for fond, res in resultater.items():
        print(f"  {fond}: {_tal(res['loebetid_aar'])}")


if __name__ == "__main__":
    main()
