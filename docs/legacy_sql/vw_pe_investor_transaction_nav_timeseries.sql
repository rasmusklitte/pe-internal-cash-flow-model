






CREATE   VIEW [dbo].[vw_pe_investor_transaction_nav_timeseries]
AS
WITH
-- 1) Daglige ændringer i investor-andele (delta shares)
investor_daily_changes AS (
    SELECT
        t.DATO,
        t.NAVN,
        t.FOND,

        SUM(CASE
              WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB') THEN  ABS(ISNULL(t.ANTAL_AKTIER, 0))
              WHEN t.EVENT =  N'SALG'                           THEN -ABS(ISNULL(t.ANTAL_AKTIER, 0))
              ELSE 0
        END) AS delta_investor,

        -- 2) Gældende tilsagn-niveau på dagen (uanset event)
        -- Hvis der er flere rækker samme dag, tager vi den største udfyldte værdi.
        -- (Hvis du har et transaktions-id/timestamp, kan vi vælge "sidste" i stedet.)
        MAX(TRY_CAST(t.TILSAGN_PR_DAGS_DATO AS decimal(18,2))) AS tilsagn_niveau_dag
    FROM dbo.tbl_pe_transactions AS t
    GROUP BY t.DATO, t.NAVN, t.FOND
),

-- 3) Daglige ændringer i fondens samlede andele (delta shares fund)
fund_daily_changes AS (
    SELECT
        t.DATO,
        t.FOND,
        SUM(CASE
              WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB') THEN  ABS(ISNULL(t.ANTAL_AKTIER, 0))
              WHEN t.EVENT =  N'SALG'                           THEN -ABS(ISNULL(t.ANTAL_AKTIER, 0))
              ELSE 0
        END) AS delta_fund
    FROM dbo.tbl_pe_transactions AS t
    GROUP BY t.DATO, t.FOND
),

-- 4) Alle datoer pr fond (transaktioner + NAV)
fund_all_dates AS (
    SELECT DISTINCT fdc.FOND, fdc.DATO FROM fund_daily_changes fdc
    UNION
    SELECT DISTINCT nav.FOND, nav.DATO FROM dbo.tbl_pe_fund_nav nav
),

-- 5) Investor/fond-par (kun dem der faktisk findes i transaktioner)
investor_fund_pairs AS (
    SELECT DISTINCT t.NAVN, t.FOND
    FROM dbo.tbl_pe_transactions t
),

-- 6) Fuldt grid: alle datoer i fonden x alle investorer i fonden
date_grid AS (
    SELECT d.DATO, p.NAVN, d.FOND
    FROM fund_all_dates d
    JOIN investor_fund_pairs p
      ON p.FOND = d.FOND
),

-- 7) Cumulative positions + “last observation carried forward” for tilsagn-niveau
cumulative_positions AS (
    SELECT
        g.DATO,
        g.NAVN,
        g.FOND,

        ISNULL(idc.delta_investor, 0) AS daily_shares_change_investor,
        ISNULL(fdc.delta_fund, 0)     AS daily_shares_change_fund,

        -- niveau registreret på selve dagen (kan være NULL)
        idc.tilsagn_niveau_dag        AS tilsagn_niveau_paa_dagen,

        -- gældende tilsagn pr. dato = seneste kendte niveau <= dato (carry forward)
        ISNULL(tlast.tilsagn, 0)      AS total_tilsagn_investor,

        SUM(ISNULL(idc.delta_investor, 0))
            OVER (PARTITION BY g.NAVN, g.FOND ORDER BY g.DATO ROWS UNBOUNDED PRECEDING) AS total_shares_investor,

        SUM(ISNULL(fdc.delta_fund, 0))
            OVER (PARTITION BY g.NAVN, g.FOND ORDER BY g.DATO ROWS UNBOUNDED PRECEDING) AS total_shares_fund

    FROM date_grid g
    LEFT JOIN investor_daily_changes idc
      ON idc.DATO = g.DATO
     AND idc.NAVN = g.NAVN
     AND idc.FOND = g.FOND
    LEFT JOIN fund_daily_changes fdc
      ON fdc.DATO = g.DATO
     AND fdc.FOND = g.FOND

    OUTER APPLY (
        SELECT TOP (1)
            idc2.tilsagn_niveau_dag AS tilsagn
        FROM investor_daily_changes idc2
        WHERE idc2.NAVN = g.NAVN
          AND idc2.FOND = g.FOND
          AND idc2.DATO <= g.DATO
          AND idc2.tilsagn_niveau_dag IS NOT NULL
        ORDER BY idc2.DATO DESC
    ) tlast
),

-- Step 5: Add NAV data with forward filling
    positions_with_nav AS (
        SELECT 
            cp.DATO,
            cp.NAVN,
            cp.FOND,
            cp.total_shares_investor,
            cp.total_shares_fund,
			cp.total_tilsagn_investor,
            
            -- Calculate ownership percentage
            CASE 
                WHEN cp.total_shares_fund > 0 
                THEN cp.total_shares_investor / CAST(cp.total_shares_fund AS DECIMAL(18,8))
                ELSE 0 
            END AS ownership_percentage,
            
            -- Get NAV data (current or most recent at or before date)
            COALESCE(
                nav.EGENKAPITAL_VAERDI,
                (SELECT TOP 1 nav_prev.EGENKAPITAL_VAERDI 
                 FROM dbo.tbl_pe_fund_nav nav_prev 
                 WHERE nav_prev.FOND = cp.FOND 
                   AND nav_prev.DATO <= cp.DATO 
                   AND nav_prev.EGENKAPITAL_VAERDI IS NOT NULL 
                 ORDER BY nav_prev.DATO DESC, nav_prev.ID DESC)
            ) AS fund_nav_dkk,
            
            COALESCE(
                nav.EGENKAPITAL_VAERDI / NULLIF(nav.VALUTA_KURS, 0),
                (SELECT TOP 1 nav_prev.EGENKAPITAL_VAERDI / NULLIF(nav_prev.VALUTA_KURS, 0)
                 FROM dbo.tbl_pe_fund_nav nav_prev 
                 WHERE nav_prev.FOND = cp.FOND 
                   AND nav_prev.DATO <= cp.DATO 
                   AND nav_prev.EGENKAPITAL_VAERDI IS NOT NULL 
                 ORDER BY nav_prev.DATO DESC, nav_prev.ID DESC)
            ) AS fund_nav_foreign_currency,
            
            -- Currency information
            COALESCE(
                nav.VALUTA,
                (SELECT TOP 1 nav_prev.VALUTA 
                 FROM dbo.tbl_pe_fund_nav nav_prev 
                 WHERE nav_prev.FOND = cp.FOND 
                   AND nav_prev.DATO <= cp.DATO 
                   AND nav_prev.EGENKAPITAL_VAERDI IS NOT NULL 
                 ORDER BY nav_prev.DATO DESC, nav_prev.ID DESC)
            ) AS currency,
            
            COALESCE(
                nav.VALUTA_KURS,
                (SELECT TOP 1 nav_prev.VALUTA_KURS 
                 FROM dbo.tbl_pe_fund_nav nav_prev 
                 WHERE nav_prev.FOND = cp.FOND 
                   AND nav_prev.DATO <= cp.DATO 
                   AND nav_prev.EGENKAPITAL_VAERDI IS NOT NULL 
                 ORDER BY nav_prev.DATO DESC, nav_prev.ID DESC)
            ) AS exchange_rate,
            
            -- Mark NAV update dates
            CASE WHEN nav.DATO IS NOT NULL THEN N'NAV' ELSE NULL END AS nav_event
            
        FROM cumulative_positions cp
        LEFT JOIN dbo.tbl_pe_fund_nav nav
          ON cp.DATO = nav.DATO 
         AND nav.FOND = cp.FOND
		-- GROUP BY cp.DATO, cp.FOND, cp.NAVN
),
transaction_summary AS (
    SELECT 
        t.TRANSAKTIONSID,
        t.NAVN,
        t.DATO,
        t.FOND,
        (t.TILSAGN_PROCENT * t.TILSAGN_PR_DAGS_DATO)
          - ISNULL(LAG(t.RABAT, 1) OVER (PARTITION BY t.NAVN, t.FOND ORDER BY t.DATO), 0) AS amount,
        ISNULL(LAG(t.RABAT, 1) OVER (PARTITION BY t.NAVN, t.FOND ORDER BY t.DATO), 0)     AS previous_discount,
        (t.TILSAGN_PROCENT * t.TILSAGN_PR_DAGS_DATO * t.VALUTA_KURS)                      AS drawdown_dkk,
        t.BELOEB                                                                          AS transaction_amount,
		t.BETALT_DKK																	  AS transaction_amount_dkk,
        CASE WHEN t.EVENT IN (N'CLOSING', N'DRAWDOWN', N'KØB') THEN t.OPKRÆVET END        AS drawdown_amount,
        CASE WHEN t.EVENT IN (N'DISTRIBUTION', N'SALG') THEN t.OPKRÆVET END               AS distribution_amount,
        t.VALUTA_KURS                                                                     AS transaction_exchange_rate,
        t.VALUTA                                                                          AS transaction_currency,
        t.EVENT                                                                           AS EVENT,
        t.DEPOSIT_NOTICE_NR
    FROM dbo.tbl_pe_transactions AS t
),
final_table AS (
    SELECT DISTINCT
        pn.DATO                              AS transaction_date,
        pn.NAVN                              AS investor_name,
        pn.FOND                              AS fund_name,
        COALESCE(ts.EVENT, pn.nav_event)     AS event_type,
        ts.DEPOSIT_NOTICE_NR                 AS deposit_notice_number,
        pn.currency,
        ts.transaction_exchange_rate,
        pn.exchange_rate                     AS nav_exchange_rate,
        ts.transaction_amount,
		ts.transaction_amount_dkk,
        ts.drawdown_amount,
        ts.drawdown_dkk,
        ts.amount,
        ts.distribution_amount,
        pn.total_shares_investor             AS cumulative_shares_investor,
        pn.total_shares_fund                 AS cumulative_shares_fund,
		pn.total_tilsagn_investor			 AS cumulative_tilsagn_investor, 
        pn.ownership_percentage,
        pn.fund_nav_dkk                      AS total_fund_nav_dkk,
        pn.fund_nav_foreign_currency         AS total_fund_nav_foreign,
        (pn.ownership_percentage * pn.fund_nav_dkk)              AS investor_nav_dkk,
        (pn.ownership_percentage * pn.fund_nav_foreign_currency) AS investor_nav_foreign,
        CASE WHEN ts.EVENT IN (N'DRAWDOWN', N'CLOSING')
             THEN (pn.ownership_percentage * pn.fund_nav_dkk) + ts.drawdown_dkk
             ELSE (pn.ownership_percentage * pn.fund_nav_dkk)
        END AS investor_nav_dkk_with_drawdown,
        CASE WHEN ts.EVENT IN (N'DRAWDOWN', N'CLOSING')
             THEN (pn.ownership_percentage * pn.fund_nav_foreign_currency) + ts.drawdown_amount
             ELSE (pn.ownership_percentage * pn.fund_nav_foreign_currency)
        END AS investor_nav_foreign_with_drawdown,
        CASE 
            WHEN COALESCE(ts.EVENT, pn.nav_event) IN (N'COMMITMENT', N'FORHØJELSE') THEN NULL
            ELSE ts.transaction_amount
        END AS Cashflow,CASE 
            WHEN COALESCE(ts.EVENT, pn.nav_event) IN (N'COMMITMENT', N'FORHØJELSE') THEN NULL
            ELSE ts.transaction_amount_dkk
        END AS Cashflow_dkk
    FROM positions_with_nav pn
    LEFT JOIN transaction_summary ts
      ON ts.DATO = pn.DATO AND ts.NAVN = pn.NAVN AND ts.FOND = pn.FOND
)
SELECT
    investor_name    AS Investor,
    fund_name        AS Fond,
    event_type       AS [Event],
    transaction_date AS Dato,
	cumulative_shares_investor AS [Antal aktier (investor)],
	cumulative_shares_fund AS [Antal aktier (Fond)],
	cumulative_tilsagn_investor AS [Tilsagn pr. dags dato (investor)],
	ownership_percentage AS Ejerandel,
	total_fund_nav_dkk AS [Total Fond NAV DKK],
	total_fund_nav_foreign AS [Total Fond NAV],
    CASE WHEN event_type = N'NAV' THEN investor_nav_foreign ELSE transaction_amount END AS [Værdi],
	 CASE WHEN event_type = N'NAV' THEN investor_nav_dkk_with_drawdown ELSE transaction_amount_dkk END AS [Værdi_dkk],
    investor_nav_foreign_with_drawdown                                                  AS [NAV],
	investor_nav_dkk AS [NAV DKK],
    Cashflow,
	Cashflow_dkk,
    drawdown_amount                                                                     AS [Drawdown],
    distribution_amount                                                                 AS [Distribution],
    CASE WHEN event_type = N'COMMITMENT' THEN 0 ELSE
         SUM(ISNULL(Cashflow, 0)) OVER (PARTITION BY investor_name, fund_name ORDER BY transaction_date
                                        ROWS UNBOUNDED PRECEDING) END                   AS [Cashflow akkumuleret],
    CASE WHEN event_type = N'COMMITMENT' THEN 0 ELSE
         SUM(ISNULL(drawdown_amount, 0)) OVER (PARTITION BY investor_name, fund_name ORDER BY transaction_date
                                               ROWS UNBOUNDED PRECEDING) END            AS [Drawdown akkumuleret],
    ABS(SUM(ISNULL(distribution_amount, 0)) OVER (PARTITION BY investor_name, fund_name ORDER BY transaction_date
                                                  ROWS UNBOUNDED PRECEDING))            AS [Distribution akkumuleret],
    nav_exchange_rate                                                                    AS [NAV Valutakurs],
    transaction_exchange_rate                                                            AS [Cashflow Valutakurs],
    ISNULL(
      ( investor_nav_foreign_with_drawdown
        + ABS(SUM(ISNULL(distribution_amount, 0)) OVER (PARTITION BY investor_name, fund_name ORDER BY transaction_date
                                                        ROWS UNBOUNDED PRECEDING))
      )
      / NULLIF(
          SUM(ISNULL(CASE WHEN Cashflow > 0 THEN Cashflow ELSE 0 END, 0))
            OVER (PARTITION BY investor_name, fund_name ORDER BY transaction_date ROWS UNBOUNDED PRECEDING)
        , 0)
      , 0)                                                                               AS TVPI,
	  ISNULL(
      ( investor_nav_foreign_with_drawdown
              )
      / NULLIF(
          SUM(ISNULL(CASE WHEN Cashflow > 0 THEN Cashflow ELSE 0 END, 0))
            OVER (PARTITION BY investor_name, fund_name ORDER BY transaction_date ROWS UNBOUNDED PRECEDING)
        , 0)
      , 0)                                                                               AS RVPI,
	  ISNULL(
      ( ABS(SUM(ISNULL(distribution_amount, 0)) OVER (PARTITION BY investor_name, fund_name ORDER BY transaction_date
                                                        ROWS UNBOUNDED PRECEDING))
      )
      / NULLIF(
          SUM(ISNULL(CASE WHEN Cashflow > 0 THEN Cashflow ELSE 0 END, 0))
            OVER (PARTITION BY investor_name, fund_name ORDER BY transaction_date ROWS UNBOUNDED PRECEDING)
        , 0)
      , 0)                                                                               AS DPI
	  FROM final_table
