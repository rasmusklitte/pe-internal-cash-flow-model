/*
    Stored procedure: pengestrømme (cash flows) til XIRR, pr. fond, for én investor.

    Fortegn set fra investors side:
        DRAWDOWN / CLOSING  ->  negativ (penge ud)
        DISTRIBUTION        ->  positiv (penge ind)
        Slut-NAV            ->  positiv (urealiseret værdi)

    To serier pr. fond:
        CUR = 'DKK'  bruger BETALT_DKK  -> afkast inkl. valutaeffekt
        CUR = 'VAL'  bruger BELOEB      -> afkast i fondens valuta

    Tal returneres som tekst med "," som decimalseparator (Excel-paste).
    Indsæt én (FOND, CUR)-blok i Excel og kør =XIRR(AMOUNT, CF_DATO).

    Parametre:
        @NAVN          investor, påkrævet
        @FOND          NULL = alle fonde for investoren
        @roll_forward  1 = værdiansæt pr. @today; NAV tages på sin egen
                           (ældre) dato og rulles frem til kostpris med
                           betalinger siden da
                       0 = mål pr. fondens seneste NAV-dato og se bort
                           fra alle betalinger efter den
        @today         NULL = dags dato; kan sættes for at genskabe en
                           tidligere kørsel

    Brug:
        EXEC dbo.usp_pe_cashflows @NAVN = N'Fonden Den Hageske Stiftelse';
        EXEC dbo.usp_pe_cashflows @NAVN = N'Fonden Den Hageske Stiftelse',
                                  @FOND = N'Private Equity I';
        EXEC dbo.usp_pe_cashflows @NAVN = N'Fonden Den Hageske Stiftelse',
                                  @roll_forward = 0;
*/
CREATE   PROCEDURE [dbo].[usp_pe_prognosis_cashflows]
    @NAVN         NVARCHAR(100),
    @FOND         NVARCHAR(200) = NULL,
    @roll_forward BIT           = 1,
    @today        DATE          = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @today IS NULL
        SET @today = CAST(GETDATE() AS DATE);

    /* --------------------------------------------------------
       1. Seneste NAV pr. fond + ejerandel på samme NAV-dato.
       -------------------------------------------------------- */
    CREATE TABLE #nav (
        FOND        NVARCHAR(200) COLLATE Danish_Norwegian_CI_AS,
        NAV_DATO    DATE,
        VALUTA      NVARCHAR(10)  COLLATE Danish_Norwegian_CI_AS,
        VALUTA_KURS DECIMAL(18,6),
        EJERANDEL   DECIMAL(30,10),
        FOND_NAV    DECIMAL(30,6),
        NAV_DKK     DECIMAL(30,2),
        NAV_VAL     DECIMAL(30,2),
        CUTOFF      DATE
    );

    ;WITH Funds AS (
        SELECT DISTINCT FOND
        FROM tbl_pe_transactions
        WHERE NAVN = @NAVN
          AND (@FOND IS NULL OR FOND = @FOND)
    ),
    Raw AS (
        SELECT
            f.FOND,
            nav.DATO                                      AS NAV_DATO,
            nav.VALUTA,
            TRY_CONVERT(DECIMAL(18,6),
                REPLACE(NULLIF(LTRIM(RTRIM(nav.VALUTA_KURS)), ''), ',', '.')
            )                                             AS VALUTA_KURS,
            CAST(sh.SHARES_NAVN AS DECIMAL(30,10))
                / NULLIF(sh.SHARES_FOND, 0)               AS EJERANDEL,
            CAST(nav.EGENKAPITAL_VAERDI AS DECIMAL(30,6)) AS FOND_NAV
        FROM Funds f
        OUTER APPLY (
            SELECT TOP 1 n.DATO, n.VALUTA, n.VALUTA_KURS, n.EGENKAPITAL_VAERDI
            FROM tbl_pe_fund_nav n
            WHERE n.FOND = f.FOND
              AND n.DATO <= @today
            ORDER BY n.DATO DESC
        ) nav
        OUTER APPLY (
            SELECT
                SUM(CASE WHEN t.NAVN = @NAVN THEN
                        CASE WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB')
                             THEN ISNULL(t.ANTAL_AKTIER, 0)
                             WHEN t.EVENT = N'SALG'
                             THEN -ISNULL(t.ANTAL_AKTIER, 0)
                             ELSE 0 END
                     ELSE 0 END)                          AS SHARES_NAVN,
                SUM(CASE WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB')
                         THEN ISNULL(t.ANTAL_AKTIER, 0)
                         WHEN t.EVENT = N'SALG'
                         THEN -ISNULL(t.ANTAL_AKTIER, 0)
                         ELSE 0 END)                      AS SHARES_FOND
            FROM tbl_pe_transactions t
            WHERE t.FOND = f.FOND
              AND t.DATO <= nav.DATO
        ) sh
    )
    INSERT #nav (FOND, NAV_DATO, VALUTA, VALUTA_KURS, EJERANDEL,
                 FOND_NAV, NAV_DKK, NAV_VAL, CUTOFF)
    SELECT
        r.FOND,
        r.NAV_DATO,
        r.VALUTA,
        r.VALUTA_KURS,
        r.EJERANDEL,
        r.FOND_NAV,
        CAST(r.EJERANDEL * r.FOND_NAV AS DECIMAL(30,2)),
        CAST(CASE WHEN r.VALUTA = N'DKK' THEN r.EJERANDEL * r.FOND_NAV
                  ELSE (r.EJERANDEL * r.FOND_NAV) / NULLIF(r.VALUTA_KURS, 0)
             END AS DECIMAL(30,2)),
        CASE WHEN @roll_forward = 1 THEN @today
             ELSE COALESCE(r.NAV_DATO, @today) END
    FROM Raw r;

    /* --------------------------------------------------------
       2. Pengestrømme.
       -------------------------------------------------------- */
    CREATE TABLE #cf (
        FOND    NVARCHAR(200) COLLATE Danish_Norwegian_CI_AS,
        CUR     CHAR(3),
        CF_DATO DATE,
        AMOUNT  FLOAT,
        KILDE   NVARCHAR(20)  COLLATE Danish_Norwegian_CI_AS
    );

    /* Realiserede betalinger */
    INSERT #cf (FOND, CUR, CF_DATO, AMOUNT, KILDE)
    SELECT t.FOND, 'DKK', t.DATO,
           CASE WHEN t.EVENT = N'DISTRIBUTION'
                THEN  ABS(ISNULL(t.BETALT_DKK, 0))
                ELSE -ABS(ISNULL(t.BETALT_DKK, 0)) END,
           t.EVENT
    FROM tbl_pe_transactions t
    JOIN #nav n ON n.FOND = t.FOND
    WHERE t.NAVN = @NAVN
      AND t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'DISTRIBUTION')
      AND t.DATO <= n.CUTOFF
    UNION ALL
    SELECT t.FOND, 'VAL', t.DATO,
           CASE WHEN t.EVENT = N'DISTRIBUTION'
                THEN  ABS(ISNULL(t.BELOEB, 0))
                ELSE -ABS(ISNULL(t.BELOEB, 0)) END,
           t.EVENT
    FROM tbl_pe_transactions t
    JOIN #nav n ON n.FOND = t.FOND
    WHERE t.NAVN = @NAVN
      AND t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'DISTRIBUTION')
      AND t.DATO <= n.CUTOFF;

    /* Slutværdi: NAV på sin egen dato, plus nettoindskud siden da
       (til kostpris), bogført på cutoff-datoen. */
    INSERT #cf (FOND, CUR, CF_DATO, AMOUNT, KILDE)
    SELECT n.FOND, 'DKK', n.CUTOFF, n.NAV_DKK + ISNULL(p.NET_DKK, 0), N'NAV'
    FROM #nav n
    OUTER APPLY (
        SELECT SUM(CASE WHEN t.EVENT = N'DISTRIBUTION'
                        THEN -ABS(ISNULL(t.BETALT_DKK, 0))
                        ELSE  ABS(ISNULL(t.BETALT_DKK, 0)) END) AS NET_DKK
        FROM tbl_pe_transactions t
        WHERE t.NAVN = @NAVN AND t.FOND = n.FOND
          AND t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'DISTRIBUTION')
          AND t.DATO > n.NAV_DATO AND t.DATO <= n.CUTOFF
    ) p
    WHERE n.NAV_DKK IS NOT NULL
    UNION ALL
    SELECT n.FOND, 'VAL', n.CUTOFF, n.NAV_VAL + ISNULL(p.NET_VAL, 0), N'NAV'
    FROM #nav n
    OUTER APPLY (
        SELECT SUM(CASE WHEN t.EVENT = N'DISTRIBUTION'
                        THEN -ABS(ISNULL(t.BELOEB, 0))
                        ELSE  ABS(ISNULL(t.BELOEB, 0)) END) AS NET_VAL
        FROM tbl_pe_transactions t
        WHERE t.NAVN = @NAVN AND t.FOND = n.FOND
          AND t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'DISTRIBUTION')
          AND t.DATO > n.NAV_DATO AND t.DATO <= n.CUTOFF
    ) p
    WHERE n.NAV_VAL IS NOT NULL;

    DELETE FROM #cf WHERE AMOUNT = 0 AND KILDE <> N'NAV';

    /* --------------------------------------------------------
       3. Output. Tal som tekst med "," som decimal.
       -------------------------------------------------------- */
    SELECT
        @NAVN                              AS NAVN,
        c.FOND,
        c.CUR,
        c.CF_DATO,
        REPLACE(CONVERT(NVARCHAR(40),
            CAST(c.AMOUNT AS DECIMAL(30,2))), '.', ',')      AS AMOUNT,
        c.KILDE,
        n.VALUTA,
        n.NAV_DATO,
        n.CUTOFF
    FROM #cf c
    JOIN #nav n ON n.FOND = c.FOND
    ORDER BY c.FOND, c.CUR, c.CF_DATO, c.KILDE;
END
