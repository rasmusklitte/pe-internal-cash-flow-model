-- Fondens samlede NAV. EGENKAPITAL_VAERDI er i DKK; / VALUTA_KURS giver fondsvaluta
-- (se docs/legacy_sql/vw_pe_investor_transaction_nav_timeseries.sql).
SELECT n.FOND AS fond, n.DATO AS dato, n.VALUTA AS valuta, n.VALUTA_KURS AS kurs,
       n.EGENKAPITAL_VAERDI AS nav_dkk,
       n.EGENKAPITAL_VAERDI / NULLIF(n.VALUTA_KURS, 0) AS nav_valuta, n.ID AS id
FROM dbo.tbl_pe_fund_nav n
WHERE n.FOND IN (SELECT DISTINCT FOND FROM dbo.tbl_pe_transactions WHERE NAVN = :navn)
  AND n.EGENKAPITAL_VAERDI IS NOT NULL
ORDER BY n.FOND, n.DATO, n.ID
