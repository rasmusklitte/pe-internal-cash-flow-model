"""Kører prognosemotorerne på en investors data (fra data.hent) med forudsætningerne.

Begge motorer giver samme form pr. fond, i DKK:
    linjer: [{aar, prognose, kald, udlodning, netto, nav}]  (faktiske år + prognoseår)
    irr, tvpi, dpi ved horisonten (inkl. NAV ved horisonten som slutværdi)
Indeværende år er faktisk ÅTD + resten af året (ta), eller hele året fra arket (excel; ÅTD
og resten af året vises som i arket).
"""
from datetime import date

from . import prognose_excel, prognose_ta
from .forudsaetninger import for_fond
from .noegletal import deling, multipler, xirr


def _historik(f, til_aar):
    return [dict(aar=a, prognose=False, kald=v["kald"], udlodning=v["udlodning"],
                 netto=v["udlodning"] - v["kald"], nav=v["nav"])
            for a, v in sorted(f["aar"].items()) if a < til_aar]


def ta_fond(f, fs, dato, slut_aar, scenarie=None):
    """Takahashi-Alexander for én fond i DKK (dagskurs).

    Returnerer dict(linjer, kvartaler, irr, tvpi, dpi, slut_nav).
    """
    p = prognose_ta.scenarie(fs["ta"], scenarie)
    kv = prognose_ta.fremskriv(dato, date(slut_aar, 12, 31), f["resttilsagn"],
                               f["markedsvaerdi_valuta"], f["vintage_dato"], fs["loebetid_aar"], p)
    spot = f["spot"]
    pr_aar = {a["aar"]: a for a in prognose_ta.pr_aar(kv, spot)}
    linjer = _historik(f, dato.year)
    ytd = f["aar"].get(dato.year, dict(kald=0.0, udlodning=0.0))
    for aar in range(dato.year, slut_aar + 1):
        a = pr_aar.get(aar, dict(kald=0.0, udlodning=0.0, nav=f["markedsvaerdi_dkk"]))
        kald, udl = a["kald"], a["udlodning"]
        if aar == dato.year:
            kald, udl = kald + ytd["kald"], udl + ytd["udlodning"]
        linjer.append(dict(aar=aar, prognose=True, kald=kald, udlodning=udl, netto=udl - kald,
                           nav=a["nav"], kald_rest=a["kald"], udlodning_rest=a["udlodning"]))
    flows = [(b[0], b[2]) for b in f["betalinger"]]
    flows += [(q["dato"], (q["udlodning"] - q["kald"]) * spot) for q in kv]
    slut_nav = kv[-1]["nav"] * spot if kv else f["markedsvaerdi_dkk"]
    flows.append((date(slut_aar, 12, 31), slut_nav))
    indbetalt = sum(x["kald"] for x in linjer)
    udloddet = sum(x["udlodning"] for x in linjer)
    return dict(linjer=linjer, kvartaler=kv, irr=xirr(flows), slut_nav=slut_nav,
                **multipler(indbetalt, udloddet, slut_nav))


def excel_fond(f, fs, dato, slut_aar, excel_kompatibel=True):
    """Excel-arkets metode for én fond i DKK."""
    foerste = min(f["aar"], default=dato.year)
    aar = list(range(foerste, slut_aar + 1))
    historik = {a: v for a, v in f["aar"].items() if a < dato.year}
    kald_val = {a: v["kald_valuta"] for a, v in historik.items()}
    rest = f["resttilsagn_dkk"] + f["aar"].get(dato.year, {}).get("kald", 0.0)
    linjer = prognose_excel.fremskriv(
        aar, dato.year, historik, f["tilsagn_dkk"], fs["vaekst"], f["vintage"], fs["rc"], fs["rd"],
        aktiv=bool(f["fond_nav_dkk"]), tilsagn_valuta=f["tilsagn"], kald_valuta_hist=kald_val,
        resttilsagn_dkk=rest, excel_kompatibel=excel_kompatibel)
    kpi = prognose_excel.noegletal(linjer, f["tilsagn_dkk"], f["tilsagn"],
                                   excel_kompatibel=excel_kompatibel)
    ytd = f["aar"].get(dato.year, dict(kald=0.0, udlodning=0.0))
    for a in linjer:
        if a["aar"] == dato.year:
            a.update(kald_ytd=ytd["kald"], udlodning_ytd=ytd["udlodning"],
                     kald_rest=a["kald"] - ytd["kald"], udlodning_rest=a["udlodning"] - ytd["udlodning"])
    slut_nav = linjer[-1]["nav"]
    flows = [(b[0], b[2]) for b in f["betalinger"]]
    flows += [(date(a["aar"], 12, 31), a.get("udlodning_rest", a["udlodning"])
               - a.get("kald_rest", a["kald"])) for a in linjer if a["prognose"]]
    flows.append((date(slut_aar, 12, 31), slut_nav))
    return dict(linjer=linjer, irr=xirr(flows), irr_arket=kpi["irr"], arket=kpi,
                slut_nav=slut_nav, **multipler(kpi["indbetalt"], kpi["udloddet"], slut_nav))


def summer(linjer_pr_fond):
    ud = {}
    for linjer in linjer_pr_fond:
        for a in linjer:
            s = ud.setdefault(a["aar"], dict(aar=a["aar"], prognose=a["prognose"], kald=0.0,
                                             udlodning=0.0, netto=0.0, nav=0.0))
            for k in ("kald", "udlodning", "netto", "nav"):
                s[k] += a[k]
    return [ud[k] for k in sorted(ud)]


def kumuler(linjer):
    """Kumulerede rækker som arkets række 90-136, lagt i linjerne."""
    kk = ku = 0.0
    for a in linjer:
        kk += a["kald"]
        ku += a["udlodning"]
        a.update(kum_kald=kk, kum_udlodning=ku, kum_likviditet=ku - kk,
                 afkast_akk=ku - kk + a["nav"], tvpi=deling(a["nav"] + ku, kk))
    return linjer


def prognose(r, cfg, motor=None, scenarie=None):
    """Prognosen for alle investorens fonde.

    Returnerer dict(motor, scenarie, slut_aar, fonde={fond: resultat}, total=[linjer],
    forudsaetninger={fond: anvendte}, scenarier={navn: total-linjer} (kun ta)).
    """
    g = cfg.get("generelt") or {}
    motor = motor or g.get("motor", "ta")
    scenarie = scenarie or g.get("scenarie", "basis")
    dato = r["dato"]
    slut_aar = dato.year + g.get("horisont_aar", 10) - 1
    fs = {f["fond"]: for_fond(cfg, f["fond"], r["navn"]) for f in r["fonde"]}
    scen = cfg.get("scenarier") or {}

    def koer(m, s):
        if m == "excel":
            return {f["fond"]: excel_fond(f, fs[f["fond"]], dato, slut_aar) for f in r["fonde"]}
        return {f["fond"]: ta_fond(f, fs[f["fond"]], dato, slut_aar, scen.get(s))
                for f in r["fonde"]}

    fonde = koer(motor, scenarie)
    for res in fonde.values():
        kumuler(res["linjer"])
    total = kumuler(summer(res["linjer"] for res in fonde.values()))
    ud = dict(motor=motor, scenarie=scenarie, scenarie_navn=scen.get(scenarie, {}).get("navn"),
              slut_aar=slut_aar, fonde=fonde, total=total, forudsaetninger=fs)
    ud["total_irr"] = _total_irr(r, fonde, motor, slut_aar)
    if motor == "ta":
        ud["scenarier"] = {s: summer(x["linjer"] for x in koer("ta", s).values()) for s in scen}
    ud["excel"] = koer("excel", None) if motor == "ta" else fonde
    ud["excel_total"] = summer(x["linjer"] for x in ud["excel"].values())
    return ud


def _total_irr(r, fonde, motor, slut_aar):
    flows = [(b[0], b[2]) for f in [*r["fonde"], *r.get("solgte", [])] for b in f["betalinger"]]
    for f in r["fonde"]:
        res = fonde[f["fond"]]
        if motor == "ta":
            flows += [(q["dato"], (q["udlodning"] - q["kald"]) * f["spot"]) for q in res["kvartaler"]]
        else:
            flows += [(date(a["aar"], 12, 31), a.get("udlodning_rest", a["udlodning"])
                       - a.get("kald_rest", a["kald"])) for a in res["linjer"] if a["prognose"]]
        flows.append((date(slut_aar, 12, 31), res["slut_nav"]))
    return xirr(flows)


def kommende(linjer, aar, antal=3):
    """Forventede kald og udlodninger: resten af indeværende år og de næste år (DKK).

    [{aar, kald, udlodning, netto}] for aar..aar+antal-1; i indeværende år kun resten.
    """
    ud = []
    for a in linjer:
        if aar <= a["aar"] < aar + antal:
            kald = a.get("kald_rest", a["kald"]) if a["aar"] == aar else a["kald"]
            udl = a.get("udlodning_rest", a["udlodning"]) if a["aar"] == aar else a["udlodning"]
            ud.append(dict(aar=a["aar"], kald=kald, udlodning=udl, netto=udl - kald))
    return ud
