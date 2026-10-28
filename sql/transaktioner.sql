-- Investorens transaktioner i alle fonde.
--   beloeb      kontant betalt/modtaget i fondsvaluta (inkl. true-up-rente, efter rabat)
--   opkraevet   trukket af tilsagnet (TILSAGN_PROCENT x tilsagn) - bruges til indbetalingsprocent
--   betalt_dkk  kontant i DKK til transaktionsdagens kurs
--   VALUTA_KURS er nvarchar og kan have decimalkomma; '0' og tom behandles som NULL.
-- Fortegnet i databasen er positivt for alt undtagen SALG; Python sætter investorens fortegn.
SELECT t.TRANSAKTIONSID AS id, t.DATO AS dato, t.FOND AS fond, t.EVENT AS event,
       t.VALUTA AS valuta,
       NULLIF(TRY_CONVERT(decimal(18,6), REPLACE(NULLIF(LTRIM(RTRIM(t.VALUTA_KURS)), ''), ',', '.')), 0)
           AS kurs,
       t.TILSAGN_PROCENT AS tilsagn_pct, t.BELOEB AS beloeb, t.OPKRÆVET AS opkraevet,
       t.RABAT AS rabat, t.TRUE_UP_INTEREST AS true_up, t.TILSAGN_PR_DAGS_DATO AS tilsagn,
       t.BETALT_DKK AS betalt_dkk, t.ANTAL_AKTIER AS aktier
FROM dbo.tbl_pe_transactions t
WHERE t.NAVN = :navn
ORDER BY t.FOND, t.DATO, t.TRANSAKTIONSID
