"""
models/commission.py
--------------------
Commission model and the bonus trade-copier models (CopierLink, CopierMapping).
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal
from extensions import db


class CommissionStatus(str, enum.Enum):
    """Payment status of a commission record."""

    pending = "pending"
    paid = "paid"


class Commission(db.Model):
    """
    Commission charged on a closed trade.

    The UNIQUE constraint on trade_id enforces idempotency:
    calculating the commission twice for the same trade raises an
    IntegrityError rather than creating a duplicate row.

    Relationships:
        trade:          one-to-one  → Trade
        broker_account: many-to-one → BrokerAccount
    """

    __tablename__ = "commissions"

    id: int = db.Column(db.Integer, primary_key=True)
    # UNIQUE: one commission per trade
    trade_id: int = db.Column(
        db.Integer,
        db.ForeignKey("trades.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    broker_account_id: int = db.Column(
        db.Integer,
        db.ForeignKey("broker_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    volume: Decimal = db.Column(db.Numeric(10, 2), nullable=False)
    rate_per_lot: Decimal = db.Column(
        db.Numeric(10, 2), nullable=False, default=Decimal("5.00")
    )
    amount: Decimal = db.Column(db.Numeric(18, 2), nullable=False)
    status: CommissionStatus = db.Column(
        db.Enum(CommissionStatus),
        nullable=False,
        default=CommissionStatus.pending,
    )
    created_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    trade = db.relationship("Trade", back_populates="commission")
    broker_account = db.relationship("BrokerAccount", back_populates="commissions")

    # ── Serialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation of this commission."""
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "broker_account_id": self.broker_account_id,
            "volume": str(self.volume),
            "rate_per_lot": str(self.rate_per_lot),
            "amount": str(self.amount),
            "status": self.status.value if self.status else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<Commission id={self.id} trade_id={self.trade_id} "
            f"amount={self.amount} status={self.status}>"
        )


# ── Bonus: Trade Copier Models ────────────────────────────────────────────────


class CopierLink(db.Model):
    """
    Defines a master → slave copy relationship between two broker accounts.

    All open positions on the master account will be mirrored on the slave
    account scaled by ``lot_multiplier``.

    Relationships:
        master_account: many-to-one → BrokerAccount
        slave_account:  many-to-one → BrokerAccount
        mappings:       one-to-many → CopierMapping
    """

    __tablename__ = "copier_links"

    id: int = db.Column(db.Integer, primary_key=True)
    master_account_id: int = db.Column(
        db.Integer,
        db.ForeignKey("broker_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slave_account_id: int = db.Column(
        db.Integer,
        db.ForeignKey("broker_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lot_multiplier: Decimal = db.Column(
        db.Numeric(10, 4), nullable=False, default=Decimal("1.0")
    )
    is_active: bool = db.Column(db.Boolean, nullable=False, default=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    master_account = db.relationship(
        "BrokerAccount",
        foreign_keys=[master_account_id],
        back_populates="master_links",
    )
    slave_account = db.relationship(
        "BrokerAccount",
        foreign_keys=[slave_account_id],
        back_populates="slave_links",
    )
    mappings = db.relationship(
        "CopierMapping",
        back_populates="copier_link",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict for this copier link."""
        return {
            "id": self.id,
            "master_account_id": self.master_account_id,
            "slave_account_id": self.slave_account_id,
            "lot_multiplier": str(self.lot_multiplier),
            "is_active": self.is_active,
        }

    def __repr__(self) -> str:
        return (
            f"<CopierLink id={self.id} master={self.master_account_id} "
            f"→ slave={self.slave_account_id} multiplier={self.lot_multiplier}>"
        )


class CopierMapping(db.Model):
    """
    Tracks which slave ticket was opened in response to a master ticket.

    Used to detect when a master position closes so the corresponding
    slave position can be closed too.

    Relationships:
        copier_link: many-to-one → CopierLink
        slave_account: many-to-one → BrokerAccount
    """

    __tablename__ = "copier_mappings"

    id: int = db.Column(db.Integer, primary_key=True)
    copier_link_id: int = db.Column(
        db.Integer,
        db.ForeignKey("copier_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    master_ticket: int = db.Column(db.BigInteger, nullable=False)
    slave_account_id: int = db.Column(
        db.Integer,
        db.ForeignKey("broker_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    slave_ticket: int = db.Column(db.BigInteger, nullable=False)
    is_closed: bool = db.Column(db.Boolean, nullable=False, default=False)
    created_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    copier_link = db.relationship("CopierLink", back_populates="mappings")
    slave_account = db.relationship("BrokerAccount", foreign_keys=[slave_account_id])

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict for this mapping."""
        return {
            "id": self.id,
            "copier_link_id": self.copier_link_id,
            "master_ticket": self.master_ticket,
            "slave_account_id": self.slave_account_id,
            "slave_ticket": self.slave_ticket,
            "is_closed": self.is_closed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<CopierMapping id={self.id} master_ticket={self.master_ticket} "
            f"slave_ticket={self.slave_ticket} closed={self.is_closed}>"
        )
