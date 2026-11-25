# Results for run `20261125-134848`

Base URL: `https://inference.moss.dev/v1`. Spend: $0.0000.

## Preflight (no key)

401 round trip on /chat/completions: p50 98 ms, p95 223 ms.
401 round trip on /tasks: p50 308 ms, p95 567 ms.

| credentials, route (body `{"model": ...}` only) | status | message |
| - | - | - |
| missing /chat/completions | 401 | Missing bearer token |
| missing /responses | 400 | input must be a string or a list of items |
| missing /tasks | 401 | Missing bearer token |
| no_colon /chat/completions | 401 | Send Bearer project_id:project_key |
| no_colon /responses | 400 | input must be a string or a list of items |
| no_colon /tasks | 401 | Send Bearer project_id:project_key |
| empty_parts /chat/completions | 401 | Send Bearer project_id:project_key |
| empty_parts /responses | 400 | input must be a string or a list of items |
| empty_parts /tasks | 401 | Send Bearer project_id:project_key |
| wrong_pair /chat/completions | 400 | messages is required |
| wrong_pair /responses | 400 | input must be a string or a list of items |
| wrong_pair /tasks | 401 | The project credentials were rejected |
| basic_scheme /chat/completions | 401 | Missing bearer token |
| basic_scheme /responses | 400 | input must be a string or a list of items |
| basic_scheme /tasks | 401 | Missing bearer token |
| lowercase_bearer /chat/completions | 400 | messages is required |
| lowercase_bearer /responses | 400 | input must be a string or a list of items |
| lowercase_bearer /tasks | 401 | The project credentials were rejected |

| credentials, route (valid body) | status | message |
| - | - | - |
| missing /chat/completions | 401 | Missing bearer token |
| missing /responses | 401 | Missing bearer token |
| wrong_pair /chat/completions | 401 | The project credentials were rejected |
| wrong_pair /responses | 401 | The project credentials were rejected |

## Full results

Every section, as JSON:

```json
{
  "run_id": "20261125-134848",
  "base_url": "https://inference.moss.dev/v1",
  "started": 1795594729.2459219,
  "preflight": {
    "rtt_401_s": {
      "p50": 0.0979494999628514,
      "p95": 0.22311673004878696,
      "n": 19
    },
    "rtt_401_tasks_s": {
      "p50": 0.30840610002633184,
      "p95": 0.5672528101014915,
      "n": 19
    },
    "models_no_auth": {
      "status": 200,
      "count": 19
    },
    "models_bad_auth_status": 200,
    "auth": {
      "missing /chat/completions": [
        401,
        "Missing bearer token"
      ],
      "missing /responses": [
        400,
        "input must be a string or a list of items"
      ],
      "missing /tasks": [
        401,
        "Missing bearer token"
      ],
      "no_colon /chat/completions": [
        401,
        "Send Bearer project_id:project_key"
      ],
      "no_colon /responses": [
        400,
        "input must be a string or a list of items"
      ],
      "no_colon /tasks": [
        401,
        "Send Bearer project_id:project_key"
      ],
      "empty_parts /chat/completions": [
        401,
        "Send Bearer project_id:project_key"
      ],
      "empty_parts /responses": [
        400,
        "input must be a string or a list of items"
      ],
      "empty_parts /tasks": [
        401,
        "Send Bearer project_id:project_key"
      ],
      "wrong_pair /chat/completions": [
        400,
        "messages is required"
      ],
      "wrong_pair /responses": [
        400,
        "input must be a string or a list of items"
      ],
      "wrong_pair /tasks": [
        401,
        "The project credentials were rejected"
      ],
      "basic_scheme /chat/completions": [
        401,
        "Missing bearer token"
      ],
      "basic_scheme /responses": [
        400,
        "input must be a string or a list of items"
      ],
      "basic_scheme /tasks": [
        401,
        "Missing bearer token"
      ],
      "lowercase_bearer /chat/completions": [
        400,
        "messages is required"
      ],
      "lowercase_bearer /responses": [
        400,
        "input must be a string or a list of items"
      ],
      "lowercase_bearer /tasks": [
        401,
        "The project credentials were rejected"
      ]
    },
    "auth_valid_body": {
      "missing /chat/completions": [
        401,
        "Missing bearer token"
      ],
      "missing /responses": [
        401,
        "Missing bearer token"
      ],
      "wrong_pair /chat/completions": [
        401,
        "The project credentials were rejected"
      ],
      "wrong_pair /responses": [
        401,
        "The project credentials were rejected"
      ]
    },
    "malformed_json_no_auth": 401,
    "get_with_body /tasks": [
      400,
      "text/html; charset=UTF-8"
    ],
    "get_with_body /models": [
      400,
      "text/html; charset=UTF-8"
    ],
    "get_with_body /nope": [
      400,
      "text/html; charset=UTF-8"
    ],
    "unknown_route": [
      404,
      null
    ],
    "cors_preflight": [
      200,
      {
        "access-control-allow-headers": "authorization,content-type,x-moss-indexes",
        "access-control-allow-methods": "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT, QUERY",
        "access-control-allow-origin": "*",
        "access-control-max-age": "7200"
      }
    ],
    "base_url": "https://inference.moss.dev/v1"
  },
  "spent_usd": 0.0
}
```
