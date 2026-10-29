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
    for t in ("Sammendrag", "Porteføljen pr. fond", "Bilag: Forudsætninger",
              "Bilag: To prognosemetoder"):
        assert t in titler
    # prognosen står i to afsnit: baseline først, så den nye metode
    for t in ("Forventede kapitalkald og udlodninger", "Forventet NAV og likviditet",
              "Prognose pr. fond"):
        assert titler.count(t) == 2
    afsnit = [t for t in titler if t.startswith("Prognose –")]
    assert afsnit == ["Prognose – baseline (intern metode)",
                      "Prognose – ny metode (Takahashi-Alexander)"]
