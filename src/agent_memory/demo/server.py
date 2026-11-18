"""Local HTTP server for the demo: JSON API, SSE for turns, static page. Binds 127.0.0.1 only."""
import json
import logging
import mimetypes
import sys
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from agent_memory.demo.clients import redact
from agent_memory.demo.session import Session

MAX_BODY = 65536
CHUNK = 24  # D5: the finished reply is chunked into delta events
DEFAULT_STATIC = Path(__file__).parent / "static"
log = logging.getLogger("agent_memory.demo.server")


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=lambda o: asdict(o) if is_dataclass(o) else str(o))


class _Bad(Exception):
    def __init__(self, code: int, msg: str) -> None:
        self.code, self.msg = code, msg


class Handler(BaseHTTPRequestHandler):
    server_version = "agent-memory-demo"
    timeout = 30

    # -- plumbing -----------------------------------------------------------------------------
    @property
    def session(self) -> Session:
        return self.server.session

    def _redact(self, text: str) -> str:
        return redact(text, self.session._secrets())

    def log_message(self, format, *args):
        log.info(self._redact(format % args))

    def log_error(self, format, *args):
        log.warning(self._redact(format % args))

    def send_error(self, code, message=None, explain=None):  # JSON, never the stock HTML page
        self._json({"error": self._redact(message or self.responses.get(code, ("error",))[0])}, code)

    def _json(self, obj, code: int = 200) -> None:
        body = _dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _body(self) -> dict:
        if "Transfer-Encoding" in self.headers:
            raise _Bad(400, "chunked bodies are not accepted")
        raw = self.headers.get("Content-Length", "")
        if not raw.isdigit():
            raise _Bad(400, "Content-Length required")
        n = int(raw)
        if n > MAX_BODY:
            self.close_connection = True
            left = min(n, 1 << 20)  # drain what the client is sending so it sees the 400, not a reset
            while left > 0:
                chunk = self.rfile.read(min(left, 65536))
                if not chunk:
                    break
                left -= len(chunk)
            raise _Bad(400, "body too large")
        if n and self.headers.get_content_type() != "application/json":
            raise _Bad(415, "Content-Type must be application/json")
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise _Bad(400, "malformed JSON") from None
        if not isinstance(data, dict):
            raise _Bad(400, "JSON object expected")
        return data

    def _dispatch(self, fn) -> None:
        try:
            if not self._host_ok():
                raise _Bad(403, "forbidden host")
            fn()
        except _Bad as e:
            self._reply_error(e.msg, e.code)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as exc:  # no traceback to the client, and only redacted text in the log
            log.error("request failed: %s", self._redact(f"{type(exc).__name__}: {exc}"))
            self._reply_error("internal error", 500)

    def _reply_error(self, msg: str, code: int) -> None:
        try:
            self._json({"error": msg}, code)
        except OSError:  # the client left; nothing to tell it
            self.close_connection = True

    # -- routes -------------------------------------------------------------------------------
    def do_GET(self):
        self._dispatch(self._get)

    def do_POST(self):
        self._dispatch(self._post)

    def _get(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/state":
            return self._json(self.session.snapshot())
        if path == "/":
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(unquote(path[len("/static/"):]))
        raise _Bad(404, "not found")

    def _static(self, rel: str) -> None:
        root = self.server.static_dir.resolve()
        try:
            f = (root / rel).resolve()  # resolve() follows symlinks, so escapes fail the check below
            ok = "\0" not in rel and f.is_relative_to(root) and f.is_file()
        except (OSError, ValueError):
            ok = False
        if not ok:
            raise _Bad(404, "not found")
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")  # the page is edited while the demo runs
        self.end_headers()
        self.wfile.write(data)

    def _post(self) -> None:
        path = urlsplit(self.path).path
        routes = {"/api/turn": self._turn, "/api/forget": self._forget, "/api/mode": self._mode,
                  "/api/advance": lambda b: self._act(self.session.advance),
                  "/api/reflect": lambda b: self._act(self.session.reflect),
                  "/api/reset": lambda b: self._act(self.session.reset),
                  "/api/wipe": lambda b: self._act(self.session.wipe)}
        if path not in routes:
            raise _Bad(404, "not found")
        origin = self.headers.get("Origin")  # CSRF: browsers always send Origin on cross-site POSTs
        if origin is not None and origin != f"http://{self.headers.get('Host')}":
            raise _Bad(403, "cross-origin request refused")
        routes[path](self._body())

    def _act(self, fn) -> None:
        fn()
        self._json(self.session.snapshot())

    def _forget(self, body: dict) -> None:
        col, eid = body.get("column"), body.get("entry_id")
        if not isinstance(col, str) or not isinstance(eid, str):
            raise _Bad(400, "column and entry_id are required")
        if not self.session.forget(col, eid):
            raise _Bad(404, "unknown or already forgotten entry")
        self._json(self.session.snapshot())

    def _mode(self, body: dict) -> None:
        try:
            self.session.set_mode(body.get("mode"))
        except ValueError:
            raise _Bad(400, "mode must be live or replay") from None
        self._json(self.session.snapshot())

    def _event(self, name: str, data) -> None:
        self.wfile.write(f"event: {name}\ndata: {_dumps(data)}\n\n".encode())
        self.wfile.flush()

    def _turn(self, body: dict) -> None:
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise _Bad(400, "text is required")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            before = self.session.snapshot()["notice"]
            try:
                results = self.session.turn(text)
            except Exception as exc:
                log.error("turn failed: %s", self._redact(f"{type(exc).__name__}: {exc}"))
                self._event("error", {"message": "internal error"})
                return self._event("done", {})
            for col, r in results.items():
                for i in range(0, len(r.reply or ""), CHUNK):
                    self._event("delta", {"column": col, "text": r.reply[i:i + CHUNK]})
                if r.error:
                    self._event("error", {"column": col, "message": self._redact(r.error)})
            snap = self.session.snapshot()
            if snap["notice"] and snap["notice"] != before:
                self._event("error", {"message": self._redact(snap["notice"]), "recovered": True})
            self._event("snapshot", snap)
            self._event("done", {})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, session: Session, static_dir: Path) -> None:
        super().__init__(addr, Handler)
        self.session, self.static_dir = session, Path(static_dir)

    def handle_error(self, request, client_address):  # one redacted line instead of a traceback on stderr
        exc = sys.exc_info()[1]
        if not isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            log.error("connection error: %s", redact(f"{type(exc).__name__}: {exc}", self.session._secrets()))


def make_server(session: Session, port: int = 0, static_dir: Path | None = None) -> ThreadingHTTPServer:
    return DemoServer(("127.0.0.1", port), session, static_dir or DEFAULT_STATIC)
