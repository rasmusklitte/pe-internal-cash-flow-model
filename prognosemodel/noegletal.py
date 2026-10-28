"""Nøgletal (rene funktioner, ingen database).

Fortegn er investorens: indbetaling (kald) < 0, udlodning > 0, NAV > 0.
"""
from datetime import date


def xirr(flows):
    """flows: [(dato, beløb)], act/365 som Excels XIRR, bisektion. None uden fortegnsskifte."""
    flows = [(d, a) for d, a in flows if a]
    if not flows or min(a for _, a in flows) >= 0 or max(a for _, a in flows) <= 0:
        return None
    t0 = min(d for d, _ in flows)
    f = lambda r: sum(a / (1 + r) ** ((d - t0).days / 365) for d, a in flows)
    lo, hi = -0.99, 10.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def deling(t, n):
    """t / n, None når n er 0 eller mangler."""
    return t / n if n else None


def multipler(indbetalt, udloddet, nav):
    """{dpi, rvpi, tvpi} ud fra positive beløb."""
    return dict(dpi=deling(udloddet, indbetalt), rvpi=deling(nav, indbetalt),
                tvpi=deling(udloddet + nav, indbetalt))


def kvartalsafkast(nav, netto):
    """Kvartalsafkast som i Excel-arket Kvartalsafkast.

    nav: {kvartalsultimo: NAV}, inkl. ultimo forrige år; netto: {kvartalsultimo: udlodning -
    indbetaling i kvartalet}. Afkast = (NAV_ultimo - NAV_primo + netto) / NAV_primo.
    Returnerer [{dato, primo, ultimo, netto, afkast_beloeb, afkast}] for kvartaler med begge
    NAV'er; ÅTD findes med kaedet().
    """
    datoer = sorted(nav)
    ud = []
    for forrige, d in zip(datoer, datoer[1:]):
        primo, ultimo = nav[forrige], nav[d]
        if primo is None or ultimo is None:
            continue
        beloeb = ultimo - primo + netto.get(d, 0.0)
        ud.append(dict(dato=d, primo=primo, ultimo=ultimo, netto=netto.get(d, 0.0),
                       afkast_beloeb=beloeb, afkast=deling(beloeb, primo)))
    return ud


def kaedet(afkast):
    """Geometrisk kædet afkast af en række periodeafkast (None springes over)."""
    r = 1.0
    tal = [a for a in afkast if a is not None]
    for a in tal:
        r *= 1 + a
    return r - 1 if tal else None


def kvartalsultimoer(aar):
    """31.12 året før og de fire kvartalsultimoer i aar."""
    return [date(aar - 1, 12, 31), date(aar, 3, 31), date(aar, 6, 30), date(aar, 9, 30),
            date(aar, 12, 31)]
