from app.core.module import ModuleSpec
from app.modules.eba_rules.application.handler import register_handlers
from app.modules.eba_rules.application.hooks import evaluate_active_profile
from app.modules.eba_rules.presentation.router import build_router

SPEC = ModuleSpec(
    name="eba_rules",
    description="Alert profiles (frozen EU/EBA v1.1, BNM), R0/R1 benchmark rules, alert evaluation and the alert API.",
    router_factory=build_router,
    register_handlers=register_handlers,
    migrations_dir=None,
    after_panel_rebuild=evaluate_active_profile,
    tags=[],   # alert routes keep the published `public-analysis` tag (see presentation/router.py)
)
