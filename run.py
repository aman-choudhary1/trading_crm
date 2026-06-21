"""
run.py
------
Application entry point.

Run with:
    python run.py

The server is started via socketio.run() so that WebSocket support
(eventlet) is properly initialised instead of the plain Flask dev server.
"""

import os
from app import create_app
from extensions import socketio

app = create_app(os.environ.get("FLASK_ENV", "development"))

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    debug = app.config.get("DEBUG", False)

    print(f"[run.py] Starting Mini Trading CRM on {host}:{port} (debug={debug})")
    socketio.run(app, host=host, port=port, debug=debug, use_reloader=debug)
