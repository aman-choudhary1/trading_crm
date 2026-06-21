# Mini Trading CRM Backend

A full-featured Flask-based CRM backend for trading operations. Integrates with MetaTrader 5, provides REST APIs with a consistent JSON envelope, real-time WebSocket feeds, automated trade synchronisation, commission calculation, and a master-slave trade copier.

---

## ⚠️ Platform Constraint — MetaTrader 5 (Windows Only)

> **The `MetaTrader5` Python package is Windows-only.**

The MT5 package communicates with a locally installed MetaTrader 5 terminal via shared memory / named pipes. It will **not** work on Linux or macOS natively.

**Options for non-Windows environments:**
- Run the app inside a Windows VM or Docker container with Wine.
- All MT5 calls are gracefully skipped if the package is unavailable (the server starts, but sync/copier endpoints return errors).
- All unit tests mock MT5 calls — no real MT5 terminal is needed to run tests.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web Framework | Flask 3.0 + Blueprints |
| ORM | Flask-SQLAlchemy 3.1 + Flask-Migrate |
| Database (Dev/Prod) | MySQL 8+ via PyMySQL |
| Database (Tests) | SQLite in-memory |
| WebSockets | Flask-SocketIO 5.3 (eventlet) |
| MT5 Integration | MetaTrader5 package (Windows only) |
| Background Jobs | APScheduler 3.10 |
| Encryption | cryptography (Fernet) |
| Config | python-dotenv |
| Tests | pytest + unittest.mock |

---

## Project Structure

```
trading_crm/
├── app.py                   # Application factory (create_app)
├── config.py                # Dev/Prod/Test configuration classes
├── extensions.py            # SQLAlchemy, Migrate, SocketIO instances
├── requirements.txt
├── .env.example
├── run.py                   # Entry point — socketio.run(app)
├── models/
│   ├── user.py              # User model
│   ├── broker_account.py    # BrokerAccount model (encrypted MT5 password)
│   ├── trade.py             # Trade model (unique constraint on account+ticket)
│   └── commission.py        # Commission, CopierLink, CopierMapping models
├── routes/
│   ├── user_routes.py       # POST/GET /api/users
│   ├── broker_routes.py     # Broker accounts + copier links
│   ├── trade_routes.py      # Sync trigger + filtered trade list
│   └── commission_routes.py # Commission calc + summary endpoints
├── services/
│   ├── mt5_service.py       # MT5 session, history, positions (Windows only)
│   ├── trade_sync_service.py# Fetch + deduplicate + insert MT5 deals
│   ├── commission_service.py# Idempotent commission calculation
│   └── trade_copier_service.py # Master-slave position mirroring
├── workers/
│   ├── scheduler.py         # APScheduler setup
│   └── sync_worker.py       # Scheduled sync job function
├── live_data/
│   └── market_feed.py       # WebSocket market tick background task
├── sockets/
│   ├── market_events.py     # subscribe/unsubscribe_symbol handlers
│   └── commission_events.py # emit_commission_created helper
├── utils/
│   ├── exceptions.py        # AppError hierarchy (400/404/409/422/502)
│   ├── error_handlers.py    # Flask errorhandler registration
│   ├── response.py          # success_response / error_response helpers
│   ├── validators.py        # Input validation helpers
│   ├── crypto.py            # Fernet encrypt/decrypt for MT5 passwords
│   └── logger.py            # Rotating file + console logging
└── tests/
    ├── test_users.py
    ├── test_broker_accounts.py
    ├── test_trade_sync.py
    └── test_commission.py
```

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd trading_crm
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

> **Note:** `MetaTrader5` in `requirements.txt` will fail to install on non-Windows systems. Remove or comment it out if you are on Linux/macOS and only want to run tests.

### 2. Configure environment

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # Linux/macOS
```

Edit `.env` and fill in all required values:

```env
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
SQLALCHEMY_DATABASE_URI=mysql+pymysql://root:yourpassword@localhost:3306/trading_crm
API_KEY=<your-api-key>
FERNET_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
COMMISSION_RATE_PER_LOT=5.00
SYNC_INTERVAL_SECONDS=60
```

### 3. Create the MySQL database

```sql
CREATE DATABASE trading_crm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 4. Run database migrations

```bash
# Initialise Alembic (only needed once per project)
flask db init

# Generate migration script from models
flask db migrate -m "initial schema"

# Apply migrations to the database
flask db upgrade
```

> Set `FLASK_APP=app:create_app` and `FLASK_ENV=development` in your `.env` or shell before running flask commands.

### 5. Start the server

```bash
python run.py
```

The server starts on `http://0.0.0.0:5000` (configurable via `FLASK_HOST` / `FLASK_PORT` env vars).

---

## Running Tests

Tests use SQLite in-memory — no MySQL database or MT5 terminal required.

```bash
pytest tests/ -v --tb=short
```

Run a specific test file:

```bash
pytest tests/test_users.py -v
pytest tests/test_commission.py -v
```

---

## API Reference

All endpoints require the `X-API-Key` header.

> **Security Note:** The current API key auth is a simple shared-secret suitable for development and internal tooling. Replace with proper **JWT / OAuth2** authentication before deploying to production.

All responses follow the envelope:

```json
{
  "success": true | false,
  "data": { ... } | null,
  "error": null | "error message"
}
```

---

### Users

#### `POST /api/users` — Create user

```bash
curl -X POST http://localhost:5000/api/users \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice Smith", "email": "alice@example.com", "phone": "+1234567890"}'
```

**Response 201:**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "name": "Alice Smith",
    "email": "alice@example.com",
    "phone": "+1234567890",
    "created_at": "2024-01-15T10:00:00"
  },
  "error": null
}
```

---

#### `GET /api/users` — List users (paginated)

```bash
curl "http://localhost:5000/api/users?page=1&per_page=20" \
  -H "X-API-Key: your-api-key"
```

---

#### `GET /api/users/<id>` — User detail with broker accounts

```bash
curl http://localhost:5000/api/users/1 \
  -H "X-API-Key: your-api-key"
```

---

### Broker Accounts

#### `POST /api/users/<id>/broker-accounts` — Add broker account

The MT5 password is encrypted with Fernet before being stored. The plain-text password is never returned in API responses.

```bash
curl -X POST http://localhost:5000/api/users/1/broker-accounts \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "mt5_login": 12345678,
    "mt5_password": "your_mt5_password",
    "server": "MetaQuotes-Demo",
    "account_type": "standalone",
    "test_connect": false
  }'
```

Set `"test_connect": true` to validate MT5 credentials before saving (returns 502 if login fails — Windows only).

**account_type** values: `"master"` | `"slave"` | `"standalone"`

---

#### `GET /api/users/<id>/broker-accounts` — List accounts

```bash
curl http://localhost:5000/api/users/1/broker-accounts \
  -H "X-API-Key: your-api-key"
```

---

### Trades

#### `POST /api/broker-accounts/<id>/sync-trades` — Trigger MT5 sync

Fetches new deals from MT5 since the account's last sync, inserts new trades, and auto-calculates commissions for closed trades.

```bash
curl -X POST http://localhost:5000/api/broker-accounts/1/sync-trades \
  -H "X-API-Key: your-api-key"
```

**Response:**
```json
{"success": true, "data": {"new_trades_count": 5}, "error": null}
```

---

#### `GET /api/broker-accounts/<id>/trades` — List trades (filtered)

```bash
# All trades
curl "http://localhost:5000/api/broker-accounts/1/trades" \
  -H "X-API-Key: your-api-key"

# Closed trades only
curl "http://localhost:5000/api/broker-accounts/1/trades?status=closed" \
  -H "X-API-Key: your-api-key"

# Filtered by date range
curl "http://localhost:5000/api/broker-accounts/1/trades?from=2024-01-01T00:00:00&to=2024-12-31T23:59:59" \
  -H "X-API-Key: your-api-key"

# Paginated
curl "http://localhost:5000/api/broker-accounts/1/trades?page=2&per_page=50" \
  -H "X-API-Key: your-api-key"
```

---

### Commissions

#### `POST /api/trades/<id>/calculate-commission` — Calculate commission (idempotent)

Returns the existing commission if already calculated, otherwise creates a new one.
Also emits a `commission_created` WebSocket event.

```bash
curl -X POST http://localhost:5000/api/trades/1/calculate-commission \
  -H "X-API-Key: your-api-key"
```

---

#### `GET /api/broker-accounts/<id>/commissions` — List commissions with totals

```bash
curl "http://localhost:5000/api/broker-accounts/1/commissions?page=1&per_page=20" \
  -H "X-API-Key: your-api-key"
```

**Response includes summary totals:**
```json
{
  "success": true,
  "data": {
    "commissions": [...],
    "pagination": {"page": 1, "per_page": 20, "total": 42, "pages": 3},
    "summary": {
      "pending_total": "150.00",
      "paid_total": "350.00",
      "grand_total": "500.00"
    }
  }
}
```

---

#### `GET /api/commissions/summary` — Aggregate summary

```bash
# All accounts
curl "http://localhost:5000/api/commissions/summary" \
  -H "X-API-Key: your-api-key"

# Single account
curl "http://localhost:5000/api/commissions/summary?broker_account_id=1" \
  -H "X-API-Key: your-api-key"
```

---

### Trade Copier (Bonus)

#### `POST /api/copier-links` — Create master→slave link

```bash
curl -X POST http://localhost:5000/api/copier-links \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "master_account_id": 1,
    "slave_account_id": 2,
    "lot_multiplier": 0.5
  }'
```

#### `GET /api/copier-links` — List all copier links

```bash
curl http://localhost:5000/api/copier-links \
  -H "X-API-Key: your-api-key"
```

---

## WebSocket Events

Connect to the WebSocket server at `ws://localhost:5000`.

### Market Data (`/market` namespace)

```javascript
const socket = io('http://localhost:5000/market');

// Subscribe to live price data for a symbol
socket.emit('subscribe_symbol', { symbol: 'EURUSD' });

// Receive market data every ~1 second
socket.on('market_data', (data) => {
    console.log(data);
    // { symbol: 'EURUSD', bid: 1.08521, ask: 1.08523, time: 1705312800 }
});

// Unsubscribe
socket.emit('unsubscribe_symbol', { symbol: 'EURUSD' });
```

### Commission Updates (default namespace)

```javascript
const socket = io('http://localhost:5000');

socket.on('commission_created', (data) => {
    console.log('New commission:', data);
    // { commission_id: 1, trade_id: 5, amount: "10.00", broker_account_id: 1, status: "pending" }
});
```

---

## Security Notes

1. **API Key**: The `X-API-Key` header check is a development convenience. Replace with JWT/OAuth2 before production deployment.
2. **MT5 Passwords**: Stored encrypted with Fernet symmetric encryption. Back up your `FERNET_KEY` — losing it means existing passwords cannot be decrypted.
3. **HTTPS**: Always run behind a reverse proxy (nginx/Caddy) with TLS in production.
4. **SECRET_KEY**: Must be a long random string in production. Never commit to version control.

---

## Background Jobs

- **Trade Sync**: APScheduler runs `sync_worker.run_sync_job()` every `SYNC_INTERVAL_SECONDS` (default 60s). Per-account MT5 errors are logged and skipped without crashing the job.
- **Market Feed**: A SocketIO background task ticks every 1 second, emitting `market_data` to subscribed symbol rooms.
- **Trade Copier**: A daemon thread polls master positions every `COPIER_POLL_SECONDS` (default 2s) and mirrors them to slave accounts.

---

## Logs

Application logs are written to `logs/trading_crm.log` (rotating, max 10MB, 5 backups) and to the console. Log level defaults to `INFO` (configurable via `LOG_LEVEL` env var).

---

## License

MIT
