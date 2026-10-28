"""Stier til de filer i repoet, som pakken læser og skriver."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "sql"                                          # SELECT-scripts, ét pr. datasæt
FORUDSAETNINGER = ROOT / "config" / "forudsaetninger.yaml"  # prognosens antagelser
MASTER = ROOT / "assets" / "ppim_slidemaster.pptx"          # PPIM-slidemasteren
WORKBOOK = ROOT / "assets" / "alternativer_prognosemodel.xlsm"  # det gamle Excel-ark (spec)
EXPORTS = ROOT / "exports"                                  # færdige rapporter (ikke i git)
