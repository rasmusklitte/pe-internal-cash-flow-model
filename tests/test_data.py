"""data.position og venner på små, konstruerede datasæt (ingen database)."""
from datetime import date

import pandas as pd
import pytest

from prognosemodel import data

COLS = ["id", "dato", "fond", "event", "valuta", "kurs", "tilsagn_pct", "beloeb", "opkraevet",
        "rabat", "true_up", "tilsagn", "betalt_dkk", "aktier"]


def _tr(*raekker):
    df = pd.DataFrame([dict(zip(COLS, r)) for r in raekker])
    for k in COLS[5:]:
        df[k] = pd.to_numeric(df[k], errors="coerce")
    return df


def _fond_nav(*raekker):
    return pd.DataFrame([dict(fond="X", dato=d, valuta="USD", kurs=k, nav_dkk=n,
                              nav_valuta=n / k, id=i) for i, (d, k, n) in enumerate(raekker)])


TR = _tr(
    (1, date(2024, 1, 10), "X", "COMMITMENT", "USD", None, None, 1000.0, None, None, None, 1000.0,
     None, None),
    (2, date(2024, 2, 1), "X", "CLOSING", "USD", 7.0, 0.2, 210.0, 200.0, None, 10.0, 1000.0,
     1470.0, 100.0),
    (3, date(2025, 3, 1), "X", "DRAWDOWN", "USD", 6.5, 0.1, 100.0, 100.0, None, None, 1000.0,
     650.0, 10.0),
    (4, date(2025, 8, 1), "X", "DRAWDOWN", "USD", 6.8, 0.1, 100.0, 100.0, None, None, 1000.0,
     680.0, 10.0),
)
FOND_AKTIER = pd.DataFrame([dict(fond="X", dato=date(2024, 2, 1), delta_aktier=1000.0,
                                 delta_opkraevet=2000.0),
                            dict(fond="X", dato=date(2025, 3, 1), delta_aktier=100.0,
                                 delta_opkraevet=1000.0),
                            dict(fond="X", dato=date(2025, 8, 1), delta_aktier=100.0,
                                 delta_opkraevet=1000.0)])
FOND_NAV = _fond_nav((date(2024, 12, 31), 7.0, 21_000.0), (date(2025, 6, 30), 6.6, 33_000.0))


def test_position():
    p = data.position(TR, FOND_AKTIER, FOND_NAV, date(2025, 10, 1), spot=7.0)
    assert p["tilsagn"] == 1000.0
    assert p["indbetalt"] == 400.0
    assert p["resttilsagn"] == 600.0
    assert p["nav_dato"] == date(2025, 6, 30)
    assert p["ejerandel"] == pytest.approx(110 / 1100)        # aktier på NAV-datoen
    assert p["nav_dkk"] == pytest.approx(3300.0)
    assert p["nav_valuta"] == pytest.approx(500.0)
    # markedsværdi: NAV + indbetalingen 1.8.2025 efter NAV-datoen (til kostpris)
    assert p["markedsvaerdi_valuta"] == pytest.approx(600.0)
    assert p["markedsvaerdi_dkk_kost"] == pytest.approx(3300.0 + 680.0)
    assert p["markedsvaerdi_dkk"] == pytest.approx(600.0 * 7.0)
    assert p["betalt_valuta"] == pytest.approx(410.0)          # kontant inkl. true-up
    assert p["aar"][2025]["kald"] == pytest.approx(1330.0)
    assert p["aar"][2024]["nav"] == pytest.approx(21_000.0 * 100 / 1000)


def test_ejerandel_uden_aktier_bruger_indbetalt():
    tr = TR.assign(aktier=float("nan"))
    fa = FOND_AKTIER.assign(delta_aktier=0.0)
    p = data.position(tr, fa, FOND_NAV, date(2025, 10, 1), spot=7.0)
    assert p["ejerandel_grundlag"] == "indbetalt"
    assert p["ejerandel"] == pytest.approx(300 / 3000)


def test_betalinger_fortegn():
    tr = _tr((1, date(2025, 1, 1), "X", "SALG", "USD", 7.0, None, -50.0, -40.0, None, None, 0.0,
              -350.0, 5.0),
             (2, date(2025, 1, 1), "X", "DRAWDOWN", "USD", 7.0, 0.1, 100.0, 100.0, None, None,
              1000.0, 700.0, 10.0))
    bet = data.betalinger(tr)
    assert [(b[1], b[2], b[3]) for b in bet] == [(50.0, 350.0, "SALG"),
                                                (-100.0, -700.0, "DRAWDOWN")]


def test_kvartaler_kun_med_praecis_nav():
    p = data.position(TR, FOND_AKTIER, FOND_NAV, date(2025, 10, 1), spot=7.0)
    kv = {k["dato"]: k for k in p["kvartaler"]}
    assert kv[date(2024, 12, 31)]["nav_dkk"] is not None
    assert kv[date(2025, 3, 31)]["nav_dkk"] is None
    assert kv[date(2025, 9, 30)]["netto_valuta"] == pytest.approx(-100.0)
