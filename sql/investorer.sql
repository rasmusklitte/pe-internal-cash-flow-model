-- Investorer med mindst én transaktion i P&P-fondene.
-- tbl_pe_stamdata har en PASSWORD-kolonne - vælg aldrig med *.
SELECT DISTINCT CAST(s.ID AS int) AS id, s.NAVN AS navn
FROM dbo.tbl_pe_stamdata s
WHERE EXISTS (SELECT 1 FROM dbo.tbl_pe_transactions t WHERE t.NAVN = s.NAVN)
ORDER BY s.NAVN
