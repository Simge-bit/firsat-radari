"""Yerel prototip sunucusu. Kullanım: python3 server.py  ->  http://localhost:8765"""

import json
import os
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import rapor
from radar import urunler

PORT = 8765
WEB = Path(__file__).resolve().parent / "web"
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8"))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        # Rapor adresleri de aynı sayfayı döndürür; hangi raporun açılacağına tarayıcıdaki kod karar verir.
        if url.path == "/" or url.path.startswith("/rapor/"):
            self._send(200, "text/html; charset=utf-8", (WEB / "index.html").read_bytes())
        elif url.path.startswith("/static/"):
            file = (WEB / url.path[len("/static/"):]).resolve()
            if file.is_file() and WEB in file.parents and file.suffix in STATIC_TYPES:
                self._send(200, STATIC_TYPES[file.suffix], file.read_bytes())
            else:
                self._send(404, "text/plain; charset=utf-8", "Bulunamadı".encode("utf-8"))
        elif url.path == "/api/ara":
            self._json(200, urunler.search(urllib.parse.parse_qs(url.query).get("q", [""])[0]))
        elif url.path == "/api/rapor":
            gtip = urllib.parse.parse_qs(url.query).get("gtip", [""])[0]
            try:
                self._json(200, rapor.build(rapor.hs6_from(gtip)))
            except ValueError as error:
                self._json(400, {"error": str(error)})
            except RuntimeError as error:
                self._json(502, {"error": str(error)})
            except Exception:
                traceback.print_exc()
                self._json(500, {"error": "Rapor hazırlanırken beklenmeyen bir hata oluştu."})
        else:
            self._send(404, "text/plain; charset=utf-8", "Bulunamadı".encode("utf-8"))


if __name__ == "__main__":
    # Barındırma ortamı PORT değişkenini verir ve dışarıdan erişim ister; yerelde yalnızca bu bilgisayar.
    port = int(os.environ.get("PORT", PORT))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    print(f"Fırsat Radarı: http://localhost:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
