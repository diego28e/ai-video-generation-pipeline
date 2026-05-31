#!/usr/bin/env python3
"""Mock LMS webhook receiver for Gate G3 — verifies the engine's HMAC and prints events.

Run:  ENGINE_HMAC_SECRET=dev-secret python scripts/mock_lms.py
Listens on 127.0.0.1:9000 by default.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ.get("ENGINE_HMAC_SECRET", "dev-secret")
PORT = int(os.environ.get("MOCK_LMS_PORT", "9000"))


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        sig = self.headers.get("X-Signature")
        ok = sig is not None and hmac.compare_digest(_sign(body), sig)
        try:
            data = json.loads(body)
        except Exception:  # noqa: BLE001
            data = {}
        flag = "OK " if ok else "BAD"
        print(f"[mock-lms] sig={flag} event={data.get('type')!r:18} body={json.dumps(data)[:240]}", flush=True)
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):  # silence default logging
        pass


if __name__ == "__main__":
    print(f"[mock-lms] listening on http://127.0.0.1:{PORT} (HMAC via ENGINE_HMAC_SECRET)", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
