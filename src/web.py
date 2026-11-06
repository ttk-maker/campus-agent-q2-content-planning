"""Local workbench with durable business state and bounded asynchronous jobs."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit
import uuid

from .agent import Agent
from .domain import validate_catalog, validate_request
from .models import HTTPModel, MockModel, ModelError
from .scenarios import LABELS, scenario
from .store import Store, StateError

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LIMIT = 256 * 1024


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Application:
    def __init__(self, database, model_factory=None):
        self.store = Store(database)
        self.model_factory = model_factory or (lambda mode: MockModel() if mode == "mock" else HTTPModel())
        self.token = secrets.token_urlsafe(32)
        self.jobs = {}
        self.lock = threading.RLock()
        self.active = None

    def bootstrap(self):
        with self.lock:
            return {"csrf_token": self.token, "scenarios": {name: scenario(name) for name in LABELS},
                    "labels": LABELS, "model_name": os.environ.get("MODEL_NAME", "未配置"),
                    "active_job": self.active}

    def validate_payload(self, payload):
        if not isinstance(payload, dict) or not {"request", "catalog", "mode"} <= set(payload):
            raise ValueError("request, catalog, mode required")
        if set(payload) - {"request", "catalog", "mode", "max_steps"}: raise ValueError("unknown fields")
        validate_request(payload["request"])
        validate_catalog(payload["catalog"])
        if payload["mode"] not in ("mock", "real"): raise ValueError("invalid mode")
        limit = payload.get("max_steps", 16)
        if type(limit) is not int or not 1 <= limit <= 100: raise ValueError("invalid step limit")
        return deepcopy(payload)

    def start(self, payload):
        payload = self.validate_payload(payload)
        with self.lock:
            if self.active: raise APIError(409, "已有任务执行中，请稍后重试")
            try: model = self.model_factory(payload["mode"])
            except ModelError: raise APIError(503, "模型配置不可用，请检查 Ollama 和服务端环境变量") from None
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {"job_id": job_id, "state": "running", "payload": payload,
                                 "created_at": datetime.now(timezone.utc).isoformat(),
                                 "result": None, "trace": [], "error": None}
            self.active = job_id
            while len(self.jobs) > 100: self.jobs.pop(next(iter(self.jobs)))
            threading.Thread(target=self._execute, args=(job_id, model), daemon=True).start()
            return {"job_id": job_id, "state": "running"}

    def _execute(self, job_id, model):
        payload = self.jobs[job_id]["payload"]
        agent = Agent(model, self.store, payload["catalog"], payload.get("max_steps", 16))
        try:
            result = agent.run(payload["request"])
            with self.lock: self.jobs[job_id].update(state="done", result=result, trace=agent.trace)
        except Exception as exc:
            error = str(exc) if isinstance(exc, StateError) else type(exc).__name__
            with self.lock:
                self.jobs[job_id].update(state="error", error="执行未完成：" + error,
                                        trace=agent.trace)
        finally:
            with self.lock: self.active = None

    def job(self, job_id):
        with self.lock:
            if job_id not in self.jobs: raise APIError(404, "运行记录不存在或服务已重启；可用原请求续跑")
            return deepcopy(self.jobs[job_id])

def make_server(app, port=8767):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send_bytes(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def json(self, status, data):
            self.send_bytes(status, json.dumps(data, ensure_ascii=False, allow_nan=False).encode(),
                            "application/json; charset=utf-8")

        def check_host(self):
            if self.headers.get("Host") not in (f"127.0.0.1:{self.server.server_port}",
                                                f"localhost:{self.server.server_port}"):
                raise APIError(403, "仅允许本机访问")

        def do_GET(self):
            try:
                self.check_host()
                path = urlsplit(self.path).path
                if path in ("/", "/index.html", "/app.js", "/style.css", "/manual.html"):
                    name = "index.html" if path == "/" else path[1:]
                    kind = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[Path(name).suffix]
                    self.send_bytes(200, (WEB / name).read_bytes(), kind + "; charset=utf-8")
                elif path == "/favicon.ico":
                    self.send_bytes(204, b"", "image/x-icon")
                elif path == "/api/health":
                    self.json(200, {"status": "ok", "published": False})
                elif path == "/api/bootstrap":
                    self.json(200, app.bootstrap())
                elif path == "/api/plans":
                    self.json(200, {"plans": app.store.saved()})
                elif path.startswith("/api/jobs/"):
                    self.json(200, app.job(path.rsplit("/", 1)[-1]))
                else:
                    raise APIError(404, "页面不存在。请打开首页 http://127.0.0.1:" + str(self.server.server_port) + "/")
            except APIError as exc:
                self.json(exc.status, {"error": exc.message})
            except Exception:
                self.json(500, {"error": "读取失败，请检查本地服务日志或重启服务"})

        def do_POST(self):
            try:
                self.check_host()
                origin = self.headers.get("Origin")
                if origin and origin != "http://" + self.headers.get("Host", ""):
                    raise APIError(403, "跨站请求被拒绝")
                if self.headers.get("X-CSRF-Token") != app.token:
                    raise APIError(403, "页面会话已过期，请刷新后重试")
                if self.headers.get_content_type() != "application/json":
                    raise APIError(415, "请使用 JSON 请求")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise APIError(400, "请求长度无效") from None
                if not 0 < length <= LIMIT:
                    raise APIError(413, "请求为空或超过 256 KB")
                self.connection.settimeout(10)
                def invalid_constant(value):
                    raise ValueError("JSON 不允许非有限数字")
                payload = json.loads(self.rfile.read(length).decode("utf-8"), parse_constant=invalid_constant)
                path = urlsplit(self.path).path
                if path == "/api/jobs":
                    self.json(202, app.start(payload))
                else:
                    raise APIError(404, "API 路径不存在")
            except APIError as exc:
                self.json(exc.status, {"error": exc.message})
            except (ValueError, TypeError, KeyError, UnicodeError):
                self.json(400, {"error": "输入格式不正确，请检查请求、素材、时间及规则"})
            except Exception:
                self.json(500, {"error": "服务暂时无法处理请求；未报告保存成功"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Local content planning workbench")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--db", default="runtime/workbench.db")
    args = parser.parse_args()
    os.environ.setdefault("MODEL_BASE_URL", "http://localhost:11434/v1")
    os.environ.setdefault("MODEL_NAME", "qwen2.5:7b-instruct")
    app = Application(args.db)
    server = make_server(app, args.port)
    print(f"Open http://127.0.0.1:{server.server_port}/ (UI); Ollama /v1 is an API base, not a webpage.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
