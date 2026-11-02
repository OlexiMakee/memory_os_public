# Audit: LLM Layer

Scope:
- `src/memory_os/llm/gateway.py`
- `src/memory_os/llm/routing.py`
- `src/memory_os/llm/base.py`
- `src/memory_os/llm/providers/mlx_provider.py`
- `src/memory_os/llm/providers/ollama_provider.py`
- `src/memory_os/llm/providers/openai_compatible_provider.py`

Focus areas reviewed:
- Caller-controlled OpenAI-compatible / Ollama endpoints and SSRF risk, especially `169.254.169.254`.
- API key logging, printing, or exception-message exposure in this layer.
- HTTP timeout coverage.
- `routing.py` dynamic import / class-name construction from caller-controlled strings.
- Whether `gateway.py` is wired into live code or effectively dead.

## Findings

### 1. OpenAI-compatible provider accepts arbitrary `base_url` and will send requests and bearer credentials to it

- Severity: medium
- File: `src/memory_os/llm/providers/openai_compatible_provider.py:15`
- Code path verified: `OpenAICompatibleProvider.__init__()` accepts caller-supplied `base_url` and passes it directly to `OpenAI(base_url=base_url, api_key=api_key)` at `src/memory_os/llm/providers/openai_compatible_provider.py:18-21`. `generate()` then calls `self.client.chat.completions.create(**kwargs)` at `src/memory_os/llm/providers/openai_compatible_provider.py:45`.
- Confirmed exploit/repro scenario: constructing this provider with `base_url="http://169.254.169.254/latest/meta-data"` is accepted; the OpenAI client normalizes it to `http://169.254.169.254/latest/meta-data/`. A call to `generate()` would POST the chat-completions request under that configured origin. A local HTTP-server repro with `base_url=http://127.0.0.1:<port>/custom-root` confirmed that `generate()` sends a POST to the configured origin path and includes `Authorization: Bearer <api_key>` in the outbound request. Therefore, if this provider is wired to user/admin-supplied configuration in a cloud runtime, it becomes an SSRF primitive that can reach the link-local metadata address and can also disclose the configured API key to any attacker-controlled endpoint.
- Practical wiring note: this provider is not currently used by the CLI routing path. The only in-repo construction found is `run_llm_benchmark.py:31`, with a fixed `http://localhost:8000/v1` URL. That limits current exploitability, but the provider itself is unsafe as a reusable abstraction.
- Suggested fix: add the same kind of URL validation already present in `src/memory_os/adapters/vllm_provider.py`: allow only `http`/`https`, require a host, reject `169.254.0.0/16`, and consider rejecting loopback/private ranges unless explicitly enabled for local development. Also require a short explicit timeout when constructing the OpenAI client.

### 2. Ollama provider accepts arbitrary `host`, enabling the same internal-network request primitive

- Severity: medium
- File: `src/memory_os/llm/providers/ollama_provider.py:15`
- Code path verified: `OllamaProvider.__init__()` accepts caller-supplied `host` and passes it directly to `ollama.Client(host=host)` at `src/memory_os/llm/providers/ollama_provider.py:18`. `generate()` then calls `self.client.chat(...)` at `src/memory_os/llm/providers/ollama_provider.py:41-48`.
- Confirmed exploit/repro scenario: constructing an `ollama.Client(host="http://169.254.169.254")` is accepted by the installed Ollama Python client and creates an underlying `httpx.Client` with `base_url http://169.254.169.254`. With the audited provider, a later `generate()` call would POST Ollama's chat request to that configured host. In a cloud runtime where this host comes from configuration that an attacker or lower-privileged user can influence, the provider can reach the link-local metadata endpoint or other internal HTTP services.
- Practical wiring note: no CLI/API path currently passes user input into this provider. The in-repo benchmark constructs `OllamaProvider()` with the default localhost host at `run_llm_benchmark.py:23`, so the current live surface is limited.
- Suggested fix: validate `host` before creating the client. Keep `localhost` as the default, but reject link-local metadata ranges such as `169.254.0.0/16`; consider an explicit allowlist for remote Ollama hosts if remote serving is intended.

### 3. Ollama provider has no timeout, so a malicious or broken endpoint can hang indefinitely

- Severity: medium
- File: `src/memory_os/llm/providers/ollama_provider.py:18`
- Code path verified: the provider constructs `ollama.Client(host=host)` without passing a `timeout` at `src/memory_os/llm/providers/ollama_provider.py:18`, then performs the blocking request at `src/memory_os/llm/providers/ollama_provider.py:41-48`. The installed Ollama client's `BaseClient.__init__` defaults `timeout=None` and passes that into `httpx.Client`; local introspection of `ollama.Client(host="http://169.254.169.254")._client.timeout` returned `Timeout(timeout=None)`.
- Confirmed failure scenario: set `host` to an HTTP server that accepts the TCP connection and never sends a response, then call `OllamaProvider.generate()`. Because the underlying httpx read timeout is `None`, the caller can block forever waiting for `self.client.chat()` to return. This can wedge `run_llm_benchmark.py` or any future gateway-backed worker thread/process that uses this provider.
- Suggested fix: add a bounded timeout parameter to `OllamaProvider.__init__()` and pass it into `ollama.Client(host=host, timeout=timeout)`. Use a conservative default such as 30-60 seconds, with a documented override for long local generations.

### 4. Eager MLX import can abort the process when importing unrelated provider modules

- Severity: high
- File: `src/memory_os/llm/providers/mlx_provider.py:5`
- Code path verified: `mlx_provider.py` imports `from mlx_lm import load, generate` at module import time and catches only `ImportError` at `src/memory_os/llm/providers/mlx_provider.py:5-9`. The provider package also eager-imports `MLXProvider` from `src/memory_os/llm/providers/__init__.py:3`, so a normal import such as `from memory_os.llm.providers.openai_compatible_provider import OpenAICompatibleProvider` first executes the package `__init__` and imports MLX.
- Confirmed failure scenario: in this environment, `mlx_lm` is installed but aborts during native Metal initialization with an uncaught `NSRangeException` (`index 0 beyond bounds for empty array`). Running `PYTHONPATH=src python3 -c "from memory_os.llm.providers.openai_compatible_provider import OpenAICompatibleProvider"` terminated the Python process with exit code 134 before the OpenAI-compatible provider could be imported. The same failure blocks `run_llm_benchmark.py`, because it imports provider submodules through the package path.
- Suggested fix: remove eager provider imports from `src/memory_os/llm/providers/__init__.py`, or implement lazy exports. Also defer the `mlx_lm` import until `MLXProvider.__init__()` so importing unrelated providers cannot initialize MLX. If MLX construction is attempted, convert supported Python exceptions into a controlled unavailable-provider error; native aborts may require a preflight capability check or process isolation.

## Files With No Confirmed Issues

### `src/memory_os/llm/gateway.py`

No confirmed direct issue found in the gateway implementation itself. It stores registered providers by `provider.name` and dispatches to `provider.generate(request)`.

Wiring note: `gateway.py` is effectively not part of the live CLI/provider path today. Repo-wide search found `LLMGateway` exported from `src/memory_os/llm/__init__.py`, constructed in `run_llm_benchmark.py:17`, and discussed in docs/audit context, but no production CLI or core service path constructs `LLMGateway`, registers providers, or calls `gateway.generate()`. `DEV_STRATEGY.md:1252-1270` correctly describes this abstraction as currently unused/dead except for the standalone benchmark script. `routing.py` is live through `src/memory_os/core/routing_policy.py:186`.

### `src/memory_os/llm/routing.py`

No confirmed dynamic-import injection issue found. `LLMRouter.route()` compares `task_type` against fixed in-code sets and returns static `RuntimeDecision(provider, model, reason)` values. It does not import modules, shell out, use `getattr()` on caller input, construct class names, or instantiate providers.

### `src/memory_os/llm/base.py`

No confirmed issue found. The file only defines the abstract `LLMProvider.generate()` contract and a default `healthcheck()` returning `True`; there is no network, credential, import, or routing behavior here.

### `src/memory_os/llm/providers/openai_compatible_provider.py`

No confirmed API-key logging, printing, or exception-message inclusion was found in this file. It does not log or print. It does pass the configured API key to the OpenAI client, which sends it as an authorization credential to the configured base URL; that is covered in Finding 1 as endpoint validation risk, not local logging.

No confirmed indefinite hang was found for the installed OpenAI client path: local introspection of `OpenAI(base_url=..., api_key=...)` showed the SDK default timeout as `Timeout(connect=5.0, read=600, write=600, pool=600)`. The repo code does not set its own explicit timeout, so relying on the SDK default is still weaker than the fixed `timeout=5` pattern in `adapters/vllm_provider.py`, but I did not verify a forever-hang condition for this provider.

### `src/memory_os/llm/providers/ollama_provider.py`

No confirmed API-key logging, printing, or exception-message inclusion was found in this file. It does not log or print. Note that the installed Ollama client may add `Authorization: Bearer <OLLAMA_API_KEY>` from the environment internally; combined with arbitrary `host`, that can send the key to a configured endpoint, but the audited file itself does not log or print it.

### `src/memory_os/llm/providers/mlx_provider.py`

No confirmed HTTP SSRF, API-key logging, or HTTP timeout issue found. This provider is local inference only and performs no HTTP calls in the audited code. Its confirmed import-time availability issue is covered in Finding 4.

## VERDICT

4 issues found (1 critical/high)
