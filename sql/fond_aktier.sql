-- Ændring i fondens samlede antal aktier og indbetalte beløb pr. dag (alle investorer).
-- Ejerandel = investorens kumulerede aktier / fondens kumulerede aktier (som i de gamle
-- procedurer). FoF er et K/S uden aktier (ANTAL_AKTIER er NULL); dér bruges andelen af det
-- indbetalte (OPKRÆVET) i stedet - kald i FoF er pro rata efter tilsagn.
SELECT t.FOND AS fond, t.DATO AS dato,
       SUM(CASE WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB') THEN ABS(ISNULL(t.ANTAL_AKTIER, 0))
                WHEN t.EVENT = N'SALG' THEN -ABS(ISNULL(t.ANTAL_AKTIER, 0))
                ELSE 0 END) AS delta_aktier,
       SUM(CASE WHEN t.EVENT IN (N'DRAWDOWN', N'CLOSING', N'KØB') THEN ABS(ISNULL(t.OPKRÆVET, 0))
                WHEN t.EVENT = N'SALG' THEN -ABS(ISNULL(t.OPKRÆVET, 0))
                ELSE 0 END) AS delta_opkraevet
FROM dbo.tbl_pe_transactions t
WHERE t.FOND IN (SELECT DISTINCT FOND FROM dbo.tbl_pe_transactions WHERE NAVN = :navn)
GROUP BY t.FOND, t.DATO
ORDER BY t.FOND, t.DATO
