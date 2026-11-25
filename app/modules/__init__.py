"""Registry of the application's modules. Adding a module = adding its SPEC here."""
from app.modules.eba_ingest.module import SPEC as EBA_INGEST
from app.modules.eba_processing.module import SPEC as EBA_PROCESSING
from app.modules.eba_public_analysis.module import SPEC as EBA_PUBLIC_ANALYSIS
from app.modules.eba_ml.module import SPEC as EBA_ML
from app.modules.eba_rules.module import SPEC as EBA_RULES

MODULES = [EBA_INGEST, EBA_PROCESSING, EBA_PUBLIC_ANALYSIS, EBA_RULES, EBA_ML]
