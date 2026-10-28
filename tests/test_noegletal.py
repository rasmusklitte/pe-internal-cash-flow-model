from datetime import date

import pytest

from prognosemodel.noegletal import kaedet, kvartalsafkast, multipler, xirr


def test_xirr_et_aar():
    assert xirr([(date(2020, 1, 1), -100), (date(2021, 1, 1), 110)]) == pytest.approx(
        0.10, abs=1e-3)


def test_xirr_uden_fortegnsskifte():
    assert xirr([(date(2020, 1, 1), -100)]) is None


def test_multipler():
    m = multipler(100, 20, 110)
    assert m == pytest.approx(dict(dpi=0.2, rvpi=1.1, tvpi=1.3))
    assert multipler(0, 0, 10)["tvpi"] is None


def test_kvartalsafkast_som_arket():
    # Private Equity I, CR ApS, Q2 2026 i arket Kvartalsafkast: 246.571 / 10.823.303 = 2,28 %
    nav = {date(2026, 3, 31): 10_823_303.0, date(2026, 6, 30): 11_069_874.0}
    (q,) = kvartalsafkast(nav, {})
    assert q["afkast"] == pytest.approx(0.02278, abs=1e-4)


def test_kvartalsafkast_med_indbetaling():
    nav = {date(2025, 12, 31): 100.0, date(2026, 3, 31): 130.0}
    (q,) = kvartalsafkast(nav, {date(2026, 3, 31): -20.0})   # 20 indbetalt i kvartalet
    assert q["afkast"] == pytest.approx(0.10)


def test_kaedet():
    assert kaedet([0.1, None, 0.1]) == pytest.approx(0.21)
    assert kaedet([None]) is None
