from app.core.module import ModuleSpec
from app.modules.eba_ml.presentation.api import TAG, build_router
from app.modules.eba_ml.application.worker_handlers import register_handlers
from app.modules.eba_ml.application.hooks import queue_score_jobs

SPEC = ModuleSpec(
    name="eba_ml",
    description="Deterministic machine-learning datasets, experiments, models and predictions.",
    router_factory=build_router,
    register_handlers=register_handlers,
    migrations_dir=None,
    after_panel_rebuild=queue_score_jobs,
    tags=[{"name": TAG, "description": "Machine-learning datasets, experiments, models and predictions."}],
)
