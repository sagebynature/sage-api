# sage-api Architectural Review (2026-03-03)

## Findings (prioritized by severity)

### CRITICAL

#### F-001 [Bugs & Race Conditions] No cross-replica session concurrency control

- Severity: CRITICAL
- Location: `sage_api/services/session_manager.py:27-29`, `sage_api/services/session_manager.py:46-49`, `sage_api/services/session_store.py:59-72`
- Problem: Concurrency control is per-process (`asyncio.Lock` in `_locks`). In a multi-replica deployment, two pods can process the same `session_id` concurrently. Persistence is still read-modify-write (`GET` then `SET`), so writes can race.
- Impact: Lost updates / corrupted conversation history; non-deterministic session state depending on which pod handled which request.
- Recommendation: Add a distributed lock (Redis lock key with TTL + token-verified release) or optimistic concurrency (version + WATCH/MULTI or Lua). Make `save_history()` update atomic relative to the lock.

#### F-002 [Security Concern] API key grants full agent capability (RCE if agents enable `shell`/tools)

- Severity: CRITICAL
- Location: `README.md:133-145`, `sage_api/services/agent_registry.py:168-176`
- Problem: The README demonstrates agents can enable `shell`. With a single shared API key, any bearer can drive the agent to execute tools.
- Impact: Container compromise, data exfiltration (env vars, mounted volumes), and lateral movement if egress/network access exists.
- Recommendation: Treat the API key as an admin secret and network-restrict the service. Enforce a server-side allowlist of permitted tools/extensions for API-exposed agents and/or sandbox tool execution.

### HIGH

#### F-004 [Bugs] Error handler drops `detail` when `HTTPException.detail` is a dict

- Severity: HIGH
- Location: `sage_api/middleware/errors.py:30-44`, `sage_api/middleware/auth.py:35-54`, `sage_api/api/agents.py:40-49`
- Problem: For dict-shaped details, the handler sets `detail` to `None` and only keeps `error`.
- Impact: Auth failures and structured 404s lose their actionable details; clients get degraded/inconsistent error bodies.
- Recommendation: If `exc.detail` already matches `{error, detail, status_code}`, return it as-is. Otherwise, map dicts to both fields.

#### F-005 [Bugs] `delete_session()` can fail to delete if `agent.close()` raises

- Severity: HIGH
- Location: `sage_api/services/session_manager.py:114-124`
- Problem: Agent close happens before Redis delete; exceptions abort deletion.
- Impact: Sessions become undeletable in edge cases; leaks Redis keys and in-memory bookkeeping.
- Recommendation: Delete from Redis first, then best-effort close the agent (catch exceptions and continue).

#### F-006 [Architecture Issue] Service layer depends on FastAPI (`HTTPException`)

- Severity: HIGH
- Location: `sage_api/services/session_manager.py:8`, `sage_api/services/session_manager.py:30-107`, `sage_api/a2a/routes.py:124-134`
- Problem: Business/service code raises HTTP transport exceptions directly.
- Impact: Cross-protocol behavior (REST vs JSON-RPC) is coupled to HTTP semantics; harder to test and reuse.
- Recommendation: Raise domain exceptions (NotFound/Conflict/Timeout) in services and translate at the API edges.

### MEDIUM

#### F-008 [Bugs & Race Conditions] Lock check is non-atomic (`locked()` then `acquire()`)

- Severity: MEDIUM
- Location: `sage_api/services/session_manager.py:46-49`, `sage_api/services/session_manager.py:79-83`
- Problem: Two tasks can both pass `locked()` before one acquires; the second then blocks instead of returning 409.
- Impact: "Fail fast" concurrency semantics are unreliable; requests can queue and hit timeouts.
- Recommendation: Use a non-blocking acquire pattern (e.g., `asyncio.wait_for(lock.acquire(), timeout=0)`), or maintain explicit per-session in-flight state.

#### F-009 [Data Integrity] Redis `update()` uses `SET` then `EXPIRE` as separate commands

- Severity: MEDIUM
- Location: `sage_api/services/session_store.py:44-47`
- Problem: TTL is applied in a second command.
- Impact: If the process crashes between calls, keys can become immortal; extra Redis round trips.
- Recommendation: Use `SET ... EX` (single command) or wrap in a transaction.

#### F-010 [Observability] Request logging does not log exceptions

- Severity: MEDIUM
- Location: `sage_api/middleware/logging.py:36-51`
- Problem: Middleware logs only after `call_next()` returns; exceptions bypass logging entirely.
- Impact: Failed requests disappear from access logs; harder incident debugging.
- Recommendation: Wrap `call_next()` in try/except/finally to log both success and failure, and re-raise.

#### F-011 [Protocol] A2A stream emits `completed` even after error

- Severity: MEDIUM
- Location: `sage_api/a2a/routes.py:98-110`
- Problem: `_stream_events()` yields an `error` event but then always yields a `done` event with state `completed`.
- Impact: Clients can treat failed runs as successful completion.
- Recommendation: Emit a terminal `failed` state and stop streaming after error.

#### F-012 [Missing Capability] No rate limiting / quotas / request size limits

- Severity: MEDIUM
- Location: `sage_api/main.py:81-117` (no such middleware), `sage_api/api/messages.py:24-71`
- Problem: Nothing prevents abuse (SSE connection exhaustion, message spam, LLM cost blowups).
- Impact: DoS risk and runaway cost.
- Recommendation: Add per-API-key rate limits and max body size; cap concurrent streams per key.

#### F-013 [Missing Capability] No CORS configuration

- Severity: MEDIUM
- Location: `sage_api/main.py:81-117`
- Problem: No CORSMiddleware.
- Impact: Browser-based clients will fail unless proxied; or (if later enabled broadly) could be misconfigured.
- Recommendation: Add explicit CORS allowlist only if you intend browser usage.

#### F-014 [Metrics] Exceptions are not recorded in HTTP request metrics

- Severity: MEDIUM
- Location: `sage_api/middleware/metrics.py:35-45`
- Problem: On exception, active is decremented but no request_total/duration is recorded.
- Impact: Under-counted error traffic; missing latency for failures.
- Recommendation: Record metrics in a finally block with a synthetic status_code or error label.

### LOW

#### F-016 [Testing Gap] Lifespan and error-handler behavior are under-tested

- Severity: LOW
- Location: `tests/test_main.py:90-104`, `tests/test_auth.py:22-70`
- Problem: Tests note ASGITransport does not run lifespan; auth tests assert default FastAPI error shapes (not the app's custom exception handlers).
- Impact: Startup/shutdown regressions and error-shape regressions slip through.
- Recommendation: Add an integration test that actually runs lifespan and asserts the ErrorResponse shape produced by `add_exception_handlers()`.

#### F-017 [Code Smell] Hot reload docstring/comment is stale

- Severity: LOW
- Location: `sage_api/services/hot_reload.py:86-88`
- Problem: Comment says reload is called synchronously, but code uses `asyncio.to_thread`.
- Impact: Confusing maintenance.
- Recommendation: Update docstring/comments to match behavior.
