# Moss Inference: what I tested and what I would fix

Rishi Popawala, rishipopawala@gmail.com. Code, scripts and raw logs: {{REPO_URL}}

I ran everything from Mumbai on home broadband on 25 Nov 2026. Each number comes from the logs in the repo. Total spend: $0.25 of the $10 credits.

## 1. Portal

**Liked.** Sign-in took one click with Google. The last setup screen gave me Python code with my project id filled in and a "Create key" button beside it.

**Didn't like.** I came in through the `/inference` link, but the setup steps were about the search product: "give your agent memory", pick a data source, a sample index. The ready-to-run code calls `load_index` and `query`. Nothing told me how to make my first inference call. The docs add to it: the Quickstart says inference has "no included allowance", while the link gave me $10.

**What I'd ship.** A separate setup path for anyone who arrives through `/inference`: skip the index steps, show the key, and end on a curl to `/v1/chat/completions` with the `id:key` already in it.

## 2. Inference API

**Liked.** `moss/fastlane-1` streamed its first token at 96 ms p50 and 202 ms p95 over 30 calls, and decoded at about 127 tokens/s. On the same key, `claude-haiku-5.5` took 619 ms and `gpt-6-luna` 1139 ms. The prefix cache cut TTFT from 449 ms to 109 ms on a 6.9k token prompt. The OpenAI SDK worked with a base URL change. 24 of 27 bad requests got the exact error the docs promise, each with a request id.

**Didn't like.** Auth runs in a different order on each route. With no key, `/v1/responses` returns `400` about `input`; with a wrong key, chat checks the body before it rejects the key; `/v1/models` needs no key at all. Three requests break the docs: empty `input` on responses returns 200, a `text/plain` body returns 200, 33 indexes return 403 instead of 400. Load hurts early: TTFT went from 62 ms with one request in flight to 360 ms with four. The headers advertise 120 requests a minute, but a burst of 11 gets a 429.

**What I'd ship.** One auth check in front of every route, so a bad key always gets 401 first. A CI contract test that runs the 27 error cases from my repo against the docs table. Rate limit headers that show the burst limit people hit.

## 3. Tasks API

**What I tested.** 38 tasks: 30 invalid bodies, the lifecycle on `moss-fast` and `moss-balanced`, idempotency (replay, reordered JSON, 8 parallel creates on one key), cancel while queued and while running, cost and runtime caps, a dead start URL, the 20-task queue limit, and 819 polls from 20 pollers.

**Liked.** Idempotency held: 8 parallel creates with one key made one task, and a reused key with another body got a clear 422. The 60 s runtime cap stopped at 61 s. Each task reports cost split into model and browser.

**Where I broke it.**
- A schema no value can match (`minimum: 10, maximum: 5`) came back `completed` with `{"n": 1}` and `verification.passed: true`. The docs say it should be `false`.
- A start URL that fails to load ends `completed`, with the error inside `output_text`, and still bills.
- 23 back-to-back creates all got `202 queued`. The 20-task limit never returned a 429.
- Cost reads $0.00 while a task runs. One I cancelled at 15 s finished at $0.0056.
- `moss/fastlane-1` as a task model said example.com has no heading. `moss-fast` found the `<h1>`.
- Each poll costs 321 ms p50 and 1.26 s p99.

**What I'd ship.** Check the result against the schema on the server, and mark it failed when it does not match. A `navigation_failed` error that ends the task as `failed`. A queue limit that returns 429 with `Retry-After`. Cost that updates while the task runs. A `?wait=30` long poll on `GET /v1/tasks/{id}`, so clients stop polling every second.
