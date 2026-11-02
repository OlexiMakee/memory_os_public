# Adversarial Security and Correctness Audit: Adapters Bridge

Scope:
- `src/memory_os/adapters/pydantic_ai_bridge.py`
- `src/memory_os/adapters/vllm_provider.py`
- `src/memory_os/adapters/mcp_adapter.py`
- `src/memory_os/adapters/temporal_adapter.py`

Review constraints honored:
- No source files under `src/` were edited.
- Findings below are limited to issues confirmed by reading the code paths involved and, where possible, by local isolated repros using temporary stub packages outside `src/`.

## Findings

### 1. Untrusted `base_url` can drive outbound requests to arbitrary internal or metadata endpoints

- File: `src/memory_os/adapters/vllm_provider.py:55`
- Severity: medium
- Code path verified:
  - `VLLMProvider.__init__()` stores caller-supplied `base_url` without validation at `src/memory_os/adapters/vllm_provider.py:38`.
  - `complete()` passes that value directly to `openai.OpenAI(base_url=self.base_url, timeout=5)` at `src/memory_os/adapters/vllm_provider.py:55`.
  - `complete()` then performs a network request through `client.chat.completions.create(...)` at `src/memory_os/adapters/vllm_provider.py:60`.
- Concrete exploit/repro scenario:
  - If any CLI, MCP tool, config loader, web route, or future automation path passes attacker-controlled input into `VLLMProvider(base_url=...)`, the attacker can set `base_url` to an internal target such as `http://169.254.169.254/latest/meta-data`, `http://127.0.0.1:2375/v1`, or another service reachable only from the host.
  - Calling `VLLMProvider(attacker_url).complete("hello")` will issue an OpenAI-compatible POST request to that host. The request path is expected to be the chat completions path under the configured base URL, but the host and scheme are not constrained.
  - I confirmed the adapter stores arbitrary URLs unchanged through `audit()` and passes `base_url` unchanged into the OpenAI client constructor. The current repo call sites I found only instantiate `VLLMProvider()` without a base URL for audit/testing, so this is exploitable when a caller wires untrusted or semi-trusted configuration into this adapter.
- Suggested fix:
  - Parse `base_url` with `urllib.parse.urlparse()` before constructing the OpenAI client.
  - For the default local-inference-server mode, allow only `http`/`https` URLs whose hosts are loopback names or loopback IPs, for example `localhost`, `127.0.0.0/8`, and `::1`.
  - Explicitly reject link-local metadata ranges such as `169.254.0.0/16`, private network ranges unless an `allow_remote=True` or explicit host allowlist is configured, non-HTTP schemes, empty hosts, credentials in the URL, and redirects to disallowed hosts if the underlying client follows redirects.
  - Treat remote vLLM endpoints as an explicit advanced configuration, not the default interpretation of a caller-supplied string.

Notes on timeout review:
- I did not find a confirmed infinite hang in `complete()`.
- The adapter passes `timeout=5` into `openai.OpenAI(...)` at `src/memory_os/adapters/vllm_provider.py:58`.
- In the installed OpenAI client (`2.41.1`), the constructed client reports `timeout == 5` and `max_retries == 2`; this means a slow network path can take longer than five seconds overall because retries are enabled, but each OpenAI-client request is still configured with a finite timeout.
- A direct test against a non-routable URL in this sandbox returned cleanly with `{"ok": False, ...}` in about 2.34 seconds. A local slow HTTP server test could not be run because the sandbox denies binding a listening socket.

### 2. MCP least-privilege policy is only declared, not enforced by any tool-call path

- File: `src/memory_os/adapters/mcp_adapter.py:68`
- Severity: medium
- Code path verified:
  - `manifest()` builds a list of allowed tools and denied tools at `src/memory_os/adapters/mcp_adapter.py:45`.
  - `serve(dry_run=True)` returns that manifest and text saying it "would start" a server at `src/memory_os/adapters/mcp_adapter.py:68`.
  - `serve(dry_run=False)` imports `mcp` if available, deletes the import, and returns `{"ok": False, "detail": "real MCP server loop not implemented in this stage"}` at `src/memory_os/adapters/mcp_adapter.py:81`.
  - The CLI `mcp serve --write` path calls `mcp_adapter.serve(dry_run=not args.write)` from `src/memory_os/cli.py:657`.
- Concrete failure scenario:
  - The regression test text says `mcp_adapter manifest enforces least-privilege (writes need approval, dangerous tools denied)`, but the actual adapter has no dispatcher, no server registration, no approval gate, and no function that checks an incoming tool name against `_ALLOWED_TOOLS` or `_DENIED_TOOLS`.
  - With `mcp` absent in this environment, `PYTHONPATH=src python3 -m memory_os mcp serve --write --format json` returns `{"ok": false, "detail": "mcp package not installed"}`.
  - With a temporary stub `mcp` package injected so `is_available()` is true, `mcp_adapter.serve(dry_run=False)` returns `{"ok": False, "detail": "real MCP server loop not implemented in this stage"}`.
  - Therefore the manifest is a policy document, not an enforcement mechanism. I found no current code path that lets a caller construct a tool call and bypass the denial list, because there is no implemented tool-call path at all.
- Suggested fix:
  - Add a single policy-enforcement function, for example `authorize_tool_call(tool_name: str, approved: bool = False)`, that rejects unknown and denied tools before any handler executes.
  - Make the real MCP server registration call this guard for every incoming tool request.
  - For write-capable tools such as `propose_memory_update`, require an explicit approval token/state before dispatching.
  - Change tests so they exercise denial of `arbitrary_shell`, `secret_read`, `network_fetch`, unknown tool names, and unapproved write tools through the actual dispatch/authorization path, not just by reading the manifest.
  - Until the server exists, keep CLI/help/test wording precise: "declares least-privilege manifest" rather than "enforces least-privilege."

### 3. Temporal timeout guard can return from `mirror_run()` but still leave a non-daemon thread that keeps the process hung

- File: `src/memory_os/adapters/temporal_adapter.py:65`
- Severity: high
- Code path verified:
  - `mirror_run()` creates a normal `threading.Thread(target=worker)` at `src/memory_os/adapters/temporal_adapter.py:65`.
  - Python threads are non-daemon by default when created from the main thread.
  - The worker creates an event loop and calls `new_loop.run_until_complete(asyncio.wait_for(_connect_with_timeout(), timeout=2.0))` at `src/memory_os/adapters/temporal_adapter.py:56`.
  - The caller waits with `t.join(timeout=3.0)` at `src/memory_os/adapters/temporal_adapter.py:67`.
  - If the worker is still alive, `mirror_run()` returns a timeout error at `src/memory_os/adapters/temporal_adapter.py:69`, but it does not cancel, stop, daemonize, or otherwise terminate the still-running thread.
- Concrete failure scenario:
  - If `temporalio` is installed and `Client.connect(self.target_host)` blocks the event loop before yielding back to asyncio, `asyncio.wait_for(..., timeout=2.0)` cannot fire. This is a realistic class of failure for native transport, DNS, resolver, or library bugs; the outer thread join is meant to defend against exactly this kind of hang.
  - I reproduced the failure mode with a temporary `temporalio.client.Client` stub whose async `connect()` blocks with `time.sleep()` in an infinite loop. `mirror_run()` printed `{'ok': False, 'detail': 'temporal mirror failed: connection attempt timed out'}`, but the child Python process did not exit and had to be killed by a 5-second parent-process timeout.
  - This means the double guard prevents the function body from waiting forever, but it does not prevent the host process from hanging after the function returns.
- Suggested fix:
  - Do not rely on an unkillable non-daemon thread as the hard timeout boundary.
  - Prefer Temporal SDK connection options that enforce a real transport/connect RPC timeout, if available, and keep the operation in one event loop.
  - If a thread fallback remains necessary, create it as `threading.Thread(target=worker, daemon=True)` so a stuck connection attempt cannot keep the process alive. Also record this as best-effort only because daemon threads can leak until process exit.
  - For a hard isolation boundary, run the connection attempt in a subprocess and terminate the subprocess on timeout.
  - Add a regression test with a fake `temporalio.client.Client.connect()` that blocks the event loop and assert that the parent process exits within the timeout budget.

### 4. Contract validation accepts unexpected extra keys as valid contract shape

- File: `src/memory_os/adapters/pydantic_ai_bridge.py:25`
- Severity: low
- Code path verified:
  - `validate_contract()` defines a local Pydantic `Contract` model with required fields at `src/memory_os/adapters/pydantic_ai_bridge.py:25`.
  - It calls `Contract(**contract)` at `src/memory_os/adapters/pydantic_ai_bridge.py:39`.
  - With Pydantic v2 default model configuration, extra fields are ignored rather than rejected.
- Concrete failure scenario:
  - With a temporary stub `pydantic_ai` package to force the validation branch, I passed a contract containing every required field plus an unexpected key:
    - `unexpected_network_instruction: "exfiltrate secrets"`
  - `validate_contract()` returned `{"ok": True, "detail": "validated", "errors": []}`.
  - If a caller treats `ok=True` as proof that the original dictionary has only the canonical contract-builder shape, that caller can accidentally preserve and forward unexpected untrusted fields after validation.
- Suggested fix:
  - For Pydantic v2, add `model_config = ConfigDict(extra="forbid")` to the `Contract` model and import `ConfigDict`.
  - If Pydantic v1 compatibility is required, add an inner `Config` with `extra = "forbid"` or a version-compatible equivalent.
  - Add a test that a valid contract plus one unknown key returns `ok=False` with a validation error.

Notes on "never raises" review:
- I did not find a confirmed raise from malformed ordinary inputs.
- With the pydantic branch forced on, these inputs all returned dictionaries instead of raising out of `validate_contract()`:
  - bad-shape dict: `{"bad": "shape"}`
  - non-mapping list: `[]`
  - recursive dict value: `r = {}; r["feature_id"] = r`
  - valid required fields plus a large nested extra object
- The issue above is not that the function raises; it is that one malformed shape is accepted as valid.

## Files With No Additional Confirmed Issues

### `src/memory_os/adapters/vllm_provider.py`

- No confirmed infinite hang in `complete()` from the reviewed code path.
- `timeout=5` is passed to the OpenAI client constructor.
- The installed OpenAI client has finite default retries (`max_retries == 2`), so total wall time may exceed five seconds but is not unbounded in the normal client path.

### `src/memory_os/adapters/mcp_adapter.py`

- No current tool-call bypass was found.
- The reason is not that the denial list is strongly enforced; the reason is that there is no implemented tool-call path or real MCP server loop in this adapter yet.

### `src/memory_os/adapters/temporal_adapter.py`

- No additional confirmed issues beyond the non-daemon-thread hang described above.

### `src/memory_os/adapters/pydantic_ai_bridge.py`

- No confirmed case where `validate_contract()` raises out to the caller for ordinary malformed dict/list/recursive-value inputs tested through the actual validation branch.

VERDICT: 4 issues found (1 critical/high)
