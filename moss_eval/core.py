import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("MOSS_BASE_URL", "https://inference.moss.dev/v1").rstrip("/")

# USD per 1M tokens (input, cached input, output), docs.moss.dev/docs/inference/models, 2026-11-05
PRICES = {
    "moss/fastlane-1": (0.25, 0.03, 1.75),
    "openai/gpt-6-luna": (0.10, 0.01, 0.50),
    "anthropic/claude-haiku-5.5": (0.10, 0.01, 0.50),
    "google/gemini-3.5-flash-lite": (0.30, 0.03, 2.50),
    "deepseek/deepseek-v4.1-flash": (0.054, 0.0072, 0.60),
}
RETRIEVAL_USD = 0.50 / 1000

SECRET_RE = re.compile(r"(Bearer\s+)[\w.\-]+:[\w.\-]+", re.I)


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def api_key():
    pid, key = os.environ.get("MOSS_PROJECT_ID"), os.environ.get("MOSS_PROJECT_KEY")
    if not pid or not key:
        return None
    return f"{pid}:{key}"


def redact(text: str) -> str:
    text = SECRET_RE.sub(lambda m: m.group(0) if m.group(0).endswith("project_id:project_key")
                         else m.group(1) + "<redacted>", text)
    for name in ("MOSS_PROJECT_ID", "MOSS_PROJECT_KEY"):
        v = os.environ.get(name)
        if v and len(v) >= 6:
            text = text.replace(v, f"<{name}>")
    return text


class BudgetExceeded(Exception):
    pass


class Ledger:
    def __init__(self, path: Path, budget: float):
        self.path, self.budget = path, budget
        self.spent = 0.0
        if path.exists():
            for line in path.read_text().splitlines():
                self.spent += json.loads(line)["usd"]

    def add(self, test: str, usd: float, detail: dict):
        self.spent += usd
        with self.path.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "test": test, "usd": usd, **detail}) + "\n")

    def check(self, upcoming: float = 0.0):
        if self.spent + upcoming > self.budget:
            raise BudgetExceeded(f"spent ${self.spent:.4f} + planned ${upcoming:.4f} > budget ${self.budget}")


def usage_cost(model: str, usage: dict | None, retrievals: int = 0) -> float:
    if not usage:
        return retrievals * RETRIEVAL_USD
    p_in, p_cached, p_out = PRICES.get(model, PRICES["moss/fastlane-1"])
    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
    out = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    det = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = det.get("cached_tokens", 0) or 0
    return ((prompt - cached) * p_in + cached * p_cached + out * p_out) / 1e6 + retrievals * RETRIEVAL_USD


class Recorder:
    """Writes every HTTP exchange of a run as one JSON line."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)

    def write(self, stage: str, rec: dict):
        line = redact(json.dumps(rec, ensure_ascii=False))
        with (self.run_dir / f"{stage}.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _clip(s: str, n: int = 4000) -> str:
    return s if len(s) <= n else s[:n] + f"...<{len(s) - n} more chars>"


def _body_for_log(body):
    if body is None:
        return None
    s = body if isinstance(body, str) else json.dumps(body)
    return _clip(s, 2000)


class Client:
    def __init__(self, recorder: Recorder, ledger: Ledger, key: str | None, timeout: float = 120):
        self.rec, self.ledger, self.key = recorder, ledger, key
        self.http = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=200))

    async def close(self):
        await self.http.aclose()

    def headers(self, extra: dict | None = None, auth: str | None = "default"):
        h = {"Content-Type": "application/json"}
        if auth == "default" and self.key:
            h["Authorization"] = f"Bearer {self.key}"
        elif auth not in (None, "default"):
            h["Authorization"] = auth
        if extra:
            h.update(extra)
        return h

    async def request(self, stage, test, method, path, body=None, headers=None, auth="default", raw=None):
        url = path if path.startswith("http") else BASE_URL + path
        h = self.headers(headers, auth)
        content = raw if raw is not None else (json.dumps(body) if body is not None else None)
        t0 = time.perf_counter()
        err = None
        try:
            r = await self.http.request(method, url, headers=h, content=content)
            status, rh, text = r.status_code, dict(r.headers), r.text
        except httpx.HTTPError as e:
            status, rh, text, err = None, {}, "", repr(e)
        dt = time.perf_counter() - t0
        try:
            data = json.loads(text) if text else None
        except ValueError:
            data = None
        rec = {
            "id": uuid.uuid4().hex[:12], "ts": time.time(), "test": test, "method": method, "url": url,
            "req_headers": {k: v for k, v in h.items() if k.lower() != "authorization"} | (
                {"Authorization": "<redacted>"} if "Authorization" in h else {}),
            "req_body": _body_for_log(body if body is not None else raw),
            "status": status, "resp_headers": rh, "latency_s": dt, "error": err,
            "resp_body": data if data is not None else _clip(text),
        }
        self.rec.write(stage, rec)
        return rec

    async def stream(self, stage, test, path, body, headers=None, stop_after_chunks=None):
        """POST with stream=true; records per-chunk arrival times."""
        url = BASE_URL + path
        h = self.headers(headers)
        t0 = time.perf_counter()
        events, status, rh, err, ttfb = [], None, {}, None, None
        try:
            async with self.http.stream("POST", url, headers=h, content=json.dumps(body)) as r:
                status, rh = r.status_code, dict(r.headers)
                ttfb = time.perf_counter() - t0
                if status != 200:
                    events.append({"t": ttfb, "raw": _clip((await r.aread()).decode(errors="replace"))})
                else:
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        t = time.perf_counter() - t0
                        try:
                            ev = json.loads(payload) if payload != "[DONE]" else "[DONE]"
                        except ValueError:
                            ev = {"unparsed": payload}
                        events.append({"t": t, "ev": ev})
                        if stop_after_chunks and len(events) >= stop_after_chunks:
                            break
        except httpx.HTTPError as e:
            err = repr(e)
        rec = {
            "id": uuid.uuid4().hex[:12], "ts": time.time(), "test": test, "method": "POST", "url": url,
            "req_headers": {k: v for k, v in h.items() if k.lower() != "authorization"},
            "req_body": _body_for_log(body), "status": status, "resp_headers": rh, "error": err,
            "ttfb_s": ttfb, "total_s": time.perf_counter() - t0, "events": events,
        }
        rec.update(stream_metrics(events))
        self.rec.write(stage, rec)
        return rec


def _delta_text(ev):
    if not isinstance(ev, dict):
        return None
    if ev.get("type") == "response.output_text.delta":
        return ev.get("delta")
    ch = ev.get("choices")
    if ch:
        return (ch[0].get("delta") or {}).get("content")
    return None


def stream_metrics(events):
    """TTFT = first event with non-empty text. ITL = gaps between text events."""
    text_t = [e["t"] for e in events if _delta_text(e.get("ev"))]
    usage, err = None, None
    for e in events:
        ev = e.get("ev")
        if isinstance(ev, dict):
            if ev.get("usage"):
                usage = ev["usage"]
            if ev.get("type") in ("response.completed", "response.incomplete", "response.failed"):
                usage = (ev.get("response") or {}).get("usage") or usage
                if ev["type"] == "response.failed":
                    err = (ev.get("response") or {}).get("error")
            if ev.get("error"):
                err = ev["error"]
    gaps = [b - a for a, b in zip(text_t, text_t[1:])]
    out_tokens = (usage or {}).get("completion_tokens", (usage or {}).get("output_tokens"))
    decode_s = (text_t[-1] - text_t[0]) if len(text_t) > 1 else None
    return {
        "ttft_s": text_t[0] if text_t else None,
        "text_events": len(text_t),
        "itl_s": gaps,
        "usage": usage,
        "stream_error": err,
        "decode_tok_s": (out_tokens - 1) / decode_s if out_tokens and decode_s else None,
        "text": "".join(_delta_text(e.get("ev")) or "" for e in events),
    }


def pct(values, p):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)
