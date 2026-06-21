# 📊 Mini Trading CRM Backend

[![Render Deployment](https://img.shields.io/badge/Render-Live-brightgreen?style=for-the-badge&logo=render&logoColor=white)](https://trading-crm-backend.onrender.com/docs)
[![Database](https://img.shields.io/badge/MySQL-Clever_Cloud-blue?style=for-the-badge&logo=mysql&logoColor=white)](https://console.clever-cloud.com)
[![Python Version](https://img.shields.io/badge/Python-3.11.9-yellow?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Tests Status](https://img.shields.io/badge/Tests-37%20Passed-success?style=for-the-badge&logo=pytest&logoColor=white)]()

A premium, production-ready Flask-based backend CRM for trading operations. It integrates with **MetaTrader 5 (MT5)**, provides a consistent REST API, hosts a custom dark-themed interactive **Swagger developer portal**, runs real-time WebSocket feeds, and features an automated trade synchronizer, idempotent commission calculator, and master-slave trade copier.

---

## 🔗 Live Deployment Details

The application is deployed and running live on Render, connected to a Clever Cloud MySQL instance.

* **Primary Backend API URL:** `https://trading-crm-backend.onrender.com`
* **Interactive Developer Portal (Swagger UI):** 🚀 **[https://trading-crm-backend.onrender.com/docs](https://trading-crm-backend.onrender.com/docs)**
* **Demo API Key:** `fc8d781b0a8c2fe5918e7e17e4f16dc4`

> [!TIP]
> Go to the live **[Developer Portal (/docs)](https://trading-crm-backend.onrender.com/docs)**, click the **Authorize** button at the top right, paste the demo API key, and you can execute actual API requests directly in your browser against the live database!

---

## 🎨 Interactive Swagger Developer Portal

We built a custom Developer Portal served directly from the `/docs` endpoint. It has been designed with premium aesthetics in mind:
* **Dark Mode Aesthetics:** Custom style overrides applied over a material-dark theme for a modern, high-contrast look that matches top-tier SaaS portals.
* **Sticky API Key Widget:** A custom glassmorphic top bar displaying the current session credentials, equipped with a one-click clipboard copying mechanism.
* **OpenAPI 3.0 Conformance:** Fully defined in `static/openapi.json` and rendered dynamically.

---

## 🛠️ Tech Stack & Architecture

| Layer | Technology | Role |
| :--- | :--- | :--- |
| **Core Framework** | Flask 3.0 + Blueprints | REST API & Core Routing |
| **Real-time Comms**| Flask-SocketIO 5.3 + Eventlet | WebSocket Rooms & Live Streaming |
| **ORM** | Flask-SQLAlchemy 3.1 | Database mapping & abstraction |
| **Migrations** | Flask-Migrate (Alembic) | Programmatic database schema versioning |
| **Database** | MySQL 8.0 (Clever Cloud) | Primary persistent data store |
| **Background Jobs**| APScheduler 3.10 | Scheduled synchronization across active accounts |
| **Encryption** | cryptography (Fernet) | Symmetric encryption for broker credentials |
| **Testing** | pytest + unittest.mock | Complete test harness with 37 mocks |

---

## 🏗️ Folder Structure

```
trading_crm/
├── app.py                     # App factory (initializes DB, sockets, auto-migrations)
├── config.py                  # Environment-specific configuration manager
├── extensions.py              # Singleton extension holder
├── run.py                     # Application runner (Eventlet/SocketIO entry point)
├── static/
│   └── openapi.json           # OpenAPI 3.0 JSON specification document
├── models/                    # Database models (User, BrokerAccount, Trade, Commission, etc.)
├── routes/                    # API endpoints split logically into blueprints
│   ├── docs_routes.py         # Swagger UI serving route (custom styling and JS widgets)
│   └── ...
├── services/                  # Business logic (MT5 connection, sync engine, copier)
├── workers/                   # Background loop handlers
├── live_data/                 # WebSocket market ticks generation loop
├── sockets/                   # WebSocket event listeners (namespaces, rooms)
├── utils/                     # Exceptions, error-handlers, validators, cryptography
└── tests/                     # 37 pytest cases covering all endpoints & services
```

---

## ⚠️ Platform Constraint — MetaTrader 5 (Windows Only)

> [!WARNING]
> **The `MetaTrader5` Python package is Windows-only.**
> It communicates with a locally installed MT5 desktop client via local named pipes. It does not compile or run on Linux natively.
> 
> * **How we handle this on Linux (Render):** The application checks for MT5 package availability dynamically. If not installed, it gracefully enters mock/fail mode for real MT5 calls (syncing or connecting will log errors), but the rest of the application runs perfectly.
> * **Testing:** All 37 unit and integration tests use unit mocks to test connection, synchronization, and copier flows without requiring a real MT5 terminal or a Windows runner.

---

## 🚀 Local Development Setup

We have configured the project with SQLite out-of-the-box so you can spin up the server locally without installing MySQL.

### 1. Clone and Install Dependencies
```bash
git clone https://github.com/aman-choudhary1/trading_crm.git
cd trading_crm

# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy the `.env.example` to `.env`:
```bash
# Windows
copy .env.example .env
# Linux/macOS
cp .env.example .env
```
Ensure you have the default keys set up. For local testing, you can use the SQLite default URI:
```env
SQLALCHEMY_DATABASE_URI=sqlite:///trading_crm.db
API_KEY=fc8d781b0a8c2fe5918e7e17e4f16dc4
```

### 3. Run the Server
```bash
python run.py
```
> [!NOTE]
> Database migrations will run **automatically** at startup. The local sqlite file `instance/trading_crm.db` will be created and migrated to the latest version immediately.

Open **`http://localhost:5000/docs`** in your browser to view the local interactive portal.

---

## 🧪 Running Tests
We maintain 100% passing tests for all modules.
```bash
python -m pytest
```

---

## 📡 API Reference & WebSocket Feeds

All API calls must contain a consistent JSON envelope:
```json
{
  "success": true,
  "data": { ... },
  "error": null
}
```

### 🔑 Authorization Header
Include the following header on all `/api/*` requests:
`X-API-Key: fc8d781b0a8c2fe5918e7e17e4f16dc4`

### WebSocket Integration
The backend serves real-time events at `ws://localhost:5000` (or the Render server domain):
1. **`/market` Namespace:** Subscribe to live symbol updates:
   ```javascript
   const socket = io("https://trading-crm-backend.onrender.com/market");
   socket.emit("subscribe_symbol", { symbol: "EURUSD" });
   socket.on("market_data", (tick) => {
       console.log(tick); // { symbol: "EURUSD", bid: 1.08520, ask: 1.08522, time: ... }
   });
   ```
2. **Default Namespace:** Listen for real-time commission creation alerts:
   ```javascript
   const socket = io("https://trading-crm-backend.onrender.com");
   socket.on("commission_created", (commission) => {
       console.log("New Commission:", commission);
   });
   ```

---

## 📝 License
This project is licensed under the MIT License.
