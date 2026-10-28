"""Hele decket bygget af konstruerede data (ingen database): alle slides kommer med."""
from datetime import date

import pytest
from test_data import FOND_AKTIER, FOND_NAV, TR

from prognosemodel import beregning, data, forudsaetninger, report


@pytest.mark.parametrize("motor", ["ta", "excel"])
def test_deck(motor):
    dato = date(2025, 10, 1)
    p = data.position(TR, FOND_AKTIER, FOND_NAV, dato, spot=7.0)
    p.update(fond="Maritime", valuta="USD", vintage=2024, vintage_dato=date(2024, 1, 10),
             underliggende_fond="Testfond III")
    r = dict(navn="Test ApS", dato=dato, fonde=[p], solgte=[],
             kurser={"USD": dict(dato=dato, kurs=7.0)}, total=data.total([p]))
    cfg = forudsaetninger.indlaes()
    prog = beregning.prognose(r, cfg, motor=motor)
    prs = report.byg_deck(r, prog, cfg)
    titler = [s.shapes.title.text for s in prs.slides if s.shapes.title is not None]
    for t in ("Sammendrag", "Porteføljen pr. fond", "Forventede kapitalkald og udlodninger",
              "Forventet NAV og likviditet", "Prognose pr. fond", "Bilag: Forudsætninger"):
        assert t in titler
    assert ("Bilag: To prognosemetoder" in titler) == (motor == "ta")
