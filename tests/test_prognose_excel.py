"""prognose_excel skal gentage det gamle Excel-ark tal for tal (gemte værdier i xlsm)."""
import pytest

import excel_ark
from prognosemodel import prognose_excel as pe

START = 2026            # arkets første prognoseår (kolonne L)


def _kør(f, **kw):
    aar = excel_ark.aar()
    historik = {a: dict(kald=k, udlodning=u, nav=n)
                for a, k, u, n in zip(aar, f["kald"], f["udlodning"], f["nav"]) if a < START}
    kald_valuta = {a: k for a, k in zip(aar, f["kald_valuta"]) if a < START}
    linjer = pe.fremskriv(aar, START, historik, f["tilsagn_dkk"], f["vaekst"], f["vintage"],
                          f["rc"], f["rd"], aktiv=f["aktiv"], tilsagn_valuta=f["tilsagn_valuta"],
                          kald_valuta_hist=kald_valuta, **kw)
    kompatibel = kw.get("excel_kompatibel", True)
    return linjer, pe.noegletal(linjer, f["tilsagn_dkk"], f["tilsagn_valuta"],
                                excel_kompatibel=kompatibel)


@pytest.mark.parametrize("i", range(6))
def test_gentager_arket(i):
    f = excel_ark.fond(i)
    linjer, kpi = _kør(f)
    assert [a["stadie"] for a in linjer] == f["stadie"]
    for felt in ("kald", "udlodning", "nav"):
        assert [a[felt] for a in linjer] == pytest.approx(f[felt], abs=0.01), felt
    assert [a["netto"] for a in linjer][1:] == pytest.approx(f["netto"][1:], abs=0.01)
    if not f["aktiv"]:
        return
    for k in ("indbetalt", "udloddet", "tvpi", "irr", "indbetalt_pct_valuta"):
        assert kpi[k] == pytest.approx(f["kpi"][k], rel=1e-6, abs=1e-6), k


def test_rettet_tilstand_kalder_hoejst_resttilsagnet():
    f = excel_ark.fond(4)       # Maritime: RC 3 x 20 % i prognosen
    rest = 1_000_000.0
    linjer, kpi = _kør(f, excel_kompatibel=False, resttilsagn_dkk=rest)
    assert sum(a["kald"] for a in linjer if a["prognose"]) == pytest.approx(rest)
    assert kpi["irr"] is not None


def test_stadie():
    assert pe.stadie(0.1, 0.0, "") == "RC"
    assert pe.stadie(0.0, 0.0, "") == ""
    assert pe.stadie(0.0, 0.0, "RC") == "RC"
    assert pe.stadie(0.1, 0.5, "RC") == "RC"     # RC vinder over RD i arket
    assert pe.stadie(0.0, 0.5, "RC") == "RD"
    assert pe.stadie(0.0, 1.0, "RD") == "Exit"
    assert pe.stadie(0.0, 0.5, "Exit") == ""
    assert pe.stadie(0.2, 0.0, "", foer_vintage=True) == ""
