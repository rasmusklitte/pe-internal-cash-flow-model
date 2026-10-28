-- Nationalbankens kurser (DKK pr. 1 enhed) for de valutaer, fondene bruger.
SELECT rate_date AS dato, currency AS valuta, CAST(dkk_per_1 AS float) AS kurs
FROM dbo.fx_rates_nationalbanken
WHERE currency IN ('EUR', 'USD') AND rate_date <= :til
ORDER BY currency, rate_date
