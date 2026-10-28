"""db.read_sql må kun lade rene SELECT/WITH-sætninger igennem (ingen database her)."""
import pytest

from prognosemodel import db


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "  select a FROM t WHERE b = :b",
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    "SELECT 'DELETE' AS tekst -- UPDATE i en kommentar",
    "SELECT 1 /* DROP TABLE t */",
    "SELECT 1;",
    "SELECT [Værdi_dkk], intoleranse FROM v",
])
def test_tillader_laesning(sql):
    db.tjek_kun_laesning(sql)


@pytest.mark.parametrize("sql", [
    "DELETE FROM t",
    "UPDATE t SET a = 1",
    "EXEC dbo.usp_pe_period_data 'x'",
    "SELECT 1; DROP TABLE t",
    "SELECT * INTO #kopi FROM t",
    "WITH x AS (SELECT 1 AS a) INSERT INTO t SELECT a FROM x",
    "SELECT * FROM OPENROWSET('x', 'y', 'z')",
    "-- kun en kommentar",
])
def test_afviser_skrivning(sql):
    with pytest.raises(ValueError):
        db.tjek_kun_laesning(sql)


def test_procedurer_kun_fra_listen():
    with pytest.raises(ValueError):
        db.koer_procedure("usp_pe_slet_alt", NAVN="x")
    with pytest.raises(ValueError):
        db.koer_procedure("usp_pe_period_data", NAVN="x", ukendt=1)


def test_sql_filerne_er_kun_laesning():
    from prognosemodel.paths import SQL
    filer = list(SQL.rglob("*.sql"))
    assert filer
    for f in filer:
        db.tjek_kun_laesning(f.read_text(encoding="utf-8"))
