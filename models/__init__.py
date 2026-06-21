"""
models/__init__.py
------------------
Imports all model classes so that Flask-Migrate / SQLAlchemy can discover
them when building migration scripts.
"""

from .user import User
from .broker_account import BrokerAccount
from .trade import Trade
from .commission import Commission, CopierLink, CopierMapping

__all__ = [
    "User",
    "BrokerAccount",
    "Trade",
    "Commission",
    "CopierLink",
    "CopierMapping",
]
