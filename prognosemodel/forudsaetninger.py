"""config/forudsaetninger.yaml: indlæsning, validering og opslag pr. investor og fond."""
import copy

import yaml

from .paths import FORUDSAETNINGER
from .prognose_ta import FELTER as TA_FELTER

TOP = {"generelt", "fonde", "profiler", "scenarier", "investorer"}
GENERELT = {"motor", "scenarie", "horisont_aar"}
FOND = {"vaekst", "loebetid_aar", "ta", "excel"}
EXCEL = {"rc", "rd"}
TA_AFVIGELSER = {"profil", "kaldsrater", "kald_til_aar", "bow", "udbytte"}
PROFIL = {"kaldsrater", "kald_til_aar", "bow", "udbytte"}
SCENARIE = {"navn", "vaekst", "bow", "udbytte", "kaldsrater"}
MOTORER = ("ta", "excel")


def _ukendte(d, tilladte, hvor):
    ukendte = set(d or {}) - set(tilladte)
    if ukendte:
        raise ValueError(f"{hvor}: ukendte nøgler {', '.join(sorted(ukendte))}")


def _sats(v, hvor):
    if not isinstance(v, (int, float)) or not 0 <= v <= 1:
        raise ValueError(f"{hvor}: {v!r} skal være et tal mellem 0 og 1")


def _tjek_fond(f, hvor, profiler):
    _ukendte(f, FOND, hvor)
    if "vaekst" in f and not isinstance(f["vaekst"], (int, float)):
        raise ValueError(f"{hvor}.vaekst skal være et tal")
    ta = f.get("ta") or {}
    _ukendte(ta, TA_AFVIGELSER, f"{hvor}.ta")
    if "profil" in ta and ta["profil"] not in profiler:
        raise ValueError(f"{hvor}.ta: ukendt profil {ta['profil']!r}")
    for r in ta.get("kaldsrater", []):
        _sats(r, f"{hvor}.ta.kaldsrater")
    excel = f.get("excel") or {}
    _ukendte(excel, EXCEL, f"{hvor}.excel")
    for k in EXCEL:
        for aar, sats in (excel.get(k) or {}).items():
            if not isinstance(aar, int):
                raise ValueError(f"{hvor}.excel.{k}: årstal {aar!r} skal være et heltal")
            _sats(sats, f"{hvor}.excel.{k}[{aar}]")


def valider(cfg):
    _ukendte(cfg, TOP, "forudsaetninger")
    g = cfg.get("generelt") or {}
    _ukendte(g, GENERELT, "generelt")
    if g.get("motor", "ta") not in MOTORER:
        raise ValueError(f"generelt.motor skal være en af {MOTORER}")
    profiler = cfg.get("profiler") or {}
    for navn, p in profiler.items():
        _ukendte(p, PROFIL, f"profiler.{navn}")
        for r in p.get("kaldsrater", []):
            _sats(r, f"profiler.{navn}.kaldsrater")
    scenarier = cfg.get("scenarier") or {}
    if g.get("scenarie", "basis") not in scenarier:
        raise ValueError(f"generelt.scenarie: ukendt scenarie {g.get('scenarie')!r}")
    for navn, s in scenarier.items():
        _ukendte(s, SCENARIE, f"scenarier.{navn}")
    for fond, f in (cfg.get("fonde") or {}).items():
        _tjek_fond(f, f"fonde.{fond}", profiler)
    for inv, fonde in (cfg.get("investorer") or {}).items():
        for fond, f in (fonde or {}).items():
            _tjek_fond(f, f"investorer.{inv}.{fond}", profiler)
    return cfg


def indlaes(sti=FORUDSAETNINGER):
    with open(sti, encoding="utf-8") as fh:
        return valider(yaml.safe_load(fh) or {})


def _flet(a, b):
    ud = copy.deepcopy(a)
    for k, v in (b or {}).items():
        ud[k] = _flet(ud.get(k) or {}, v) if isinstance(v, dict) else copy.deepcopy(v)
    return ud


def for_fond(cfg, fond, investor=None):
    """De anvendte forudsætninger for én fond hos én investor.

    dict(vaekst, loebetid_aar, profil, ta (fulde TA-parametre), rc, rd, afvigelser), hvor
    afvigelser er de nøgler, investoren har overstyret.
    """
    basis = (cfg.get("fonde") or {}).get(fond)
    if basis is None:
        raise ValueError(f"Ingen forudsætninger for fonden {fond!r} i forudsaetninger.yaml")
    egne = ((cfg.get("investorer") or {}).get(investor) or {}).get(fond) or {}
    f = _flet(basis, egne)
    ta = dict(f.get("ta") or {})
    profil = ta.pop("profil", None)
    profiler = cfg.get("profiler") or {}
    if profil not in profiler:
        raise ValueError(f"{fond}: ukendt eller manglende TA-profil {profil!r}")
    params = {**profiler[profil], **ta, "vaekst": f["vaekst"], "loebetid_aar": f["loebetid_aar"]}
    assert set(params) == set(TA_FELTER), set(TA_FELTER) ^ set(params)
    excel = f.get("excel") or {}
    afvig = sorted(_stier(egne))
    return dict(vaekst=f["vaekst"], loebetid_aar=f["loebetid_aar"], profil=profil, ta=params,
                rc=dict(excel.get("rc") or {}), rd=dict(excel.get("rd") or {}), afvigelser=afvig)


def _stier(d, forfra=""):
    for k, v in (d or {}).items():
        sti = f"{forfra}{k}"
        if isinstance(v, dict) and v and not all(isinstance(x, int) for x in v):
            yield from _stier(v, sti + ".")
        else:
            yield sti
