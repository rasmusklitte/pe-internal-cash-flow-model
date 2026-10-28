"""Afstem prognosemodel.data mod de gamle procedurer for alle (eller udvalgte) investorer.

    python scripts/afstem.py                 # alle investorer pr. i dag
    python scripts/afstem.py "CR ApS"         # én investor

Sammenligner pr. fond: årlige indbetalinger (DKK og valuta) og NAV pr. 31.12 med
usp_pe_period_data, og seneste NAV + markedsværdi (til kostpris) med
usp_pe_prognosis_cashflows. Kendte, bevidste forskelle:
- KØB/SALG indgår her som betalinger; de gamle procedurer ser bort fra dem.
- usp_pe_period_data bruger ejerandelen pr. 31.12, vi bruger den på NAV-datoen.
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prognosemodel import data, db  # noqa: E402

TOL = 1.0   # DKK / valuta


def _tal(v):
    """Procedurernes tal (evt. tekst med decimalkomma) som float; NULL/NaN er 0, ellers ville
    en sammenligning med NaN aldrig give en afvigelse."""
    if v is None or str(v) == "" or pd.isna(v):
        return 0.0
    return float(str(v).replace(",", "."))


def afstem(navn, dato):
    r = data.hent(navn, dato)
    fonde = {f["fond"]: f for f in r["fonde"]}
    afvig = []
    pd_ = db.koer_procedure("usp_pe_period_data", NAVN=navn)
    for row in pd_.itertuples():
        f = fonde.get(row.FOND)
        if f is None or row.YEAR >= dato.year:
            continue
        a = f["aar"].get(row.YEAR, {})
        for felt, gl, ny in (("kald_dkk", row.DRAWDOWN_DKK, a.get("kald", 0.0)),
                             ("kald_valuta", row.DRAWDOWN_VALUTA, a.get("kald_valuta", 0.0)),
                             ("nav_dkk", row.NAV_DKK, a.get("nav", 0.0))):
            if abs(_tal(gl) - ny) > TOL:
                afvig.append((navn, row.FOND, row.YEAR, felt, _tal(gl), ny))
    cf = db.koer_procedure("usp_pe_prognosis_cashflows", NAVN=navn, today=dato)
    for row in cf[cf.KILDE == "NAV"].itertuples():
        f = fonde.get(row.FOND)
        if f is None:
            continue
        ny = f["markedsvaerdi_dkk_kost"] if row.CUR == "DKK" else f["markedsvaerdi_valuta"]
        if abs(_tal(row.AMOUNT) - ny) > TOL:
            afvig.append((navn, row.FOND, dato.year, f"mv_{row.CUR.lower()}", _tal(row.AMOUNT), ny))
    handler = any(b[3] in ("KØB", "SALG") for f in r["fonde"] for b in f["betalinger"])
    return afvig, handler


def main():
    dato = date.today()
    navne = sys.argv[1:] or list(data.investorer()["navn"])
    alle, med_handler = [], set()
    for navn in navne:
        try:
            afvig, handler = afstem(navn, dato)
        except ValueError as e:
            print(f"{navn}: {e}")
            continue
        alle += afvig
        if handler:
            med_handler.add(navn)
    df = pd.DataFrame(alle, columns=["investor", "fond", "aar", "felt", "gammel", "ny"])
    df["kendt_aarsag"] = df["investor"].isin(med_handler).map({True: "KØB/SALG", False: ""})
    # FoF har ingen aktier, så de gamle procedurer giver ingen NAV; vi bruger andelen af det
    # indbetalte (se data.nav_pr)
    df.loc[(df["fond"] == "FoF") & (df["felt"] == "nav_dkk"), "kendt_aarsag"] = "FoF uden aktier"
    print(f"{len(navne)} investorer, {len(df)} afvigelser > {TOL}")
    if len(df):
        pd.set_option("display.width", 200)
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
