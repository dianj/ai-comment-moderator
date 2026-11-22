"""A scripted, in-process stand-in for LM Studio's OpenAI-compatible chat endpoint.

Tests queue the moderator's next verdicts with `verdict(...)`, so every run is deterministic
and needs no GPU. Every request is recorded, so tests can assert on the prompt the model saw.
"""
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeLMStudio:
    def __init__(self):
        self.queue = []        # pending raw assistant replies (strings)
        self.requests = []     # recorded /v1/chat/completions payloads
        self.fail_count = 0    # answer the next N requests with HTTP 500 (simulated outage)
        self.delay_s = 0.0     # think time before each answer (a slow local model)
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def reset(self):
        with self.lock:
            self.queue.clear()
            self.requests.clear()
            self.fail_count = 0
            self.delay_s = 0.0

    def verdict(self, decision="APPROVED", category="Clean", toxicity_score=0, reason="Looks fine."):
        """Queue one verdict, exactly as the model would write it."""
        self.raw(json.dumps({"decision": decision, "category": category,
                             "toxicity_score": toxicity_score, "reason": reason}))

    def raw(self, content):
        with self.lock:
            self.queue.append(content)

    def last_user_message(self):
        return self.requests[-1]["messages"][-1]["content"]

    def _next(self):
        with self.lock:
            if self.fail_count:
                self.fail_count -= 1
                return None
            return self.queue.pop(0) if self.queue else json.dumps(
                {"decision": "APPROVED", "category": "Clean", "toxicity_score": 0, "reason": "OK."})

    def _handler(fake):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send(200, {"object": "list", "data": [{"id": "gemma-4-26b-a4b-it", "object": "model"}]})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                with fake.lock:
                    fake.requests.append(payload)
                if fake.delay_s:
                    time.sleep(fake.delay_s)
                content = fake._next()
                if content is None:
                    self._send(500, {"error": "simulated LM Studio failure: CUDA out of memory at 0xDEADBEEF"})
                    return
                self._send(200, {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion",
                    "model": payload.get("model"),
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                })
        return Handler
