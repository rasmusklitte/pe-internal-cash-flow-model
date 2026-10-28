-- Stamdata for de seks feederfonde. VALUTA styrer valutakursen (EUR/USD).
SELECT FOND AS fond, VINTAGE AS vintage, VALUTA AS valuta, NAVN AS underliggende_fond,
       SELSKABSNAVN AS selskab, IDENTIFIER AS kode
FROM dbo.tbl_pe_stamdata_fund
ORDER BY FOND
