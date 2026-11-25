"""Tasks API tests: /v1/tasks lifecycle, validation, idempotency, cancel, limits."""
import asyncio
import json
import time
import uuid

S = "tasks"
CREATED = set()
TERMINAL = {"completed", "failed", "cancelled"}
FAKE_ID = "task_" + "0" * 32
LONG_GOAL = ("Open https://en.wikipedia.org/wiki/Special:Random twenty times. For each page write down its title. "
             "Then return all twenty titles as a numbered list.")


def b(r):
    return r["resp_body"] if isinstance(r.get("resp_body"), dict) else {}


def e(r):
    x = b(r).get("error") or {}
    return {"status": r["status"], "code": x.get("code"), "type": x.get("type"), "message": (x.get("message") or "")[:200]}


def task_body(goal="Return the text of the main heading on this page.", start="https://example.com", **kw):
    d = {"goal": goal, "environment": {"type": "browser", "start_url": start}, "model": "moss-fast",
         "limits": {"max_runtime_seconds": 180, "max_cost_usd": 0.05}}
    d.update(kw)
    return d


async def create(c, test, body=None, headers=None, raw=None):
    r = await c.request(S, test, "POST", "/tasks", body, headers, raw=raw)
    if r["status"] in (200, 201, 202) and b(r).get("id"):
        CREATED.add(b(r)["id"])
    return r


async def get(c, tid, test="get"):
    return await c.request(S, test, "GET", f"/tasks/{tid}")


async def cancel(c, tid, test="cancel"):
    return await c.request(S, test, "POST", f"/tasks/{tid}/cancel", body={})


async def wait(c, tid, timeout=900, every=2.0, test="poll"):
    """Polls until terminal. Returns final task and first-seen time of each status."""
    t0, seen, last = time.perf_counter(), {}, None
    while time.perf_counter() - t0 < timeout:
        r = await get(c, tid, test)
        last = b(r)
        st = last.get("status")
        seen.setdefault(st, round(time.perf_counter() - t0, 2))
        if st in TERMINAL:
            break
        await asyncio.sleep(every)
    return last, seen


def brief(t):
    u = t.get("usage") or {}
    return {"status": t.get("status"), "error": t.get("error"), "result": t.get("result"),
            "verification": t.get("verification"), "cost": u.get("cost"), "steps": u.get("steps"),
            "model_calls": u.get("model_calls"), "browser_seconds": u.get("browser_seconds"),
            "created_at": t.get("created_at"), "started_at": t.get("started_at"), "finished_at": t.get("finished_at")}


async def t_validation(c):
    big_schema = {"type": "object", "properties": {f"p{i}": {"type": "string", "description": "x" * 200} for i in range(100)}}
    cases = [
        ("missing_goal", {"environment": {"type": "browser"}}),
        ("empty_goal", task_body(goal="")),
        ("goal_20001_chars", task_body(goal="a" * 20001)),
        ("missing_environment", {"goal": "x"}),
        ("env_type_desktop", {**task_body(), "environment": {"type": "desktop"}}),
        ("start_url_ftp", task_body(start="ftp://example.com/file")),
        ("start_url_javascript", task_body(start="javascript:alert(1)")),
        ("start_url_not_a_url", task_body(start="example dot com")),
        ("runtime_59", task_body(limits={"max_runtime_seconds": 59, "max_cost_usd": 0.05})),
        ("runtime_7201", task_body(limits={"max_runtime_seconds": 7201, "max_cost_usd": 0.05})),
        ("runtime_string", task_body(limits={"max_runtime_seconds": "600", "max_cost_usd": 0.05})),
        ("runtime_float", task_body(limits={"max_runtime_seconds": 90.5, "max_cost_usd": 0.05})),
        ("cost_0_009", task_body(limits={"max_runtime_seconds": 120, "max_cost_usd": 0.009})),
        ("cost_50_01", task_body(limits={"max_runtime_seconds": 120, "max_cost_usd": 50.01})),
        ("cost_negative", task_body(limits={"max_runtime_seconds": 120, "max_cost_usd": -1})),
        ("limits_unknown_key", task_body(limits={"max_runtime_seconds": 120, "max_cost_usd": 0.05, "max_steps": 3})),
        ("effort_max", task_body(effort="max")),
        ("model_unknown", task_body(model="gpt-4")),
        ("schema_type_array", task_body(output_schema={"type": "array", "items": {"type": "string"}})),
        ("schema_over_20000_bytes", task_body(output_schema=big_schema)),
        ("schema_invalid_jsonschema", task_body(output_schema={"type": "object", "properties": {"a": {"type": "banana"}}})),
        ("metadata_over_4000_bytes", task_body(metadata={"k": "v" * 4100})),
        ("metadata_list", task_body(metadata=["a"])),
        ("unknown_top_field", task_body(priority="high")),
    ]
    out = {}
    for name, body in cases:
        r = await create(c, f"val_{name}", body)
        out[name] = e(r)
        if b(r).get("id"):
            out[name]["CREATED_TASK"] = b(r)["id"]
            await cancel(c, b(r)["id"], f"val_{name}_cleanup")
    r = await create(c, "val_malformed_json", raw='{"goal": "x", "environment": {"type": "browser"')
    out["malformed_json"] = e(r)
    r = await create(c, "val_body_over_256k", raw=json.dumps(task_body(goal="g", metadata=None) | {"goal": "a" * 270_000}))
    out["body_over_256KiB"] = e(r)
    for key, label in (("k" * 256, "idem_key_256_chars"), ("has space", "idem_key_space"), ("ключ", "idem_key_non_ascii"),
                       ("", "idem_key_empty")):
        try:
            r = await create(c, f"val_{label}", task_body(), {"Idempotency-Key": key})
            out[label] = e(r)
            if b(r).get("id"):
                out[label]["CREATED_TASK"] = b(r)["id"]
                await cancel(c, b(r)["id"], f"val_{label}_cleanup")
        except Exception as ex:
            out[label] = {"client_side_error": f"{type(ex).__name__}: {ex}"}
    return out


async def t_routes(c):
    out = {}
    out["get_unknown"] = e(await get(c, FAKE_ID, "get_unknown"))
    out["get_malformed_id"] = e(await get(c, "abc", "get_malformed"))
    out["cancel_unknown"] = e(await cancel(c, FAKE_ID, "cancel_unknown"))
    out["files_unknown"] = e(await c.request(S, "files_unknown", "GET", f"/tasks/{FAKE_ID}/files"))
    out["list_tasks_undocumented"] = e(await c.request(S, "list_tasks", "GET", "/tasks"))
    out["path_traversal_file"] = e(await c.request(S, "files_traversal", "GET", f"/tasks/{FAKE_ID}/files/..%2F..%2Fetc%2Fpasswd"))
    return out


async def t_lifecycle(c):
    """Happy path with a schema, files before and after finish."""
    out = {}
    schema = {"type": "object", "properties": {"heading": {"type": "string"}}, "required": ["heading"]}
    for model in ("moss-fast", "moss-balanced"):
        t0 = time.perf_counter()
        r = await create(c, f"life_create_{model}", task_body(model=model, output_schema=schema,
                                                             limits={"max_runtime_seconds": 300, "max_cost_usd": 0.20},
                                                             metadata={"suite": "moss-eval", "case": "lifecycle"}))
        create_s = time.perf_counter() - t0
        tid = b(r).get("id")
        if not tid:
            out[model] = {"create_failed": e(r)}
            continue
        early_files = e(await c.request(S, "life_files_early", "GET", f"/tasks/{tid}/files"))
        final, seen = await wait(c, tid, test=f"life_poll_{model}")
        files = await c.request(S, "life_files", "GET", f"/tasks/{tid}/files")
        listing = b(files).get("data") or []
        dl = None
        if listing:
            p = listing[0]["path"]
            d = await c.request(S, "life_file_download", "GET", f"/tasks/{tid}/files/{p}")
            dl = {"path": p, "status": d["status"], "content_type": d["resp_headers"].get("content-type"),
                  "bytes_listed": listing[0].get("bytes"),
                  "content_length": d["resp_headers"].get("content-length")}
        out[model] = {"create_status": r["status"], "create_latency_s": round(create_s, 3),
                      "initial_status": b(r).get("status"), "status_first_seen_s": seen,
                      "files_before_finish": early_files, "files_after": {"status": files["status"], "count": len(listing),
                                                                           "sample": listing[:5]},
                      "download": dl, "final": brief(final), "echo_metadata": final.get("metadata")}
        out[model]["cancel_after_finish"] = b(await cancel(c, tid, "cancel_finished")).get("status")
    return out


async def t_schema_mismatch(c):
    schema = {"type": "object", "properties": {"n": {"type": "integer", "minimum": 10, "maximum": 5}}, "required": ["n"]}
    r = await create(c, "schema_unsat", task_body(goal="Count the links on this page and return the count as n.",
                                                  output_schema=schema))
    if not b(r).get("id"):
        return {"create": e(r)}
    final, seen = await wait(c, b(r)["id"], test="schema_unsat_poll")
    return {"create_status": r["status"], "final": brief(final), "seen": seen}


async def t_cancel(c):
    out = {}
    r = await create(c, "cancel_queued_create", task_body(goal=LONG_GOAL, start="https://en.wikipedia.org"))
    tid = b(r).get("id")
    if tid:
        c1 = await cancel(c, tid, "cancel_queued")
        c2 = await cancel(c, tid, "cancel_queued_again")
        await asyncio.sleep(5)
        g = b(await get(c, tid, "cancel_queued_after"))
        out["immediate"] = {"status_at_create": b(r).get("status"), "cancel_resp_status": b(c1).get("status"),
                            "cancel_requested": b(c1).get("cancel_requested"), "second_cancel_http": c2["status"],
                            "final": brief(g)}
    r = await create(c, "cancel_running_create",
                     task_body(goal=LONG_GOAL, start="https://en.wikipedia.org",
                               limits={"max_runtime_seconds": 300, "max_cost_usd": 0.10}))
    tid = b(r).get("id")
    if tid:
        t0 = time.perf_counter()
        st = None
        while time.perf_counter() - t0 < 300:
            st = b(await get(c, tid, "cancel_running_wait")).get("status")
            if st != "queued":
                break
            await asyncio.sleep(1)
        await asyncio.sleep(15)
        before = b(await get(c, tid, "cancel_running_before"))
        tc = time.perf_counter()
        cr = await cancel(c, tid, "cancel_running")
        final, seen = await wait(c, tid, timeout=300, every=1, test="cancel_running_poll")
        await asyncio.sleep(20)
        later = b(await get(c, tid, "cancel_running_later"))
        out["running"] = {"status_before": before.get("status"), "cost_before": (before.get("usage") or {}).get("cost"),
                          "cancel_http": cr["status"], "cancel_requested": b(cr).get("cancel_requested"),
                          "seconds_to_cancelled": round(time.perf_counter() - tc, 1), "seen": seen,
                          "final": brief(final), "cost_20s_later": (later.get("usage") or {}).get("cost"),
                          "result_after_cancel": later.get("result")}
    return out


async def t_limits(c):
    out = {}
    r = await create(c, "budget_create", task_body(goal=LONG_GOAL, start="https://en.wikipedia.org",
                                                   limits={"max_runtime_seconds": 600, "max_cost_usd": 0.01}))
    if b(r).get("id"):
        final, seen = await wait(c, b(r)["id"], test="budget_poll")
        cost = ((final.get("usage") or {}).get("cost") or {})
        out["budget_0_01"] = {"final": brief(final), "seen": seen,
                              "model_usd_over_cap": (cost.get("model_usd") or 0) - 0.01}
    else:
        out["budget_0_01"] = e(r)
    r = await create(c, "time_create", task_body(goal=LONG_GOAL, start="https://en.wikipedia.org",
                                                 limits={"max_runtime_seconds": 60, "max_cost_usd": 0.20}))
    if b(r).get("id"):
        final, seen = await wait(c, b(r)["id"], test="time_poll")
        out["runtime_60"] = {"final": brief(final), "seen": seen}
    else:
        out["runtime_60"] = e(r)
    r = await create(c, "dead_host", task_body(goal="Return the page title.", start="https://moss-eval-nonexistent.invalid/"))
    if b(r).get("id"):
        final, seen = await wait(c, b(r)["id"], test="dead_host_poll")
        out["unreachable_start_url"] = {"final": brief(final), "seen": seen}
    r = await create(c, "cost_cap_above_balance", task_body(limits={"max_runtime_seconds": 120, "max_cost_usd": 50}))
    out["max_cost_50_with_10_usd_credit"] = e(r) | {"created": bool(b(r).get("id"))}
    if b(r).get("id"):
        await cancel(c, b(r)["id"], "cost_cap_cleanup")
    r = await create(c, "byok_fake_with_moss_model", task_body(), {"X-Moss-Provider-Key": "sk-moss-eval-fake-000"})
    out["byok_header_with_moss_fast"] = e(r) | {"created": bool(b(r).get("id"))}
    if b(r).get("id"):
        await cancel(c, b(r)["id"], "byok_cleanup")
    r = await create(c, "fastlane_as_task_model", task_body(model="moss/fastlane-1"))
    out["model_fastlane_1"] = e(r) | {"created": bool(b(r).get("id"))}
    if b(r).get("id"):
        final, _ = await wait(c, b(r)["id"], test="fastlane_task_poll")
        out["model_fastlane_1"]["final"] = brief(final)
    return out


async def t_idempotency(c):
    out = {}
    key = f"moss-eval-{uuid.uuid4().hex}"
    body = task_body(goal="Return the main heading.", limits={"max_runtime_seconds": 120, "max_cost_usd": 0.03})
    r1 = await create(c, "idem_first", body, {"Idempotency-Key": key})
    r2 = await create(c, "idem_replay", body, {"Idempotency-Key": key})
    reordered = json.dumps(dict(reversed(list(body.items()))))
    r3 = await create(c, "idem_reordered_json", raw=reordered, headers={"Idempotency-Key": key})
    r4 = await create(c, "idem_other_body", {**body, "goal": "Different goal."}, {"Idempotency-Key": key})
    out["sequential"] = {
        "first": (r1["status"], b(r1).get("id")),
        "replay": (r2["status"], b(r2).get("id"), r2["resp_headers"].get("idempotent-replayed")),
        "same_task": b(r1).get("id") == b(r2).get("id"),
        "reordered_keys": (r3["status"], b(r3).get("id") == b(r1).get("id"), e(r3).get("code")),
        "other_body": e(r4),
    }
    for tid in {b(x).get("id") for x in (r1, r2, r3)} - {None}:
        await cancel(c, tid, "idem_cleanup")
    key2 = f"moss-eval-race-{uuid.uuid4().hex}"
    rs = await asyncio.gather(*(create(c, "idem_race", body, {"Idempotency-Key": key2}) for _ in range(8)))
    ids = [b(r).get("id") for r in rs]
    out["race_8_parallel_same_key"] = {"statuses": [r["status"] for r in rs], "distinct_task_ids": len(set(ids) - {None}),
                                       "replayed_flags": [r["resp_headers"].get("idempotent-replayed") for r in rs],
                                       "errors": [e(r) for r in rs if r["status"] not in (200, 201, 202)][:3]}
    for tid in set(ids) - {None}:
        await cancel(c, tid, "idem_race_cleanup")
    r5 = await create(c, "no_key_dup_1", body)
    r6 = await create(c, "no_key_dup_2", body)
    out["no_key_duplicate_creates_two"] = b(r5).get("id") != b(r6).get("id")
    for x in (r5, r6):
        if b(x).get("id"):
            await cancel(c, b(x)["id"], "no_key_cleanup")
    return out


async def t_queue_and_polling(c):
    out = {}
    rs = []
    for i in range(23):
        r = await create(c, "queue_fill", task_body(goal=f"[{i}] Return the main heading.",
                                                    limits={"max_runtime_seconds": 60, "max_cost_usd": 0.01}))
        rs.append(r)
        if r["status"] == 429:
            break
    first429 = next((i for i, r in enumerate(rs) if r["status"] == 429), None)
    out["queue_fill"] = {"created": sum(1 for r in rs if b(r).get("id")), "first_429_index": first429,
                         "error_429": e(rs[first429]) if first429 is not None else None,
                         "retry_after": rs[first429]["resp_headers"].get("retry-after") if first429 is not None else None,
                         "statuses_at_create": [b(r).get("status") for r in rs if b(r).get("id")]}
    t0 = time.perf_counter()
    await asyncio.gather(*(cancel(c, b(r)["id"], "queue_cleanup") for r in rs if b(r).get("id")))
    out["cancel_all_s"] = round(time.perf_counter() - t0, 2)
    target = next((b(r)["id"] for r in rs if b(r).get("id")), FAKE_ID)
    lat, codes = [], {}
    t_end = time.perf_counter() + 15

    async def hammer():
        while time.perf_counter() < t_end:
            r = await get(c, target, "poll_hammer")
            lat.append(r["latency_s"])
            codes[str(r["status"])] = codes.get(str(r["status"]), 0) + 1

    await asyncio.gather(*(hammer() for _ in range(20)))
    lat.sort()
    out["poll_hammer_20x15s"] = {"requests": len(lat), "status_counts": codes,
                                 "p50_ms": lat[len(lat) // 2] * 1000 if lat else None,
                                 "p99_ms": lat[int(len(lat) * 0.99)] * 1000 if lat else None}
    return out


async def reconcile(c):
    """Final cost of every task this run created, from usage.cost."""
    rows, total = [], 0.0
    for tid in sorted(CREATED):
        t = b(await get(c, tid, "reconcile"))
        cost = ((t.get("usage") or {}).get("cost") or {})
        usd = cost.get("total_usd") or 0
        total += usd
        rows.append({"id": tid, "status": t.get("status"), "error": (t.get("error") or {}).get("code"), **cost})
        c.ledger.add(f"task {tid}", usd, {"status": t.get("status")})
    return {"tasks_created": len(CREATED), "total_usd": total, "rows": rows}


TESTS = [("routes", t_routes), ("validation", t_validation), ("lifecycle", t_lifecycle),
         ("schema_mismatch", t_schema_mismatch), ("idempotency", t_idempotency), ("cancel", t_cancel),
         ("limits", t_limits), ("queue_and_polling", t_queue_and_polling)]


async def run(c, only=None):
    results = {}
    for name, fn in TESTS:
        if only and name not in only:
            continue
        c.ledger.check(upcoming=0.5)
        print(f"  tasks/{name} ... spent so far ${c.ledger.spent:.4f}", flush=True)
        try:
            results[name] = await fn(c)
        except Exception as ex:
            if type(ex).__name__ == "BudgetExceeded":
                raise
            results[name] = {"harness_exception": f"{type(ex).__name__}: {ex}"}
    results["reconcile"] = await reconcile(c)
    return results
