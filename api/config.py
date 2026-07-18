"""Vercel serverless function — returns runtime config to the frontend.

The frontend fetches /api/config on load to get the backend URL.
This avoids any build-time substitution tricks (which are flaky on Vercel).
"""
import os
import json
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        config = {
            "api_base_url": os.environ.get("RENDER_BACKEND_URL", "")
        }
        body = json.dumps(config).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
