# Moss Inference: what I tested and what I would fix

Rishi Popawala, rishipopawala@gmail.com. Code, scripts and raw logs: {{REPO_URL}}

Every number below comes from the logs in the repo. I ran it from Mumbai on home broadband. TTFT includes the network; the preflight measured an 18 ms floor to the inference edge.

## 1. Portal

**Liked.** Sign-in takes one click with GitHub, Google or an email link, and the `/inference` link survives the login redirect. {{one more concrete thing from signup, e.g. "I had a project id and key in N minutes"}}

**Didn't like.** The docs and the offer disagree. The Quickstart says inference has "no included allowance" and to buy $5 of credits first, and the overview calls it private beta with a link to the portal root. The `/inference` link that gave me $10 appears nowhere in the docs. {{portal rough edge from signup, e.g. where credits and spend show up}}

**What I'd ship.** One "Get started" path: the `/inference` link in the docs, credits on the first screen, and a copy-ready `id:key` string with a curl that works on the first paste.

## 2. Inference API

**Liked.** `moss/fastlane-1` streamed its first token in {{TTFT p50}} ms at p50 and {{TTFT p95}} ms at p95 (n={{n}}, reply cache off). Decode ran at {{tok/s}} tokens/s. The OpenAI SDK worked with only a base URL change, and every error carried a request id and the OpenAI error shape. The docs list every error code with what to do about it, which few providers do.

**Didn't like.** Auth runs in a different order on each route. With no key, `/v1/responses` answers `400` about `input` while `/v1/chat/completions` answers `401`. With a wrong key, chat checks the body first and only then rejects the key. `/v1/models` needs no key at all, though the docs show one. {{one measured issue from the errors or concurrency run, with numbers}}

**What I'd ship.** One auth middleware in front of every route, so a missing or wrong key always gets `401` first. Then a contract test in CI that runs the 27 error cases from this repo against the docs table, so the docs and the server cannot drift.

## 3. Tasks API

**What I tested.** About 45 tasks: 30 invalid bodies, the full lifecycle with an output schema on `moss-fast` and `moss-balanced`, idempotency (replay, reordered JSON, 8 parallel creates on one key), cancel while queued and while running, the cost and runtime caps, a dead start URL, the 20-task queue limit, and 20 pollers on one task.

**Liked.** {{e.g. idempotency held under 8 parallel creates / schema verification flagged the bad answer}}

**Didn't like.** Every Tasks call costs about 300 ms before any work: a `401` from `/v1/tasks` took 312 ms at p50 against 18 ms from the chat route. A poller every 2 s pays that on each poll. {{where I broke it, with repro: e.g. cap overrun of $X past max_cost_usd 0.01, or duplicate tasks from one idempotency key}}

**What I'd ship.** A wait option on `GET /v1/tasks/{id}` (hold up to 30 s until the status changes) or a webhook on finish, so clients stop polling. Tasks routes served from the same edge as inference. {{fix for the break above}}

Total spent: ${{SPENT}} of the $10 credits.
