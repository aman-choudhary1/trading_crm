"""
workers/scheduler.py
---------------------
APScheduler configuration and startup for the Mini Trading CRM.

The scheduler runs a trade sync job every SYNC_INTERVAL_SECONDS (default 60).

IMPORTANT — Double-start prevention:
Flask's debug reloader forks two processes: a monitor and a worker child.
APScheduler must only start in the worker child (where WERKZEUG_RUN_MAIN='true')
to avoid running duplicate jobs. This guard is applied in app.py's
``_start_background_tasks()`` before calling start_scheduler().
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from utils.logger import get_logger

logger = get_logger(__name__)

# Module-level scheduler instance (one per process)
_scheduler: BackgroundScheduler | None = None


def start_scheduler(app) -> BackgroundScheduler:
    """
    Initialise and start the APScheduler BackgroundScheduler.

    Registers:
        - A trade sync interval job (every SYNC_INTERVAL_SECONDS seconds).

    The scheduler is started only once; calling this again when already
    running is a no-op with a warning.

    Args:
        app: The Flask application instance (passed to the sync job for context).

    Returns:
        The running BackgroundScheduler instance.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler is already running — skipping duplicate start.")
        return _scheduler

    interval_seconds = app.config.get("SYNC_INTERVAL_SECONDS", 60)

    _scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,       # Skip missed executions when catching up
            "max_instances": 1,     # Never run the same job concurrently
            "misfire_grace_time": 30,
        },
        timezone="UTC",
    )

    # ── Trade sync job ────────────────────────────────────────────────────────
    from workers.sync_worker import run_sync_job

    _scheduler.add_job(
        func=run_sync_job,
        args=[app],
        trigger=IntervalTrigger(seconds=interval_seconds),
        id="trade_sync_job",
        name="Trade Sync (all active accounts)",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "APScheduler started — trade sync job every %ds.", interval_seconds
    )
    return _scheduler


def stop_scheduler() -> None:
    """
    Gracefully shut down the scheduler.

    Safe to call even if the scheduler was never started.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
    _scheduler = None


def get_scheduler() -> BackgroundScheduler | None:
    """Return the current scheduler instance (or None if not started)."""
    return _scheduler
