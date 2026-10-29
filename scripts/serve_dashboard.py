#!/usr/bin/env python3
"""
Simple HTTP server to serve the CrossCheck dashboard.
Useful for local development and as a template for deployment.

Usage:
    python scripts/serve_dashboard.py              # Default: localhost:8000
    python scripts/serve_dashboard.py --port 3000  # Custom port
    python scripts/serve_dashboard.py --host 0.0.0.0  # Accessible from outside
"""

import argparse
import functools
import http.server
import socketserver
import sys
from pathlib import Path

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler for serving the dashboard with proper headers.

    Path resolution is left to SimpleHTTPRequestHandler (``directory=``), which
    strips ``..`` segments and query strings, so nothing outside dashboard/ is served.
    """

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }

    def do_GET(self):
        if self.path == "/dashboard":
            self.path = "/index.html"
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format, *args):
        """Log requests to stdout."""
        print(f"[{self.log_date_time_string()}] {format % args}")


def main():
    parser = argparse.ArgumentParser(
        description="Serve CrossCheck dashboard (no authentication required)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to serve on (default: 8000)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1, use 0.0.0.0 for network access)"
    )
    args = parser.parse_args()

    # Verify dashboard files exist
    if not (DASHBOARD_DIR / "index.html").exists():
        print(f"Error: {DASHBOARD_DIR / 'index.html'} not found")
        sys.exit(1)
    if not (DASHBOARD_DIR / "data.json").exists():
        print(f"Error: {DASHBOARD_DIR / 'data.json'} not found")
        sys.exit(1)

    server_address = (args.host, args.port)
    handler = functools.partial(DashboardHandler, directory=str(DASHBOARD_DIR))

    with socketserver.TCPServer(server_address, handler) as httpd:
        print("\n" + "="*60)
        print("CrossCheck Dashboard Server")
        print("="*60)
        print(f"Serving from: {DASHBOARD_DIR}")
        print(f"URL: http://{args.host}:{args.port}/")
        print("\nNo authentication required")
        print("Press Ctrl+C to stop\n")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped")
            sys.exit(0)


if __name__ == "__main__":
    main()
