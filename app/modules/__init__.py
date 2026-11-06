"""Registry of the application's modules. Adding a module = adding its SPEC here."""
from app.modules.eba_ingest.module import SPEC as EBA_INGEST
from app.modules.eba_processing.module import SPEC as EBA_PROCESSING

MODULES = [EBA_INGEST, EBA_PROCESSING]
