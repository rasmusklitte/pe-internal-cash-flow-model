

--CLOSE fund_cursor;
--DEALLOCATE fund_cursor;
CREATE PROCEDURE [dbo].[usp_pe_prognosis_pr_investor_data]
    @Fund NVARCHAR(100),
    @fx   FLOAT,     -- FX-kurs som anvendes på @dato (hvis @dato ligger efter seneste NAV)
    @dato DATE,      -- ønsket værdi-dato (kan ligge efter seneste NAV)
    @NAVN NVARCHAR(100)
AS
BEGIN
    SET NOCOUNT ON;

    /* ---------- Clean up temp tables ---------- */
    DROP TABLE IF EXISTS #temp_basis, #temp_basis_v2, #temp_fund_data, #final_table, #NAV_results, #funds, #result;
    DROP TABLE IF EXISTS #irr_per_fund;


    /* Hent fonde kunden har investeringer i */
    SELECT DISTINCT FOND
    INTO #funds
    FROM tbl_pe_transactions
    WHERE NAVN = @NAVN;

    /* Resultattabel (udvidet med markedsværdi) */
    CREATE TABLE #result (
        DATO DATE,
        FOND NVARCHAR(50),
        NAVN NVARCHAR(50),

        VALUTA NVARCHAR(10),
        VALUTA_KURS DECIMAL(18,6),

        KUMULERET_AKTIER_PR_NAVN DECIMAL(18,6),
        KUMULERET_AKTIER_PR_FOND DECIMAL(18,6),

        EJERANDEL DECIMAL(18,6),

        -- NAV-basis (seneste NAV pr. dato)
        EGENKAPITAL DECIMAL(18,6),
        NAV_DKK DECIMAL(18,6),
        NAV_FREMMEDVALUTA DECIMAL(18,6),

        -- Markedsværdi (NAV-basis + post-NAV cash events på fondsniveau)
        EGENKAPITAL_MV_DKK DECIMAL(18,6),
        MARKEDSVÆRDI_DKK DECIMAL(18,6),
        MARKEDSVÆRDI_FREMMEDVALUTA DECIMAL(18,6)
    );

    DECLARE @FOND NVARCHAR(50);

    DECLARE fund_cursor CURSOR FOR
        SELECT FOND FROM #funds;

    OPEN fund_cursor;
    FETCH NEXT FROM fund_cursor INTO @FOND;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        /* -------------------- Byg #result pr. fond -------------------- */
        ;WITH DateSpine AS (
            SELECT DISTINCT DATO
            FROM tbl_pe_transactions
            WHERE FOND = @FOND
              AND DATO <= @dato
            UNION
            SELECT DISTINCT DATO
            FROM tbl_pe_fund_nav
            WHERE FOND = @FOND
              AND DATO <= @dato
            UNION
            SELECT @dato
        ),
        InvDelta AS (
            -- Kundens dags-delta i aktier
            SELECT
                DATO,
                SUM(
                    CASE
                        WHEN EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB') THEN ISNULL(ANTAL_AKTIER,0)
                        WHEN EVENT = N'SALG' THEN -ISNULL(ANTAL_AKTIER,0)
                        ELSE 0
                    END
                ) AS DeltaAktier
            FROM tbl_pe_transactions
            WHERE FOND = @FOND
              AND NAVN = @NAVN
              AND DATO <= @dato
            GROUP BY DATO
        ),
        FundDelta AS (
            -- Fondens dags-delta i aktier (alle investorer)
            SELECT
                DATO,
                SUM(
                    CASE
                        WHEN EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB') THEN ISNULL(ANTAL_AKTIER,0)
                        WHEN EVENT = N'SALG' THEN -ISNULL(ANTAL_AKTIER,0)
                        ELSE 0
                    END
                ) AS DeltaAktier
            FROM tbl_pe_transactions
            WHERE FOND = @FOND
              AND DATO <= @dato
            GROUP BY DATO
        ),

		FundCashImpact AS (
    SELECT
        DATO,
        -- DKK-impact
        SUM(
            CASE
                WHEN EVENT IN (N'CLOSING', N'DRAWDOWN') THEN  ABS(ISNULL(BETALT_DKK,0))
                WHEN EVENT =  N'DISTRIBUTION'          THEN -ABS(ISNULL(BETALT_DKK,0))
                ELSE 0
            END
        ) AS ImpactDKK

    FROM tbl_pe_transactions
    WHERE FOND = @FOND
      AND DATO <= @dato
      AND EVENT NOT IN (N'COMMITMENT', N'FORHØJELSE')
    GROUP BY DATO
),
FundImpactSpine AS (
    -- Cumulative impact på DateSpine (både DKK og fremmed)
    SELECT
        d.DATO,
        SUM(COALESCE(fci.ImpactDKK,0))      OVER (ORDER BY d.DATO ROWS UNBOUNDED PRECEDING) AS CumImpactDKK
    FROM DateSpine d
    LEFT JOIN FundCashImpact fci
        ON fci.DATO = d.DATO
),
FundCashImpactFremmed AS (
    SELECT
        DATO,

         SUM(
  CASE
    WHEN EVENT IN (N'CLOSING', N'DRAWDOWN') THEN
      ABS(ISNULL(BETALT_DKK,0)) /
      NULLIF(
        TRY_CONVERT(DECIMAL(18,6),
          REPLACE(NULLIF(LTRIM(RTRIM(VALUTA_KURS)), ''), ',', '.')
        ),
        CAST(0 AS DECIMAL(18,6))
      )
    WHEN EVENT = N'DISTRIBUTION' THEN
     -ABS(ISNULL(BETALT_DKK,0)) /
      NULLIF(
        TRY_CONVERT(DECIMAL(18,6),
          REPLACE(NULLIF(LTRIM(RTRIM(VALUTA_KURS)), ''), ',', '.')
        ),
        CAST(0 AS DECIMAL(18,6))
      )
    ELSE 0
  END
) AS ImpactFremmed
    FROM tbl_pe_transactions
    WHERE FOND = @FOND
      AND DATO <= @dato
      AND EVENT NOT IN (N'COMMITMENT', N'FORHØJELSE', 'KØB', 'SALG')
    GROUP BY DATO
),
FundImpactSpineFremmed AS (
    -- Cumulative impact på DateSpine (både DKK og fremmed)
    SELECT
        d.DATO,
        SUM(COALESCE(fci.ImpactFremmed,0))  OVER (ORDER BY d.DATO ROWS UNBOUNDED PRECEDING) AS CumImpactFremmed
    FROM DateSpine d

    LEFT JOIN FundCashImpactFremmed fci
        ON fci.DATO = d.DATO
),

        Shares AS (
            -- Running sums (dilution-fix)
            SELECT
                d.DATO,
                SUM(COALESCE(i.DeltaAktier,0)) OVER (ORDER BY d.DATO ROWS UNBOUNDED PRECEDING) AS KUMULERET_AKTIER_PR_NAVN,
                SUM(COALESCE(f.DeltaAktier,0)) OVER (ORDER BY d.DATO ROWS UNBOUNDED PRECEDING) AS KUMULERET_AKTIER_PR_FOND
            FROM DateSpine d
            LEFT JOIN InvDelta  i ON i.DATO = d.DATO
            LEFT JOIN FundDelta f ON f.DATO = d.DATO
        ),
        Base AS (
            SELECT
                d.DATO,
                @FOND AS FOND,
                @NAVN AS NAVN,

                s.KUMULERET_AKTIER_PR_NAVN,
                s.KUMULERET_AKTIER_PR_FOND,

                CASE
                    WHEN s.KUMULERET_AKTIER_PR_NAVN = 0 THEN NULL
                    ELSE s.KUMULERET_AKTIER_PR_NAVN / NULLIF(s.KUMULERET_AKTIER_PR_FOND, 0)
                END AS EJERANDEL_RAW,

                navBase.NAV_DATO_BASE,
                navBase.VALUTA,
                navBase.VALUTA_KURS,
                navBase.EGENKAPITAL_BASE_DKK
            FROM DateSpine d
            LEFT JOIN Shares s
                ON s.DATO = d.DATO
            OUTER APPLY (
                -- Seneste NAV på/inden datoen
                SELECT TOP (1)
                    n.DATO AS NAV_DATO_BASE,
                    n.VALUTA,
                    n.VALUTA_KURS,
                    n.EGENKAPITAL_VAERDI AS EGENKAPITAL_BASE_DKK
                FROM tbl_pe_fund_nav n
                WHERE n.FOND = @FOND
                  AND n.DATO <= d.DATO
                ORDER BY n.DATO DESC
            ) navBase
        )
        INSERT INTO #result
        SELECT
            b.DATO,
            b.FOND,
            b.NAVN,

            b.VALUTA,
            b.VALUTA_KURS,

            b.KUMULERET_AKTIER_PR_NAVN,
            b.KUMULERET_AKTIER_PR_FOND,

            COALESCE(b.EJERANDEL_RAW, lastOwner.LastEJERANDEL) AS EJERANDEL,

            -- NAV-basis
            b.EGENKAPITAL_BASE_DKK AS EGENKAPITAL,
            COALESCE(b.EJERANDEL_RAW, lastOwner.LastEJERANDEL) * b.EGENKAPITAL_BASE_DKK AS NAV_DKK,
            (COALESCE(b.EJERANDEL_RAW, lastOwner.LastEJERANDEL) * b.EGENKAPITAL_BASE_DKK)
                / NULLIF(CASE WHEN b.DATO = @dato THEN b.VALUTA_KURS ELSE @fx END, 0) AS NAV_FREMMEDVALUTA,

            -- Markedsværdi (NAV + fond cash impact siden NAV_DATO_BASE)
            (b.EGENKAPITAL_BASE_DKK
                + COALESCE(fis.CumImpactDKK,0)
                - COALESCE(fisBase.CumImpactDKK,0)
            ) AS EGENKAPITAL_MV_DKK,

            COALESCE(b.EJERANDEL_RAW, lastOwner.LastEJERANDEL)
                * (b.EGENKAPITAL_BASE_DKK
                    + COALESCE(fis.CumImpactDKK,0)
                    - COALESCE(fisBase.CumImpactDKK,0)
                  ) AS MARKEDSVÆRDI_DKK,

			 (COALESCE(b.EJERANDEL_RAW, lastOwner.LastEJERANDEL)
                * (b.EGENKAPITAL_BASE_DKK
                    
                  )
             ) /  NULLIF(CASE WHEN b.DATO = @dato THEN b.VALUTA_KURS ELSE @fx END, 0) + (COALESCE(b.EJERANDEL_RAW, lastOwner.LastEJERANDEL)*(COALESCE(fis2.CumImpactFremmed,0)
                   - COALESCE(fisBase2.CumImpactFremmed,0 )))   AS MARKEDSVÆRDI_FREMMEDVALUTA
        FROM Base b
        LEFT JOIN FundImpactSpine fis
            ON fis.DATO = b.DATO
        LEFT JOIN FundImpactSpine fisBase
            ON fisBase.DATO = b.NAV_DATO_BASE
		LEFT JOIN FundImpactSpineFremmed fis2
            ON fis2.DATO = b.DATO
        LEFT JOIN FundImpactSpineFremmed fisBase2
            ON fisBase2.DATO = b.NAV_DATO_BASE
        OUTER APPLY (
            -- Carry-forward ejerandel
            SELECT TOP (1) x.EJERANDEL_RAW AS LastEJERANDEL
            FROM Base x
            WHERE x.DATO < b.DATO AND x.EJERANDEL_RAW IS NOT NULL
            ORDER BY x.DATO DESC
        ) lastOwner
        ORDER BY b.DATO;

        /* -------------------- Cashflows + slutværdi (MARKETVALUE) -------------------- */
        DROP TABLE IF EXISTS #table_flows, #cashflow_table;

        SELECT
            t1.DATO, t1.ID, t1.NAVN, t1.FOND, t1.EVENT, t1.BELOEB,
            CASE t1.EVENT
                WHEN N'CLOSING'      THEN -ABS(t1.BELOEB)
                WHEN N'DRAWDOWN'     THEN -ABS(t1.BELOEB)
                WHEN N'SALG'         THEN  ABS(t1.BELOEB)
                WHEN N'KØB'          THEN -ABS(t1.BELOEB)
                WHEN N'DISTRIBUTION' THEN -ABS(t1.BELOEB)
                ELSE 0
            END AS BELØB,
            CASE t1.EVENT
                WHEN N'CLOSING'      THEN -ABS(t1.BETALT_DKK)
                WHEN N'DRAWDOWN'     THEN -ABS(t1.BETALT_DKK)
                WHEN N'SALG'         THEN  ABS(t1.BETALT_DKK)
                WHEN N'KØB'          THEN -ABS(t1.BETALT_DKK)
                WHEN N'DISTRIBUTION' THEN -ABS(t1.BETALT_DKK)
                ELSE 0
            END AS BETALT_DKK
        INTO #table_flows
        FROM tbl_pe_transactions t1
        WHERE t1.FOND = @FOND
          AND t1.NAVN = @NAVN
          AND t1.EVENT NOT IN (N'COMMITMENT', N'FORHØJELSE')
          AND t1.DATO <= @dato;

        SELECT DATO, BELØB AS CASHFLOW, BETALT_DKK, EVENT
        INTO #cashflow_table
        FROM #table_flows
        WHERE BELØB IS NOT NULL;

        -- Slutværdi: MARKETVALUE (kan ligge efter seneste NAV)
        INSERT INTO #cashflow_table (DATO, CASHFLOW, BETALT_DKK, EVENT)
        SELECT TOP 1
            r.DATO,
            r.MARKEDSVÆRDI_DKK / NULLIF(CASE WHEN r.DATO = @dato  THEN r.VALUTA_KURS ELSE @fx  END, 0),
            r.MARKEDSVÆRDI_DKK,
            N'MARKETVALUE'
        FROM #result r
        WHERE r.FOND = @FOND
          AND r.NAVN = @NAVN
          AND r.DATO <= @dato
          AND r.MARKEDSVÆRDI_DKK IS NOT NULL
        ORDER BY r.DATO DESC;

        /* Clean pr-iteration */
        DROP TABLE IF EXISTS #table_flows, #cashflow_table, #cf_work;

        FETCH NEXT FROM fund_cursor INTO @FOND;
    END

    CLOSE fund_cursor;
    DEALLOCATE fund_cursor;

    /* =========================================================
       Slut-udtræk (din blok) + tilføj markedsværdier
       ========================================================= */

    DECLARE @SENESTE_DATO DATE;
    SELECT @SENESTE_DATO = MAX(t1.DATO)
    FROM #result t1
    WHERE t1.DATO <= @dato
      AND t1.FOND = @Fund;

    -- Vis resultat (for den valgte fond på seneste dato <= @dato)
    SELECT
        t1.DATO,
		(SELECT TOP 1 DATO FROM tbl_pe_fund_nav WHERE DATO <= @SENESTE_DATO AND FOND = @Fund ORDER BY DATO DESC) AS NAV_DATO,
        t1.FOND,
        t1.NAVN,
        t1.VALUTA,
        COALESCE(t2.VALUTA_KURS, t1.VALUTA_KURS, @fx) AS VALUTA_KURS,
        t1.EJERANDEL,
        t1.EGENKAPITAL,
        t1.NAV_DKK,
        t1.NAV_FREMMEDVALUTA AS NAV_FREMMED,

        -- Markedsværdi (nye felter)
        t1.EGENKAPITAL_MV_DKK,
        t1.MARKEDSVÆRDI_DKK,
        t1.MARKEDSVÆRDI_FREMMEDVALUTA

--        t3.IRR,
--        t3.IRR_DKK
    INTO #NAV_results
    FROM #result t1
    LEFT JOIN tbl_pe_fund_nav t2
        ON t2.DATO = t1.DATO
       AND t2.FOND COLLATE SQL_Latin1_General_CP1_CI_AS = t1.FOND COLLATE SQL_Latin1_General_CP1_CI_AS
    WHERE t1.DATO = @SENESTE_DATO
      AND t1.FOND = @Fund
    ORDER BY t1.NAVN, t1.FOND, t1.DATO;

    /* Oprydning (bevar #NAV_results til output) */
    DROP TABLE IF EXISTS #funds, #result;

    /* =========================================================
       Din basis-blok (uændret) for @Fund
       ========================================================= */

    WITH CTE_NyesteTransaktion AS (
        SELECT
            ID,
            NAVN,
            DATO,
            FOND,
            TILSAGN_PR_DAGS_DATO,
            ROW_NUMBER() OVER (PARTITION BY ID ORDER BY DATO DESC) AS rn
        FROM tbl_pe_transactions
        WHERE FOND = @Fund
    )
    SELECT
        t1.ID,
        t1.NAVN,
        t1.FOND,
        t2.TILSAGN_PR_DAGS_DATO AS COMMITMENT,
        SUM(t1.OPKRÆVET) AS DRAWDOWN,
        SUM(CASE WHEN t1.EVENT IN ('SALG') THEN ISNULL(t1.BELOEB, 0) ELSE 0 END) AS SALG,
        SUM(t1.OPKRÆVET * t1.VALUTA_KURS) AS DRAWDOWN_DKK,
        ISNULL(SUM(CASE
            WHEN YEAR(t1.DATO) = YEAR(@dato)
             AND t1.DATO <= @dato
            THEN t1.BETALT_DKK
            ELSE 0
        END),0) AS LIKVIDITET_YTD,
        @fx AS FX
    INTO #temp_basis
    FROM tbl_pe_transactions t1
    LEFT JOIN CTE_NyesteTransaktion t2
        ON t1.ID = t2.ID
    WHERE t1.DATO <= @dato
      AND t1.FOND = @Fund
      AND t2.rn = 1
    GROUP BY t1.ID, t1.NAVN, t1.FOND, t2.TILSAGN_PR_DAGS_DATO;

    SELECT
        t1.*,
        t1.COMMITMENT - t1.DRAWDOWN AS RESTTILSAGN,
        t1.COMMITMENT * FX AS COMMITMENT_DKK,
        (t1.DRAWDOWN) / NULLIF(t1.COMMITMENT,0) AS DRAWDOWN_PCT,
        ROUND(t1.DRAWDOWN_DKK / NULLIF((t1.COMMITMENT * FX),0), 2) AS DRAWDOWN_PCT_DKK
    INTO #temp_basis_v2
    FROM #temp_basis t1
    WHERE t1.COMMITMENT > 0;


-- Udvidet beregning af likviditet og drawdown for hvert år 2025-2031
SELECT 
    t1.*, 
	ISNULL(t1.COMMITMENT_DKK,0) - ISNULL(t1.DRAWDOWN_DKK,0) AS RESTTILSAGN_DKK
    --t2.[2025], t2.[2026], t2.[2027], t2.[2028], t2.[2029], t2.[2030], t2.[2031],

INTO #final_table
FROM #temp_basis_v2 t1

WHERE FOND = @Fund
ORDER BY t1.ID;


SELECT t1.ID, t1.NAVN, t1.FOND, t2.NAV_DATO AS NAV_DATO,  ISNULL(t2.EGENKAPITAL,0) AS NAV_FOND_DKK, ISNULL(t2.EJERANDEL,0), MARKEDSVÆRDI_FREMMEDVALUTA,
	COMMITMENT, ISNULL(DRAWDOWN,0) , ISNULL(RESTTILSAGN,0), ISNULL(DRAWDOWN_PCT,0), ISNULL(NAV_FREMMED,0) AS NAV, t2.VALUTA,
	t2.VALUTA_KURS, MARKEDSVÆRDI_DKK AS MARKEDSVAERDI, COMMITMENT_DKK, ISNULL(DRAWDOWN_DKK,0), ISNULL(RESTTILSAGN_DKK,0), ISNULL(DRAWDOWN_PCT_DKK,0), ISNULL(NAV_DKK,0) 
FROM #final_table t1
LEFT JOIN #NAV_results t2 ON t1.FOND COLLATE SQL_Latin1_General_CP1_CI_AS = t2.FOND COLLATE SQL_Latin1_General_CP1_CI_AS
	AND t1.NAVN COLLATE SQL_Latin1_General_CP1_CI_AS = t2.NAVN COLLATE SQL_Latin1_General_CP1_CI_AS
WHERE t1.NAVN = @NAVN

-- Oprydning af midlertidige tabeller
DROP TABLE IF EXISTS #temp_basis, #temp_basis_v2, #temp_fund_data, #final_table, #NAV_results, #funds, #result;

-- Oprydning af midlertidige tabeller
DROP TABLE IF EXISTS #temp_basis, #temp_basis_v2, #temp_fund_data, #final_table, #NAV_results, #funds, #result, #cashflow_table, #table_flows, #flows, #table1, #table2;

END
