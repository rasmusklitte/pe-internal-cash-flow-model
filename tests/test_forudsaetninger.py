import copy

import pytest

from prognosemodel import forudsaetninger as fu
from prognosemodel.data import FONDSORDEN


@pytest.fixture(scope="module")
def cfg():
    return fu.indlaes()


def test_alle_fonde_har_forudsaetninger(cfg):
    for fond in FONDSORDEN:
        f = fu.for_fond(cfg, fond)
        assert 0 < f["vaekst"] < 0.5
        assert f["ta"]["loebetid_aar"] == f["loebetid_aar"]


def test_investorafvigelse(cfg):
    c = copy.deepcopy(cfg)
    c["investorer"] = {"Test ApS": {"Maritime": {"vaekst": 0.05, "ta": {"bow": 3.0}}}}
    fu.valider(c)
    f = fu.for_fond(c, "Maritime", "Test ApS")
    assert f["vaekst"] == 0.05 and f["ta"]["vaekst"] == 0.05 and f["ta"]["bow"] == 3.0
    assert f["afvigelser"] == ["ta.bow", "vaekst"]
    assert fu.for_fond(c, "Maritime", "Anden")["vaekst"] == cfg["fonde"]["Maritime"]["vaekst"]


@pytest.mark.parametrize("aendring", [
    lambda c: c["fonde"]["Maritime"].update(vækst=0.1),                      # stavefejl
    lambda c: c["fonde"]["Maritime"]["excel"]["rd"].update({2030: 1.5}),     # sats > 1
    lambda c: c["fonde"]["Maritime"]["ta"].update(profil="Ukendt"),
    lambda c: c["generelt"].update(motor="magi"),
    lambda c: c["generelt"].update(scenarie="ukendt"),
])
def test_fejl_fanges(cfg, aendring):
    c = copy.deepcopy(cfg)
    aendring(c)
    with pytest.raises(ValueError):
        fu.valider(c)
