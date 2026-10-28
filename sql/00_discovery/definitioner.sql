-- Definitionerne af de gamle dbo-objekter, som Excel-modellen kalder.
-- Kun læsning: OBJECT_DEFINITION returnerer kildeteksten.
SELECT o.name AS objekt, o.type_desc AS type, OBJECT_DEFINITION(o.object_id) AS definition
FROM sys.objects o
WHERE o.schema_id = SCHEMA_ID('dbo')
  AND (o.name LIKE 'usp_pe_prognosis%' OR o.name LIKE 'usp_pe_period%'
       OR o.name LIKE 'vw_pe_investor_transaction_nav%' OR o.name LIKE 'pe_prognosis%')
ORDER BY o.name
