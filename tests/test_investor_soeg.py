"""Omtrentligt investornavn: find_investor og spørgsmålene i cli (uden database)."""
import pandas as pd
import pytest

from prognosemodel import cli, data

NAVNE = ["CR ApS", "CRH Holding A/S", "Kristian Rasmussen", "Anders And ApS"]


def test_normaliser():
    assert data.normaliser("C.R.  ApS") == data.normaliser("cr aps") == "cr aps"
    assert data.normaliser("CRH Holding A/S") == "crh holding as"


@pytest.mark.parametrize("soeg", ["CR ApS", "cr aps", "C.R. APS"])
def test_ens_efter_normalisering(soeg):
    assert data.find_investor(soeg, NAVNE)[0] == ("CR ApS", 1.0)


def test_helt_ord_foer_starten_af_et_ord():
    fund = data.find_investor("CR", NAVNE)
    assert [n for n, _ in fund[:2]] == ["CR ApS", "CRH Holding A/S"]
    assert data.find_investor("kri ras", NAVNE)[0][0] == "Kristian Rasmussen"


def test_stavefejl():
    assert data.find_investor("Kristan Rasmusen", NAVNE)[0][0] == "Kristian Rasmussen"


def test_intet_ligner():
    assert data.find_investor("xyz", NAVNE) == []
    assert data.find_investor("  ", NAVNE) == []
    assert len(data.naermeste_investorer("xyz", NAVNE, antal=2)) == 2


@pytest.fixture
def investorer(monkeypatch):
    monkeypatch.setattr(data, "investorer", lambda: pd.DataFrame({"navn": NAVNE}))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)


def _svar(monkeypatch, *svar):
    it = iter(svar)
    monkeypatch.setattr("builtins.input", lambda _: next(it))


def test_praecist_navn_uden_spoergsmaal(investorer, monkeypatch):
    _svar(monkeypatch)   # input må ikke kaldes
    assert cli._vaelg_investor("cr aps") == "CR ApS"


@pytest.mark.parametrize("svar", ["", "j"])
def test_bekraeft_eneste_forslag(investorer, monkeypatch, svar):
    _svar(monkeypatch, svar)
    assert cli._vaelg_investor("Kristan Rasmusen") == "Kristian Rasmussen"


def test_nej_afbryder(investorer, monkeypatch):
    _svar(monkeypatch, "n")
    with pytest.raises(SystemExit):
        cli._vaelg_investor("Kristan Rasmusen")


def test_vaelg_nummer(investorer, monkeypatch):
    _svar(monkeypatch, "9", "2")   # ugyldigt nummer spørges om igen
    assert cli._vaelg_investor("CR") == "CRH Holding A/S"


def test_q_afbryder(investorer, monkeypatch):
    _svar(monkeypatch, "q")
    with pytest.raises(SystemExit):
        cli._vaelg_investor("CR")


def test_ikke_interaktiv(investorer, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    _svar(monkeypatch)
    assert cli._vaelg_investor("Kristan Rasmusen") == "Kristian Rasmussen"
    with pytest.raises(SystemExit, match="Flere investorer"):
        cli._vaelg_investor("CR")


def test_intet_fund_giver_forslag(investorer):
    with pytest.raises(SystemExit, match="Ingen investor"):
        cli._vaelg_investor("xyz")
