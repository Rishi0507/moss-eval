"""Turns a run's results.json into results/RESULTS.md and two PNG charts."""
import json
from pathlib import Path

SURFACE, INK, MUTED, BLUE, ORANGE = "#fcfcfb", "#0b0b0b", "#52514e", "#2a78d6", "#eb6834"


def _fmt(v, unit="", scale=1.0, nd=0):
    return "-" if v is None else f"{v * scale:.{nd}f}{unit}"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#cfcfcb")
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color="#ececea", linewidth=0.8)
    ax.set_axisbelow(True)


def charts(run_dir: Path, out_dir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    made = []
    stream_file = run_dir / "inference.jsonl"
    if stream_file.exists():
        rows = [json.loads(l) for l in stream_file.read_text(encoding="utf-8").splitlines()]
        series = {}
        for api, color in (("chat", BLUE), ("responses", ORANGE)):
            v = sorted(r["ttft_s"] * 1000 for r in rows if r.get("test") == f"stream_{api}" and r.get("ttft_s"))
            if v:
                series[api] = (v, color)
        if series:
            fig, ax = plt.subplots(figsize=(6.4, 3.6), facecolor=SURFACE)
            _style(ax)
            for api, (v, color) in series.items():
                ys = [(i + 1) / len(v) for i in range(len(v))]
                ax.step(v, ys, where="post", color=color, linewidth=2,
                        label=f"{'Chat Completions' if api == 'chat' else 'Responses'} (n={len(v)})")
            ax.axvline(200, color=MUTED, linewidth=1, linestyle="--")
            ax.text(203, 0.04, "200 ms claim", color=MUTED, fontsize=8)
            ax.set_xlabel("Time to first token (ms), client in Mumbai", color=INK, fontsize=9)
            ax.set_ylabel("Share of requests", color=INK, fontsize=9)
            ax.set_title("moss/fastlane-1 TTFT, streamed, reply cache off", color=INK, fontsize=10, loc="left")
            ax.legend(frameon=False, fontsize=8, labelcolor=INK)
            fig.tight_layout()
            p = out_dir / "ttft_cdf.png"
            fig.savefig(p, dpi=150)
            plt.close(fig)
            made.append(p.name)

    res = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    conc = ((res.get("inference") or {}).get("concurrency") or {})
    if conc and all(isinstance(v, dict) and "requests" in v for v in conc.values()):
        lv = sorted(conc, key=lambda k: int(k))
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(8, 3.2), facecolor=SURFACE)
        for ax in (a1, a2):
            _style(ax)
        x = range(len(lv))
        a1.bar(x, [conc[k]["out_tok_per_s"] for k in lv], color=BLUE, width=0.6)
        a1.set_title("Output tokens/s (successful requests)", color=INK, fontsize=9, loc="left")
        a2.bar(x, [100 * (1 - conc[k]["ok"] / conc[k]["requests"]) for k in lv], color=ORANGE, width=0.6)
        a2.set_title("Failed requests (%)", color=INK, fontsize=9, loc="left")
        for ax in (a1, a2):
            ax.set_xticks(list(x), [f"c={k}" for k in lv])
        fig.tight_layout()
        p = out_dir / "concurrency.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        made.append(p.name)
    return made


def markdown(run_dir: Path, out_dir: Path, chart_files):
    res = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    L = [f"# Results for run `{run_dir.name}`", "", f"Base URL: `{res.get('base_url')}`. Spend: ${res.get('spent_usd', 0):.4f}.", ""]
    pre = res.get("preflight") or {}
    if pre:
        rtt = pre.get("rtt_401_s") or {}
        L += ["## Preflight (no key)", "",
              f"401 round trip on /chat/completions: p50 {_fmt(rtt.get('p50'), ' ms', 1000)}, p95 {_fmt(rtt.get('p95'), ' ms', 1000)}.",
              f"401 round trip on /tasks: p50 {_fmt((pre.get('rtt_401_tasks_s') or {}).get('p50'), ' ms', 1000)}, "
              f"p95 {_fmt((pre.get('rtt_401_tasks_s') or {}).get('p95'), ' ms', 1000)}.", "",
              "| credentials, route (body `{\"model\": ...}` only) | status | message |", "| - | - | - |"]
        for k, (st, msg) in (pre.get("auth") or {}).items():
            L.append(f"| {k} | {st} | {msg} |")
        L += ["", "| credentials, route (valid body) | status | message |", "| - | - | - |"]
        for k, (st, msg) in (pre.get("auth_valid_body") or {}).items():
            L.append(f"| {k} | {st} | {msg} |")
        L.append("")
    inf = res.get("inference") or {}
    sl = inf.get("stream_latency") or {}
    if sl and "chat" in sl:
        L += ["## Streaming latency, moss/fastlane-1", "",
              "| API | ok/n | TTFT p50 | TTFT p95 | TTFT p99 | ITL p50 | ITL p95 | decode tok/s p50 |",
              "| - | - | - | - | - | - | - | - |"]
        for api in ("chat", "responses"):
            d = sl.get(api) or {}
            t, i, s = d.get("ttft_s") or {}, d.get("itl_ms") or {}, d.get("decode_tok_s") or {}
            L.append(f"| {api} | {d.get('ok')}/{d.get('n')} | {_fmt(t.get('p50'), ' ms', 1000)} | {_fmt(t.get('p95'), ' ms', 1000)} | "
                     f"{_fmt(t.get('p99'), ' ms', 1000)} | {_fmt(i.get('p50'), ' ms', 1, 1)} | {_fmt(i.get('p95'), ' ms', 1, 1)} | "
                     f"{_fmt(s.get('p50'))} |")
        L.append("")
    nl = (inf.get("nonstream_latency") or {}).get("latency_s") or {}
    if nl:
        L += [f"Non-streaming, 100 max tokens: p50 {_fmt(nl.get('p50'), ' ms', 1000)}, p95 {_fmt(nl.get('p95'), ' ms', 1000)}, "
              f"p99 {_fmt(nl.get('p99'), ' ms', 1000)} (n={nl.get('n')}).", ""]
    conc = inf.get("concurrency") or {}
    if conc and all(isinstance(v, dict) and "requests" in v for v in conc.values()):
        L += ["## Concurrency sweep", "", "| in flight | requests | ok | status counts | req/s | out tok/s | TTFT p50 | TTFT p95 |",
              "| - | - | - | - | - | - | - | - |"]
        for k in sorted(conc, key=int):
            d = conc[k]
            L.append(f"| {k} | {d['requests']} | {d['ok']} | {d['status_counts']} | {d['req_per_s']:.2f} | "
                     f"{d['out_tok_per_s']:.0f} | {_fmt((d['ttft_s'] or {}).get('p50'), ' ms', 1000)} | "
                     f"{_fmt((d['ttft_s'] or {}).get('p95'), ' ms', 1000)} |")
        L.append("")
    errs = inf.get("errors") or {}
    if errs and "harness_exception" not in errs:
        L += ["## Error handling", "", "| case | docs say | got | code | request id |", "| - | - | - | - | - |"]
        for k, v in errs.items():
            L.append(f"| {k} | {v['expected']} | {v['status']} | {v.get('code') or v.get('type') or ''} | "
                     f"{'yes' if v.get('request_id') else 'no'} |")
        L.append("")
    for name in chart_files:
        L += [f"![{name}]({name})", ""]
    L += ["## Full results", "", "Every section, as JSON:", "", "```json", json.dumps(res, indent=2, default=str)[:60000], "```", ""]
    (out_dir / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")


def build(run_dir: Path):
    out_dir = run_dir
    files = charts(run_dir, out_dir)
    markdown(run_dir, out_dir, files)
    return out_dir / "RESULTS.md"
