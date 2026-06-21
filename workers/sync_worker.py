"""
workers/sync_worker.py
-----------------------
The actual trade sync job function that runs inside the APScheduler interval job.

Kept separate from scheduler.py so it can be tested and imported independently
without pulling in APScheduler.
"""

from utils.logger import get_logger

logger = get_logger(__name__)


def run_sync_job(app) -> None:
    """
    Synchronise all active broker accounts with MT5.

    Runs inside a Flask app context so that SQLAlchemy session is available.
    Errors for individual accounts are logged and skipped — the job never
    crashes the entire scheduler run.

    Args:
        app: The Flask application instance.
    """
    from extensions import db
    from models.broker_account import BrokerAccount
    from services.trade_sync_service import sync
    from utils.exceptions import MT5ConnectionError

    with app.app_context():
        logger.info("Scheduled sync job starting...")

        active_accounts = BrokerAccount.query.filter_by(is_active=True).all()
        logger.info("Found %d active broker accounts to sync.", len(active_accounts))

        success_count = 0
        fail_count = 0

        for account in active_accounts:
            try:
                new_trades = sync(account.id)
                logger.info(
                    "Sync OK: account_id=%d login=%d — %d new trades.",
                    account.id,
                    account.mt5_login,
                    new_trades,
                )
                success_count += 1
            except MT5ConnectionError as exc:
                # Log MT5 errors and continue — don't crash the whole job
                logger.error(
                    "MT5ConnectionError for account_id=%d login=%d: %s",
                    account.id,
                    account.mt5_login,
                    exc,
                )
                fail_count += 1
            except Exception as exc:
                logger.error(
                    "Unexpected error syncing account_id=%d: %s",
                    account.id,
                    exc,
                    exc_info=True,
                )
                fail_count += 1

        logger.info(
            "Scheduled sync job complete — success: %d, failed: %d.",
            success_count,
            fail_count,
        )
