"""Worker composition root: registers the job handlers of every module and runs the loop."""

from __future__ import annotations

import argparse

from app.core.config import get_schema
from app.core.hooks import register_module_hooks
from app.core.worker import JobHandlerRegistry, Worker
from app.modules import MODULES
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


def build_registry() -> JobHandlerRegistry:
    registry = JobHandlerRegistry()
    register_module_hooks(MODULES)
    for module in MODULES:
        if module.register_handlers:
            module.register_handlers(registry)
    return registry


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="EBA Analyst worker")
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--stale-after", type=int, default=900, help="seconds without heartbeat after which a processing job is requeued")
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args(argv)

    configure_logging()
    logger.info("worker starting poll_interval=%s stale_after=%s", args.poll, args.stale_after)
    Worker(build_registry(), poll_interval=args.poll, stale_after=args.stale_after, max_attempts=args.max_attempts, schema=get_schema()).run()


if __name__ == "__main__":
    main()
