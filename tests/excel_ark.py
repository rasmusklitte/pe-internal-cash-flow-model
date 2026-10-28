"""Læser de gemte værdier i det gamle Excel-ark (kun læsning, filen gemmes aldrig)."""
import datetime as dt
from functools import lru_cache

import openpyxl

from prognosemodel.paths import WORKBOOK

FONDSRAEKKER = range(11, 17)    # række 11-16: én fond pr. række i inputblokken
AAR_KOLONNER = "EFGHIJKLMNOPQRSTU"  # 2019..2035


@lru_cache(maxsize=1)
def celler():
    """{koordinat: værdi} for arket prognosemodel."""
    wb = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    try:
        ud = {}
        for raekke in wb["prognosemodel"].iter_rows(min_row=1, max_row=222, max_col=31):
            for c in raekke:
                if c.value is not None and hasattr(c, "coordinate"):
                    v = c.value
                    ud[c.coordinate] = v.date() if isinstance(v, dt.datetime) else v
        return ud
    finally:
        wb.close()


def aar():
    c = celler()
    return [c[f"{k}38"] for k in AAR_KOLONNER]


def fond(i):
    """Input og facit for fonden i række 11 + i (i = 0..5)."""
    c = celler()
    v = lambda kol, r: c.get(f"{kol}{r}")
    tal = lambda kol, r: v(kol, r) or 0.0
    aarene = aar()
    raekke = 11 + i
    return dict(
        navn=v("B", raekke), aktiv=bool(v("E", raekke)),
        tilsagn_dkk=tal("J", raekke), tilsagn_valuta=tal("G", raekke),
        vaekst=v("S", raekke), vintage=v("T", raekke),
        kald=[tal(k, 49 + i) for k in AAR_KOLONNER],
        udlodning=[tal(k, 59 + i) for k in AAR_KOLONNER],
        nav=[tal(k, 80 + i) for k in AAR_KOLONNER],
        kald_valuta=[tal(k, 185 + i) for k in AAR_KOLONNER],
        rc={a: tal(k, 21 + i) for a, k in zip(aarene, AAR_KOLONNER)},
        rd={a: tal(k, 30 + i) for a, k in zip(aarene, AAR_KOLONNER)},
        stadie=[v(k, 40 + i) or "" for k in AAR_KOLONNER],
        netto=[tal(k, 69 + i) for k in AAR_KOLONNER],
        kpi=dict(indbetalt=v("AA", raekke), udloddet=v("AB", raekke), tvpi=v("AC", raekke),
                 irr=v("AD", raekke), indbetalt_pct_valuta=v("AE", raekke)),
    )
