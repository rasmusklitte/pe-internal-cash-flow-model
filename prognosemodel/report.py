"""Bygger prognosedecket (og dataudtrækket) for én investor: data -> prognose -> slides."""
import re
from datetime import date

import pandas as pd
from pptx import Presentation

from . import beregning, data, forudsaetninger, slides
from .deck import L_FORSIDE, L_SKILLE, L_SLUT, _ny_slide, _ryd_slides, _saet_ph
from .paths import EXPORTS, MASTER

MAKS_VERSIONER = 20


def byg(investor, dato=None, motor=None, scenarie=None, out=None, med_data=True):
    """Hent data, kør prognosen og gem decket. Returnerer stien til decket."""
    dato = dato or date.today()
    cfg = forudsaetninger.indlaes()
    r = data.hent(investor, dato)
    p = beregning.prognose(r, cfg, motor=motor, scenarie=scenarie)
    prs = byg_deck(r, p, cfg)
    oenske = out or EXPORTS / f"{_filnavn(investor)}_prognose_{dato:%Y-%m-%d}.pptx"
    sti = _gem(prs, oenske)
    print(f"gemt: {sti}  ({len(r['fonde'])} fonde, {len(prs.slides._sldIdLst)} slides, "
          f"motor {p['motor']}, scenarie {p['scenarie']})")
    if med_data:
        xlsx = _gem_xlsx(r, p, sti.with_name(f"{sti.stem}_data.xlsx"))
        print(f"gemt: {xlsx}  (dataudtræk til afstemning)")
    return sti


def byg_deck(r, p, cfg):
    prs = Presentation(str(MASTER))
    _ryd_slides(prs)
    s = _ny_slide(prs, L_FORSIDE)
    _saet_ph(s, 0, f"{r['navn']} – alternative investeringer")
    _saet_ph(s, 1, f"Status og cash flow-prognose pr. {r['dato']:%d.%m.%Y}")
    slides.sammendrag(prs, r, p)
    slides.portefoelje(prs, r, p)
    slides.kvartalsafkast_slide(prs, r, p)

    s = _ny_slide(prs, L_SKILLE[0])
    _saet_ph(s, 0, "Prognose")
    slides.likviditetsprognose(prs, r, p)
    slides.nav_prognose(prs, r, p)
    slides.prognose_pr_fond(prs, r, p)

    s = _ny_slide(prs, L_SKILLE[2])
    _saet_ph(s, 0, "Bilag")
    slides.forudsaetninger(prs, r, p, cfg)
    slides.sammenligning(prs, r, p)
    slides.metode(prs, r, p)
    _ny_slide(prs, L_SLUT)
    slides.sidefod(prs, r["navn"])          # til sidst, så sidetallene er endelige
    return prs


def _filnavn(navn):
    return re.sub(r"[^\w]+", "_", navn, flags=re.UNICODE).strip("_")


def _gem(obj, outfile):
    """Gem (pptx eller xlsx) og returnér stien; er filen låst i Office, lægges _v2, _v3, ... på."""
    outfile.parent.mkdir(parents=True, exist_ok=True)
    for version in range(1, MAKS_VERSIONER + 1):
        sti = (outfile if version == 1
               else outfile.with_name(f"{outfile.stem}_v{version}{outfile.suffix}"))
        try:
            obj.save(str(sti)) if hasattr(obj, "save") else obj(sti)
            return sti
        except PermissionError:
            print(f"{sti.name} er låst (åben i Office?) - prøver næste versionsnummer")
    raise PermissionError(f"Kunne ikke gemme {outfile}")


def _gem_xlsx(r, p, outfile):
    """Alle tal bag decket i én projektmappe, så de kan afstemmes."""
    fonde = pd.DataFrame([{k: v for k, v in f.items()
                           if k not in ("betalinger", "aar", "kvartaler", "multipler_valuta",
                                        "multipler_dkk")} for f in r["fonde"]])
    betalinger = pd.DataFrame([dict(fond=f["fond"], dato=b[0], valuta=b[1], dkk=b[2], event=b[3])
                               for f in r["fonde"] for b in f["betalinger"]])
    kvartaler = pd.DataFrame([dict(fond=f["fond"], **k) for f in r["fonde"]
                              for k in f["kvartaler"]])
    prognose = pd.DataFrame([dict(fond=f, **a) for f, res in p["fonde"].items()
                             for a in res["linjer"]])
    excel = pd.DataFrame([dict(fond=f, **a) for f, res in p["excel"].items()
                          for a in res["linjer"]])
    total = pd.DataFrame(p["total"])
    fs = pd.DataFrame([dict(fond=f, **{k: str(v) for k, v in x.items()})
                       for f, x in p["forudsaetninger"].items()])

    def skriv(sti):
        with pd.ExcelWriter(sti) as xw:
            fonde.to_excel(xw, sheet_name="Fonde", index=False)
            total.to_excel(xw, sheet_name="Prognose total", index=False)
            prognose.to_excel(xw, sheet_name=f"Prognose pr fond ({p['motor']})", index=False)
            excel.to_excel(xw, sheet_name="Excel-metoden", index=False)
            kvartaler.to_excel(xw, sheet_name="Kvartaler", index=False)
            betalinger.to_excel(xw, sheet_name="Betalinger", index=False)
            fs.to_excel(xw, sheet_name="Forudsaetninger", index=False)
    return _gem(skriv, outfile)
