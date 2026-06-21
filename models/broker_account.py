"""
models/broker_account.py
------------------------
BrokerAccount model — represents a MetaTrader 5 trading account
belonging to a user.

Security note: mt5_password is stored encrypted via Fernet (see utils/crypto.py).
               Never store or log the plain-text password.
"""

import enum
from datetime import datetime, timezone
from extensions import db


class AccountType(str, enum.Enum):
    """MT5 account role within the trade-copier topology."""

    master = "master"
    slave = "slave"
    standalone = "standalone"


class BrokerAccount(db.Model):
    """
    A MetaTrader 5 broker account linked to a CRM user.

    Relationships:
        user:        many-to-one  → User
        trades:      one-to-many  → Trade
        commissions: one-to-many  → Commission
        master_links: one-to-many → CopierLink (as master)
        slave_links:  one-to-many → CopierLink (as slave)
    """

    __tablename__ = "broker_accounts"

    id: int = db.Column(db.Integer, primary_key=True)
    user_id: int = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mt5_login: int = db.Column(db.BigInteger, nullable=False)
    # Fernet-encrypted ciphertext of the plain-text MT5 password
    mt5_password: str = db.Column(db.Text, nullable=False)
    server: str = db.Column(db.String(255), nullable=False)
    account_type: AccountType = db.Column(
        db.Enum(AccountType), nullable=False, default=AccountType.standalone
    )
    is_active: bool = db.Column(db.Boolean, nullable=False, default=True)
    last_synced_at: datetime | None = db.Column(db.DateTime, nullable=True)
    created_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user = db.relationship("User", back_populates="broker_accounts")
    trades = db.relationship(
        "Trade",
        back_populates="broker_account",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    commissions = db.relationship(
        "Commission",
        back_populates="broker_account",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    master_links = db.relationship(
        "CopierLink",
        foreign_keys="CopierLink.master_account_id",
        back_populates="master_account",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    slave_links = db.relationship(
        "CopierLink",
        foreign_keys="CopierLink.slave_account_id",
        back_populates="slave_account",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    # ── Serialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict (password field is excluded)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "mt5_login": self.mt5_login,
            "server": self.server,
            "account_type": self.account_type.value if self.account_type else None,
            "is_active": self.is_active,
            "last_synced_at": (
                self.last_synced_at.isoformat() if self.last_synced_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<BrokerAccount id={self.id} login={self.mt5_login} "
            f"server={self.server!r} type={self.account_type}>"
        )
