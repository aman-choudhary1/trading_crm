"""
routes/docs_routes.py
---------------------
Routes for serving interactive Swagger API documentation.
Bypasses API key validation so the docs can be read directly in browser.
"""

import os
import json
from flask import Blueprint, current_app, render_template_string, send_from_directory, jsonify

docs_bp = Blueprint("docs", __name__)

# Dark-themed Swagger UI wrapper HTML string
SWAGGER_UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mini Trading CRM — Developer Portal</title>
    
    <!-- Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700&family=Fira+Code:wght@500&display=swap" rel="stylesheet">
    
    <!-- Swagger UI CSS CDN -->
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
    
    <!-- Material Theme for Swagger UI -->
    <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-themes@3.0.1/themes/3.x/theme-material.css" />
    
    <style>
        :root {
            --bg-color: #0b0f19;
            --header-bg: rgba(15, 23, 42, 0.85);
            --card-bg: #1e293b;
            --accent-color: #38bdf8;
            --accent-hover: #0284c7;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --border-color: rgba(51, 65, 85, 0.5);
        }
        
        body {
            background-color: var(--bg-color);
            margin: 0;
            padding: 0;
            font-family: 'Inter', sans-serif;
            color: var(--text-primary);
            min-height: 100vh;
        }

        /* Glassmorphism Header */
        .dev-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 2rem;
            background: var(--header-bg);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 1000;
        }

        .brand-container {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .brand-logo {
            width: 32px;
            height: 32px;
            background: linear-gradient(135deg, #3b82f6, #38bdf8);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: 'Outfit', sans-serif;
            font-weight: 700;
            font-size: 1.1rem;
            color: #ffffff;
            box-shadow: 0 0 15px rgba(56, 189, 248, 0.4);
        }

        .dev-header h1 {
            font-family: 'Outfit', sans-serif;
            font-size: 1.2rem;
            font-weight: 700;
            color: var(--text-primary);
            margin: 0;
            letter-spacing: -0.02em;
        }

        /* API Key Widget */
        .api-key-container {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid var(--border-color);
            padding: 0.4rem 0.9rem;
            border-radius: 9999px;
            font-size: 0.85rem;
            box-shadow: inset 0 1px 2px rgba(0,0,0,0.2);
            transition: border-color 0.2s;
        }
        
        .api-key-container:hover {
            border-color: rgba(56, 189, 248, 0.5);
        }

        .api-key-label {
            color: var(--text-secondary);
            font-weight: 500;
        }

        .api-key-value {
            color: var(--accent-color);
            font-family: 'Fira Code', monospace;
            font-weight: 500;
            letter-spacing: 0.02em;
        }

        .copy-btn {
            background: #2563eb;
            color: #ffffff;
            border: none;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }

        .copy-btn:hover {
            background: #1d4ed8;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
        }

        .copy-btn:active {
            transform: translateY(0);
        }

        /* Toast Notification */
        .toast {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            background: #10b981;
            color: white;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            font-weight: 500;
            font-size: 0.9rem;
            box-shadow: 0 10px 15px -3px rgba(16, 185, 129, 0.4);
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            z-index: 9999;
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }

        /* Custom overrides to merge Material UI Theme with custom page styles */
        .swagger-ui {
            background-color: var(--bg-color) !important;
            padding-top: 1.5rem;
        }
        
        .swagger-ui .info {
            margin: 20px 0 !important;
            padding: 0 20px;
        }
        
        .swagger-ui .info .title {
            font-family: 'Outfit', sans-serif !important;
            color: var(--text-primary) !important;
            font-size: 2.2rem !important;
        }
        
        .swagger-ui .info p, .swagger-ui .info li, .swagger-ui .info code {
            font-size: 0.95rem !important;
            line-height: 1.6 !important;
            color: var(--text-secondary) !important;
        }
        
        .swagger-ui .info a {
            color: var(--accent-color) !important;
        }
        
        .swagger-ui .scheme-container {
            background-color: #111827 !important;
            border-top: 1px solid var(--border-color) !important;
            border-bottom: 1px solid var(--border-color) !important;
            box-shadow: none !important;
            padding: 15px 20px !important;
        }

        .swagger-ui .btn.authorize {
            background-color: #10b981 !important;
            border-color: #10b981 !important;
            color: white !important;
            border-radius: 6px !important;
            font-weight: 600 !important;
            transition: background-color 0.2s;
        }
        
        .swagger-ui .btn.authorize:hover {
            background-color: #059669 !important;
        }
        
        .swagger-ui .btn.authorize svg {
            fill: white !important;
        }

        /* Make standard inputs look modern */
        .swagger-ui input[type=text], .swagger-ui select {
            background-color: #1f2937 !important;
            border: 1px solid var(--border-color) !important;
            color: var(--text-primary) !important;
            border-radius: 6px !important;
        }
    </style>
</head>
<body>

    <!-- Dev Portal Header -->
    <header class="dev-header">
        <div class="brand-container">
            <div class="brand-logo">T</div>
            <h1>Mini Trading CRM &mdash; Developer Portal</h1>
        </div>
        
        <div class="api-key-container">
            <span class="api-key-label">Dev API Key:</span>
            <span class="api-key-value" id="apiKeyText">{{ api_key }}</span>
            <button class="copy-btn" onclick="copyApiKey()">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
                Copy
            </button>
        </div>
    </header>

    <!-- Swagger UI container -->
    <div id="swagger-ui"></div>

    <!-- Toast message -->
    <div id="copyToast" class="toast">API Key copied to clipboard!</div>

    <!-- Swagger UI scripts -->
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"> </script>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"> </script>
    
    <script>
        window.onload = function() {
            // Build UI pointed to openapi JSON endpoint
            const ui = SwaggerUIBundle({
                url: "/docs/openapi.json",
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "BaseLayout",
                persistAuthorization: true
            });
            window.ui = ui;
        };

        function copyApiKey() {
            const apiKey = document.getElementById("apiKeyText").innerText;
            navigator.clipboard.writeText(apiKey).then(() => {
                const toast = document.getElementById("copyToast");
                toast.classList.add("show");
                setTimeout(() => {
                    toast.classList.remove("show");
                }, 2000);
            }).catch(err => {
                console.error("Could not copy API Key: ", err);
            });
        }
    </script>
</body>
</html>
"""


@docs_bp.route("/docs")
def get_swagger_ui():
    """Render the customized Swagger UI HTML page."""
    api_key = current_app.config.get("API_KEY", "dev-api-key")
    return render_template_string(SWAGGER_UI_HTML, api_key=api_key)


@docs_bp.route("/docs/openapi.json")
def get_openapi_spec():
    """Serve the raw openapi.json file directly."""
    # Find the path to static/openapi.json relative to the app root
    static_dir = os.path.join(current_app.root_path, "static")
    return send_from_directory(static_dir, "openapi.json")
