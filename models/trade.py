"""
models/trade.py
---------------
Trade model — a single deal record synced from MetaTrader 5.

The UNIQUE constraint on (broker_account_id, mt5_ticket) guarantees that
the same MT5 deal cannot be inserted twice, even under concurrent sync jobs.
IntegrityError from this constraint is caught by the sync service and treated
as a harmless duplicate.
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal
from extensions import db


class TradeType(str, enum.Enum):
    """Direction of the trade."""

    buy = "buy"
    sell = "sell"


class TradeStatus(str, enum.Enum):
    """Whether the trade is still open or has been closed."""

    open = "open"
    closed = "closed"


class Trade(db.Model):
    """
    A single MT5 deal (deal record from history or open position).

    Relationships:
        broker_account: many-to-one → BrokerAccount
        commission:     one-to-one  → Commission
    """

    __tablename__ = "trades"
    __table_args__ = (
        db.UniqueConstraint(
            "broker_account_id",
            "mt5_ticket",
            name="uq_trade_account_ticket",
        ),
    )

    id: int = db.Column(db.Integer, primary_key=True)
    broker_account_id: int = db.Column(
        db.Integer,
        db.ForeignKey("broker_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mt5_ticket: int = db.Column(db.BigInteger, nullable=False)
    symbol: str = db.Column(db.String(50), nullable=False)
    volume: Decimal = db.Column(db.Numeric(10, 2), nullable=False)
    trade_type: TradeType = db.Column(db.Enum(TradeType), nullable=False)
    open_price: Decimal = db.Column(db.Numeric(18, 5), nullable=False)
    close_price: Decimal | None = db.Column(db.Numeric(18, 5), nullable=True)
    profit: Decimal = db.Column(db.Numeric(18, 2), nullable=False, default=Decimal("0"))
    open_time: datetime = db.Column(db.DateTime, nullable=False)
    close_time: datetime | None = db.Column(db.DateTime, nullable=True)
    status: TradeStatus = db.Column(
        db.Enum(TradeStatus), nullable=False, default=TradeStatus.open
    )
    synced_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    broker_account = db.relationship("BrokerAccount", back_populates="trades")
    commission = db.relationship(
        "Commission",
        back_populates="trade",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # ── Serialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation of this trade."""
        return {
            "id": self.id,
            "broker_account_id": self.broker_account_id,
            "mt5_ticket": self.mt5_ticket,
            "symbol": self.symbol,
            "volume": str(self.volume),
            "trade_type": self.trade_type.value if self.trade_type else None,
            "open_price": str(self.open_price),
            "close_price": str(self.close_price) if self.close_price else None,
            "profit": str(self.profit),
            "open_time": self.open_time.isoformat() if self.open_time else None,
            "close_time": self.close_time.isoformat() if self.close_time else None,
            "status": self.status.value if self.status else None,
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<Trade id={self.id} ticket={self.mt5_ticket} "
            f"symbol={self.symbol!r} status={self.status}>"
        )
