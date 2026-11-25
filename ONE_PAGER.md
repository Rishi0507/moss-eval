# Moss Inference: what I tested and what I would fix

Rishi Popawala, rishipopawala@gmail.com. Code, scripts and raw logs: {{REPO_URL}}

I ran everything from Mumbai on home broadband on 25 Nov 2026 and spent $0.25 of the $10 credits. You can check each number below against the logs in the repo.

## 1. Portal

**Liked.** Google sign-in took one click. On the last setup screen I got Python code with my project id filled in, next to a "Create key" button.

**Didn't like.** I came in through the `/inference` link, and the setup walked me through the search product: "give your agent memory", pick a data source, keep a sample index. The sample code calls `load_index` and `query`. I had to open the docs to find my first inference call. The Quickstart also says inference has "no included allowance", while your link gave me $10.

**What I'd ship.** A setup path for people who arrive through `/inference`. It skips the index steps, shows the key and ends on a curl to `/v1/chat/completions` with the `id:key` filled in.

## 2. Inference API

**Liked.** `moss/fastlane-1` streamed its first token at 96 ms p50 and 202 ms p95 over 30 calls and decoded at about 127 tokens/s. On the same key, `claude-haiku-5.5` took 619 ms and `gpt-6-luna` 1139 ms. The prefix cache cut TTFT from 449 ms to 109 ms on a 6.9k token prompt. The OpenAI SDK worked after I changed the base URL. 24 of 27 bad requests got the exact error the docs promise, each with a request id.

**Didn't like.** Each route checks auth in its own order. With no key, `/v1/responses` returns `400` about `input`. With a wrong key, chat checks the body first. `/v1/models` answers with no key at all. Three requests break the docs: empty `input` on responses returns 200, a `text/plain` body returns 200, and 33 indexes return 403 instead of 400. TTFT went from 62 ms with one request in flight to 360 ms with four. The headers advertise 120 requests a minute, and the eleventh request in a burst gets a 429.

**What I'd ship.** One auth check in front of every route, so a bad key gets 401 first. A CI contract test that runs my 27 error cases against the docs table. Rate limit headers that show the burst limit you hit.

## 3. Tasks API

**What I tested.** 38 tasks: 30 invalid bodies, the lifecycle on `moss-fast` and `moss-balanced`, idempotency (replay, reordered JSON, 8 parallel creates on one key), cancel while queued and while running, cost and runtime caps, a dead start URL, the 20-task queue limit, and 819 polls from 20 pollers.

**Liked.** Idempotency held. 8 parallel creates with one key made one task, and a reused key with another body got a clear 422. The 60 s runtime cap stopped the task at 61 s. Each task splits its cost into model and browser.

**Where I broke it.**

- I sent a schema no value can match (`minimum: 10, maximum: 5`). The task came back `completed` with `{"n": 1}` and `verification.passed: true`. The docs say `false`.
- A start URL that fails to load ends `completed`, puts the error inside `output_text`, and bills.
- I created 23 tasks back to back and got 23 `202 queued`. The 20-task limit never sent a 429.
- Cost reads $0.00 while a task runs. One I cancelled at 15 s finished at $0.0056.
- `moss/fastlane-1` as a task model said example.com has no heading. `moss-fast` found the `<h1>`.
- Each poll takes 321 ms at p50 and 1.26 s at p99.

**What I'd ship.** A server-side check of the output against the schema that fails the task on a mismatch. A `navigation_failed` error that ends the task as `failed`. A queue limit that returns 429 with `Retry-After`. Live cost while a task runs. A `?wait=30` long poll on `GET /v1/tasks/{id}`, so clients stop polling every second.
