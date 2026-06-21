"""
models/user.py
--------------
User model — the top-level entity that owns broker accounts.
"""

from datetime import datetime, timezone
from extensions import db


class User(db.Model):
    """
    Represents a CRM user (trader / client).

    Relationships:
        broker_accounts: one-to-many → BrokerAccount
    """

    __tablename__ = "users"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(255), nullable=False)
    email: str = db.Column(db.String(255), nullable=False, unique=True, index=True)
    phone: str | None = db.Column(db.String(50), nullable=True)
    created_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    broker_accounts = db.relationship(
        "BrokerAccount",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    # ── Serialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_accounts: bool = False) -> dict:
        """Return a JSON-serialisable dict representation of this user."""
        data: dict = {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_accounts:
            data["broker_accounts"] = [
                acc.to_dict() for acc in self.broker_accounts
            ]
        return data

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
