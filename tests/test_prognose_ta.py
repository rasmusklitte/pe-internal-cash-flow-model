from datetime import date

import pytest

from prognosemodel import prognose_ta as ta

P = dict(kaldsrater=[0.3, 0.4], kald_til_aar=5, vaekst=0.1, bow=2.0, udbytte=0.0,
         loebetid_aar=10)


def test_nav_kaede_lukker():
    kv = ta.fremskriv(date(2026, 1, 1), date(2040, 12, 31), 1000.0, 500.0, date(2024, 1, 1),
                      10, P)
    for q in kv:
        assert q["nav"] == pytest.approx(q["nav_primo"] * q["vaekstfaktor"] + q["kald"]
                                         - q["udlodning"])
    assert kv[-1]["nav"] == pytest.approx(0.0, abs=1e-6)   # alt udloddet ved løbetidens udgang
    assert sum(q["kald"] for q in kv) <= 1000.0


def test_svagt_scenarie_lavere_vaekst():
    s = ta.scenarie(P, dict(vaekst=-0.06, bow=1.3))
    assert s["vaekst"] == pytest.approx(0.04) and s["bow"] == pytest.approx(2.6)
