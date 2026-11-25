"""Local fake of the Moss endpoints, only for dry-running the harness. Numbers from it mean nothing.

python tools/mock_moss.py  then  MOSS_BASE_URL=http://127.0.0.1:8765/v1 python run.py
"""
import json
import random
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TASKS = {}
LOCK = threading.Lock()


def usage(p=20, c=12):
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c, "prompt_tokens_details": {"cached_tokens": 0}}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, obj, headers=None):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("x-moss-request-id", uuid.uuid4().hex)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def authed(self):
        if ":" not in self.headers.get("Authorization", ""):
            self.send(401, {"error": {"message": "Missing bearer token", "type": "authentication_error"}})
            return False
        return True

    def do_OPTIONS(self):
        self.send(204, {})

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            return self.send(200, {"object": "list", "data": [{"id": "moss/fastlane-1", "object": "model"}]})
        if not self.authed():
            return
        parts = self.path.split("/")
        if len(parts) >= 4 and parts[2] == "tasks":
            t = TASKS.get(parts[3])
            if not t:
                return self.send(404, {"error": {"message": "not found", "type": "not_found_error"}})
            self.tick(t)
            if len(parts) >= 5:
                if t["status"] not in ("completed", "failed", "cancelled"):
                    return self.send(409, {"error": {"code": "task_not_finished"}})
                if len(parts) == 5:
                    return self.send(200, {"object": "list", "data": [{"path": "screenshot_0.png", "bytes": 10}]})
                return self.send(200, {"file": parts[5]})
            return self.send(200, t)
        self.send(404, {"error": {"message": "no route"}})

    def tick(self, t):
        age = time.time() - t["_t"]
        if t["status"] == "queued" and age > 1:
            t["status"] = "running"
        if t["status"] == "running" and (age > 4 or t["cancel_requested"]):
            t["status"] = "cancelled" if t["cancel_requested"] else "completed"
            t["result"] = {"output_text": "Example Domain", "output": {"heading": "Example Domain"}}
            t["usage"]["cost"] = {"model_usd": 0.004, "browser_usd": 0.0003, "traffic_usd": None, "total_usd": 0.0043}

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        if not self.authed():
            return
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self.send(400, {"error": {"message": "bad json", "type": "invalid_request_error"}})
        if self.path == "/v1/tasks":
            if "goal" not in body:
                return self.send(400, {"error": {"message": "goal required", "type": "invalid_request_error"}})
            tid = "task_" + uuid.uuid4().hex
            with LOCK:
                TASKS[tid] = {"id": tid, "object": "task", "status": "queued", "cancel_requested": False, "_t": time.time(),
                              "metadata": body.get("metadata"), "result": None, "error": None,
                              "usage": {"cost": {"total_usd": 0}}}
            return self.send(202, TASKS[tid])
        if self.path.endswith("/cancel"):
            t = TASKS.get(self.path.split("/")[3])
            if not t:
                return self.send(404, {"error": {"type": "not_found_error"}})
            t["cancel_requested"] = True
            if t["status"] == "queued":
                t["status"] = "cancelled"
            return self.send(200, t)
        if not body.get("messages") and self.path.endswith("completions"):
            return self.send(400, {"error": {"message": "messages required", "type": "invalid_request_error"}})
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            time.sleep(0.12)
            for w in ["Hello", " from", " the", " mock", "."]:
                if self.path.endswith("completions"):
                    ev = {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": w}}]}
                else:
                    ev = {"type": "response.output_text.delta", "delta": w}
                self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                self.wfile.flush()
                time.sleep(random.uniform(0.005, 0.02))
            if self.path.endswith("completions"):
                self.wfile.write(f"data: {json.dumps({'choices': [], 'usage': usage()})}\n\ndata: [DONE]\n\n".encode())
            else:
                ev = {"type": "response.completed", "response": {"usage": {"input_tokens": 20, "output_tokens": 5}}}
                self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
            self.close_connection = True
            return
        if self.path.endswith("completions"):
            return self.send(200, {"object": "chat.completion", "model": "moss/fastlane-1", "usage": usage(),
                                   "choices": [{"index": 0, "finish_reason": "stop",
                                                "message": {"role": "assistant", "content": "{\"name\": \"x\", \"year\": 1, \"langs\": []}"}}]})
        return self.send(200, {"object": "response", "model": "moss/fastlane-1", "status": "completed",
                               "output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}],
                               "usage": {"input_tokens": 20, "output_tokens": 5}})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
