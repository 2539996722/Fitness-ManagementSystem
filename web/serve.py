"""本地开发 web server：静态文件 + /api 反代到后端。

用法：python serve.py [port]
默认 8080。/api/* 反代到 http://127.0.0.1:8002。

注：仅供本地 dev。生产环境用 Caddy/Nginx。
"""

import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib import request as urlreq, error as urlerr

BACKEND = "http://127.0.0.1:8002"


class DevHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/") or self.path.startswith("/static/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy("POST")
        else:
            self.send_error(405)

    def do_PUT(self):
        if self.path.startswith("/api/"):
            self._proxy("PUT")
        else:
            self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            self._proxy("DELETE")
        else:
            self.send_error(405)

    def do_PATCH(self):
        if self.path.startswith("/api/"):
            self._proxy("PATCH")
        else:
            self.send_error(405)

    def do_OPTIONS(self):
        # CORS 预检
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def _proxy(self, method):
        url = BACKEND + self.path
        # 透传 body
        body = None
        if method in ("POST", "PUT", "PATCH"):
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else None
        req = urlreq.Request(url, data=body, method=method)
        # 透传部分 headers
        for k in ("Authorization", "Content-Type", "Accept", "User-Agent"):
            v = self.headers.get(k)
            if v:
                req.add_header(k, v)
        try:
            with urlreq.urlopen(req, timeout=60) as resp:
                self.send_response(resp.status)
                # 透传响应 headers
                for k, v in resp.headers.items():
                    if k.lower() in ("transfer-encoding", "connection"):
                        continue
                    self.send_header(k, v)
                # CORS
                self.send_header("Access-Control-Allow-Origin", "*")
                data = resp.read()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urlerr.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() in ("transfer-encoding", "connection"):
                    continue
                self.send_header(k, v)
            self.send_header("Access-Control-Allow-Origin", "*")
            data = e.read() if hasattr(e, "read") else b""
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_error(502, f"backend unreachable: {e}")

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[dev] {self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"[dev] http://127.0.0.1:{port}  (static)  +  /api/*  →  {BACKEND}")
    HTTPServer(("127.0.0.1", port), DevHandler).serve_forever()
