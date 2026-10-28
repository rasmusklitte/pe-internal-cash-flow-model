"""Prognosen efter det gamle Excel-ark (alternativer_prognosemodel.xlsm, arket prognosemodel).

Rene funktioner, ingen database. Én fond fremskrives år for år i DKK:

- Stadie pr. år: tomt før vintage, efter Exit, eller når RC = RD = 0 og året før ikke var
  RC; ellers "RC" hvis RC > 0 eller RD = 0, "RD" hvis 0 < RD < 1, og "Exit" hvis RD = 1.
- Kald = RC x tilsagn i DKK (tilsagn i valuta x dagskurs), kun i RC-stadiet.
- Udlodning = RD x NAV året før i RD-stadiet, hele NAV året før ved Exit.
- NAV = NAV året før x (1 + vækst) + kald - udlodning; 0 ved Exit.

Historiske år (før prognosens første år) er faktiske tal; deres RC og RD regnes baglæns
(kald / tilsagn, udlodning / samme års NAV) og bruges kun til stadiet.

excel_kompatibel=True gentager arket tal for tal, også dets fejl. Med False rettes de:
- kald kan ikke overstige resttilsagnet,
- et år kan både have kald og udlodning (i arket vinder RC over RD),
- IRR medtager NAV ved horisonten som slutværdi (arket ignorerer den),
- ingen dummy-betaling på -0,00001 i første år.
"""
from datetime import date

from .noegletal import deling, xirr

STADIER = ("", "RC", "RD", "Exit")


def stadie(rc, rd, forrige, aktiv=True, foer_vintage=False):
    """Stadiet i et år som arkets række 40-45."""
    if not aktiv or foer_vintage or forrige == "Exit" or (rc == 0 and rd == 0 and forrige != "RC"):
        return ""
    if rc > 0 or rd == 0:
        return "RC"
    if 0 < rd < 1:
        return "RD"
    return "Exit" if rd == 1 else ""


def fremskriv(aar, start, historik, tilsagn_dkk, vaekst, vintage, rc, rd, aktiv=True,
              tilsagn_valuta=None, kald_valuta_hist=None, resttilsagn_dkk=None,
              excel_kompatibel=True):
    """Én fonds år.

    aar: alle år i tabellen (fx 2019..2035); start: prognosens første år (år før er
    faktiske). historik: {år: dict(kald, udlodning, nav)} i DKK (positive beløb). rc/rd:
    {år: sats} for prognoseårene. resttilsagn_dkk bruges kun uden excel_kompatibel.
    Returnerer [{aar, prognose, rc, rd, stadie, kald, udlodning, netto, nav, kald_valuta}].
    """
    kald_valuta_hist = kald_valuta_hist or {}
    rest = resttilsagn_dkk
    ud, forrige_stadie, nav_foer = [], "", 0.0
    for t in aar:
        if t < start:
            h = historik.get(t, {})
            kald, udl, nav = h.get("kald", 0.0), h.get("udlodning", 0.0), h.get("nav", 0.0) or 0.0
            r_c = deling(kald, tilsagn_dkk) or 0.0
            r_d = deling(udl, nav) or 0.0
            st = stadie(r_c, r_d, forrige_stadie, aktiv, t < vintage)
            kald_val = kald_valuta_hist.get(t, 0.0)
        else:
            r_c, r_d = rc.get(t, 0.0), rd.get(t, 0.0)
            st = stadie(r_c, r_d, forrige_stadie, aktiv, t < vintage)
            if excel_kompatibel:
                kald = r_c * tilsagn_dkk if st == "RC" else 0.0
                udl = r_d * nav_foer if st == "RD" else nav_foer if st == "Exit" else 0.0
            else:
                kald = r_c * tilsagn_dkk if st else 0.0
                if rest is not None:
                    kald = min(kald, max(rest, 0.0))
                    rest -= kald
                udl = nav_foer if st == "Exit" or r_d >= 1 else r_d * nav_foer if st else 0.0
            if st == "Exit" or (not excel_kompatibel and r_d >= 1 and st):
                nav = 0.0
            elif st == "" and nav_foer == 0:
                nav = 0.0
            else:
                nav = nav_foer * (1 + vaekst) + kald - udl
            kald_val = r_c * (tilsagn_valuta or 0.0) if st == "RC" else 0.0
        ud.append(dict(aar=t, prognose=t >= start, rc=r_c, rd=r_d, stadie=st, kald=kald,
                       udlodning=udl, netto=udl - kald, nav=nav, kald_valuta=kald_val))
        forrige_stadie, nav_foer = st, nav
    return ud


def noegletal(linjer, tilsagn_dkk, tilsagn_valuta=None, excel_kompatibel=True):
    """Arkets afledte rækker pr. år (lagt i linjerne) og fondens KPI'er (kolonne AA-AE).

    Returnerer dict(indbetalt, udloddet, tvpi, irr, indbetalt_pct_valuta).
    """
    kum_kald = kum_udl = kum_val = 0.0
    nav_foer = None
    for i, a in enumerate(linjer):
        kum_kald += a["kald"]
        kum_udl += a["udlodning"]
        kum_val += a["kald_valuta"]
        a.update(kum_kald=kum_kald, kum_udlodning=kum_udl, kum_likviditet=kum_udl - kum_kald,
                 indbetalt_pct=deling(kum_kald, tilsagn_dkk) or 0.0,
                 afkast_akk=kum_udl - kum_kald + a["nav"],
                 tvpi=deling(a["nav"] + kum_udl, kum_kald),
                 dpi=deling(kum_udl, kum_kald) or 0.0,
                 afkast_aar=deling(a["nav"] - nav_foer + a["udlodning"] - a["kald"], nav_foer)
                 if i else None,
                 kum_kald_valuta=kum_val,
                 indbetalt_pct_valuta=deling(kum_val, tilsagn_valuta))
        nav_foer = a["nav"]
    flows = [(date(a["aar"], 12, 31), a["netto"]) for a in linjer]
    if excel_kompatibel and flows[0][1] == 0:
        flows[0] = (flows[0][0], -0.00001)     # arkets celle E69 (første år er tomt i arket)
    else:
        flows[-1] = (flows[-1][0], flows[-1][1] + linjer[-1]["nav"])
    return dict(indbetalt=kum_kald, udloddet=kum_udl, tvpi=deling(kum_udl, kum_kald) or 0.0,
                irr=xirr(flows), indbetalt_pct_valuta=linjer[-1]["indbetalt_pct_valuta"])


def summer(fonde):
    """Flere fondes linjer lagt sammen år for år: [{aar, kald, udlodning, netto, nav}]."""
    ud = {}
    for linjer in fonde:
        for a in linjer:
            s = ud.setdefault(a["aar"], dict(aar=a["aar"], prognose=a["prognose"], kald=0.0,
                                             udlodning=0.0, netto=0.0, nav=0.0))
            for k in ("kald", "udlodning", "netto", "nav"):
                s[k] += a[k]
    return [ud[k] for k in sorted(ud)]
