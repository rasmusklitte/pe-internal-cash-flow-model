r"""Læseadgang til PE-databasen.

Standard er sql1\ppim / PE med Windows-godkendelse. Kan overstyres med miljøvariablerne
PE_DB_SERVER, PE_DB_DATABASE og PE_DB_DRIVER.

Projektet skriver ALDRIG til databasen. read_sql afviser alt andet end én SELECT/WITH-
sætning, forbindelsen åbnes med ApplicationIntent=ReadOnly, og transaktionen rulles altid
tilbage.
"""
import os
import re
from functools import lru_cache

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.engine import URL

from .paths import SQL

SERVER   = os.environ.get("PE_DB_SERVER", r"sql1\ppim")
DATABASE = os.environ.get("PE_DB_DATABASE", "PE")
DRIVER   = os.environ.get("PE_DB_DRIVER", "ODBC Driver 18 for SQL Server")

# ord der kan ændre data eller skema; matches som hele ord uden for kommentarer og strenge
_FORBUDT = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|EXEC|EXECUTE|INTO|GRANT|"
    r"REVOKE|DENY|BACKUP|RESTORE|DBCC|SP_\w+|XP_\w+|OPENROWSET|OPENQUERY)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def engine():
    # Driver 18 krypterer som standard, og det fejler mod en on-prem-server med
    # selvsigneret certifikat - derfor Encrypt=no.
    odbc = (f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={DATABASE};"
            "Trusted_Connection=yes;Encrypt=no;TrustServerCertificate=yes;"
            "ApplicationIntent=ReadOnly;")
    # pool_pre_ping: en forbindelse, netværket har lukket, erstattes i stedet for at fejle
    return sa.create_engine(URL.create("mssql+pyodbc", query={"odbc_connect": odbc}),
                            pool_pre_ping=True)


def _uden_kommentarer_og_strenge(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"N?'(?:[^']|'')*'", "''", sql)


def tjek_kun_laesning(sql):
    """Rejs ValueError, hvis sql ikke er én ren SELECT/WITH-sætning."""
    ren = _uden_kommentarer_og_strenge(sql).strip().rstrip(";").strip()
    if not ren or ren.split(None, 1)[0].upper() not in ("SELECT", "WITH"):
        raise ValueError("prognosemodel læser kun fra databasen - kun SELECT/WITH er tilladt")
    if ";" in ren:
        raise ValueError("Kun én sætning pr. kald - semikolon er ikke tilladt")
    if m := _FORBUDT.search(ren):
        raise ValueError(f"Forbudt nøgleord i SQL: {m.group(0)}")


def read_sql(sql, **params):
    """Kør en SELECT og returnér en DataFrame. Parametre bindes som :navn."""
    tjek_kun_laesning(sql)
    with engine().connect() as conn:
        try:
            return pd.read_sql(sa.text(sql), conn, params=params)
        finally:
            conn.rollback()


def sql_fil(fil, /, **params):
    """Kør sql/<fil>.sql med :parametre."""
    return read_sql((SQL / f"{fil}.sql").read_text(encoding="utf-8"), **params)


# De gamle procedurer, som scripts/afstem.py sammenligner med. De er gennemlæst
# (docs/legacy_sql/) og skriver kun til #midlertidige tabeller.
AFSTEMNINGSPROCEDURER = {
    "usp_pe_period_data": ("NAVN",),
    "usp_pe_prognosis_cashflows": ("NAVN", "FOND", "roll_forward", "today"),
}


def koer_procedure(navn, **params):
    """Kør en af AFSTEMNINGSPROCEDURER (kun til afstemning) og returnér første resultatsæt."""
    if navn not in AFSTEMNINGSPROCEDURER:
        raise ValueError(f"{navn} er ikke godkendt til afstemning")
    ukendte = set(params) - set(AFSTEMNINGSPROCEDURER[navn])
    if ukendte:
        raise ValueError(f"ukendte parametre: {', '.join(sorted(ukendte))}")
    args = ", ".join(f"@{k} = :{k}" for k in params)
    with engine().connect() as conn:
        try:
            return pd.read_sql(sa.text(f"EXEC dbo.{navn} {args}"), conn, params=params)
        finally:
            conn.rollback()
