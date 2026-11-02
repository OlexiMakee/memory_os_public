# Розділ 10: Agent Brain — base-модель як двигун дій, не як чат-бот

`src/memory_os/agent_brain/` — інтерфейси й мінімальна робоча реалізація для архітектури, де модель **не розмовляє з користувачем напряму**. Вона лише вибирає дію. Усе інше (знання, дозволи, виконання, стиль фінальної відповіді) живе зовні, у вже існуючих частинах Memory OS.

Це продовження [lora_training.md](lora_training.md): там — як готувати датасет і скрипт для LoRA; тут — навіщо й куди ця LoRA вставляється в живій системі.

Концептуально `lora/` + `agent_brain/` разом — перша реалізація підсистеми, яку приватний design-документ `agent_context/IMPORTANT_PROPOSAL.md` §13 називає **Neural Capability Manager (NCM)**: LoRA — лише перший backend цього менеджера, не його фундамент (звідси `SkillAdapterSpec.adapter_kind`, а не жорстко "LoRA" в назвах класів).

---

## 1. Філософія

Instruct-модель несе в собі вбудовану поведінку: "будь корисним", "пояснюй", "відмовляйся", "пиши як асистент". Для агента, що повинен лише вибрати дію, це шум — і модель, і LoRA над нею витрачають "увагу" на боротьбу з власною заводською особистістю замість чистого `вхід → дія`.

Base-модель (без instruction-tuning) ближча до `патерн → продовження патерна`. Навчена action-only LoRA на ній — це не асистент, а **компілятор задачі в дію**: на вхід — текст задачі, на вихід — рівно один JSON-виклик дії, без жодного зайвого слова.

**Головне правило:** Action Brain ніколи не формує текст для користувача. Це робить окрема модель (Responder) — інстракт чи creative, з власною LoRA на стиль/тон. Розділення дає дві переваги:
- Помилка/нестабільність генерації дій не псує якість фінальної відповіді, і навпаки.
- Кожна сторона тренується/обирається незалежно — можна поставити сильнішу модель для відповіді й найдешевшу для дій, або навпаки.

База не геній — це дикий, але швидкий "кінь". Без дресури (LoRA) і без вузди (Orchestrator + валідація словника дій) вона ненадійна. Усі три шари потрібні разом:

```
BASE MODEL  +  action-only LoRA  +  жорсткий зовнішній Orchestrator
```

## 2. Архітектура: чотири шари

```
                         User
                          │
                          ▼
                    ┌─────────────┐
                    │ Orchestrator │  ← закон і порядок: валідує дію,
                    └─────────────┘     виконує, вирішує, чи кликати Responder
                     │           │
                     ▼           ▼
              ┌────────────┐  ┌──────────────────┐
              │ ActionBrain │  │ ActionExecutor    │
              │ base+LoRA   │  │ (вже існуючий код │
              │ action-only │  │ memory_os)         │
              └────────────┘  └──────────────────┘
                     │                  │
                     ▼                  ▼
              ActionRequest        ActionResult
              {action, args}       {ok, data/error}
                                          │
                                          ▼
                                  ┌──────────────┐
                                  │  Responder    │  ← instruct/creative
                                  │ instruct+LoRA │     модель, стиль і мова
                                  └──────────────┘
                                          │
                                          ▼
                                  Фінальна відповідь
```

Знання (retrieval/SQL/стан пам'яті) **не** в моделі — їх вже надає [MemorySearcher](src/memory_os/modules/search.py) (FTS5 + traversal) і [LifecycleManager](src/memory_os/modules/lifecycle.py) (propose/transition). ActionBrain не повинен "знати" 30 ГБ документів — він повинен знати, як назвати дію `memory.search`, а решту робить вже написаний код.

## 3. Словник дій — [vocabulary.py](src/memory_os/agent_brain/vocabulary.py)

`ActionVocabulary` — єдине джерело правди про те, що агент уміє робити: і текстовий блок `<available_actions>`, який бачить модель, і таблиця, яку перевіряє Orchestrator. `default_memory_os_vocabulary()` навмисно мапить дії на вже існуючі можливості проєкту (`memory.search` → `MemorySearcher`, `memory.write` → `LifecycleManager.propose`, `file.read` → локальний файл під `confine_to_root`) — жодного паралельного набору команд не вигадано.

## 4. ActionBrain і Responder — [brain.py](src/memory_os/agent_brain/brain.py), [responder.py](src/memory_os/agent_brain/responder.py)

- **`ActionBrain`** (ABC): один метод `propose_action(task, vocabulary) -> ActionRequest`.
  - `ScriptedActionBrain` — фіксована мапа замість моделі. Дозволяє перевірити весь Orchestrator/executors-ланцюжок вже зараз, без GPU й без натренованого адаптера.
  - `LocalLLMActionBrain` — реальний місток: формує мінімальний промпт `<task>/<available_actions>/<answer_format>` і йде через уже існуючий local-first ланцюжок [core/llm_service.py](src/memory_os/core/llm_service.py) (Ollama → безкоштовна хмара). Коли action-LoRA натренується на іншому залізі й буде роздана через Ollama, цей клас підключити — достатньо вказати `--model <ollama-tag>`.
- **`Responder`** (ABC): `respond(task, result) -> str`. `LocalLLMResponder` — той самий ланцюжок, але зі звичайним system prompt — тут навмисне місце для стилю/особистості/creative LoRA.

## 5. Orchestrator — [orchestrator.py](src/memory_os/agent_brain/orchestrator.py)

Єдине місце, що викликає ActionBrain, єдине місце, що виконує дію, єдине місце, що вирішує, чи кликати Responder. Перевіряє `ActionRequest.action` проти словника **до** виконання — якщо модель "вигадала" неіснувану дію, результат — `ActionResult(ok=False, ...)`, а не виконання чогось невизначеного. `run()` повертає сирий результат; `handle()` додає крок Responder.

## 6. Виконавці дій — [executors.py](src/memory_os/agent_brain/executors.py)

`default_executors(config)` зв'язує словник із реальним кодом проєкту: `memory_search_executor` і `memory_write_executor` викликають `MemorySearcher`/`LifecycleManager` напряму, `file_read_executor` читає файл через `confine_to_root` (захист від path traversal — перевірено: `../../etc/passwd` коректно відхиляється). Жодних нових залежностей, жодної моделі — це вже працює сьогодні.

## 7. Constrained decoding — [grammar.py](src/memory_os/agent_brain/grammar.py)

`GrammarConstraint` — інтерфейс, що перетворює словник дій у формат, який конкретний інференс-бекенд (Ollama `format=`, llama.cpp grammar, `outlines`/`guidance`) розуміє напряму. `JSONSchemaConstraint` рендерить стандартну JSON Schema (`{"action": enum[...], "args": object}`).

**Реально підключено для Ollama** (з 2026-06-27): [LocalLLMActionBrain](src/memory_os/agent_brain/brain.py) передає цю схему як `response_schema` у [DefaultLlmProviderService.call_llm()](src/memory_os/core/llm_service.py) → [_call_ollama()](src/memory_os/core/llm_service.py) кладе її в параметр `format` HTTP-запиту до `/api/chat` — це реальне decode-time обмеження Ollama, не лише текстова інструкція в промпті. Для хмарних fallback-провайдерів (gemini/groq/openrouter/openai) схема свідомо ігнорується — лише текстова інструкція в промпті, без власної структурованої-виводу інтеграції на кожного провайдера. `propose_action()` додатково перевіряє, що повернута дія справді є в словнику, навіть якщо бекенд не підтримав схему.

## 8. Ролі адаптерів у AdapterRegistry

[SkillAdapterSpec.role](src/memory_os/lora/types.py) (`"action"` за умовчанням, або `"responder"`) і [AdapterRegistry.for_role()](src/memory_os/lora/registry.py) дозволяють зберігати в одному реєстрі і дії-адаптери (`tool_router.lora`, `sql_writer.lora`, `memory_operator.lora`), і відповідач-адаптери (`creative_dirty_humor.lora`, `news_editor.lora`), та питати "дай мені дію-адаптер" окремо від "дай мені відповідач-адаптер". CLI: `memory_os lora script render --role action|responder`.

## 9. Що вже працює зараз, а що чекає на GPU-машину

**Працює сьогодні, на цьому Маку, без жодної моделі** (перевірено end-to-end): `ActionVocabulary`, `Orchestrator` + `ScriptedActionBrain` + `default_executors` проти справжнього `memory/` графа — write і search дії реально створюють/шукають вузли; валідація невідомої дії; захист `file.read` від виходу за межі кореня проєкту.

**Чекає на тренування на іншому залізі** (RTX 3060 Ti — див. [lora_training.md](lora_training.md)): сама дія-only LoRA (`tool_router.lora` чи подібна, на базовій моделі типу `Qwen2.5-Coder-7B-Base`), її роздача через Ollama (constrained decoding через `format=` для Ollama вже підключено — чекає лише на модель, яку можна цим обмежувати), і Modelfile-крок "як підняти натренований адаптер в Ollama" (поки не реалізовано).

## 10. Стратегія

Зафіксовано як `Open Decision G` у `DEV_STRATEGY.md` (приватний файл) — варіанти впровадження та рекомендований шлях. Резюме: почати з однієї action-LoRA (`tool_router`) на `Qwen2.5-Coder-7B-Base`, датасет через уже існуючий `memory_os lora dataset build --source capsules --source sqlite`, оцінка через `memory_os eval compare` за тим самим принципом, що й для memory-нод.

## 11. Майбутня фаза (не почато): стиснення стану сесії

Зовнішній огляд (2026-06-27, третій раунд — повний розбір у `agent_context/IMPORTANT_PROPOSAL.md` §13) описав MAGE: довгу агентну сесію зберігають не пласким логом, а ієрархічним деревом станів із чотирма операціями — **Grow** (зафіксувати новий крок), **Compress** (згорнути завершену гілку підзадачі в резюме), **Maintain** (перевірити, що резюме коректне), **Revise** (відкотитись до межі помилки й відкрити нову гілку). Це **не** те саме, що `LifecycleManager.decay_nodes()`: decay — це чищення застарілих нод за часом, MAGE — це стиснення в межах однієї *активної* багатокрокової сесії, поки вона ще триває.

Чому це не реалізовано просто зараз: `Orchestrator.run()`/`handle()` сьогодні — одна дія за один виклик (`brain.propose_action()` → виконати → відповісти), без поняття "сесія з кількох кроків" взагалі. Стиснення дерева стану безглузде без самого дерева стану — спершу потрібен `Orchestrator`, здатний виконати кілька дій підряд у межах однієї задачі (наприклад: `memory.search` → за результатом `memory.write` → відповідь), і десь зберігати послідовність викликів цієї задачі. Лише тоді Compress/Revise мають що стискати/відкочувати.

Зафіксовано як ідея на майбутнє, не специфіковано в `specs/` — кандидат для `memory_os spec init` коли (і якщо) Orchestrator отримає багатокрокові сесії.
