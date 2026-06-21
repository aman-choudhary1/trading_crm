"""
routes/broker_routes.py
-----------------------
REST endpoints for broker account management and trade copier links.

Endpoints:
    POST /api/users/<id>/broker-accounts     — Add a broker account to a user
    GET  /api/users/<id>/broker-accounts     — List a user's broker accounts
    POST /api/copier-links                   — Create a master→slave copier link
    GET  /api/copier-links                   — List all copier links
"""

from flask import Blueprint, request

from extensions import db
from models.user import User
from models.broker_account import BrokerAccount, AccountType
from models.commission import CopierLink
from utils.crypto import encrypt_password
from utils.exceptions import NotFoundError, ValidationError, MT5ConnectionError
from utils.response import success_response
from utils.validators import (
    validate_required_fields,
    validate_positive_int,
    validate_account_type,
)
from utils.logger import get_logger

logger = get_logger(__name__)

broker_bp = Blueprint("broker", __name__)


@broker_bp.route("/users/<int:user_id>/broker-accounts", methods=["POST"])
def create_broker_account(user_id: int):
    """
    Add a new MetaTrader 5 broker account to a user.

    The plain-text MT5 password is encrypted with Fernet before being stored.
    Optionally validates the MT5 credentials by attempting a connection
    before saving — returns 502 if the connection fails.

    Path params:
        user_id (int)

    Request body (JSON):
        mt5_login    (int,    required) — MT5 account login number
        mt5_password (str,    required) — MT5 account password (stored encrypted)
        server       (str,    required) — MT5 broker server name
        account_type (str,    required) — 'master' | 'slave' | 'standalone'
        test_connect (bool,  optional, default false) — test MT5 connection first

    Returns:
        201 with the created broker account dict.
        404 if the user does not exist.
        422 on validation failure.
        502 if test_connect=true and MT5 login fails.
    """
    user = db.session.get(User, user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found.")

    data: dict = request.get_json(force=True, silent=True) or {}
    validate_required_fields(data, ["mt5_login", "mt5_password", "server", "account_type"])

    mt5_login = validate_positive_int(data["mt5_login"], "mt5_login")
    account_type_str = validate_account_type(data["account_type"])
    server = data["server"].strip()
    plain_password = str(data["mt5_password"])

    if not server:
        raise ValidationError("'server' must not be blank.")

    # Optional: test MT5 connection before saving
    if data.get("test_connect", False):
        _test_mt5_connection(mt5_login, plain_password, server)

    # Encrypt the password before persisting
    encrypted_password = encrypt_password(plain_password)

    account = BrokerAccount(
        user_id=user_id,
        mt5_login=mt5_login,
        mt5_password=encrypted_password,
        server=server,
        account_type=AccountType(account_type_str),
    )

    db.session.add(account)
    db.session.commit()
    logger.info(
        "Created broker account id=%d login=%d for user_id=%d",
        account.id,
        account.mt5_login,
        user_id,
    )
    return success_response(account.to_dict(), status=201)


@broker_bp.route("/users/<int:user_id>/broker-accounts", methods=["GET"])
def list_broker_accounts(user_id: int):
    """
    List all broker accounts belonging to a user.

    Path params:
        user_id (int)

    Returns:
        200 with list of broker account dicts.
        404 if user does not exist.
    """
    user = db.session.get(User, user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found.")

    accounts = BrokerAccount.query.filter_by(user_id=user_id).all()
    return success_response([acc.to_dict() for acc in accounts])


# ── Copier Link Routes ────────────────────────────────────────────────────────


@broker_bp.route("/copier-links", methods=["POST"])
def create_copier_link():
    """
    Create a master→slave trade copier link between two broker accounts.

    Request body (JSON):
        master_account_id (int,   required)
        slave_account_id  (int,   required)
        lot_multiplier    (float, optional, default 1.0)

    Returns:
        201 with the created CopierLink dict.
        404 if either account does not exist.
        422 on validation failure.
    """
    data: dict = request.get_json(force=True, silent=True) or {}
    validate_required_fields(data, ["master_account_id", "slave_account_id"])

    master_id = validate_positive_int(data["master_account_id"], "master_account_id")
    slave_id = validate_positive_int(data["slave_account_id"], "slave_account_id")

    master = db.session.get(BrokerAccount, master_id)
    if not master:
        raise NotFoundError(f"Master broker account {master_id} not found.")

    slave = db.session.get(BrokerAccount, slave_id)
    if not slave:
        raise NotFoundError(f"Slave broker account {slave_id} not found.")

    if master_id == slave_id:
        raise ValidationError("master_account_id and slave_account_id must be different.")

    try:
        lot_multiplier = float(data.get("lot_multiplier", 1.0))
        if lot_multiplier <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ValidationError("'lot_multiplier' must be a positive number.")

    link = CopierLink(
        master_account_id=master_id,
        slave_account_id=slave_id,
        lot_multiplier=lot_multiplier,
    )
    db.session.add(link)
    db.session.commit()
    logger.info("Created CopierLink id=%d master=%d → slave=%d", link.id, master_id, slave_id)
    return success_response(link.to_dict(), status=201)


@broker_bp.route("/copier-links", methods=["GET"])
def list_copier_links():
    """
    List all trade copier links.

    Returns:
        200 with list of CopierLink dicts.
    """
    links = CopierLink.query.all()
    return success_response([link.to_dict() for link in links])


# ── Internal helpers ──────────────────────────────────────────────────────────


def _test_mt5_connection(login: int, password: str, server: str) -> None:
    """
    Attempt a real MT5 login to validate credentials before saving.

    This is a best-effort check — the MT5 package is Windows-only, so
    on other platforms this silently skips the check with a warning.

    Args:
        login:    MT5 account number.
        password: Plain-text MT5 password.
        server:   MT5 broker server name.

    Raises:
        MT5ConnectionError: If the MT5 login attempt fails.
    """
    try:
        from services.mt5_service import mt5_session
        with mt5_session(login, password, server):
            pass  # Connection succeeded
        logger.info("MT5 test-connect succeeded for login=%d server=%s", login, server)
    except ImportError:
        logger.warning(
            "MetaTrader5 package not available on this platform — "
            "skipping connection test."
        )
    except MT5ConnectionError:
        raise  # Re-raise to return 502
    except Exception as exc:
        logger.error("Unexpected error during MT5 test-connect: %s", exc)
        raise MT5ConnectionError(f"MT5 connection test failed: {exc}") from exc
