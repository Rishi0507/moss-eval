"""Turns a run's results.json into RESULTS.md and PNG charts."""
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
    made += _more_charts(run_dir, out_dir, res, plt)
    return made


def _save(fig, plt, out_dir, name):
    fig.tight_layout()
    fig.savefig(out_dir / name, dpi=150)
    plt.close(fig)
    return name


def _more_charts(run_dir, out_dir, res, plt):
    made = []
    inf, tasks = res.get("inference") or {}, res.get("tasks") or {}
    GREEN, GREY = "#2f9e6e", "#9a9993"

    conc = inf.get("concurrency") or {}
    if conc and all(isinstance(v, dict) and v.get("ttft_s") for v in conc.values()):
        lv = sorted(conc, key=int)
        fig, ax = plt.subplots(figsize=(6.4, 3.4), facecolor=SURFACE)
        _style(ax)
        x = list(range(len(lv)))
        ax.plot(x, [conc[k]["ttft_s"]["p50"] * 1000 for k in lv], color=BLUE, marker="o", linewidth=2, label="TTFT p50")
        ax.plot(x, [conc[k]["ttft_s"]["p95"] * 1000 for k in lv], color=BLUE, marker="o", linewidth=1, linestyle="--", label="TTFT p95")
        for i, k in enumerate(lv):
            r429 = int(conc[k]["status_counts"].get("429", 0))
            if r429:
                ax.annotate(f"{r429}/{conc[k]['requests']} got 429", (i, conc[k]["ttft_s"]["p95"] * 1000),
                            textcoords="offset points", xytext=(0, 10), ha="center", fontsize=7.5, color=ORANGE)
        ax.set_xlim(-0.4, len(lv) - 0.6)
        ax.set_xticks(x, [f"{k} in flight" for k in lv])
        ax.set_ylabel("ms (successful requests)", color=INK, fontsize=9)
        ax.set_ylim(0, max(conc[k]["ttft_s"]["p95"] for k in lv) * 1000 * 1.25)
        ax.set_title("fastlane-1 TTFT as concurrency grows", color=INK, fontsize=10, loc="left")
        ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left")
        made.append(_save(fig, plt, out_dir, "concurrency_ttft.png"))

    vc = inf.get("vendor_compare") or {}
    vc = {m: d["ttft_s"] for m, d in vc.items() if (d or {}).get("ttft_s")}
    if vc:
        ms = sorted(vc, key=lambda m: vc[m]["p50"], reverse=True)
        fig, ax = plt.subplots(figsize=(7.6, 2.8), facecolor=SURFACE)
        _style(ax)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color="#ececea", linewidth=0.8)
        y = list(range(len(ms)))
        ax.barh(y, [vc[m]["p50"] * 1000 for m in ms], color=[BLUE if m.startswith("moss/") else GREY for m in ms], height=0.55)
        ax.scatter([vc[m]["p95"] * 1000 for m in ms], y, color=INK, marker="|", s=200, zorder=3)
        for i, m in enumerate(ms):
            ax.text(vc[m]["p95"] * 1000 + 40, i, f"p50 {vc[m]['p50'] * 1000:.0f} ms, p95 {vc[m]['p95'] * 1000:.0f} ms",
                    va="center", fontsize=8, color=INK)
        ax.set_yticks(y, [f"{m} (n={vc[m]['n']})" for m in ms])
        ax.set_xlim(0, max(vc[m]["p95"] for m in ms) * 1000 * 1.75)
        ax.set_xlabel("Time to first token (ms) from Mumbai. Bar: p50. Tick: p95", color=INK, fontsize=9)
        ax.set_title("TTFT by model, same Moss key", color=INK, fontsize=10, loc="left")
        made.append(_save(fig, plt, out_dir, "vendor_ttft.png"))

    pc = [c for c in ((inf.get("caches") or {}).get("prefix_cache") or []) if c.get("ttft_s")]
    if len(pc) >= 2:
        fig, ax = plt.subplots(figsize=(6.4, 2.8), facecolor=SURFACE)
        _style(ax)
        labels = ["cold" if i == 0 else f"warm {i}" for i in range(len(pc))]
        bars = ax.bar(range(len(pc)), [c["ttft_s"] * 1000 for c in pc], color=[GREY] + [GREEN] * (len(pc) - 1), width=0.55)
        for b, c in zip(bars, pc):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 8, f"{c['ttft_s'] * 1000:.0f} ms\n{c['cached']}/{c['prompt_tokens']} cached",
                    ha="center", fontsize=7.5, color=INK)
        ax.set_xticks(range(len(pc)), labels)
        ax.set_ylim(0, max(c["ttft_s"] for c in pc) * 1000 * 1.35)
        ax.set_ylabel("TTFT (ms)", color=INK, fontsize=9)
        ax.set_title("Prefix cache on a 6.9k token system prompt", color=INK, fontsize=10, loc="left")
        made.append(_save(fig, plt, out_dir, "prefix_cache.png"))

    runs = []
    for label, d in (("lifecycle, moss-fast", (tasks.get("lifecycle") or {}).get("moss-fast")),
                     ("lifecycle, moss-balanced", (tasks.get("lifecycle") or {}).get("moss-balanced")),
                     ("unsatisfiable schema", tasks.get("schema_mismatch")),
                     ("cost cap $0.01", (tasks.get("limits") or {}).get("budget_0_01")),
                     ("runtime cap 60 s", (tasks.get("limits") or {}).get("runtime_60")),
                     ("start URL does not load", (tasks.get("limits") or {}).get("unreachable_start_url"))):
        seen = (d or {}).get("seen") or (d or {}).get("status_first_seen_s")
        final = (d or {}).get("final") or {}
        if seen and final.get("status") in seen:
            runs.append((label, seen.get("running", 0), seen[final["status"]], final["status"],
                         ((final.get("cost") or {}).get("total_usd") or 0), (final.get("verification") or {}).get("passed")))
    if runs:
        colors = {"completed": GREEN, "failed": ORANGE, "cancelled": GREY}
        fig, ax = plt.subplots(figsize=(7.2, 0.5 * len(runs) + 1.2), facecolor=SURFACE)
        _style(ax)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color="#ececea", linewidth=0.8)
        runs = runs[::-1]
        for i, (label, start, end, st, cost, passed) in enumerate(runs):
            ax.barh(i, end - start, left=start, color=colors.get(st, BLUE), height=0.5)
            note = f"{st}, ${cost:.4f}" + ("" if passed is None else f", verified={str(passed).lower()}")
            ax.text(end + 1, i, note, va="center", fontsize=7.5, color=INK)
        ax.set_yticks(range(len(runs)), [r[0] for r in runs])
        ax.set_xlim(0, max(r[2] for r in runs) * 1.75)
        ax.set_xlabel("Seconds after create (first poll that saw each status)", color=INK, fontsize=9)
        ax.set_title("Tasks API: time to a terminal status, final status and cost", color=INK, fontsize=10, loc="left")
        made.append(_save(fig, plt, out_dir, "tasks_timeline.png"))

    tf = run_dir / "tasks.jsonl"
    if tf.exists():
        lat = sorted(r["latency_s"] * 1000 for r in map(json.loads, tf.read_text(encoding="utf-8").splitlines())
                     if r.get("test") == "poll_hammer" and r.get("status") == 200 and r.get("latency_s"))
        if lat:
            p50, p99 = lat[len(lat) // 2], lat[min(len(lat) - 1, int(len(lat) * 0.99))]
            fig, ax = plt.subplots(figsize=(6.4, 3.0), facecolor=SURFACE)
            _style(ax)
            ax.hist(lat, bins=40, color=BLUE)
            for v, name in ((p50, "p50"), (p99, "p99")):
                ax.axvline(v, color=ORANGE, linewidth=1, linestyle="--")
                ax.text(v + 10, ax.get_ylim()[1] * 0.9, f"{name} {v:.0f} ms", color=ORANGE, fontsize=8)
            ax.set_xlabel("GET /v1/tasks/{id} latency (ms)", color=INK, fontsize=9)
            ax.set_ylabel("Polls", color=INK, fontsize=9)
            ax.set_title(f"{len(lat)} polls from 20 concurrent pollers on one task", color=INK, fontsize=10, loc="left")
            made.append(_save(fig, plt, out_dir, "poll_latency.png"))
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
