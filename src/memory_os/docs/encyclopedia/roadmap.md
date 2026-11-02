# Memory OS: Global Roadmap & Memory Runtime (Proposal Evaluation)

Цей документ містить критично переглянутий глобальний роадмап розвитку Memory OS на базі пропозиції розширення memory runtime.

## 1. Аналіз сумісності з архітектурою
Пропозиція добре відповідає ключовим принципам Memory OS:
* **Local-first & LLM speaks little**: Пропозиція закріплює пріоритет детермінованих інструментів над LLM.
* **Dependency Inversion (DIP)**: Запропоновані інтерфейси (`IDomainAdapter`, `IRelationSchema`, `IGraphIndex`) є логічним продовженням `interfaces.py`.
* **Resource Politeness**: Hardware Profiles є розвитком існуючих `resource_mode` (`quiet`, `normal`, `max`).

### Критичні зауваження
1. **Складність міграції схем**: Запропонована універсальна схема вузлів та ребер вимагає глибокого рефакторингу поточних `MemoryNode` та `MemoryEdge`.
2. **Передчасна оптимізація апаратних профілів**: Створення `IHardwareScheduler` має сенс лише після реалізації багатопроцесорності (Phase 14). До цього часу поточні режими `resource_mode` є достатніми.
3. **SQLite як Graph Index**: Використання SQLite для ієрархії, retrieval і аудиту значно прискорить роботу, але вимагає зміни механізмів читання — зараз читається JSONL, а SQLite використовується лише для телеметрії. Це фундаментальний зсув.

## 2. Найвдаліші рішення для імплементації (Запам'ятовано)
1. **Relation Contract Registry (P0-P13 Mapping)**: Ідея прив'язати конкретні типи зв'язків (наприклад, `caused_by`, `reads_from`) до рівнів протоколу (P0-P13) для контролю доступу (min_create_protocol, min_verify_protocol) є геніальною. Вона формалізує 12-рівневу філософію.
2. **Domain Adapters (`IDomainAdapter`)**: Дозволить Memory OS вийти за межі кодової бази і працювати з іншими джерелами (документи, історія) без ускладнення ядра.
3. **Relation Patch System**: Усі зміни в графах відбуваються через патчі з фіксацією протоколу ініціатора та валідатора, замість прямого запису. Це підвищить безпеку графу від галюцинацій LLM.
4. **Індексація в SQLite**: Створення таблиць `graph_nodes` та `graph_edges` паралельно з еталонним збереженням в JSONL є оптимальним балансом між швидкістю та аудитом.

## 2.1. Стратегічна корекція позиціонування
Після аналізу критики і поточної архітектури фіксуємо:
* **Memory OS не продається як пошуковий інструмент**. Це локальний runtime довготривалої пам'яті для агентів.
* **Граф — механізм, не продукт**. Користувачеві важливі lifecycle, provenance, curation, retrieval quality і repeatable state, а не сам факт наявності графа.
* **Code understanding і memory — різні шари**. `grep`/AST/LSP мають бути детермінованими адаптерами для кодової бази, а не основною обіцянкою системи.
* **LLM має обробляти семантику, а не будувати те, що можна порахувати детерміновано**. AST/metadata/link inference/FTS — first-class inputs; semantic merge і conflict resolution — точка, де LLM доречна.
* **Нативна пам'ять середовища розробки не є стратегічним бенчмарком**. Memory OS тримає міжсесійну, аудиторну, явну пам'ять з історією змін.
* **SOLID, Unix і portability — не декоративні принципи**. Вони визначають межі модулів, CLI-контракти, спосіб пакування і можливість використати окремо memory engine, swarm runtime або UI без підтягування всього продукту.
* **Linux-first не означає Linux-only**. Linux/Ubuntu є робочим прискорювачем для нас зараз, macOS має лишатися first-class ціллю для core/CLI/runtime, а Windows відкладається до зрілого продуктового етапу з окремими платформними адаптерами.

## 3. Фази імплементації (Оптимізований порядок)
* **Phase 1: Memory integrity first** — весь write-path через `RelationPatchStore`, legible history, `health`, `curate`, `merge-preview`/`merge-apply`, і node-level confidence/eval-gates перед promotion.
* **Phase 2: Deterministic domain adapters** — виділити `CodebaseDomainAdapter` та інші адаптери для AST/grep/LSP/metadata, щоб кодова навігація не змішувалась із memory core.
* **Phase 3: Retrieval quality loop** — layered retrieval, retrieval evals, and confidence thresholds tuned against measurable recall/precision, not intuition.
* **Phase 4: Memory maintenance automation** — semantic deduplication, incremental stale-index repair, and repeatable curation; graph health is part of the product surface.
* **Phase 5: Optional storage/index backends** — SQLite graph mirror for speed/audit where it helps, but JSONL remains the source of truth until measurements prove otherwise.
* **Phase 6: Resource optimization** — hardware scheduling, multiprocessing, caching, and other runtime tuning only after the core memory loop is stable.

### 3.1. Implementation checkpoint — 2026-07-02
* **Phase 1 integrity gate advanced**: `RelationPatchStore` now enforces `RelationContractRegistry` by default for edge creation/deletion; unknown relation types and under-protocol semantic edges fail before they reach canonical graph state.
* **Patch-path release gate added**: `release-check` now includes `graph-write-path`, a static hard gate that rejects direct writes to live `nodes.jsonl`/`edges.jsonl` outside `MemoryRepository`/patch-backed mutation paths while allowing archive/event/snapshot writes.
* **Deterministic adapter boundary started**: dependency traversal and reverse-dependency blast-radius logic moved behind `CodebaseDomainAdapter`; `MemorySearcher` delegates instead of owning codebase matching rules.
* **Domain adapter runtime path added**: `DomainAdapterRegistry` selects deterministic adapters for metadata and patch extraction, while `DomainAdapterIngestor` applies adapter output through `RelationPatchStore` instead of direct JSONL writes.
* **Codebase patch IDs hardened**: `CodebaseDomainAdapter.parse_to_patches()` now emits validator-safe file/class/function/module node IDs and creates module nodes for imported dependencies before writing `depends_on` edges.
* **Graph map logic moved behind adapter boundary**: dependency graph construction, god-node ranking, module clustering, cluster node creation, and cluster-to-memory `contains` edge inference now live in `CodebaseDomainAdapter`; `GraphMapper` is reduced to orchestration, markdown output, and optional graph emission.
* **Current gate state**: private `release-check` passes, full pytest suite passes.

### 3.2. Implementation checkpoint — 2026-07-04 (нічна зміна claude+codex)
* **Phase 1 закрита по обох залишках R2**: (R2.2) node-level confidence/eval-gate — `confidence` на нодах, промоція лише вище `memory.confidence_threshold` (default 0.7); hard-порушення → `stale`, low-confidence → HOLD у `draft`; явні `LifecycleManager.promote()`/`reject()`. (R2.3) весь lifecycle write-path (`propose`/`transition`/`promote`/`reject`) — через `RelationPatchStore.propose()+apply()` з patch audit events.
* **Таймлайн-когерентність**: `user_timezone` у конфізі; `ts=` у заголовках SWARM/Telegram-доставки; `now:` + відносний час `(5m ago)` у `inbox`/`feed`; `memory normalize-timecodes` вирівняв 331 ноду / 2864 події до ISO з offset; offset-aware значення канонічні (ніколи не переписуються — ідемпотентність поруч з UTC-писарями); нові write-paths пишуть offset-aware local time.
* **Phase 3 стартувала**: confidence-aware ранжування пошуку в усіх трьох шляхах (FTS/fuzzy/embedding), `score *= 0.5+0.5*confidence`; retrieval-relevance eval без регресії (0.92); розширення eval-набору виконано: 22 кейси, precision@5 поряд з recall@5 (baseline 0.25/1.00), негативні кейси охороняють downranking; R2.5 events.jsonl soft-limit сигнал у DiskGuard; `memory write` — агентський запис фактів через lifecycle gate.
* **Runtime/оптимізації**: quantizer-derived `[EFFORT tier L<n>]` у кожній swarm/telegram задачі; quota_harvester (точні % codex з rollout-файлів, пасивний збір лімітів agy/claude, idle-gated `/usage` probe); inbox read-cursor + `comm read` + `feed --new` (економія ~1.5k токенів на wake-up); ротація журналів з ребейзом курсорів; `MultiplexerAgentTransport` з чесним runtime-імʼям; health probe без pane-скану.
* **Runtime hardening додано**: daemon `watchdog_limits` і `agent-manager --status` пасивно сканують live-консолі агентів (`AgentConsoleScanner`) і оновлюють quota/health state по strict/delta limit-подіях; inbox cursor self-heal fast-forwardить пошкоджений або out-of-range cursor до кінця hot-файлу; `agent-manager --restart-all` / `--shutdown-all` стали єдиною user-facing точкою для restart/shutdown core daemon, Telegram daemon і workspace runtime.

### 3.3. Implementation checkpoint — 2026-07-05 (odysseus-спринт + автономний нагляд)
* **Phase 4 maintenance повністю закрита**: semantic dedup (deterministic `get_dedup_candidates`, попередній чекпоінт) + **incremental stale-index repair** — застосований `RelationPatch` тепер оновлює лише зачеплені рядки FTS (`graph_nodes` тригери) та інвалідує embedding-кеш точково; повний `sync_sqlite` більше не викликається на кожну мутацію.
* **UI став продуктовою поверхнею графового health** (Phase 4 "graph health is part of the product surface"): 2D/3D перемикач візуалізації (force-graph + 3d-force-graph), Memory-панель (timeline по локальних датах, pin/edit/delete через patch store, export), REST API канонізовано (`/api/nodes/*`, `/api/edges/*`); всі UI-мутації через `MemoryGraphService` + `RelationPatchStore`.
* **Автономний нагляд**: 1-токенні quota-пінги з телеграм-сповіщеннями про відновлення лімітів (liveness через STATUS_REPORT після `limit_seen_at`, once-per-episode); `TaskKernel.expire_stale` (чат-таски >24h, щогодинний `task_gc`); telegram-daemon наглядає за core daemon (авто-рестарт + алерт; демон до цього пролежав мертвим 4 доби непоміченим); shutdown-фікс polling loop (`should_stop`).
* **Daemon hardening backlog — закрито 2026-07-13**: task lease watchdog, JSONL/patch-audit budget guard, взаємний core/Telegram watchdog, inbox-lag watchdog, resource guard preflight і runtime session reconciler — **зроблено**. `snapshot_runtime_health()` детектує ghost-пейни за нормалізованим executable; `reconcile_agent_panes()` відновлює `codex`/`agy` через спільний `RuntimeControl.restart_pane()` із 5-хвилинним cooldown. `claude` навмисно protected: daemon лише пише warning, бо автоматичний перезапуск orchestrator може обірвати координацію активної задачі.
* **Daemon housekeeping foundation додано**: core daemon раз на хвилину пише `agent_context/agents/runtime_health.json` (truth-cache по session/panes/agent activity) і `agent_context/agents/relay_watch.json` (lag по `done/` та stale leases). `agent-manager` читає цей cache першим, тому статус агентів більше не залежить лише від випадкового live-scan у момент відкриття TUI.
* **Future runtime backend contract**: zellij лишається default runtime, але Memory OS має готувати backend-агностичні інтерфейси під `herdr`. Розділити треба `workspace/session`, `pane`, `agent-status`, `event-subscription`, `restore`, `send-input`, `read-output`, щоб `agent-manager`, `daemon_hygiene` і swarm/Telegram не були прив'язані до zellij-only id semantics. Herdr тут не міграційна ціль, а другий backend для майбутньої глибшої інтеграції. Позиція підтверджена agy-аудитом `task_herdr_roadmap_audit_20260706`: копіювати event subscription і restore/session model; zellij-specific лишити KDL/layout, WASM plugins, pane id parsing; не overfit-итись під herdr socket protocol, бо це ламає Unix/fallback простоту.
* **Zellij live transport incident**: sandboxed Codex процеси (`bwrap --unshare-pid`) не мають валідного active zellij action context, тому `zellij action list-panes/paste/send-keys` з sandbox падає `There is no active session`, хоча session socket існує і unsandboxed `zellij action list-panes` працює. Висновок для roadmap: live multiplexer delivery має виконуватись daemon-owned/unsandboxed або мати чесний file-only fallback; не вважати `comm.sent` доказом live wake-up без відсутності `comm.failed`.
* **Skill OS foundation — повністю закрито**: repo-local `skills/` pack + `memory_os skills list|validate|sync` + всі 4 пункти "наступного етапу" зроблено: remote source/ref/sub-dir pinning (`SOURCE.toml` + `skills refresh`), `skills.lock` як commit-friendly manifest (`memory_os skills lock`), managed instruction blocks (auto-інжекція переліку скілів у `AGENTS.md` між `MEMORY_OS SKILLS BLOCK` маркерами, ідемпотентно), `commands/`+`mcp/` як типізовані validated resource kinds. Каталог розширено 4 адаптованими з NousResearch/hermes-agent скілами (`systematic-debugging`/`plan`/`simplify-code`/`requesting-code-review`) — консюмерські/персонал-асистентські скіли Hermes (apple/smart-home/social-media/creative) свідомо не взято, суперечить стратегії "не розширювати зовнішні адаптери".
* **Retrieval quality (Phase 3, 2026-07-13)**: `eval_runner.py` precision@5 ділив на фіксовані 5 замість фактичної кількості повернутих результатів — структурно обмежував single-answer запити до 0.2 навіть при ідеальній відповіді; виправлено на стандартну IR-формулу. `link_inferrer.py`'s bm25-евристика класифікувала `refutes` (protocol 7, рівень довіри supersedes/overrides) лише за regex-збігом слова "override"/"deprecate" — підтверджено живу шкоду (застейлило 3 verified вузли); гілку прибрано повністю. Результат: retrieval-relevance pass_rate 0.77→1.0, precision@5 0.19→0.76. Source-symbol indexing закрито командою `memory_os codebase index`: `DomainAdapterIngestor` проходить `src/**/*.py`, а nodes/edges застосовуються двома bounded bulk patch-ами через `RelationPatchStore`; dry-run на поточному repo: 171 файл, понад 7k semantic operations.
* **`models recommend`**: hardware-aware підбір локальних моделей (RAM/VRAM/CPU детект, статичний каталог, fit/tight/no-fit з рекомендованим контекстом) — адаптація Cookbook-ідеї з odysseus.
* **Odysseus-вердикт**: memory-бекенд odysseus (плаский текстовий стор) слабший за наш граф — взято лише REST-поверхню та UI-патерни; Deep Research поза стратегією; Cookbook реалізовано.
* **Gate state**: 309 passed, private release-check OK; спроба env-байпаса eval-gate у release-check відхилена на ревʼю (гейти не послаблюються заради тестів).

### 3.4. Implementation checkpoint — 2026-07-13 (quota/runtime revision, claude+codex, 3 раунди аудиту)

* **Codex quota tracking закрито наскрізь**: `refresh_quota_state` більше не лишає застарілий `has_limit=True` після чистого оновлення; `read_codex_rate_limits()` — новий авторитетний шлях через read-only Codex app-server JSON-RPC (`account/rateLimits/read`) в ізольованому короткоживучому subprocess (5с timeout, гарантований terminate/kill, не чіпає живий codex-пейн), rollout-парсер лишається fallback-ом.
* **False-positive pane-scan клас закрито**: усі три незалежні шляхи сканування (`agent_console_scanner.py`, `agent_health.py`, `agent_state_monitor.py`) уніфіковано на `extract_limit_event(strict=True)` — розмовні згадки "rate limit"/"quota exceeded" (наприклад, у власних коміт-повідомленнях про цю ж роботу) більше не мутують health/quota стан.
* **`attempt_model_switch()` видалено повністю**: раніше автоматично інжектив `/model`+Down+Enter у живий пейн агента при вичерпанні квоти; також хардкодив `subprocess.run(["tmux", ...])` безумовно, ігноруючи `MultiplexerManager` — вже був зламаний під zellij. Заміна: сповіщення "перемкніть вручну". Одночасно і safety-, і correctness-фікс.
* **`daemon_hygiene.py` ghost-detection виправлено**: `_agent_pane_alive` порівнював `pane.current_command` (повний command line запуску) точним рядком проти голого імені бінарника — живі агентські пейни могли хибно позначатись мертвими. Тепер `shlex.split(...)[0]` + `Path(...).name`.
* **`memory_os daemon stop` тепер верифікує реальну смерть процесу**: ескалація IPC→confirm→SIGTERM→confirm→SIGKILL→confirm (~12с bounded) замість негайного рапорту успіху одразу після відправки сигналу.
* **Gate state**: 422 passed, release-check OK. Відкриті дрібниці: ізольований тест на daemon-stop escalation ladder (наразі лише жива верифікація), окремого `test_agent_limits.py` немає.

### 3.5. SOLID/Unix/Portability audit — 2026-07-15 (повна ревізія коду за вказівкою Олексія)

Повний аудит 171 файлу/43k рядків на SOLID/Unix-контракт/дублікати/хардкодинг, 4 паралельні
домен-аудити (toolkit/, core/, modules/, cli+adapters+ui). agy розпочав, вичерпав квоту
без збережених результатів; продовжено та завершено. Повний список 63 знахідок із
пріоритизацією: `audit_2026_07_15_solid_unix.md`. Ключове: реальний crash-баг (dispatch до
`local`-агента), суперечливі хардкоджені zellij pane-мапи, залишкове 212-рядкове дублювання в
`core/adapters.py` (не покрите комітом `07ba4fa`), другий обхідний write-path повз
`RelationPatchStore` (`ingest_project.py`), недетермінований `rglob()`-fallback у
path-confinement функції `ui/data_provider.py`, і той самий клас бага, що й сьогоднішній
prune/pinned інцидент — неузгоджені writer'и одного skill-файлу, один з яких обходить
lifecycle-верифікацію (`exporter.py`/`compactor.py` vs `lifecycle.py`). Виконання по пунктах —
у процесі.

---
*Документ створено за протоколом оцінки великих пропозицій (L12).*

## 5. Список ідей (далека перспектива)

Ідеї, які не входять до поточних фаз але варті збереження для оцінки пізніше.

| Ідея | Суть | Чому не зараз |
|---|---|---|
| **Federated UI** | Memory OS сканує піддиректорії, знаходить інші інстанси (за наявністю `memory_os.config.json`) і відображає їх як read-only spaces в єдиному UI | Поточний "space" — це namespace всередині одного `MemoryRepository`. Федерація потребує окремого шару агрегації, вирішення cross-instance write та trust boundary. Корисна для монорепо, але передчасна без стабільного `IDomainAdapter` шару (Phase 3). |

## 4. Концептуальне позиціонування (Оновлено)
* **Основна формула**: Memory OS = local-first long-term semantic memory runtime for agents.
* **Роль**: Локальний шар довготривалої пам'яті, який зберігає знання явно, аудиторно і відновлювано.
* **Обмеження обсягу**: Сира місткість обмежена диском, але корисна пам'ять визначається якістю lifecycle, provenance, compaction, curation і retrieval.
* **Символьна/Графова пам'ять**: Граф тут не самоціль, а інтерналізація знань у вигляді `node → edge → metadata → evidence → lifecycle → index → retrieval`. LLM не повинна памʼятати все — вона має знати, як запитати Memory OS, а Memory OS має знати, що зберегти, що звести, і що визнати застарілим.
* **Стратегічний наслідок**: будь-який новий модуль оцінюється не за "чи він додає граф", а за тим, чи покращує він достовірність пам'яті, повторюваність результату, контроль змін і вартість підтримки.

---

# Memory OS: Git Memory Chain (RFC-0002) — Roadmap Evaluation

Цей розділ застосовує той самий протокол оцінки великих пропозицій (L12), що й розділ вище про memory runtime roadmap, до RFC-0002 ("Git Memory Chain"). RFC ухвалив рішення (відхилити Git/blockchain-архітектуру, прийняти вузький "legible history" kernel) і вже виконаний — `agent_context/rfcs/0002-git-memory-chain.md` видалений після того, як цей розділ поглинув усе цінне з нього. Нумерація підрозділів — власна, не продовжує нумерацію 1-5 вище.

## R1. Аналіз сумісності з архітектурою

**Сильні сторони пропозиції:**
* Правильний діагноз: пам'ять має бути читабельною історією, не лише поточним станом — і це вже відповідає тому, як побудований Memory OS (`events.jsonl`, `core/patch.py`), просто без формальної назви "event sourcing".
* Принцип "агент ніколи не пише в production-пам'ять напряму, лише пропонує патч" — вже існує як `RelationPatchStore.propose()`/`.apply()`, і `MemoryRepository`'s власні deprecation-попередження (`"{method} is deprecated. Use RelationPatchStore.propose()+apply()..."`) підтверджують, що це вже **цільова** архітектура проєкту, не нова ідея.
* "Versioned commits з explicit promote/reject перед тим, як вважати їх поточними" — уже доведено корисним для LoRA-адаптерів (`AdapterRegistry`); пропозиція справедливо натякає, що той самий патерн варто застосувати і до самих memory-нод.

**Слабкі сторони пропозиції:**
* Hash-chains/цифрові підписи захищають від взаємно недовірливих писачів — модель загроз, якої в цього локального, однокористувацького інструменту немає.
* Branch-per-agent + merge engine вимагає розв'язання "семантичного злиття конфліктів" — нерозв'язаної індустрією дослідницької задачі — для concurrency-потреби, яку `swarm_sync.py` вже закриває файловими лізами, без розгалужень.
* Розподілені публічні репозиторії пам'яті (`memory://ukraine`, ...) — це інший продукт (платформа обміну знаннями), а не підсистема локального інструменту, і необхідний вектор атаки (отруєння "перевірених" публічних фактів) не адресований пропозицією взагалі.
* Суперечить власному Core Decision проєкту (`IMPORTANT_PROPOSAL.md`): "Small core. Rich toolkit. Optional adapters. Local-first discipline."

Повний point-by-point розбір (що саме вже існує під іншою назвою) і причини відхилення кожного великого блоку — вже перенесені нижче й у код; оригінальний документ RFC видалений, бо все цінне з нього тепер тут і в `src/memory_os/modules/history.py`.

## R2. Найвдаліші рішення для імплементації (Запам'ятовано)

1. **Legible history view** — `MemoryHistory.log()`/`.show()`/`.revert()` + CLI `memory log/show/revert`. **Зроблено.**
2. **Node-level confidence/eval-gate перед промоцією** — `MemoryNode.confidence`, config-driven threshold (`confidence_threshold`, default `0.7`), `LifecycleManager.propose_candidate()`/`promote()`/`reject()` і rejection нижче порогу реалізують explicit `candidate → eval → promote/reject` цикл для memory-нод. `transition()` більше не промоутить низько-confidence draft/observed вузли автоматично. **Зроблено.**
3. **RelationPatchStore як єдиний шлях мутації графу** — `LifecycleManager.propose()`/`transition()`/`promote()`/`reject()`/`prune()` тепер проводять graph mutations через `RelationPatchStore.propose()+apply()/apply_many()`; deprecated `MemoryRepository.upsert_node()`/`replace_nodes()` більше не є lifecycle write-path. **Зроблено.**
4. **`memory show` автоматично резолвить "що це замінило"** — зараз показує лише `archived`-вміст самої ноди; поєднання з `overrides`/`refutes`-ребром (уже доступне через `backlinks`) дало б одну команду замість двох. Розглядалося в RFC як заміна `memory diff`; не зроблено, бо досі не виявилось реально незручним вручну.
5. **Event-log-специфічний сигнал у `StorageTierAdvisor`** — `DiskGuard` окремо рахує `memory/events.jsonl`, порівнює його з `memory.events_soft_limit_mb` (default `16`) і віддає advisory щодо archive rotation. Автоматичний prune/rotation не робиться, бо `events.jsonl` є audit source of truth. **Зроблено.**

## R3. Фази імплементації (Оптимізований порядок)

* **Phase 1 (done):** `MemoryHistory` + CLI `memory log/show/revert`.
* **Phase 2 (done):** Node-level confidence/eval-gate. `MemoryNode.confidence` зберігається на вузлі, `RelationPatch.confidence` стає default для node patch, `transition()` промоутить лише вище config threshold, а explicit `promote()`/`reject()` закривають ручний eval цикл.
* **Phase 3 (done):** `LifecycleManager.propose()`/`transition()`/`promote()`/`reject()`/`prune()` використовують `RelationPatchStore.propose()+apply()/apply_many()` для graph mutations; event/history ланцюжок збережено через existing patch audit events + lifecycle events.
* **Phase 4 (done):** `memory show <id>` підтягує дані з `backlinks` автоматично, коли вузол `archived`/`superseded` — показує, що й чому його замінило, в одній команді.
* **Phase 5 (done):** `events.jsonl`-специфічний soft-limit сигнал додано в `DiskGuard`/`StorageTierAdvisor` і `resources snapshot`; це лише advisory для archive rotation, не автоматичний prune audit-журналу.

Кожна фаза незалежна й мінімальна — природна одиниця для делегування підзадачі (наприклад через `scripts/swarm_invoke.py` codex-воркеру), коли прийде час її починати. Не специфіковано заздалегідь у `specs/` — `memory_os spec init "<title>"` варто запускати в момент старту конкретної фази, не зараз про всі одразу.

## R4. Список ідей (далека перспектива, не зараз)

| Ідея | Суть | Чому не зараз |
|---|---|---|
| Розподілені/публічні репозиторії пам'яті (`memory://...`) | Git-подібний clone/push/pull для пам'яті між організаціями | Інший продукт (платформа обміну знаннями), не підсистема локального інструменту; необхідний vector довіри/модерації контенту не спроєктований. Переглянути, лише якщо продуктова ідентичність Memory OS свідомо зміниться в цей бік. |
| Hash-chained events / цифрові підписи | Криптографічна незмінність історії | Захищає від моделі загроз (взаємно недовірливі писачі), якої в цього локального інструменту немає; `manifest.json` SHA-256 уже покриває реальний випадок (виявлення випадкового пошкодження). |
| Branch-per-agent + merge engine | Кожен агент працює у своїй гілці, потім merge | "Семантичне злиття конфліктів" — нерозв'язана дослідницька задача; поточна swarm-конкурентність (кілька локальних CLI-процесів) уже розв'язана простіше через файлові лізи. |
| ~~Embedding staleness tracking~~ | Підтримання семантичного індексу свіжим при зміні нод/ребер | **Зроблено 2026-07-05** (checkpoint 3.3): incremental stale-index repair — застосовані патчі точково оновлюють FTS та інвалідують embedding-кеш. |

## R5. Концептуальне позиціонування

Доповнення до формули в розділі вище: Memory OS — це не лише "node → edge → metadata → evidence → lifecycle → index → retrieval", а й, неявно, уже сьогодні `propose → events.jsonl → transition/prune → archived_nodes.jsonl` — журнал подій, з якого читабельна історія (`memory log/show/revert`) є природним, а не доданим ззовні, в'юером. Git Memory Chain правильно це помітив; неправильно вирішив, що бракує git-семантики, а не лише в'юера.
