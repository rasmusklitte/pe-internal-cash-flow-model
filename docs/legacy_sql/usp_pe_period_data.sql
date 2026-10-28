/*
    Stored procedure: combined per-investor, per-fund, per-year period table.
    One row per (NAVN, FOND, YEAR) with drawdowns, distributions and ultimo NAV.

    - Drawdowns     = sum of DRAWDOWN + CLOSING events in the year (amounts positive).
    - Distributions = sum of DISTRIBUTION events in the year (amounts positive).
    - NAV           = period-end ownership share * fund EGENKAPITAL (past years only).

    Current year is included as a YTD row (through @today); NAV columns are NULL there.
    Numerics formatted with "," as decimal separator for Excel paste.

    To (re)create via ssb (DDL — requires --allow-writes --commit):
        ssb run scripts/period-combined.sql --allow-writes --commit

    Usage:
        EXEC dbo.usp_InvestorPeriodSummary @NAVN = N'CR ApS';
*/

CREATE   PROCEDURE [dbo].[usp_pe_period_data]
    @NAVN NVARCHAR(100)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @today     DATE = CAST(GETDATE() AS DATE);
    DECLARE @this_year INT  = YEAR(@today);

    ;WITH InvestorFunds AS (
        SELECT FOND, YEAR(MIN(DATO)) AS first_year
        FROM tbl_pe_transactions
        WHERE NAVN = @NAVN
        GROUP BY FOND
    ),
    Years AS (
        SELECT @this_year AS y
        UNION ALL
        SELECT y - 1 FROM Years WHERE y - 1 >= 1990
    ),
    YearGrid AS (
        SELECT
            f.FOND,
            y.y AS YR,
            CASE WHEN y.y = @this_year
                 THEN @today
                 ELSE DATEFROMPARTS(y.y, 12, 31)
            END AS PERIOD_END
        FROM InvestorFunds f
        JOIN Years y ON y.y >= f.first_year AND y.y <= @this_year
    ),
    FlowAgg AS (
        SELECT
            g.FOND,
            g.YR,
            g.PERIOD_END,
            COALESCE(SUM(CASE WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING')
                              THEN ABS(ISNULL(t.BELOEB, 0)) ELSE 0 END), 0)     AS DRAWDOWN_NUM,
            COALESCE(SUM(CASE WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING')
                              THEN ABS(ISNULL(t.BETALT_DKK, 0)) ELSE 0 END), 0) AS DRAWDOWN_DKK_NUM,
            COALESCE(SUM(CASE WHEN t.EVENT = N'DISTRIBUTION'
                              THEN ABS(ISNULL(t.BELOEB, 0)) ELSE 0 END), 0)     AS DISTRIBUTION_NUM,
            COALESCE(SUM(CASE WHEN t.EVENT = N'DISTRIBUTION'
                              THEN ABS(ISNULL(t.BETALT_DKK, 0)) ELSE 0 END), 0) AS DISTRIBUTION_DKK_NUM
        FROM YearGrid g
        LEFT JOIN tbl_pe_transactions t
            ON t.FOND = g.FOND
           AND t.NAVN = @NAVN
           AND t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'DISTRIBUTION')
           AND YEAR(t.DATO) = g.YR
           AND t.DATO <= g.PERIOD_END
        GROUP BY g.FOND, g.YR, g.PERIOD_END
    ),
    NavYearEnds AS (
        SELECT FOND, YR, PERIOD_END AS YEAR_END
        FROM YearGrid
    ),
    InvCum AS (
        SELECT
            ye.FOND,
            ye.YR,
            ye.YEAR_END,
            COALESCE(SUM(
                CASE
                    WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB') THEN ISNULL(t.ANTAL_AKTIER, 0)
                    WHEN t.EVENT = N'SALG'                             THEN -ISNULL(t.ANTAL_AKTIER, 0)
                    ELSE 0
                END
            ), 0) AS SHARES_NAVN
        FROM NavYearEnds ye
        LEFT JOIN tbl_pe_transactions t
            ON t.FOND = ye.FOND
           AND t.NAVN = @NAVN
           AND t.DATO <= ye.YEAR_END
        GROUP BY ye.FOND, ye.YR, ye.YEAR_END
    ),
    FundCum AS (
        SELECT
            ye.FOND,
            ye.YR,
            ye.YEAR_END,
            COALESCE(SUM(
                CASE
                    WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB') THEN ISNULL(t.ANTAL_AKTIER, 0)
                    WHEN t.EVENT = N'SALG'                             THEN -ISNULL(t.ANTAL_AKTIER, 0)
                    ELSE 0
                END
            ), 0) AS SHARES_FOND
        FROM NavYearEnds ye
        LEFT JOIN tbl_pe_transactions t
            ON t.FOND = ye.FOND
           AND t.DATO <= ye.YEAR_END
        GROUP BY ye.FOND, ye.YR, ye.YEAR_END
    ),
    NavCalc AS (
        SELECT
            ye.FOND,
            ye.YR,
            nav.DATO AS NAV_DATO,
            nav.VALUTA AS NAV_VALUTA_CODE,
            TRY_CONVERT(DECIMAL(18,6),
                REPLACE(NULLIF(LTRIM(RTRIM(nav.VALUTA_KURS)), ''), ',', '.')
            ) AS VALUTA_KURS_NUM,
            CAST(ic.SHARES_NAVN AS DECIMAL(30,10))
                / NULLIF(fc.SHARES_FOND, 0) AS EJERANDEL_NUM,
            CAST(nav.EGENKAPITAL_VAERDI AS DECIMAL(30,6)) AS EGENKAPITAL_NUM,
            (CAST(ic.SHARES_NAVN AS DECIMAL(30,10))
                / NULLIF(fc.SHARES_FOND, 0))
                * nav.EGENKAPITAL_VAERDI AS NAV_DKK_NUM
        FROM NavYearEnds ye
        JOIN InvCum  ic ON ic.FOND = ye.FOND AND ic.YR = ye.YR
        JOIN FundCum fc ON fc.FOND = ye.FOND AND fc.YR = ye.YR
        OUTER APPLY (
            SELECT TOP 1
                n.DATO,
                n.VALUTA,
                n.VALUTA_KURS,
                n.EGENKAPITAL_VAERDI
            FROM tbl_pe_fund_nav n
            WHERE n.FOND = ye.FOND
              AND n.DATO <= ye.YEAR_END
            ORDER BY n.DATO DESC
        ) nav
        WHERE ic.SHARES_NAVN <> 0
    )
    SELECT
        @NAVN                                                                              AS NAVN,
        f.FOND,
        f.YR                                                                               AS [YEAR],
        f.PERIOD_END,
        COALESCE(n.NAV_VALUTA_CODE, cur.VALUTA)                                            AS VALUTA,
        CAST(f.DRAWDOWN_NUM         AS DECIMAL(30,2)) AS DRAWDOWN_VALUTA,
        CAST(f.DRAWDOWN_DKK_NUM     AS DECIMAL(30,2)) AS DRAWDOWN_DKK,
        CAST(f.DISTRIBUTION_NUM     AS DECIMAL(30,2)) AS DISTRIBUTION_VALUTA,
        CAST(f.DISTRIBUTION_DKK_NUM AS DECIMAL(30,2)) AS DISTRIBUTION_DKK,

        n.NAV_DATO,
        --CASE WHEN n.NAV_DATO IS NULL THEN NULL
        --     ELSE DATEDIFF(DAY, n.NAV_DATO, f.PERIOD_END)
        --END                                                                                AS NAV_ALDER_DAGE,
        CASE WHEN n.VALUTA_KURS_NUM IS NULL THEN NULL
             ELSE CAST(n.VALUTA_KURS_NUM AS DECIMAL(18,6))
        END                                                                                AS VALUTA_KURS,
        CASE WHEN n.EJERANDEL_NUM IS NULL THEN NULL
             ELSE CAST(n.EJERANDEL_NUM AS DECIMAL(18,10))
        END                                                                                AS EJERANDEL,
        CASE WHEN n.EGENKAPITAL_NUM IS NULL THEN NULL
             ELSE CAST(n.EGENKAPITAL_NUM AS DECIMAL(30,2))
        END                                                                                AS FOND_NAV,
        CASE WHEN n.NAV_DKK_NUM IS NULL THEN NULL
             ELSE CAST(n.NAV_DKK_NUM AS DECIMAL(30,2))
        END                                                                                AS NAV_DKK,
        CASE WHEN n.NAV_DKK_NUM IS NULL THEN NULL
             ELSE
                CAST(
                    CASE
                        WHEN n.NAV_VALUTA_CODE = N'DKK' THEN n.NAV_DKK_NUM
                        ELSE n.NAV_DKK_NUM / NULLIF(n.VALUTA_KURS_NUM, 0)
                    END AS DECIMAL(30,2)
                )
        END                                                                                AS NAV_VALUTA
    FROM FlowAgg f
    LEFT JOIN NavCalc n
        ON n.FOND = f.FOND AND n.YR = f.YR
    OUTER APPLY (
        SELECT TOP 1 nv.VALUTA
        FROM tbl_pe_fund_nav nv
        WHERE nv.FOND = f.FOND
          AND nv.DATO <= f.PERIOD_END
        ORDER BY nv.DATO DESC
    ) cur
    ORDER BY f.FOND, f.YR DESC
    OPTION (MAXRECURSION 200);
END

