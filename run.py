"""moss-eval: one command to test Moss Inference and Tasks.

python run.py                 preflight + inference + tasks + report
python run.py preflight       no key needed, costs nothing
python run.py inference --only stream_latency,errors
python run.py report logs/<run>
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from moss_eval import core, inference, preflight, report, tasks


async def main(a):
    core.load_env()
    key = core.api_key()
    run_id = time.strftime("%Y%m%d-%H%M%S") + ("-mock" if "127.0.0.1" in core.BASE_URL or "localhost" in core.BASE_URL else "")
    run_dir = core.ROOT / "logs" / run_id
    rec = core.Recorder(run_dir)
    ledger_path = run_dir / "spend.jsonl" if run_id.endswith("-mock") else core.ROOT / "logs" / "spend.jsonl"
    ledger = core.Ledger(ledger_path, a.budget)
    c = core.Client(rec, ledger, key)
    stages = ["preflight", "inference", "tasks"] if a.stage == "all" else [a.stage]
    only = set(a.only.split(",")) if a.only else None
    results = {"run_id": run_id, "base_url": core.BASE_URL, "started": time.time()}
    print(f"run {run_id}, budget ${a.budget}, spent before this run ${ledger.spent:.4f}")
    try:
        for s in stages:
            if s != "preflight" and not key:
                print(f"skip {s}: set MOSS_PROJECT_ID and MOSS_PROJECT_KEY in .env")
                continue
            print(f"[{s}]")
            mod = {"preflight": preflight, "inference": inference, "tasks": tasks}[s]
            results[s] = await (mod.run(c) if s == "preflight" else mod.run(c, only))
    except core.BudgetExceeded as e:
        results["stopped"] = f"budget: {e}"
        print("STOP", e)
    finally:
        if tasks.CREATED:
            for tid in tasks.CREATED:
                await tasks.cancel(c, tid, "final_cleanup")
        await c.close()
    results["spent_usd"] = ledger.spent
    (run_dir / "results.json").write_text(core.redact(json.dumps(results, indent=2, default=str)), encoding="utf-8")
    print("results:", report.build(run_dir))
    print(f"total spent (local ledger) ${ledger.spent:.4f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", nargs="?", default="all", choices=["all", "preflight", "inference", "tasks", "report"])
    p.add_argument("run_dir", nargs="?")
    p.add_argument("--only", help="comma-separated test names")
    p.add_argument("--budget", type=float, default=8.0, help="stop when the local ledger passes this many USD")
    a = p.parse_args()
    if a.stage == "report":
        print(report.build(Path(a.run_dir)))
        sys.exit()
    asyncio.run(main(a))
