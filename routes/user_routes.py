"""
routes/user_routes.py
---------------------
REST endpoints for managing CRM users.

Endpoints:
    POST   /api/users          — Create a new user
    GET    /api/users          — Paginated user list
    GET    /api/users/<id>     — User detail with nested broker accounts
"""

from flask import Blueprint, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.user import User
from utils.exceptions import NotFoundError, ValidationError
from utils.response import success_response, paginated_response
from utils.validators import validate_required_fields, validate_email

users_bp = Blueprint("users", __name__)


@users_bp.route("/users", methods=["POST"])
def create_user():
    """
    Create a new CRM user.

    Request body (JSON):
        name  (str, required)
        email (str, required, must be unique)
        phone (str, optional)

    Returns:
        201 with the created user dict on success.
        422 on validation failure.
        409 on duplicate email.
    """
    data: dict = request.get_json(force=True, silent=True) or {}

    validate_required_fields(data, ["name", "email"])
    email = validate_email(data["email"])

    user = User(
        name=data["name"].strip(),
        email=email,
        phone=data.get("phone", "").strip() or None,
    )

    try:
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValidationError(f"Email address '{email}' is already registered.")

    return success_response(user.to_dict(), status=201)


@users_bp.route("/users", methods=["GET"])
def list_users():
    """
    Return a paginated list of all users.

    Query params:
        page     (int, default 1)
        per_page (int, default 20, max 100)

    Returns:
        200 with paginated items and pagination metadata.
    """
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", 20, type=int)))

    pagination = User.query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return paginated_response(
        items=[u.to_dict() for u in pagination.items],
        page=page,
        per_page=per_page,
        total=pagination.total,
    )


@users_bp.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id: int):
    """
    Return detailed information about a single user, including their
    broker accounts.

    Path params:
        user_id (int)

    Returns:
        200 with user dict (broker_accounts included).
        404 if the user does not exist.
    """
    user = db.session.get(User, user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found.")

    return success_response(user.to_dict(include_accounts=True))
