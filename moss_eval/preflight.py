"""Probes that need no key and cost nothing."""
from .core import BASE_URL, pct

S = "preflight"


async def run(c):
    out = {}

    # network floor: a 401 does no model work, so its round trip is our RTT to Moss
    rtts = []
    for i in range(20):
        r = await c.request(S, "rtt_401", "POST", "/chat/completions", body={}, auth=None)
        rtts.append(r["latency_s"])
    out["rtt_401_s"] = {"p50": pct(rtts[1:], 50), "p95": pct(rtts[1:], 95), "n": len(rtts) - 1}
    rtts = []
    for i in range(20):
        r = await c.request(S, "rtt_401_tasks", "POST", "/tasks", body={}, auth=None)
        rtts.append(r["latency_s"])
    out["rtt_401_tasks_s"] = {"p50": pct(rtts[1:], 50), "p95": pct(rtts[1:], 95), "n": len(rtts) - 1}

    r = await c.request(S, "models_no_auth", "GET", "/models", auth=None)
    out["models_no_auth"] = {"status": r["status"], "count": len((r["resp_body"] or {}).get("data", []))
                             if isinstance(r["resp_body"], dict) else None}
    r = await c.request(S, "models_bad_auth", "GET", "/models", auth="Bearer not:real")
    out["models_bad_auth_status"] = r["status"]

    auth_cases = {
        "missing": None,
        "no_colon": "Bearer abcdef",
        "empty_parts": "Bearer :",
        "wrong_pair": "Bearer proj_000:key_000",
        "basic_scheme": "Basic dXNlcjpwYXNz",
        "lowercase_bearer": "bearer a:b",
    }
    out["auth"] = {}
    for name, a in auth_cases.items():
        for path in ("/chat/completions", "/responses", "/tasks"):
            r = await c.request(S, f"auth_{name}", "POST", path, body={"model": "moss/fastlane-1"}, auth=a)
            b = r["resp_body"] if isinstance(r["resp_body"], dict) else {}
            out["auth"][f"{name} {path}"] = (r["status"], (b.get("error") or {}).get("message"))

    # same bad credentials with a valid body, to see whether body checks run before auth
    valid = {"/chat/completions": {"model": "moss/fastlane-1", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
             "/responses": {"model": "moss/fastlane-1", "input": "hi", "max_output_tokens": 16}}
    out["auth_valid_body"] = {}
    for name, a in (("missing", None), ("wrong_pair", "Bearer proj_000:key_000")):
        for path, vb in valid.items():
            r = await c.request(S, f"auth_valid_body_{name}", "POST", path, body=vb, auth=a)
            b = r["resp_body"] if isinstance(r["resp_body"], dict) else {}
            out["auth_valid_body"][f"{name} {path}"] = (r["status"], (b.get("error") or {}).get("message"))

    r = await c.request(S, "malformed_json_no_auth", "POST", "/chat/completions", raw="{not json", auth=None)
    out["malformed_json_no_auth"] = r["status"]

    for path in ("/tasks", "/models", "/nope"):
        r = await c.request(S, "get_with_body", "GET", path, raw="{}", auth=None)
        out[f"get_with_body {path}"] = (r["status"], r["resp_headers"].get("content-type"))
    r = await c.request(S, "unknown_route", "GET", "/nope", auth=None)
    out["unknown_route"] = (r["status"], r["resp_headers"].get("content-type"))

    r = await c.request(S, "cors_preflight", "OPTIONS", "/chat/completions", auth=None, headers={
        "Origin": "https://example.com", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,x-moss-indexes"})
    out["cors_preflight"] = (r["status"], {k: v for k, v in r["resp_headers"].items()
                                           if k.lower().startswith("access-control")})

    out["base_url"] = BASE_URL
    return out
