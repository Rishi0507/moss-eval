"""Inference API tests: /v1/chat/completions, /v1/responses, /v1/models."""
import asyncio
import json
import os
import random
import time

from .core import PRICES, pct, usage_cost

S = "inference"
FAST = "moss/fastlane-1"
NOCACHE = {"X-Moss-Cache": "off"}
GAP = float(os.environ.get("MOSS_EVAL_GAP", "65"))
TOPICS = ["RabbitMQ", "Redis streams", "B-trees", "TCP slow start", "Raft", "bloom filters", "CRDTs",
          "consistent hashing", "LSM trees", "vector clocks", "QUIC", "gossip protocols", "WAL", "MVCC"]


def prompt(i):
    return f"[{i}-{random.randint(0, 10**9)}] In two sentences, explain {TOPICS[i % len(TOPICS)]} to a new backend engineer."


def chat(text, **kw):
    return {"model": FAST, "messages": [{"role": "user", "content": text}], **kw}


def body(r):
    return r["resp_body"] if isinstance(r.get("resp_body"), dict) else {}


def err(r):
    b = body(r).get("error") or {}
    return {"status": r["status"], "type": b.get("type"), "code": b.get("code"), "message": b.get("message"),
            "request_id": r["resp_headers"].get("x-moss-request-id"),
            "should_retry": r["resp_headers"].get("x-should-retry"),
            "retry_after": r["resp_headers"].get("retry-after")}


def bill(c, test, r, model=FAST):
    u = r.get("usage") or body(r).get("usage")
    if r.get("status") == 200 and u:
        c.ledger.add(test, usage_cost(model, u), {"model": model, "usage": u})


def summarize(vals):
    vals = [v for v in vals if v is not None]
    return {"n": len(vals), "p50": pct(vals, 50), "p95": pct(vals, 95), "p99": pct(vals, 99),
            "min": min(vals) if vals else None, "max": max(vals) if vals else None}


async def t_models(c):
    r = await c.request(S, "models", "GET", "/models")
    ids = [m["id"] for m in body(r).get("data", [])]
    documented = set(PRICES) | {
        "openai/gpt-6.1-terra", "openai/gpt-6.1-sol", "openai/gpt-6-astra", "anthropic/claude-sonnet-5.5",
        "anthropic/claude-opus-5.5", "anthropic/claude-fable-5.1", "google/gemini-3.8-flash",
        "google/gemini-4-argon", "z-ai/glm-5.3", "z-ai/glm-5.3-flash", "moonshotai/kimi-k3",
        "deepseek/deepseek-v4.1-flash-1017", "minimax/minimax-m3.1-flash", "qwen/qwen3.8-flash"}
    return {"status": r["status"], "count": len(ids), "missing_vs_docs": sorted(documented - set(ids)),
            "extra_vs_docs": sorted(set(ids) - documented),
            "ratelimit_headers": {k: v for k, v in r["resp_headers"].items() if k.startswith("x-ratelimit")}}


async def t_basic(c):
    out = {}
    r = await c.request(S, "chat_basic", "POST", "/chat/completions", chat(prompt(0), max_tokens=80), NOCACHE)
    bill(c, "chat_basic", r)
    b = body(r)
    out["chat"] = {"status": r["status"], "object": b.get("object"), "model": b.get("model"),
                   "n_choices": len(b.get("choices", [])), "finish": (b.get("choices") or [{}])[0].get("finish_reason"),
                   "usage": b.get("usage"), "headers": {k: v for k, v in r["resp_headers"].items()
                                                         if k.startswith(("x-moss", "x-ratelimit"))}}
    r = await c.request(S, "responses_basic", "POST", "/responses",
                        {"model": FAST, "input": prompt(1), "max_output_tokens": 80}, NOCACHE)
    bill(c, "responses_basic", r)
    b = body(r)
    out["responses"] = {"status": r["status"], "object": b.get("object"), "model": b.get("model"),
                        "status_field": b.get("status"), "usage": b.get("usage"),
                        "has_output_text_item": any(o.get("type") == "message" for o in b.get("output", []))}
    r = await c.request(S, "alias_moss", "POST", "/chat/completions",
                        {**chat(prompt(2), max_tokens=20), "model": "moss"}, NOCACHE)
    bill(c, "alias_moss", r)
    out["alias_moss_model"] = (r["status"], body(r).get("model"))
    r = await c.request(S, "no_model", "POST", "/chat/completions",
                        {"messages": [{"role": "user", "content": prompt(3)}], "max_tokens": 20}, NOCACHE)
    bill(c, "no_model", r)
    out["no_model_field"] = (r["status"], body(r).get("model"))
    return out


def t_openai_sdk(c):
    """Same calls through the official OpenAI Python SDK."""
    from openai import OpenAI
    from .core import BASE_URL
    cli = OpenAI(base_url=BASE_URL, api_key=c.key, default_headers=NOCACHE, max_retries=0)
    out = {}
    try:
        out["models_list"] = len(list(cli.models.list()))
        cc = cli.chat.completions.create(model=FAST, messages=[{"role": "user", "content": prompt(4)}], max_tokens=40)
        c.ledger.add("sdk_chat", usage_cost(FAST, cc.usage.model_dump()), {"usage": cc.usage.model_dump()})
        out["chat_text_ok"] = bool(cc.choices[0].message.content)
        rs = cli.responses.create(model=FAST, input=prompt(5), max_output_tokens=40)
        c.ledger.add("sdk_responses", usage_cost(FAST, rs.usage.model_dump()), {"usage": rs.usage.model_dump()})
        out["responses_output_text_ok"] = bool(rs.output_text)
        n, usage = 0, None
        for ch in cli.chat.completions.create(model=FAST, messages=[{"role": "user", "content": prompt(6)}],
                                              max_tokens=40, stream=True, stream_options={"include_usage": True}):
            n += 1
            usage = ch.usage or usage
        out["chat_stream_chunks"] = n
        out["chat_stream_usage"] = usage.model_dump() if usage else None
        if usage:
            c.ledger.add("sdk_stream", usage_cost(FAST, usage.model_dump()), {})
        with cli.responses.stream(model=FAST, input=prompt(7), max_output_tokens=40) as st:
            final = st.get_final_response()
        c.ledger.add("sdk_resp_stream", usage_cost(FAST, final.usage.model_dump()), {})
        out["responses_stream_final_ok"] = bool(final.output_text)
    except Exception as e:
        out["exception"] = f"{type(e).__name__}: {str(e)[:300]}"
    c.rec.write(S, {"test": "openai_sdk", "ts": time.time(), "result": out})
    return out


async def t_stream_latency(c, n=30):
    """Sequential streams, reply cache off, unique prompts. TTFT, ITL, decode tokens/s."""
    out = {}
    for api in ("chat", "responses"):
        recs = []
        for i in range(n):
            if api == "chat":
                b = chat(prompt(i), max_tokens=150, stream=True)
                r = await c.stream(S, f"stream_{api}", "/chat/completions", b, NOCACHE)
            else:
                b = {"model": FAST, "input": prompt(i), "max_output_tokens": 150, "stream": True}
                r = await c.stream(S, f"stream_{api}", "/responses", b, NOCACHE)
            bill(c, f"stream_{api}", r)
            recs.append(r)
        ok = [r for r in recs if r["status"] == 200 and r["ttft_s"] is not None]
        itl = [g for r in ok for g in r["itl_s"]]
        out[api] = {"ok": len(ok), "n": n, "ttft_s": summarize([r["ttft_s"] for r in ok]),
                    "ttfb_s": summarize([r["ttfb_s"] for r in ok]),
                    "itl_ms": {k: (v * 1000 if isinstance(v, float) else v) for k, v in summarize(itl).items()},
                    "decode_tok_s": summarize([r["decode_tok_s"] for r in ok]),
                    "total_s": summarize([r["total_s"] for r in ok]),
                    "usage_missing": sum(1 for r in ok if not r["usage"]),
                    "events_per_out_token": (sum(r["text_events"] for r in ok) /
                                             max(1, sum((r["usage"] or {}).get("completion_tokens",
                                                        (r["usage"] or {}).get("output_tokens", 0)) for r in ok)))}
    return out


async def t_nonstream_latency(c, n=60):
    lat, toks = [], []
    for i in range(n):
        r = await c.request(S, "nonstream_latency", "POST", "/chat/completions", chat(prompt(i), max_tokens=100), NOCACHE)
        bill(c, "nonstream_latency", r)
        if r["status"] == 200:
            lat.append(r["latency_s"])
            toks.append(body(r)["usage"]["completion_tokens"])
        await asyncio.sleep(0.6)
    return {"latency_s": summarize(lat), "completion_tokens_mean": sum(toks) / max(1, len(toks))}


async def t_caches(c):
    """Reply cache (same request twice, cache on) and prefix cache (long shared system prompt)."""
    out = {}
    b = chat("What is 17 * 23? Answer with the number only.", max_tokens=10)
    a1 = await c.request(S, "reply_cache_1", "POST", "/chat/completions", b)
    a2 = await c.request(S, "reply_cache_2", "POST", "/chat/completions", b)
    bill(c, "reply_cache", a1)
    bill(c, "reply_cache", a2)
    out["reply_cache"] = {"first": (a1["latency_s"], body(a1).get("usage")),
                          "second": (a2["latency_s"], body(a2).get("usage")),
                          "same_text": body(a1).get("choices") == body(a2).get("choices")}
    system = "You are a support agent for a logistics company. " + " ".join(
        f"Policy {k}: parcels in zone {k} ship within {k % 5 + 1} business days and cost {k * 3} rupees." for k in range(250))
    rows = []
    for i in range(6):
        r = await c.stream(S, "prefix_cache", "/chat/completions",
                           {"model": FAST, "stream": True, "max_tokens": 30,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": f"[{random.random()}] How long does zone {i + 7} take?"}]},
                           NOCACHE)
        bill(c, "prefix_cache", r)
        u = r["usage"] or {}
        rows.append({"ttft_s": r["ttft_s"], "prompt_tokens": u.get("prompt_tokens"),
                     "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens")})
    out["prefix_cache"] = rows
    return out


async def t_concurrency(c, levels=(1, 4, 16, 64)):
    """For each level, fire max(8, 2*level) requests with that many in flight. Gap of 65 s resets the RPM window."""
    out = {}
    for li, lvl in enumerate(levels):
        if li:
            await asyncio.sleep(GAP)
        total = max(8, 2 * lvl)
        c.ledger.check(total * usage_cost(FAST, {"prompt_tokens": 60, "completion_tokens": 64}))
        sem = asyncio.Semaphore(lvl)

        async def one(i):
            async with sem:
                r = await c.stream(S, f"concurrency_{lvl}", "/chat/completions",
                                   chat(prompt(i), max_tokens=64, stream=True), NOCACHE)
                bill(c, f"concurrency_{lvl}", r)
                return r

        t0 = time.perf_counter()
        recs = await asyncio.gather(*(one(i) for i in range(total)))
        wall = time.perf_counter() - t0
        ok = [r for r in recs if r["status"] == 200 and not r["stream_error"]]
        codes = {}
        for r in recs:
            codes[str(r["status"])] = codes.get(str(r["status"]), 0) + 1
        out_tok = sum((r["usage"] or {}).get("completion_tokens", 0) for r in ok)
        out[lvl] = {"requests": total, "ok": len(ok), "status_counts": codes, "wall_s": wall,
                    "req_per_s": len(ok) / wall, "out_tok_per_s": out_tok / wall,
                    "ttft_s": summarize([r["ttft_s"] for r in ok]),
                    "retry_after": sorted({r["resp_headers"].get("retry-after") for r in recs if r["status"] == 429} - {None})}
    return out


async def t_rate_limit(c):
    """Burst of 15 tiny requests at once; docs say burst 10 on fastlane-1. Then record headers."""
    await asyncio.sleep(GAP)
    recs = await asyncio.gather(*(c.request(S, "burst15", "POST", "/chat/completions",
                                            chat(prompt(i), max_tokens=1), NOCACHE) for i in range(15)))
    for r in recs:
        bill(c, "burst15", r)
    codes = [r["status"] for r in recs]
    hdrs = [{k: v for k, v in r["resp_headers"].items() if k.startswith("x-ratelimit") or k == "retry-after"}
            for r in sorted(recs, key=lambda r: r["ts"])]
    e429 = [err(r) for r in recs if r["status"] == 429][:2]
    return {"status_counts": {s: codes.count(s) for s in set(codes)}, "headers_in_order": hdrs, "sample_429": e429}


async def t_errors(c):
    """Each case: what the docs say vs what came back."""
    long_text = "lorem " * 280_000
    cases = [
        ("bad_model", "/chat/completions", chat("hi", model="moss/not-a-model"), "400 model_not_found"),
        ("vendor_name_without_prefix", "/chat/completions", chat("hi", model="gpt-6-luna"), "400 missing_provider_key"),
        ("empty_messages", "/chat/completions", {"model": FAST, "messages": []}, "400"),
        ("missing_messages", "/chat/completions", {"model": FAST}, "400"),
        ("bad_role", "/chat/completions", {"model": FAST, "messages": [{"role": "wizard", "content": "hi"}]}, "400"),
        ("temperature_5", "/chat/completions", chat("hi", temperature=5, max_tokens=5), "400 (OpenAI range 0-2)"),
        ("temperature_neg", "/chat/completions", chat("hi", temperature=-1, max_tokens=5), "400"),
        ("max_tokens_0", "/chat/completions", chat("hi", max_tokens=0), "400"),
        ("max_tokens_neg", "/chat/completions", chat("hi", max_tokens=-5), "400"),
        ("max_tokens_huge", "/chat/completions", chat("hi", max_tokens=10_000_000), "400 or clamp"),
        ("n_2", "/chat/completions", chat("hi", n=2, max_tokens=5), "docs: one choice"),
        ("tools_not_list", "/chat/completions", chat("hi", tools={"type": "function"}), "400 per docs"),
        ("unknown_field_chat", "/chat/completions", chat("hi", max_tokens=5, frobnicate=True), "docs: passed to model"),
        ("unknown_field_responses", "/responses", {"model": FAST, "input": "hi", "frobnicate": True}, "400 unsupported_parameter"),
        ("previous_response_id", "/responses", {"model": FAST, "input": "hi", "previous_response_id": "resp_1"}, "400 unsupported_parameter"),
        ("background_true", "/responses", {"model": FAST, "input": "hi", "background": True}, "400 unsupported_parameter"),
        ("responses_empty_input", "/responses", {"model": FAST, "input": ""}, "400"),
        ("web_search_tool", "/responses", {"model": FAST, "input": "hi", "tools": [{"type": "web_search"}]}, "400 unsupported_parameter"),
        ("anthropic_temperature", "/chat/completions", chat("hi", model="anthropic/claude-haiku-5.5", temperature=0.2, max_tokens=5), "400 unsupported_parameter"),
        ("openai_seed", "/chat/completions", chat("hi", model="openai/gpt-6-luna", seed=1, max_tokens=5), "400 unsupported_parameter"),
        ("anthropic_temperature_1_is_unset", "/chat/completions", chat("hi", model="anthropic/claude-haiku-5.5", temperature=1, max_tokens=5), "200 (1 counts as unset)"),
        ("too_many_indexes", "/chat/completions", chat("hi", max_tokens=5), "400 (33 indexes)"),
        ("foreign_index", "/chat/completions", chat("hi", max_tokens=5), "403"),
        ("context_over_262k", "/chat/completions", chat(long_text, max_tokens=5), "400 context_length_exceeded"),
    ]
    extra_headers = {
        "too_many_indexes": {"X-Moss-Indexes": ",".join(f"i{k}" for k in range(33))},
        "foreign_index": {"X-Moss-Indexes": "definitely-not-my-index-xyz"},
    }
    out = {}
    for name, path, b, expect in cases:
        r = await c.request(S, f"err_{name}", "POST", path, b, {**NOCACHE, **extra_headers.get(name, {})})
        model = b.get("model", FAST)
        bill(c, f"err_{name}", r, model if model in PRICES else FAST)
        out[name] = {"expected": expect, **err(r), "latency_s": round(r["latency_s"], 3)}
        if r["status"] == 200:
            out[name]["usage"] = body(r).get("usage")
            out[name]["n_choices"] = len(body(r).get("choices", []))
    raw_cases = [
        ("malformed_json", "{\"model\": \"moss/fastlane-1\", \"messages\": [", "400 JSON error"),
        ("body_over_4mb", json.dumps(chat("x " * 2_200_000, max_tokens=1)), "413"),
        ("wrong_content_type_text", None, "400 or 415"),
    ]
    for name, raw, expect in raw_cases:
        if name == "wrong_content_type_text":
            r = await c.request(S, f"err_{name}", "POST", "/chat/completions", raw=json.dumps(chat("hi", max_tokens=3)),
                                headers={"Content-Type": "text/plain", **NOCACHE})
        else:
            r = await c.request(S, f"err_{name}", "POST", "/chat/completions", raw=raw, headers=NOCACHE)
        bill(c, f"err_{name}", r)
        out[name] = {"expected": expect, **err(r), "latency_s": round(r["latency_s"], 3)}
    await asyncio.sleep(GAP)  # let the input-token window recover after the 280k prompt
    return out


async def t_limits_semantics(c):
    out = {}
    r = await c.request(S, "max_tokens_5", "POST", "/chat/completions", chat(prompt(9), max_tokens=5), NOCACHE)
    bill(c, "max_tokens_5", r)
    b = body(r)
    out["max_tokens_5"] = {"completion_tokens": (b.get("usage") or {}).get("completion_tokens"),
                           "finish_reason": (b.get("choices") or [{}])[0].get("finish_reason")}
    r = await c.stream(S, "max_output_tokens_5_stream", "/responses",
                       {"model": FAST, "input": prompt(10), "max_output_tokens": 5, "stream": True}, NOCACHE)
    bill(c, "max_output_tokens_5_stream", r)
    out["responses_max_output_5_last_event"] = (r["events"][-1]["ev"].get("type")
                                                if r["events"] and isinstance(r["events"][-1]["ev"], dict) else None)
    r = await c.request(S, "stop_seq", "POST", "/chat/completions",
                        chat("Count from 1 to 20 separated by commas.", max_tokens=80, stop=["7"]), NOCACHE)
    bill(c, "stop_seq", r)
    txt = ((body(r).get("choices") or [{}])[0].get("message") or {}).get("content")
    out["stop_7"] = {"status": r["status"], "text": txt, "contains_7": "7" in (txt or "")}
    r1 = await c.request(S, "sysprompt_on", "POST", "/chat/completions", chat("ok", max_tokens=1), NOCACHE)
    r2 = await c.request(S, "sysprompt_off", "POST", "/chat/completions", chat("ok", max_tokens=1),
                         {**NOCACHE, "X-Moss-System-Prompt": "off"})
    bill(c, "sysprompt", r1)
    bill(c, "sysprompt", r2)
    out["min_prompt_tokens"] = {"project_prompt_on": (body(r1).get("usage") or {}).get("prompt_tokens"),
                                "project_prompt_off": (body(r2).get("usage") or {}).get("prompt_tokens")}
    return out


async def t_usage_consistency(c):
    """Same prompt streamed and non-streamed; compare usage to a local tokenizer and to each other."""
    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")
    text = "Summarize the CAP theorem in exactly three bullet points."
    rows = []
    for mode in ("plain", "stream"):
        b = chat(text, max_tokens=120, temperature=0)
        if mode == "stream":
            r = await c.stream(S, "usage_stream", "/chat/completions", {**b, "stream": True}, NOCACHE)
            u, out_text = r["usage"], r["text"]
        else:
            r = await c.request(S, "usage_plain", "POST", "/chat/completions", b, NOCACHE)
            u = body(r).get("usage")
            out_text = ((body(r).get("choices") or [{}])[0].get("message") or {}).get("content", "")
        bill(c, f"usage_{mode}", r)
        u = u or {}
        rows.append({"mode": mode, "prompt_tokens": u.get("prompt_tokens"),
                     "completion_tokens": u.get("completion_tokens"), "total_tokens": u.get("total_tokens"),
                     "sum_ok": (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0) == u.get("total_tokens"),
                     "o200k_output_tokens": len(enc.encode(out_text or "")),
                     "o200k_prompt_text_tokens": len(enc.encode(text))})
    return rows


async def t_determinism(c, n=5):
    out = {}
    q = "Write one sentence about the ocean."
    for label, extra in (("temp0", {"temperature": 0}), ("temp0_seed42", {"temperature": 0, "seed": 42}),
                         ("temp1_seed42", {"temperature": 1, "seed": 42})):
        texts = []
        for _ in range(n):
            r = await c.request(S, f"determinism_{label}", "POST", "/chat/completions",
                                chat(q, max_tokens=40, **extra), NOCACHE)
            bill(c, f"determinism_{label}", r)
            texts.append(((body(r).get("choices") or [{}])[0].get("message") or {}).get("content") if r["status"] == 200
                         else f"HTTP {r['status']}")
        out[label] = {"unique_outputs": len(set(texts)), "n": n, "samples": list(dict.fromkeys(texts))[:3]}
    return out


WEATHER_TOOL = {"type": "function", "function": {
    "name": "get_weather", "description": "Current weather for a city",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"},
                                                   "unit": {"type": "string", "enum": ["c", "f"]}},
                   "required": ["city", "unit"], "additionalProperties": False}}}


async def t_tools_json(c):
    out = {}
    msgs = [{"role": "user", "content": "What's the weather in Mumbai in celsius?"}]
    r = await c.request(S, "tool_call", "POST", "/chat/completions",
                        {"model": FAST, "messages": msgs, "tools": [WEATHER_TOOL], "max_tokens": 200}, NOCACHE)
    bill(c, "tool_call", r)
    ch = (body(r).get("choices") or [{}])[0]
    calls = (ch.get("message") or {}).get("tool_calls") or []
    args_ok = None
    if calls:
        try:
            a = json.loads(calls[0]["function"]["arguments"])
            args_ok = a.get("city", "").lower().startswith("mumbai") and a.get("unit") == "c"
        except (ValueError, KeyError):
            args_ok = False
    out["tool_call"] = {"status": r["status"], "finish_reason": ch.get("finish_reason"), "n_calls": len(calls),
                        "args_valid": args_ok}
    if calls:
        msgs2 = msgs + [ch["message"], {"role": "tool", "tool_call_id": calls[0]["id"],
                                         "content": json.dumps({"temp_c": 29, "sky": "haze"})}]
        r2 = await c.request(S, "tool_roundtrip", "POST", "/chat/completions",
                             {"model": FAST, "messages": msgs2, "tools": [WEATHER_TOOL], "max_tokens": 80}, NOCACHE)
        bill(c, "tool_roundtrip", r2)
        txt = ((body(r2).get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        out["tool_roundtrip"] = {"status": r2["status"], "uses_29": "29" in txt}
    r = await c.request(S, "tool_choice_required", "POST", "/chat/completions",
                        {"model": FAST, "messages": [{"role": "user", "content": "Say hello."}],
                         "tools": [WEATHER_TOOL], "tool_choice": "required", "max_tokens": 100}, NOCACHE)
    bill(c, "tool_choice_required", r)
    ch = (body(r).get("choices") or [{}])[0]
    out["tool_choice_required"] = {"status": r["status"], "finish_reason": ch.get("finish_reason"),
                                   "n_calls": len((ch.get("message") or {}).get("tool_calls") or [])}
    rs = await c.stream(S, "tool_call_stream", "/responses",
                        {"model": FAST, "input": "Weather in Pune in f?", "stream": True, "max_output_tokens": 200,
                         "tools": [{"type": "function", **WEATHER_TOOL["function"]}]}, NOCACHE)
    bill(c, "tool_call_stream", rs)
    types = [e["ev"].get("type") for e in rs["events"] if isinstance(e["ev"], dict)]
    out["responses_tool_stream_events"] = sorted(set(types))
    schema = {"type": "object", "properties": {"name": {"type": "string"}, "year": {"type": "integer"},
                                               "langs": {"type": "array", "items": {"type": "string"}}},
              "required": ["name", "year", "langs"], "additionalProperties": False}
    ok = 0
    for i in range(5):
        r = await c.request(S, "json_schema", "POST", "/chat/completions",
                            chat(f"[{i}] Give a famous open source project as JSON.", max_tokens=120,
                                 response_format={"type": "json_schema",
                                                  "json_schema": {"name": "proj", "schema": schema, "strict": True}}),
                            NOCACHE)
        bill(c, "json_schema", r)
        try:
            d = json.loads(body(r)["choices"][0]["message"]["content"])
            ok += set(d) == {"name", "year", "langs"} and isinstance(d["year"], int)
        except (KeyError, ValueError, TypeError, IndexError):
            pass
    out["json_schema_valid"] = f"{ok}/5"
    r = await c.request(S, "json_object", "POST", "/chat/completions",
                        chat("Return a JSON object with key a=1.", max_tokens=30,
                             response_format={"type": "json_object"}), NOCACHE)
    bill(c, "json_object", r)
    out["json_object_status"] = r["status"]
    return out


async def t_vendor_compare(c, n=5):
    """Short TTFT comparison against two cheap vendor models on the Moss key."""
    out = {}
    for model in ("anthropic/claude-haiku-5.5", "openai/gpt-6-luna", FAST):
        recs = []
        for i in range(n):
            r = await c.stream(S, f"vendor_{model}", "/chat/completions",
                               {**chat(prompt(i), max_tokens=80, stream=True), "model": model}, NOCACHE)
            bill(c, f"vendor_{model}", r, model)
            recs.append(r)
        ok = [r for r in recs if r["status"] == 200 and r["ttft_s"]]
        out[model] = {"ok": len(ok), "ttft_s": summarize([r["ttft_s"] for r in ok]),
                      "errors": [r["events"][0].get("raw", "")[:200] for r in recs if r["status"] != 200][:2]}
    return out


async def t_stream_abort(c):
    """Client drops the stream after 3 events; then a normal call must still work."""
    r = await c.stream(S, "stream_abort", "/chat/completions",
                       chat("Write 300 words about compilers.", max_tokens=400, stream=True), NOCACHE, stop_after_chunks=3)
    c.ledger.add("stream_abort", usage_cost(FAST, {"prompt_tokens": 30, "completion_tokens": 400}), {"note": "worst case"})
    r2 = await c.request(S, "after_abort", "POST", "/chat/completions", chat("ping", max_tokens=3), NOCACHE)
    bill(c, "after_abort", r2)
    return {"aborted_after_events": len(r["events"]), "next_call_status": r2["status"]}


TESTS = [
    ("models", t_models), ("basic", t_basic), ("openai_sdk", None), ("errors", t_errors),
    ("limits_semantics", t_limits_semantics), ("usage_consistency", t_usage_consistency),
    ("determinism", t_determinism), ("tools_json", t_tools_json), ("caches", t_caches),
    ("stream_latency", t_stream_latency), ("nonstream_latency", t_nonstream_latency),
    ("vendor_compare", t_vendor_compare), ("stream_abort", t_stream_abort),
    ("concurrency", t_concurrency), ("rate_limit", t_rate_limit),
]


async def run(c, only=None):
    results = {}
    for name, fn in TESTS:
        if only and name not in only:
            continue
        c.ledger.check()
        print(f"  inference/{name} ... spent so far ${c.ledger.spent:.4f}", flush=True)
        try:
            if name == "openai_sdk":
                results[name] = await asyncio.to_thread(t_openai_sdk, c)
            else:
                results[name] = await fn(c)
        except Exception as e:
            if type(e).__name__ == "BudgetExceeded":
                raise
            results[name] = {"harness_exception": f"{type(e).__name__}: {e}"}
    return results
