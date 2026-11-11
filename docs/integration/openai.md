# OpenAI integration: configuration, model decision, safety and verification

OpenAI is FundBridge's initial AI provider. It powers four features: campaign drafting, translation, the beneficiary assistant, and natural-language campaign search. Business code depends only on the `AIProvider` interface (`backend/app/integrations/ai/base.py`). OpenAI is one implementation of it (`openai_provider.py`), so another provider can be added without touching the features.

## Verification status

**No request has been made to the real OpenAI API from this repository. No API key was available.** Everything below was tested against mocks or a local HTTP double:

| Level | What runs | Where |
|---|---|---|
| Provider wire tests | Real `OpenAIProvider` and OpenAI SDK; the HTTP transport is mocked. Covers the request shape, retries, 429/401/404/400/5xx, timeouts, connection errors, malformed bodies, refusals, truncation and content filtering. | `backend/tests/ai/test_openai_provider.py` |
| Application tests | Real app factory, routes, service and provider; mocked transport. Every failure mode degrades gracefully; a hostile model output changes no database row. | `backend/tests/integration/test_ai_provider_failures.py` |
| Live HTTP (e2e) | gunicorn serving the app, calling a local OpenAI-compatible double over HTTP | `backend/tests/e2e/test_journeys.py` |
| **Real OpenAI** | Opt-in; **skipped** until someone provides a key | `backend/tests/ai/test_openai_live.py`, `flask fundbridge-ai check` |

## Configuration (server-side only)

The key is read only by the backend and never sent to the browser. The frontend calls FundBridge's `/api/v1/ai/*` endpoints.

| Variable | Default | Meaning |
|---|---|---|
| `AI_PROVIDER` | `auto` | `auto` uses OpenAI when a key is set; `openai` is the same but logs a warning when the key is missing; `disabled` means fallbacks only |
| `OPENAI_API_KEY` | (empty) | Secret. Without it every feature runs on its deterministic fallback, and translation is unavailable. |
| `OPENAI_MODEL` | `gpt-5.4-mini` | Any Chat Completions model that supports strict JSON-schema Structured Outputs |
| `OPENAI_REASONING_EFFORT` | `low` for reasoning models, nothing for `gpt-4*` | Sent as `reasoning_effort`. `omit` sends nothing. |
| `OPENAI_REASONING_TOKEN_ALLOWANCE` | `1024` | Added to `max_completion_tokens` when an effort is sent, because hidden reasoning tokens count against that limit |
| `OPENAI_BASE_URL` | OpenAI | For a proxy or a compatible gateway |
| `AI_TIMEOUT_SECONDS` / `AI_MAX_RETRIES` | `15` / `1` | Per-request timeout; the SDK retries 5xx, 429 and connection errors |
| `AI_RATE_LIMIT_PER_MINUTE` / `AI_PUBLIC_RATE_LIMIT_PER_MINUTE` | `10` / `20` | FundBridge's own per-user and per-IP limits (in-process) |

## Model selection decision (2026-11-11)

Requirements: a small, inexpensive model on Chat Completions that supports strict `json_schema` structured outputs and handles English and Kiswahili, and that is **not scheduled for removal before the demo or launch**.

- `gpt-4o-mini`, the previous default, is reported to be removed from the API on **2027-01-14** ([aiengineerguide](https://aiengineerguide.com/tools/model-retirements/gpt-4o-mini/), [sessionwatcher](https://sessionwatcher.com/news/openai-api-gpt-4o-gpt-4-1-shutdown-january-14-2027)).
- `gpt-5-mini` is reported to be removed on **2026-12-11** ([aiengineerguide](https://aiengineerguide.com/tools/model-retirements/gpt-5-mini/), [privatedevops](https://privatedevops.com/news/openai-retires-gpt-5-o3-snapshots-december-2026)). Sources disagree on its successor; `gpt-5.4-mini` is one reported replacement ([endoflife.ai](https://endoflife.ai/openai-api-models/gpt-5.4-mini)).
- **Decision: default to `gpt-5.4-mini` with `reasoning_effort=low`.** `low` is accepted by every reasoning model; `minimal` and `none` are not accepted by all of them. These dates and names come from third-party trackers. They were **not** confirmed on OpenAI's deprecations page or with an API call. Before relying on them, the operator must check [OpenAI's deprecations page](https://developers.openai.com/docs/deprecations) and run `flask fundbridge-ai check`. If the model is not available, set `OPENAI_MODEL` to a small model the account lists, and for a `gpt-4*` model set `OPENAI_REASONING_EFFORT=omit`.

## How to verify with a real key

```bash
cd backend
export OPENAI_API_KEY=sk-...            # never commit; set in the host's secret store
export OPENAI_MODEL=gpt-5.4-mini        # or the model chosen above
flask --app run:app fundbridge-ai check # one search and one translation through the real service path
FUNDBRIDGE_LIVE_OPENAI_TESTS=1 python -m pytest tests/ai/test_openai_live.py -v   # all four features
```

`check` exits 0 only when the model itself answered both requests (not a fallback). It prints the model and latency, never the key. After deployment, `GET /api/v1/ai/status` shows `model_verified: true` once a real call has succeeded in that process. `mode: "live"` alone only means a key is configured.

## Safety design

**Inputs.** Before any text leaves the server it is redacted. Emails, phone numbers (9 to 15 digits), long digit runs (ID, account and card numbers) and uppercase reference codes (M-Pesa transaction codes, passport numbers) are replaced with placeholders. Names and street addresses are **not** detected; the drafting form asks only for a first name and a general location. User text is wrapped as delimited data, never as instructions. Requests send `store: false` and a salted hash of the user ID as `safety_identifier`.

**Outputs.** Every response must parse as JSON and validate against a strict Pydantic model: no extra fields, length limits, category enums and an allowlist of assistant actions. Anything else counts as a provider failure and the fallback runs. Text is then sanitized: HTML stripped, entities decoded, control and bidi characters removed, links removed. Unsafe claims, in English and Kiswahili, are handled as follows:

- **Draft:** claims that money moved, that FundBridge verified or approved something, or guarantees, produce warnings.
- **Assistant:** such claims cause the reply to be replaced entirely.
- **Search:** results always come from the database catalog. The model only proposes filters and cannot invent campaigns.
- **Translation:** placeholders are restored after translation.

**No authority.** The provider has no tools, no function calling and no database access. The AI service holds only a read-only campaign catalog. It cannot change donations, the ledger, payouts, beneficiary verification, roles or campaign status, or start a transfer. Two tests enforce this: a static import test (`test_ai_code_cannot_reach_financial_modules`) and a database snapshot test (`test_adversarial_prompts_and_hostile_outputs_change_nothing`). Drafts are suggestions; the user saves them through the normal campaign endpoints.

**Logging.** Each call logs the feature, provider, model, outcome, latency and hashed actor. Prompts and outputs are never logged.

## Failure behaviour

| OpenAI condition | Draft | Assistant | Search | Translate | `meta` |
|---|---|---|---|---|---|
| No key / disabled | template | rule-based | keyword | `503 AI_UNAVAILABLE` | `provider: fallback`, `degraded: false` |
| Timeout | template | rule-based | keyword | 503 | `degraded: true`, `fallback_reason: AI_PROVIDER_TIMEOUT` |
| 429 rate limit or quota, 401, 404 model, 400 parameter, connection error | same | same | same | 503 | `AI_PROVIDER_UNAVAILABLE` |
| 5xx after retries | same | same | same | 503 | `AI_PROVIDER_ERROR` |
| Malformed body, non-JSON content, schema violation, truncation | same | same | same | 503 | `AI_INVALID_OUTPUT` |
| Refusal or content filter | same | same | same | 503 | `AI_PROVIDER_REFUSAL` |
| FundBridge's own limit | `429 RATE_LIMITED` with `Retry-After` | | | | |

SMS and USSD never depend on AI. Only free-text SMS uses the assistant, and it falls back to rule-based replies.
