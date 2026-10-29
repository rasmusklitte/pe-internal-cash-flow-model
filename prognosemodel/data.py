"""Investorens positioner i P&P-fondene, hentet fra de gamle dbo-tabeller (kun læsning).

hent(navn, dato) kører sql/*.sql og samler én dict pr. fond. Selve regnestykkerne er rene
funktioner (position, aarstal, kvartaler), så de kan testes uden database.

Definitioner (som i de gamle procedurer, se docs/legacy_sql/):
- Ejerandel = investorens kumulerede aktier / fondens kumulerede aktier på NAV-datoen.
- NAV (DKK) = ejerandel x fondens EGENKAPITAL_VAERDI (DKK); NAV (valuta) = NAV DKK / NAV-kurs.
- Markedsværdi pr. dato = seneste NAV + nettoindskud siden NAV-datoen (til kostpris).
- Indbetalt (til tilsagnet) = OPKRÆVET; kontant betalt = BELOEB / BETALT_DKK.
- KØB/SALG er handler mellem investorer: prisen er en betaling, og OPKRÆVET flyttes med.
"""
import difflib
import re
from datetime import date

import pandas as pd

from . import db
from .noegletal import deling, kvartalsultimoer, multipler, xirr

UD = ("CLOSING", "DRAWDOWN", "KØB")     # investor betaler
IND = ("DISTRIBUTION", "SALG")          # investor modtager
FONDSORDEN = ("Private Equity I", "Private Equity II", "Private Credit I", "Private Credit II",
              "Maritime", "FoF")


def _dato(v):
    return v.date() if hasattr(v, "date") and not isinstance(v, date) else v


def investorer():
    return db.sql_fil("investorer")


def normaliser(navn):
    """Små bogstaver uden tegnsætning: 'C.R. ApS', 'cr aps' og 'CR  APS' bliver ens."""
    s = re.sub(r"[.,/']", "", str(navn).casefold().replace("-", " "))
    return " ".join(s.split())


def find_investor(soeg, navne, graense=0.6, maks=8):
    """Investornavne, der ligner søgningen, som [(navn, score)] med det bedste først.

    1.0 = ens efter normalisering; 0.95 = hvert søgeord er et helt ord i navnet;
    0.9 = hvert søgeord er starten af et ord; 0.85 = søgningen står inde i navnet;
    ellers difflibs lighed (fanger stavefejl)."""
    s = normaliser(soeg)
    if not s:
        return []
    ord_s = s.split()
    fund = []
    for navn in navne:
        n = normaliser(navn)
        ord_n = n.split()
        if n == s:
            score = 1.0
        elif all(o in ord_n for o in ord_s):
            score = 0.95
        elif all(any(w.startswith(o) for w in ord_n) for o in ord_s):
            score = 0.9
        elif s in n:
            score = 0.85
        else:
            score = difflib.SequenceMatcher(None, s, n).ratio()
        if score >= graense:
            fund.append((navn, score))
    fund.sort(key=lambda t: (-t[1], t[0]))
    return fund[:maks]


def naermeste_investorer(soeg, navne, antal=5):
    """De navne, der ligner mest, uanset grænse (forslag, når intet passer)."""
    s = normaliser(soeg)

    def lighed(navn):
        return difflib.SequenceMatcher(None, s, normaliser(navn)).ratio()

    return sorted(navne, key=lighed, reverse=True)[:antal]


def hent(navn, dato=None):
    """Alt om investoren pr. dato (standard i dag) som én dict."""
    dato = dato or date.today()
    tr = db.sql_fil("transaktioner", navn=navn)
    if tr.empty:
        raise ValueError(f"Ingen transaktioner for investoren {navn!r}")
    fonde = db.sql_fil("fonde").set_index("fond")
    aktier = db.sql_fil("fond_aktier", navn=navn)
    nav = db.sql_fil("fond_nav", navn=navn)
    kurser = db.sql_fil("valutakurser", til=dato)
    for df in (tr, aktier, nav, kurser):
        df["dato"] = pd.to_datetime(df["dato"]).dt.date
    for k in ("kurs", "tilsagn_pct", "beloeb", "opkraevet", "rabat", "true_up", "tilsagn",
              "betalt_dkk", "aktier"):
        tr[k] = pd.to_numeric(tr[k], errors="coerce")
    spot = {v: (g["dato"].iloc[-1], g["kurs"].iloc[-1]) for v, g in kurser.groupby("valuta")}

    positioner, solgte = [], []
    for fond in sorted(tr["fond"].unique(), key=_fondsorden):
        stam = fonde.loc[fond] if fond in fonde.index else None
        valuta = stam["valuta"] if stam is not None else tr.loc[tr.fond == fond, "valuta"].iloc[0]
        p = position(tr[tr.fond == fond], aktier[aktier.fond == fond], nav[nav.fond == fond],
                     dato, spot[valuta][1])
        if p is None:
            continue
        if p["tilsagn"] <= 0 and abs(p["markedsvaerdi_valuta"]) < 1:
            solgte.append(dict(fond=fond, betalinger=p["betalinger"]))    # hele andelen solgt
            continue
        vintage = _dato(stam["vintage"]) if stam is not None else min(b[0] for b in p["betalinger"])
        p.update(fond=fond, valuta=valuta, vintage=vintage.year, vintage_dato=vintage,
                 underliggende_fond=stam["underliggende_fond"] if stam is not None else None)
        positioner.append(p)
    if not positioner:
        raise ValueError(f"{navn} har ingen aktive positioner pr. {dato:%d.%m.%Y} "
                         f"(solgt: {', '.join(x['fond'] for x in solgte) or 'ingen'})")
    return dict(navn=navn, dato=dato, fonde=positioner, solgte=solgte,
                kurser={v: dict(dato=d, kurs=k) for v, (d, k) in spot.items()},
                total=total(positioner, solgte))


def _fondsorden(fond):
    return FONDSORDEN.index(fond) if fond in FONDSORDEN else len(FONDSORDEN)


def betalinger(tr):
    """Transaktionerne med investorens fortegn: [(dato, valuta, dkk, event)]."""
    ud = []
    for r in tr.itertuples():
        if r.event not in UD + IND:
            continue
        fortegn = -1 if r.event in UD else 1
        beloeb = abs(r.beloeb or 0.0)
        beloeb = 0.0 if pd.isna(beloeb) else beloeb
        kurs = 0.0 if pd.isna(r.kurs) else r.kurs
        dkk = abs(r.betalt_dkk) if pd.notna(r.betalt_dkk) else beloeb * kurs
        ud.append((r.dato, fortegn * beloeb, fortegn * dkk, r.event))
    return ud


def _kumuleret(df, kolonne, til):
    return float(df.loc[df["dato"] <= til, kolonne].sum())


def _aktier_investor(tr):
    """Investorens daglige ændring i aktier (delta) og i indbetalt (delta_opkraevet)."""
    a = tr[tr.event.isin(UD + ("SALG",))].copy()
    fortegn = a["event"].map(lambda e: -1 if e == "SALG" else 1)
    a["delta"] = a["aktier"].abs().fillna(0) * fortegn
    a["delta_opkraevet"] = a["opkraevet"].abs().fillna(0) * fortegn
    return a


def nav_pr(dato, inv_aktier, fond_aktier, fond_nav, praecis=False):
    """Investorens NAV på seneste fonds-NAV <= dato (eller præcis på dato).

    Returnerer dict(nav_dato, ejerandel, nav_dkk, nav_valuta, kurs) eller None.
    """
    n = fond_nav[fond_nav["dato"] == dato] if praecis else fond_nav[fond_nav["dato"] <= dato]
    if n.empty:
        return None
    r = n.sort_values(["dato", "id"]).iloc[-1]
    fond_aktier_i_alt = _kumuleret(fond_aktier, "delta_aktier", r.dato)
    if fond_aktier_i_alt:
        ejerandel = deling(_kumuleret(inv_aktier, "delta", r.dato), fond_aktier_i_alt) or 0.0
        grundlag = "aktier"
    else:       # K/S uden aktier (FoF): andelen af det indbetalte
        ejerandel = deling(_kumuleret(inv_aktier, "delta_opkraevet", r.dato),
                           _kumuleret(fond_aktier, "delta_opkraevet", r.dato)) or 0.0
        grundlag = "indbetalt"
    nav_dkk = ejerandel * r.nav_dkk
    return dict(nav_dato=r.dato, ejerandel=ejerandel, fond_nav_dkk=r.nav_dkk, nav_dkk=nav_dkk,
                nav_valuta=deling(nav_dkk, r.kurs) or 0.0, kurs=r.kurs, grundlag=grundlag)


def position(tr, fond_aktier, fond_nav, dato, spot):
    """Én fonds position pr. dato. None hvis investoren ikke har tilsagn i fonden."""
    tr = tr[tr["dato"] <= dato].sort_values(["dato", "id"])
    tilsagn_raekker = tr["tilsagn"].dropna()
    tilsagn = float(tilsagn_raekker.iloc[-1]) if len(tilsagn_raekker) else 0.0
    if tilsagn <= 0 and tr[tr.event.isin(UD)].empty:
        return None
    opk = tr[tr.event.isin(UD + IND)]
    indbetalt = float(opk["opkraevet"].fillna(0).sum())      # SALG er negativ i databasen
    bet = betalinger(tr)
    inv_aktier = _aktier_investor(tr)
    n = nav_pr(dato, inv_aktier, fond_aktier, fond_nav)

    efter = [b for b in bet if n is None or b[0] > n["nav_dato"]]
    mv_valuta = (n["nav_valuta"] if n else 0.0) - sum(b[1] for b in efter)
    mv_dkk_kost = (n["nav_dkk"] if n else 0.0) - sum(b[2] for b in efter)
    mv_dkk = mv_valuta * spot

    ud_val = -sum(b[1] for b in bet if b[1] < 0)
    ind_val = sum(b[1] for b in bet if b[1] > 0)
    ud_dkk = -sum(b[2] for b in bet if b[2] < 0)
    ind_dkk = sum(b[2] for b in bet if b[2] > 0)
    return dict(
        tilsagn=tilsagn, indbetalt=indbetalt, resttilsagn=tilsagn - indbetalt,
        indbetalt_pct=deling(indbetalt, tilsagn), tilsagn_dkk=tilsagn * spot,
        resttilsagn_dkk=(tilsagn - indbetalt) * spot, spot=spot,
        betalt_valuta=ud_val, udloddet_valuta=ind_val, betalt_dkk=ud_dkk, udloddet_dkk=ind_dkk,
        nav_dato=n["nav_dato"] if n else None, ejerandel=n["ejerandel"] if n else None,
        ejerandel_grundlag=n["grundlag"] if n else None,
        fond_nav_dkk=n["fond_nav_dkk"] if n else None, nav_kurs=n["kurs"] if n else None,
        nav_valuta=n["nav_valuta"] if n else None, nav_dkk=n["nav_dkk"] if n else None,
        markedsvaerdi_valuta=mv_valuta, markedsvaerdi_dkk_kost=mv_dkk_kost, markedsvaerdi_dkk=mv_dkk,
        irr_valuta=xirr([(b[0], b[1]) for b in bet] + [(dato, mv_valuta)]),
        irr_dkk=xirr([(b[0], b[2]) for b in bet] + [(dato, mv_dkk)]),
        multipler_valuta=multipler(ud_val, ind_val, mv_valuta),
        multipler_dkk=multipler(ud_dkk, ind_dkk, mv_dkk),
        betalinger=bet,
        aar=aarstal(bet, inv_aktier, fond_aktier, fond_nav, dato),
        kvartaler=kvartaler(bet, inv_aktier, fond_aktier, fond_nav, dato.year),
    )


def aarstal(bet, inv_aktier, fond_aktier, fond_nav, dato):
    """Faktiske tal pr. kalenderår fra første betaling til dato's år.

    {år: dict(kald, udlodning, kald_valuta, udlodning_valuta, nav, nav_valuta, nav_dato)}; kald
    og udlodning er positive DKK til transaktionskurs. NAV er pr. 31.12 (seneste fonds-NAV
    <= 31.12); i indeværende år pr. dato.
    """
    if not bet:
        return {}
    ud = {}
    for aar in range(min(b[0] for b in bet).year, dato.year + 1):
        i_aar = [b for b in bet if b[0].year == aar and b[0] <= dato]
        slut = min(date(aar, 12, 31), dato)
        n = nav_pr(slut, inv_aktier, fond_aktier, fond_nav)
        ud[aar] = dict(kald=-sum(b[2] for b in i_aar if b[2] < 0),
                       udlodning=sum(b[2] for b in i_aar if b[2] > 0),
                       kald_valuta=-sum(b[1] for b in i_aar if b[1] < 0),
                       udlodning_valuta=sum(b[1] for b in i_aar if b[1] > 0),
                       nav=n["nav_dkk"] if n else 0.0, nav_valuta=n["nav_valuta"] if n else 0.0,
                       nav_dato=n["nav_dato"] if n else None)
    return ud


def kvartaler(bet, inv_aktier, fond_aktier, fond_nav, aar):
    """NAV pr. kvartalsultimo (kun hvis fonden har NAV præcis den dag) og nettobetalinger i
    kvartalet, som arket Kvartalsafkast: [{dato, nav_dkk, nav_valuta, netto_dkk, netto_valuta}].
    """
    datoer = kvartalsultimoer(aar)
    ud = []
    for forrige, d in zip([None, *datoer], datoer):
        n = nav_pr(d, inv_aktier, fond_aktier, fond_nav, praecis=True)
        i_kv = [b for b in bet if forrige is not None and forrige < b[0] <= d]
        ud.append(dict(dato=d, nav_dkk=n["nav_dkk"] if n else None,
                       nav_valuta=n["nav_valuta"] if n else None,
                       netto_dkk=sum(b[2] for b in i_kv), netto_valuta=sum(b[1] for b in i_kv)))
    return ud


def total(fonde, solgte=()):
    """Porteføljen i DKK: tilsagn og resttilsagn til dagskurs, betalinger til
    transaktionskurs (inkl. solgte positioner), markedsværdi til dagskurs."""
    s = lambda k: sum(f[k] or 0.0 for f in fonde)
    bet = [b[2] for f in [*fonde, *solgte] for b in f["betalinger"]]
    mv = s("markedsvaerdi_dkk")
    dato = max((f["nav_dato"] for f in fonde if f["nav_dato"]), default=None)
    t = dict(tilsagn_dkk=s("tilsagn_dkk"), resttilsagn_dkk=s("resttilsagn_dkk"),
             betalt_dkk=-sum(b for b in bet if b < 0), udloddet_dkk=sum(b for b in bet if b > 0),
             nav_dkk=s("nav_dkk"), markedsvaerdi_dkk=mv, seneste_nav_dato=dato)
    t["indbetalt_pct"] = deling(sum(f["indbetalt"] * f["spot"] for f in fonde), t["tilsagn_dkk"])
    t.update(multipler(t["betalt_dkk"], t["udloddet_dkk"], mv))
    return t


def portefoelje_irr(r):
    """IRR i DKK for hele porteføljen med markedsværdien pr. dato som slutværdi."""
    bet = [(b[0], b[2]) for f in [*r["fonde"], *r.get("solgte", [])] for b in f["betalinger"]]
    return xirr(bet + [(r["dato"], r["total"]["markedsvaerdi_dkk"])])
