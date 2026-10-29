"""Kalibrering af TA-profilerne til den interne metode (konstruerede data, ingen database)."""
from datetime import date

import pytest
from test_data import FOND_AKTIER, FOND_NAV, TR

from prognosemodel import beregning, data, forudsaetninger, kalibrering

DATO = date(2025, 10, 1)
SLUT = 2034


@pytest.fixture
def pos():
    p = data.position(TR, FOND_AKTIER, FOND_NAV, DATO, spot=7.0)
    p.update(fond="Maritime", valuta="USD", vintage=2024, vintage_dato=date(2024, 1, 10))
    return p


@pytest.fixture
def cfg():
    return forudsaetninger.indlaes()


def test_samlet_er_summen(pos, cfg):
    fs = forudsaetninger.for_fond(cfg, "Maritime")
    en = beregning.ta_fond(pos, fs, DATO, SLUT)
    to = beregning.ta_fond(kalibrering.samlet([pos, pos]), fs, DATO, SLUT)
    for a, b in zip(en["linjer"], to["linjer"]):
        assert b["kald"] == pytest.approx(2 * a["kald"])
        assert b["udlodning"] == pytest.approx(2 * a["udlodning"])
        assert b["nav"] == pytest.approx(2 * a["nav"])
    assert to["tvpi"] == pytest.approx(en["tvpi"])
    assert to["irr"] == pytest.approx(en["irr"], abs=1e-6)


def test_exit_loebetid():
    rd = {2029: 0.2, 2034: 1.0}
    # 31.12.2034 er 10,97 år efter vintage; rundet ned til et kvart år
    assert kalibrering.exit_loebetid(rd, date(2024, 1, 10), 2025) == 10.75
    assert kalibrering.exit_loebetid({2030: 0.5}, date(2024, 1, 10), 2025) is None


def _generisk(cfg):
    fs = forudsaetninger.for_fond(cfg, "Maritime")
    generisk = cfg["profiler"]["Maritime (generisk)"]
    return {**fs, "loebetid_aar": 10, "ta": {**fs["ta"], **generisk, "loebetid_aar": 10}}


def test_soegningen_finder_kendte_parametre(pos, cfg):
    """Mål lavet af TA selv med kendte parametre: søgningen skal ramme det fra en anden start."""
    fs = _generisk(cfg)
    kendt = {**fs["ta"], "kaldsrater": [0.3, 0.5, 0.6], "kald_til_aar": 4.5, "bow": 3.5,
             "udbytte": 0.02, "loebetid_aar": 10.75}
    maal = beregning.ta_fond(pos, {**fs, "ta": kendt, "loebetid_aar": 10.75}, DATO, SLUT)
    res = kalibrering.kalibrer(pos, {**fs, "rd": {2034: 1.0}}, DATO, SLUT, maal=maal)
    assert res["loebetid_aar"] == 10.75
    assert res["tab_efter"] < 0.01 * res["tab_foer"]
    assert res["efter"]["tvpi"] == pytest.approx(maal["tvpi"], abs=0.02)
    assert res["efter"]["irr"] == pytest.approx(maal["irr"], abs=0.002)


def test_kalibrering_mod_den_interne_metode(pos, cfg):
    res = kalibrering.kalibrer(pos, _generisk(cfg), DATO, SLUT)
    assert res["tab_efter"] < res["tab_foer"]
    assert abs(res["efter"]["tvpi"] - res["intern"]["tvpi"]) < 0.05
    assert res["loebetid_aar"] == 10.75          # Exit 2034 i den interne metode
    assert all(0 <= r <= 1 for r in res["profil"]["kaldsrater"])


def test_hver_fond_har_sin_egen_profil(cfg):
    for fond, f in cfg["fonde"].items():
        assert f["ta"]["profil"] == fond
        assert fond in cfg["profiler"]
