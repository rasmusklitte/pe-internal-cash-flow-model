-- Kolonnerne i de tabeller og views, modellen læser.
SELECT TABLE_NAME AS tabel, COLUMN_NAME AS kolonne, DATA_TYPE AS datatype, ORDINAL_POSITION AS nr
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'dbo'
  AND TABLE_NAME IN ('tbl_pe_transactions', 'tbl_pe_fund_nav', 'tbl_pe_stamdata_fund',
                     'tbl_pe_subscription', 'fx_rates_nationalbanken',
                     'vw_pe_investor_transaction_nav_timeseries', 'vw_pe_events')
ORDER BY TABLE_NAME, ORDINAL_POSITION
