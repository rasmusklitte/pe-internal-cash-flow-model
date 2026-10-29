"""Kalibrering af Takahashi-Alexander-profilerne til den interne metode (rene funktioner).

Den interne metode (RC/RD pr. kalenderår) bygger på fondenes egne meldinger om forventede
kald og udlodninger. Her findes for hver fond de TA-parametre, der gentager det mønster:
årlige kald og udlodninger i prognoseårene, med ekstra vægt på TVPI og IRR ved horisonten.

- Løbetiden lægges, så TA udlodder resten i det år, hvor den interne metode har Exit (RD = 1).
- Kaldsrater (for leveårene fra i dag og fem år frem), kald_til_aar, bow og udbytte findes
  med en simpel koordinatsøgning med halveret skridt. Hver beregning er beregning.ta_fond.

Begge motorer er lineære i tilsagn, resttilsagn og NAV, så alle investorers positioner i en
fond kan lægges sammen til én (samlet) og kalibreres som fonden.
"""
import math
from datetime import date

from . import beregning
from .prognose_ta import AAR

SUMMER = ("tilsagn", "tilsagn_dkk", "indbetalt", "resttilsagn", "resttilsagn_dkk",
          "markedsvaerdi_valuta", "markedsvaerdi_dkk", "fond_nav_dkk")
N_RATER = 6             # kaldsrater, der kalibreres: indeværende leveår og fem frem
VAEGT_TVPI = 10.0       # TVPI-forskellen i anden ganges med denne vægt
VAEGT_IRR = 30.0        # IRR-forskellen ganges med denne faktor, før den kvadreres
VAEGT_GLAT = 0.02       # straf for spring mellem kaldsraterne år for år (læsbare profiler)
GRAENSER = dict(kald_til_aar=(0.0, 30.0), bow=(0.3, 8.0), udbytte=(0.0, 0.3),
                loebetid_aar=(1.0, 30.0))


def samlet(positioner):
    """Flere investorers positioner i samme fond lagt sammen til én position."""
    f0 = positioner[0]
    ud = dict(fond=f0["fond"], valuta=f0["valuta"], vintage=f0["vintage"],
              vintage_dato=f0["vintage_dato"], spot=f0["spot"], betalinger=[], aar={})
    for k in SUMMER:
        ud[k] = sum(p.get(k) or 0.0 for p in positioner)
    for p in positioner:
        ud["betalinger"] += p["betalinger"]
        for a, v in p["aar"].items():
            s = ud["aar"].setdefault(a, {})
            for k, x in v.items():
                if isinstance(x, (int, float)) and not isinstance(x, bool):
                    s[k] = s.get(k, 0.0) + (x or 0.0)
    ud["betalinger"].sort(key=lambda b: b[0])
    return ud


def _prognoseaar(linjer, aar0):
    """{år: (kald, udlodning)} for prognoseårene; i indeværende år kun resten af året."""
    return {a["aar"]: (a.get("kald_rest", a["kald"]), a.get("udlodning_rest", a["udlodning"]))
            for a in linjer if a["aar"] >= aar0}


def afvigelse(ta, intern, tilsagn_dkk, aar0):
    """Tabet: kvadrerede forskelle i årlige kald og udlodninger (andel af tilsagnet) plus
    VAEGT_TVPI x forskellen i TVPI i anden og (VAEGT_IRR x forskellen i IRR) i anden."""
    t, i = _prognoseaar(ta["linjer"], aar0), _prognoseaar(intern["linjer"], aar0)
    tab = 0.0
    for a in set(t) | set(i):
        (kt, ut), (ki, ui) = t.get(a, (0.0, 0.0)), i.get(a, (0.0, 0.0))
        tab += ((kt - ki) ** 2 + (ut - ui) ** 2) / tilsagn_dkk ** 2
    if ta["tvpi"] is not None and intern["tvpi"] is not None:
        tab += VAEGT_TVPI * (ta["tvpi"] - intern["tvpi"]) ** 2
    if ta["irr"] is not None and intern["irr"] is not None:
        tab += (VAEGT_IRR * (ta["irr"] - intern["irr"])) ** 2
    return tab


def exit_loebetid(rd, vintage_dato, aar0):
    """Løbetiden, der lægger TA's slutudlodning i den interne metodes Exit-år (første år med
    RD = 1 fra aar0), rundet ned til et kvart år. None uden Exit."""
    exit_aar = min((a for a, r in rd.items() if r >= 1 and a >= aar0), default=None)
    if exit_aar is None:
        return None
    return math.floor((date(exit_aar, 12, 31) - vintage_dato).days / AAR * 4) / 4


def _params(x, base_rater, i0):
    rater = list(base_rater[:i0]) + [base_rater[-1]] * max(0, i0 - len(base_rater))
    rater += [x[f"rate{j}"] for j in range(N_RATER)]
    while len(rater) > 1 and rater[-1] == rater[-2]:     # den sidste rate gentages alligevel
        rater.pop()
    return dict(kaldsrater=rater, kald_til_aar=x["kald_til_aar"], bow=x["bow"],
                udbytte=x["udbytte"])


def _rund(x):
    ud = {k: round(v, 2) for k, v in x.items() if k.startswith("rate")}
    ud.update(kald_til_aar=round(x["kald_til_aar"] * 4) / 4, bow=round(x["bow"], 1),
              udbytte=round(x["udbytte"], 2), loebetid_aar=round(x["loebetid_aar"] * 4) / 4)
    return ud


def kalibrer(f, fs, dato, slut_aar, maal=None, maks_runder=40):
    """TA-parametre for én (samlet) fondsposition, kalibreret til den interne metode.

    fs er forudsaetninger.for_fond for fonden; maal er resultatet, der skal rammes (standard
    beregning.excel_fond, den interne metode, som decket viser den). Returnerer dict(profil, loebetid_aar,
    intern, foer, efter, tab_foer, tab_efter), hvor intern/foer/efter er dict(tvpi, irr).
    """
    intern = maal or beregning.excel_fond(f, fs, dato, slut_aar)
    alder = max(0.0, (dato - f["vintage_dato"]).days / AAR)
    i0 = int(alder)
    base = list(fs["ta"]["kaldsrater"])
    fast_l = exit_loebetid(fs["rd"], f["vintage_dato"], dato.year)

    def koer(x):
        p = {**fs["ta"], **_params(x, base, i0), "loebetid_aar": x["loebetid_aar"]}
        return beregning.ta_fond(f, {**fs, "ta": p, "loebetid_aar": x["loebetid_aar"]},
                                 dato, slut_aar)

    def tab(x):
        spring = sum((x[f"rate{j}"] - x[f"rate{j - 1}"]) ** 2 for j in range(1, N_RATER))
        return afvigelse(koer(x), intern, f["tilsagn_dkk"], dato.year) + VAEGT_GLAT * spring

    start = {f"rate{j}": base[min(i0 + j, len(base) - 1)] for j in range(N_RATER)}
    start.update(kald_til_aar=fs["ta"].get("kald_til_aar") or fs["loebetid_aar"],
                  bow=fs["ta"]["bow"], udbytte=fs["ta"]["udbytte"],
                  loebetid_aar=fs["loebetid_aar"])
    res_foer, tab_foer = koer(start), tab(start)

    x = dict(start)
    if fast_l is not None:
        x["loebetid_aar"] = max(fast_l, alder)
    graenser = {f"rate{j}": (0.0, 1.0) for j in range(N_RATER)}
    graenser.update(GRAENSER)
    graenser["kald_til_aar"] = (alder, 30.0)
    x["kald_til_aar"] = min(max(x["kald_til_aar"], alder), 30.0)
    skridt = {k: 0.1 if k.startswith("rate") else 0.05 if k == "udbytte" else 1.0
              for k in graenser}
    if fast_l is not None:
        del skridt["loebetid_aar"]
    mindst = {k: s / 32 for k, s in skridt.items()}
    bedst = tab(x)
    for _ in range(maks_runder):
        if all(skridt[k] < mindst[k] for k in skridt):
            break
        for k in skridt:
            if skridt[k] < mindst[k]:
                continue
            lo, hi = graenser[k]
            for fortegn in (1, -1):
                y = {**x, k: min(hi, max(lo, x[k] + fortegn * skridt[k]))}
                v = tab(y)
                if v < bedst - 1e-12:
                    x, bedst = y, v
                    break
            else:
                skridt[k] /= 2

    x = _rund(x)
    res = koer(x)
    return dict(profil=_params(x, base, i0), loebetid_aar=x["loebetid_aar"],
                intern=dict(tvpi=intern["tvpi"], irr=intern["irr"]),
                foer=dict(tvpi=res_foer["tvpi"], irr=res_foer["irr"]),
                efter=dict(tvpi=res["tvpi"], irr=res["irr"]),
                tab_foer=tab_foer, tab_efter=tab(x))
