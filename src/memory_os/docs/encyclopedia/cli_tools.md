# Розділ 7: CLI та Інструментарій розробника

Memory OS постачається зі зручним та потужним CLI-інтерфейсом [cli.py](src/memory_os/cli.py) та набором інструментів автоматизації. Вони дозволяють керувати memory runtime, оцінювати складність завдань та проводити аудит стану проєкту безпосередньо з терміналу.

---

## 1. Довідник підкоманд CLI

Запуск утиліти виконується через модуль Python: `python -m memory_os [команда] [аргументи]`.
Основні підкоманди:

### 1.1. `init`
Створює базові файли керування пам'яттю в робочій директорії (якщо вони відсутні):
* `agent_context/WORKFLOWS.md` — текстовий контракт воркфлоу.
* `agent_context/HANDSHAKE.md` — поточний статус сесії агента.
* `agent_context/development_log.md` — журнал розробки.
* Заготовки порожніх файлів `task_capsules.jsonl`, `nodes.jsonl`, `edges.jsonl`, `events.jsonl`.
* Файли конфігурацій воркфлоу в папці `workflows/` (`chat.nano.toml`, `code.small.toml`, `architecture.giant.toml`).
* `memory_os.config.json` — конфігурація ядра.

### 1.2. `integrate`
Інтегрує базові інструкції Memory OS до головного файлу інструкцій проєкту `AGENTS.md`.

### 1.3. `audit`
Запускає аудит стану керування проєктом. Виводить рекомендації та інформацію про помилки валідації в консоль або у форматі Markdown.

### 1.3b. `doctor`
Перевіряє локальний стан Memory OS: конфіг, директорії, JSONL-файли, SQLite, LLM-ключі/Ollama, диск, daemon PID та workspace runtime. Для Zellij показує активну/мертву сесію і список `EXITED` сесій з підказкою `memory_os workspace clean-exited --runtime zellij --apply`.

### 1.4. `validate`
Проводить валідацію схем та цілісності файлів `nodes.jsonl`, `edges.jsonl`, `events.jsonl`, капсул та конфігів воркфлоу. Повертає код `1` у разі виявлення будь-яких помилок.

### 1.5. `snapshot`
Будує локальний зріз контексту проєкту (файли, класи, методи) та записує його за допомогою `compact_memory.py` у файл `agent_context/memory_snapshot.json`.

### 1.6. `quantize`
Оцінює складність задачі.
* **Аргументи**: `--task "Опис задачі"`, `--risk [0..1]`, `--volume [0..1]`, `--uncertainty [0..1]`, `--format [text|json]`.
* **Результат**: Розраховує бал складності, рівень (0..13), назву кроку, модельну політику та необхідність ескалації.

### 1.7. `workflows`
Перевіряє та валідує TOML-конфігурації в папці `workflows/`. Збирає їх у зведений маніфест `memory/workflow_manifest.json`.

### 1.8. `compact`
Запускає LLM-компактори для обробки неущільнених капсул задач та генерації нових draft-вузлів і ребер у memory runtime.

### 1.9. `compress`
Аналізує верифіковані знання та виконує семантичне стиснення (злиття дублікатів через ребра `overrides`).

### 1.10. `prune`
Переносить застарілі (`stale`, `superseded`) вузли в архів та очищує пошкоджені або неактивні зв'язки.

### 1.10b. `transition`
Обробляє lifecycle кандидатів пам'яті: `draft`/`observed` вузли проходять schema/evidence/confidence gate перед промоцією у `verified`. Прапорець `--min-confidence` задає ручний поріг для цього запуску; якщо його не передано, використовується `memory.confidence_threshold` або `confidence_threshold` з `memory_os.config.json` (default `0.7`). Hard-порушення (schema/відсутні evidence-файли) переводять кандидата у `stale`; вузли нижче порогу довіри лише УТРИМУЮТЬСЯ в `draft` (можуть набрати evidence і пройти пізніше). Явний обхід порогу чи свідоме відхилення — через `LifecycleManager.promote()`/`reject()`.

### 1.10c. `memory normalize-timecodes`
Одноразова maintenance-команда для вирівнювання часових кодів у memory graph. Нормалізує `freshness`/`valid_from`/`valid_until` у вузлах і `timestamp` у подіях до ISO-8601 з offset у часовому поясі користувача (`MEMORY_OS_USER_TZ`, `user_timezone` або `timezone` з config). Naive timestamps трактуються як UTC. Legacy-значення `fresh` замінюється на найранішу подію вузла або інший наявний timestamp; якщо це неможливо, поле очищується і рахується як `unresolvable`. Мутація йде через `RelationPatchStore`, тому лишає patch audit events. Підтримує `--format text|json`.

### 1.10d. `memory write`
Агентська команда «запам'ятай це»: записує факт/рішення як draft-кандидата через lifecycle gate (`propose_candidate`). `--summary` обов'язковий; `--type fact|rule|config|policy` (default fact), `--confidence` (default 0.8), `--evidence`, `--tags`, `--id` (авто-slug з summary якщо не задано), `--validator` (default `MEMORY_OS_AGENT_ID`). Нода лишається draft до промоції transition-гейтом або явним `promote()` — записане агентом не стає verified без перевірки.

### 1.11. `stats`
Виводить красивий зведений дашборд використання LLM (кількість викликів, витрати в USD, кількість токенів, середня latency за моделями та шаблонами промптів) у форматі YAML.

### 1.12. `rag`
Шукає правила пам'яті під конкретну задачу та записує топ-5 знахідок у `agent_context/active_memory.yaml` для використання агентом у поточній сесії.

### 1.13. `ingest-transcript`
Імпортує сирий Conv-Log AI-сесії розробника (`transcript.jsonl`) та за допомогою LLM вилучає завершені таски в `task_capsules.jsonl`.

### 1.14. `compile-prompt`
Збирає діючі правила пам'яті та системні інструкції в єдиний монолітний системний промпт для LLM.

### 1.15. `persona-sync`
Синхронізує та вилучає стиль спілкування користувача з файлу діалогу (`transcript.jsonl`) у файл `user_persona/persona.yaml`.

### 1.16. `persona`
Виводить поточний збережений профіль користувача з файлу `persona.yaml`.

### 1.17. `search`
Здійснює retrieval по memory runtime та кодовою базою (з урахуванням AST-символів та дерева залежностей).
* **Аргументи**: `query` (слово або назва символу), `--depth` (глибина пошуку), `--json` (вивід у форматі JSON).
* **Semantic gates**: `memory.semantic_similarity_threshold` керує `--semantic` (default `0.60`), `memory.semantic_fallback_threshold` — автоматичним semantic fallback (default `0.65`).
* **Access stats**: `count` і `last_accessed` записуються через спільний `NodeStatsStore` у `memory/node_stats.json`; lifecycle decay читає той самий runtime-контракт.

### 1.18. `analyze-os`
Аналізує внутрішню швидкодію алгоритмів Memory OS за даними таблиці `memory_os_performance` та формує пропозиції щодо оптимізації коду ядра.

### 1.19. `giant-scan`
Запускає глибокий аудит усього проєкту. Збирає повний вихідний код проєкту та memory runtime state, надсилає до великої моделі (наприклад, `gemini-2.5-pro`) та формує список архітектурних пропозицій.

### 1.20. `resources`
Керує локальним ресурсним бюджетом Memory OS без мережевих викликів:
* `snapshot` — знімає зріз вільного дискового простору, розміру бази даних SQLite, файлу WAL та загального обсягу JSONL-файлів відповідно до конфігураційних лімітів.
* `snapshot` окремо показує розмір `memory/events.jsonl` і soft-limit `memory.events_soft_limit_mb`; при перевищенні друкується лише advisory щодо archive rotation, без автоматичного prune audit-журналу.
* `compact` — архівує superseded-стани patch-аудиту та повертає новий resource snapshot.

### 1.21. `telemetry`
Використовується для моніторингу та очищення таблиць телеметрії і продуктивності системи. Підтримує дві основні дії:
* `audit` — виводить кількість рядків і розмір бази даних у порівнянні з лімітами конфігурації.
* `prune` — видаляє застарілі записи або ті, що перевищують максимальний розмір таблиць.

### 1.22. `release-check`
Виконує локальні release gates перед публікацією. `--target private` перевіряє валідацію, default security scan, приватність context pack, hygiene документації, ресурси та telemetry caps. `--target public` додатково блокує checkout, якщо в ньому присутні приватні planning docs або якщо повний security scan має знахідки.

### 1.23. `contract`
Дозволяє сформувати машиночитаний контракт для задачі на основі наявних артефактів специфікацій та планів розробки. Дія `build` генерує файли `contract.json` та `contract.md` для вказаної фічі з можливістю перевизначити клас ризику.

### 1.24. `context`
Будує цільовий відтворюваний пакет контексту (context pack) для конкретного завдання чи контракту. Дія `build` створює файли `pack.json` та `pack.md` у директорії `agent_context/context_packs/` для передачі моделі замість повного копіювання репозиторію.

### 1.25. `evidence`
Служить для збору та верифікації доказів тестування та виконання завдань розробником. Підкоманди включають:
* `init` — ініціалізує новий пакет доказів для обраної таски.
* `add-command` — запускає тестову команду та реєструє її результат і скорочений вивід.
* `summarize` — оновлює список змінених файлів та додає примітки рецензента.
* `verify` — перевіряє успішність усіх записаних команд та повертає помилку у разі наявності невирішених проблем.

### 1.26. `eval`
Запускає локальні або модельні тести (evals) для оцінки роботи системи на недетермінованих сценаріях. Доступні такі дії:
* `list` — виводить список доступних тестових наборів.
* `run` — запускає обраний тестовий набір.
* `compare` — порівнює результати кандидата з базовою лінією (baseline).
* `export` — експортує конфігурацію тесту у формати Inspect AI або promptfoo.

### 1.27. `review-pack`
Збирає разом контракт, пакет контексту та накопичені докази верифікації в один фінальний документ для рецензента. Цей зведений звіт допомагає швидко провести ручний або автоматизований аудит виконаного завдання.

### 1.28. `change-size`
Аналізує поточні незакомічені зміни в робочій копії репозиторію. Надає попередження у разі виявлення завеликого обсягу змін, що допомагає дотримуватися концепції малих безпечних кроків розробки (small-batch).

### 1.29. `security`
Виконує локальний сканер безпеки робочого простору. Дія `scan` перевіряє файли пам'яті, доказів та пакетів контексту на наявність випадково збережених секретів або ознак prompt-injection атак.

### 1.30. `route`
Маршрутизує текстовий опис задачі до оптимального провайдера або моделі за допомогою вбудованої політики маршрутизації LLMRouter. Виконується повністю локально і не робить зовнішніх мережевих запитів.

### 1.31. `budget`
Контролює ліміти використання токенів для LLM. Дія `status` відображає поточний добовий баланс токенів, обсяг витрачених ресурсів та попереджає про вичерпання бюджету.

### 1.32. `provider`
Призначена для роботи з постачальниками моделей та адаптерами. Підкоманда `list` показує статус підключення та конфігурації всіх провайдерів, а `test` виконує автономну перевірку працездатності конкретного провайдера без мережевих викликів.

### 1.33. `prompt`
Керує версіонованими шаблонами промптів без здійснення викликів LLM. Підкоманди включають:
* `list` — показує список усіх промптів з версіями та хешами.
* `show` — відображає метадані та тіло обраного промпту.
* `render` — підставляє вхідні змінні у шаблон для попереднього перегляду.
* `verify` — перевіряє правильність структури та метаданих усіх зареєстрованих промптів.

### 1.34. `idea`
Розгортає чернетку ідеї у детальний промпт для фази дослідження. Дія `expand` рендерить відповідний шаблон, не роблячи викликів до LLM.

### 1.35. `adapters`
Проводить аудит доступності необов'язкових зовнішніх адаптерів у локальному середовищі. Дія `audit` перевіряє встановлення кожної інтеграції та виводить звіт про їхню наявність.

### 1.36. `ingest`
Конвертує зовнішній документ у формат Markdown з використанням опціонального адаптера MarkItDown. Дія `file` підтримує обробку одного локального файлу в ізольованому режимі без виконання вбудованих скриптів чи мережевих звернень.

### 1.37. `observe`
Надає інтерфейс для моніторингу та сумісного з OpenTelemetry експорту локальної телеметрії. Підтримує дію `status` для перевірки наявності OTel SDK та `export` для тестового або реального вивантаження зібраних метрик і спанів.

### 1.38. `analytics`
Формує аналітичні звіти за допомогою вбудованої інтеграції з базою DuckDB. Дія `report` агрегує дані за вибраною темою (тести, телеметрія або докази), а `export` дозволяє зберегти отриману статистику у формати JSON або Parquet.

### 1.39. `mcp`
Забезпечує взаємодію з протоколом Model Context Protocol (MCP) у режимі найменших привілеїв. Дія `manifest` показує список дозволених інструментів, `audit` перевіряє статус MCP SDK, а `serve` дозволяє запустити або імітувати локальний MCP-сервер.

### 1.40. `run`
Веде native-облік та запис чекпоінтів виконання воркфлоу без використання важких оркестраторів. Дозволяє створювати нові записи (`start`), переглядати їхній статус (`status`), відновлювати стан (`resume`), завершувати роботу з передачею результатів (`complete`), переривати (`abort`) або отримувати список усіх запусків (`list`).

### 1.41. `storage`
Рекомендує оптимальний тип сховища для бази даних (sqlite / local_postgres / cloud_postgres) на основі аналізу локальних сигналів продуктивності та дискового простору.

### 1.42. `check-updates`
Перевіряє наявність оновлень ядра `memory_os` з віддаленого репозиторію та виводить діючі правила внесення змін агентами.

### 1.43. `switch-space`
Перемикає активний простір пам'яті фонового демона (наприклад, default, user_persona) для ізоляції баз знань. CLI, UI та daemon-команди використовують спільний `DaemonClient`: Unix socket є основним transport, loopback HTTP — fallback; UI не змінює локальний space без підтвердження демона.

### 1.44. `plan`
Створює покроковий план виконання завдання (Phase 3) із зазначенням ризиків, вимог до можливостей та рекомендованих агентів.

### 1.45. `dispatch`
Запускає виконання задачі через обраний адаптер агента (Phase 4), контролює тайм-аут та записує докази виконаної роботи.

Якщо задача вимагає `code_edit`, `architecture`, `deep_context` або `repro_analysis`, але жоден `cli_agent` недоступний, router повертає `blocked` plan. Daemon переводить task у `blocked` із причиною замість запуску deterministic `script` fallback і фальшивого завершення.

### 1.45b. `codebase index`
Детерміновано індексує `src/**/*.py` у `file:*`, `class:*`, `function:*` і `module:*` вузли через `DomainAdapterIngestor`. Запис відбувається через два bounded `RelationPatchStore` bulk patch-и для nodes/edges, а не тисячі окремих JSONL-транзакцій. `--source` змінює каталог у межах project root; `--dry-run` показує кількість файлів і patch-ів без мутації; `--format json` дає machine-readable звіт.

```bash
memory_os codebase index --dry-run --format json
memory_os codebase index
```

### 1.46. `handoff`
Будує зведений markdown-пакет контексту для безпечної та швидкої передачі завдання іншому агенту у випадку збою чи тайм-ауту.

### 1.47. `comm`
Управляє tmux-інбоксом між агентами. Підтримує надсилання повідомлень (`send`), перегляд вхідних тасок (`inbox`), читання повного тіла повідомлення (`read`), перевірку зв'язку (`status`), короткий resume-звіт після втрати контексту (`resume`) та timeline взаємодії (`feed`). Вивід часу у `status`, `resume` і `feed` використовує `MEMORY_OS_USER_TZ` або `user_timezone` з config, якщо вони задані.

**`comm inbox` — курсор прочитаного (економія токенів).** За замовчуванням показує лише НЕПРОЧИТАНІ повідомлення (oldest-first FIFO) і зсуває курсор (`agent_context/inbox/.cursor_<agent>.json`). Повторний виклик повертає тільки нове. Прапорці: `--all` — показати і прочитані; `--peek` — подивитись нове без зсуву курсора; `--rewind` — скинути курсор на 0; `--task-id` — фільтр по задачі (курсор НЕ зсувається). Якщо непрочитаних більше за `--limit`, показується `unread_remaining` — викликати inbox ще раз. Курсор саморемонтується: пошкоджений cursor або cursor за межами hot-файлу після truncate/rotation fast-forwardиться до безпечного кінця файлу, щоб старі повідомлення не з'являлись повторно. Тіла повідомлень у списку обрізані до 120 символів; повний текст — `comm read <#id>`.

**`comm read <#id> --recipient <agent>`** — повне тіло одного повідомлення за його `[#N]` індексом зі списку inbox (стабільний номер рядка в append-only файлі).

### 1.48. `feed`
Виводить потік подій взаємодії агентів у реальному часі. Параметр `--watch` дозволяє інтерактивно стежити за ходом виконання задач у Swarm. Параметр `--new` — лише події з моменту попереднього виклику `--new` (глобальний курсор `agent_context/feed_cursor.json`); без прапорця поведінка незмінна.

### 1.49. `tmux`
Інструмент автоматизації та контролю tmux-панелей. Дозволяє надсилати комбінації клавіш (`send`, `shortcut`), захоплювати вивід екрану (`capture`) та отримувати список вікон (`list`).

### 1.50. `telegram-daemon`
Запускає фоновий процес Telegram-бота для прийому завдань від користувача, автоматичного виклику агентів та релею статус-рапортів.

### 1.50b. `telegram-daemon-control`
Керує Telegram swarm-control daemon як detached локальним процесом: `start`, `stop`, `restart`, `status`. Використовує `data/telegram-daemon.pid` та `data/telegram-daemon.log`, перевіряє stale/wrong PID через `/proc`, запускає daemon з `--swarm-control --swarm-watch-timeout 0` за замовчуванням.

### 1.51. `task`
Керує життєвим циклом завдань у локальному ядрі (створення, перегляд лімітів, резервування агентом, зміна статусів running/done/blocked).

### 1.52. `agent-registry`
Дозволяє переглянути список зареєстрованих агентів, перевірити працездатність їхніх CLI-бінарників (`audit`) та квоти використання API (`health`).

Усі runtime-компоненти читають `agent_context/agents/registry.toml` через канонічний `toolkit.agent_registry.load_agent_registry`; Python 3.9–3.10 автоматично використовує умовну залежність `tomli`, Python 3.11+ — стандартний `tomllib`.

### 1.52b. `agent-manager`
TUI та CLI (`--status`, `--json`) огляд CLI-агентів: процес (RUNNING/STOPPED по живих пейнах tmux/zellij), ліміти квот. TUI самооновлюється кожні 5с (countdown тікає без клавіш). Відсотки використання (`5h:X% | Week:Y%`) наповнюються детерміновано модулем `toolkit/quota_harvester.py`: для codex — парсинг `rate_limits` з найсвіжішого `~/.codex/sessions/**/rollout-*.jsonl` (TTL 60с, без LLM-викликів; `CODEX_HOME` перекриває шлях; STATUS_REPORT від codex тригерить негайний перечит); для claude/agy — пасивний запис згадок лімітів з дельти пейна (`record_limit_mention` з AgentStateMonitor при RATE_LIMITED). Стан — `agent_context/agents/quota_monitor_state.json`, читається також `comm status`.

**Runtime control:** `agent-manager --restart-all` перезапускає core daemon, Telegram daemon і workspace runtime; `agent-manager --shutdown-all` зупиняє їх. У TUI: `R` — restart all, `S` — shutdown all. Workspace restart із manager виконується detached helper-процесом, щоб команда не обірвалась, коли поточний pane буде закритий.

**Agent permissions:** інтерактивні pane-и стартують через `agent_context/agents/registry.toml` поле `launch_flags`; non-interactive dispatch використовує `dispatch_flags`. Поточна trusted-local політика: Codex `--sandbox danger-full-access --ask-for-approval never`, Claude/agy `--dangerously-skip-permissions`. Це навмисно знімає approval deadlocks для локальної Memory OS, але не є безпечним default для неперевірених репозиторіїв.

**Passive runtime truth-cache:** core daemon раз на хвилину оновлює `agent_context/agents/runtime_health.json` і `relay_watch.json`. `agent-manager` читає цей snapshot першим, а вже потім fallback-ить у live tmux/zellij scan. Це прибирає фальшиві `STOPPED` стани після рестартів, dead sessions або sandboxed pane scans.

**Backend boundary:** runtime control already needs backend-agnostic contracts. `zellij` is the default, but `workspace runtime`, `multiplexer manager`, `agent-manager`, `daemon_hygiene`, and `runtime_control` should not hard-code zellij-only pane/session ids or scan formats. Keep explicit interfaces for `workspace/session`, `pane`, `agent-status`, `event stream`, `restore`, `send-input`, and `read-output` so a future `herdr` backend can plug in without rewriting the daemon/agent stack.

**Zellij live delivery caveat:** if Codex runs inside the managed sandbox, `zellij action ...` can fail with `There is no active session` even when `zellij list-sessions` shows `memory_os_workspace`. The sandbox isolates the process context; live pane injection must be run by an unsandboxed/daemon-owned path. `comm.sent` means inbox/file delivery happened; check for `comm.failed` before assuming the target agent saw a live wake-up.

**`--probe-usage` / клавіша `r` у TUI** — активна проба `toolkit/usage_probe.py`: інжектить `/usage` у пейн агента, парсить екран, закриває Esc, пише відсотки у стан. Суворі умови: пейн має бути idle (маркери "Working"/"esc to interrupt" блокують пробу) і команда має бути верифікована для цього CLI (`USAGE_COMMANDS`; наразі лише claude — agy автодоповнює невідомі команди у випадкові пункти меню, перевірено наживо, тому для agy лише пасивний харвест).

### 1.53. `ls`
Виводить таблицю запущених інстансів Memory OS, включаючи активні tmux-сесії та процеси фонових демонів.

**`resources snapshot|compact`** — bounded runtime hygiene. `snapshot` тепер окремо показує `events.jsonl` і `patches.jsonl` soft limits. `compact` робить детерміноване patch-audit archive compaction: у hot `patches.jsonl` лишається лише останній стан кожного patch id, старі superseded rows переносяться в `memory/archive/patches-*.jsonl`. SQLite працює у стандартному rollback-journal режимі; окремого WAL checkpoint немає.

### 1.54. `swarm-send`
Надсилає завдання конкретному агенту в tmux-панель за допомогою Swarm-протоколу та очікує повернення результату.

**Effort-роутинг.** Кожне завдання автоматично отримує заголовок `[EFFORT <tier> L<n>]`, який quantizer виводить зі складності тексту задачі: L0–L4 → `low` (діяти одразу, тести лише зачепленого файлу), L5–L8 → `medium` (обмежена розвідка, повний прогін тестів один раз перед STATUS_REPORT), L9+ → `high` (повний аналіз і повний прогін). Прапорець `--effort low|medium|high` перекриває авто-тир. Семантика тирів прописана в промптах агентів (`agent_context/agents/prompts/*.md`, секція Effort Routing). Той самий заголовок додається і до формальних Telegram-задач.

### 1.55. `swarm-watch`
Блокує поточний термінал та чекає на прибуття `STATUS_REPORT` для обраного завдання з автоматичним тайм-аутом.

### 1.56. `install`
Проводить діагностику оточення, перевіряє наявність обов'язкових бінарників (tmux, git, python) та встановлює системні залежності.

### 1.57. `workspace`
Керування профілями робочих просторів, реєстрація нових шляхів до проектів та налаштування локальних Telegram-токенів. Дія `status` показує поточний runtime-стан (`auto`, `tmux`, `zellij`, `file`) без запуску або attach; для Zellij відрізняє живу сесію від `EXITED`/stale state. Дія `clean-exited --runtime zellij` у dry-run режимі показує мертві Zellij-сесії, а з `--apply` видаляє тільки знайдені `EXITED` сесії.

### 1.57b. `skills`
Керує repo-local skill pack у `skills/`: `skills list`, `skills validate`, `skills sync`. Формат skill-а — директорія `skills/<name>/SKILL.md` з frontmatter `name`/`description`; детальні workflows живуть у `references/`, deterministic helpers — у `scripts/`, assets — у `assets/`. `sync` копіює skill-и в agent-native project dirs (`.codex/skills`, `.claude/skills`, `.gemini/antigravity/skills`) і пише `memory/skills.lock.json`; `--dry-run` показує planned installs без запису.

### 1.58. `triage`
Запускає консольний інтерфейс для інтерактивного огляду чорнових вузлів знань (дозволяє підтверджувати, відхиляти або змінювати теги). Similarity-підказки використовують той самий cosine/Jaccard engine, що й `memory dedup-candidates`, із triage-порогом для draft→verified порівняння.

### 1.59. `query`
Швидка фільтрація локальних і package-internal вузлів через `MemoryGraphService` за типом, рівнем довіри, статусом, тегами чи датою оновлення. `--limit` і `--offset` дають детерміновану пагінацію; без `--limit` CLI зберігає повний результат.

### 1.60. `backlinks`
Показує всі інші вузли знань, які прямо чи опосередковано посилаються на вказаний ідентифікатор вузла.

### 1.60b. `memory health`
Показує короткий health-check memory runtime: кількість live та archived вузлів і ребер, щільність графа, частку orphan-вузлів, noise від `comm:` вузлів, топ зв'язаних вузлів і статус retrieval-eval. Команда корисна як щоденний продукт-барометр замість ручного огляду сирого JSONL.

### 1.60c. `memory`
Дає доступ до історії та гігієни пам'яті як до журналу: `log` для хронології подій, `show` для поточного/архівного стану вузла, `revert` для відновлення archived вузла як draft, `health` для короткого продуктового стану memory runtime, а `curate` для черги злиття, компонентів зв'язності та orphan-вузлів.

### 1.60d. `memory curate`
Показує curation queue для memory runtime: кандидати на злиття з поясненнями, зв'язані компоненти та orphan-вузли. Команда допомагає чистити пам'ять до того, як шум починає заважати retrieval і навігації.

### 1.60e. `memory browse`
Фокусує конкретний вузол або пошуковий запит і показує його локальне оточення: inbound/outbound ребра, пов'язані ноди, сусідів і короткий навігаційний зріз.

### 1.60f. `memory merge-preview`
Показує семантичні групи для злиття: канонічний вузол, список замінюваних вузлів, об'єднані теги, evidence і текст зведення. Команда корисна для агента як детермінований план cleanup перед фактичним merge.

### 1.60g. `memory merge-apply`
Застосовує семантичне злиття через patch-backed rewrite: canonical node отримує fused summary/tags/evidence, старі вузли позначаються superseded, ребра перепрошиваються без ручного постпроцесу. Має `--dry-run` для безпечного перегляду.

### 1.60h. `memory dedup-candidates`
Детерміновано знаходить дублікати або дуже близькі за змістом вузли пам'яті (типу fact/rule) на основі косинусної близькості векторних вбудовувань (embeddings cosine similarity >= 0.9) or схожості тексту (Jaccard similarity >= 0.8). Виводить список кандидатів з їхнім статусом, рівнем confidence та готовими командами для попереднього перегляду злиття (`memory merge-preview`).

### 1.60i. `models recommend`
Аналізує апаратне забезпечення хоста (ядра CPU, обсяг RAM та VRAM) та рекомендує, які локальні LLM-моделі підходять для запуску. Запитує список встановлених локально моделей через Ollama API (`http://localhost:11434/api/tags`) та поєднує його зі статичним каталогом найпопулярніших відкритих моделей з `toolkit/model_catalog.py`. Виводить таблицю сумісності (`fit` / `tight` / `no-fit`) із поясненням причини та рекомендованим розміром контексту.

### 1.61. Огляд опціональних адаптерів
Memory OS підтримує 12 опціональних адаптерів та інтеграцій, доступність яких перевіряється командою `adapters audit`: ollama, litellm, markitdown, otel, duckdb, qdrant, phoenix, langfuse, mlflow, pydantic_ai, vllm та mcp. Жоден з цих адаптерів не є обов'язковим для функціонування базового CLI — у разі їх відсутності система просто повертає інформаційний статус про те, що адаптер не встановлено, замість критичної помилки чи аварійного завершення роботи. Провайдери та важчі SDK встановлюються через extras, наприклад `memory_os[providers-ollama]`, `memory_os[providers-openai]`, `memory_os[resource-psutil]` або `memory_os[all]`.

---

## 2. OS Performance Analyzer (Аналізатор Швидкодії)

Клас [OSPerformanceAnalyzer](src/memory_os/toolkit/analyzer.py#L31) використовується для самоперевірки продуктивності ядра:
1. Зчитує середню тривалість викликів LLM та обробки алгоритмів із таблиць SQLite.
2. Формує текстовий звіт про роботу системи (Digest).
3. Надсилає його до моделі Gemini з інструкцією [ADVISOR_PROMPT](src/memory_os/toolkit/analyzer.py#L11).
4. Отримані рекомендації зберігаються у файлі `agent_proposals/admin_proposals.jsonl` зі статусом `draft` для подальшого схвалення розробником.

---

## 3. Transcript Ingestor (Зчитувач логів)

Клас [TranscriptIngestor](src/memory_os/toolkit/transcript_ingestor.py#L37) розпізнає успішно завершені завдання з Conv-Log сесій.

---

## 4. Автоматизація Аудитора (Auditor) та Запуск Тестів

Клас [auditor.py](src/memory_os/toolkit/auditor.py) виконує не лише пасивний збір статистики, а й активну верифікацію пропозицій (пропозиції типу `proposal.<номер>`):

### Процес автоматичної верифікації пропозицій:
1. Метод [auto_transition_proposals()](src/memory_os/toolkit/auditor.py#L176) знаходить у `nodes.jsonl` верифіковані вузли, ідентифікатор яких починається з `proposal.`.
2. Система шукає відповідний запис у файлі пропозицій `agent_proposals/admin_proposals.jsonl` зі статусом `active`.
3. З масиву `evidence` цього вузла вибираються Python файли тестів (що знаходяться в директоріях `tests/` або `scratch/`).
4. Для кожного файлу тесту запускається ізольована команда тестування через `subprocess`:
   `python -m unittest tests/test_file.py`
5. Якщо всі тести завершилися з кодом повернення `0` (успішно):
   * Статус пропозиції в `admin_proposals.jsonl` змінюється на `done`.
   * До журналу `events.jsonl` додається подія завершення пропозиції `memory.proposal.completed` із переліком запущених тестів.
   * Автоматично перекомпілюється маніфест знань.
   
Це дозволяє реалізувати повністю автоматизований цикл: *LLM пропонує фічу -> Агент пише код та тести -> Компактор фіксує знання -> Аудитор проганяє тести і закриває пропозицію.*

---

## 5. UI-сервер та веб-візуалізатор

`memory_os ui [--port 8080]` запускає zero-dependency HTTP-сервер ([ui/server.py](src/memory_os/ui/server.py), 127.0.0.1-only, cross-origin відсікається) зі статикою з `toolkit/ui_templates/` (index.html, app.js, styles.css).

**Граф:** візуалізація на `3d-force-graph` (3D) та `force-graph` (2D) — режим перемикається тумблером 2D/3D у шапці лівої панелі, вибір зберігається у `localStorage (mos_graph_mode)`. Спільний конфіг-ланцюжок для обох рендерерів; camera-виклики йдуть через mode-aware хелпери (`focusViewOn`/`resetView`), auto-rotate у 2D інертний.

**Memory-панель** (кнопка Memory): таймлайн вузлів по локальних датах з фільтрами типу/вікна, pin/edit/delete прямо з панелі, експорт графа, перехід до вузла у графі.

**REST API** (усі мутації через `MemoryGraphService` + `RelationPatchStore`, gate R2.3; у federated-режимі read-only):
- `GET /api/graph`, `GET /api/spaces`, `POST /api/switch_space`, `GET /api/tasks`, `GET /api/read_file`
- `GET /api/memory/health|curate|merge-preview|merge-apply|browse`
- `GET /api/memory/timeline?days=&type=&status=` — вузли, згруповані за локальною датою (`user_timezone`)
- `GET /api/memory/export` — повний дамп `{nodes, edges}` (attachment)
- `POST /api/nodes/update {id, summary?, tags?}` / `POST /api/nodes/delete {id}` / `POST /api/nodes/pin {id, pinned}` — pinned-вузли пропускаються decay/compactor
- `POST /api/nodes/verify`, `POST /api/nodes/merge`, `POST /api/edges/create`, `POST /api/link-infer`

### 5.1. Автономний нагляд за агентами та демоном

**Квота-пінги (`toolkit/quota_monitor.py`, тик `watchdog_limits` кожні 30с у core daemon):** коли агент у ліміті (`has_limit`), після `reset_at` (або кожні ~10хв, якщо reset невідомий) йому надсилається `[QUOTA PING]` — вимога відповісти однією командою `comm send system ok` (мінімальний спал токенів). Done-файл → ліміт знято → телеграм «✅ Ліміти X відновлено». Liveness short-circuit: будь-який STATUS_REPORT від агента після `limit_seen_at` знімає ліміт без пінга (нотифікація один раз на епізод — `restored_notified_at`). `parse_reset_time` розуміє повні дати банерів («try again at Jul 8th, 2026 3:24 PM»), час/AM-PM, відносні тривалості.

**Task GC (`TaskKernel.expire_stale`, тик `task_gc` щогодини):** kernel-таски з титулом `telegram*` без активності >24год автоматично закриваються (`status=done`, `handoff_summary=auto-expired`). Робочі таски не чіпаються.

**Нагляд за core daemon (`telegram_polling._watch_core_daemon`, кожні 5хв):** telegram-daemon перевіряє `data/daemon_status.json` (мертвий pid або last_activity >10хв = down), перезапускає `memory_os daemon start` і сповіщає дозволені чати один раз на епізод.

**Housekeeping у core daemon (`toolkit/daemon_hygiene.py::DaemonHygiene`, тик `housekeeping` щохвилини):** `snapshot_runtime_health()` пише `agent_context/agents/runtime_health.json` (per-agent `is_active`/`is_working`/`is_ghost` за живими zellij/tmux пейнами — truth-cache, який `agent-manager` читає першим замість live-scan); `reconcile_agent_panes()` автоматично перезапускає ghost-пейни `codex`/`agy` через `RuntimeControl.restart_pane()`, але не перезапускає protected orchestrator `claude`, і ставить 5-хвилинний cooldown після кожної спроби; `snapshot_relay_watch()` пише `agent_context/agents/relay_watch.json` (lag непрорелейованих `done/*.json` і протерміновані task leases; `task_gc`/`watch_done_files` тригеряться, якщо є lag); `check_telegram_daemon()` використовує той самий pane-restart primitive. Разом з `_watch_core_daemon` це замикає взаємний watchdog між core daemon і telegram-daemon.

**Діагностика диспатчу:** `send_task` при виключенні пише traceback у stderr та подію `comm.failed` з reason у `task_events.jsonl`.

### 5.2. Стартовий профіль автономії (`memory_os` без аргументів)

Після вибору workspace у TUI-пікері (`toolkit/project_picker.py`) з'являється другий пікер — `toolkit/startup_profile.py::select_startup_profile()` — вибір профілю прав для агентських панелей цього запуску. Перший (дефолтний, Enter без вибору) пункт — **Повна автономія**: реєстрові `launch_flags`/`dispatch_flags` (`--dangerously-skip-permissions`, `--sandbox danger-full-access --ask-for-approval never`) застосовуються як є. Другий — **Супервізований режим**: `apply_profile_to_flags()` вирізає ці ж флаги з будь-якого списку, агенти повертаються до власних інтерактивних запитів підтвердження. Непорожній обраний профіль пишеться в `agent_context/runtime/startup_profile.json` (`record_startup_profile`) і читається неінтерактивним `CliAgentAdapter.build_command()` (`read_startup_profile`), тож і панельний запуск, і одноразовий CLI-диспатч узгоджені в межах сесії. Неінтерактивний термінал (CI, dumb TERM) завжди отримує дефолт без запиту.
