# Розділ 9: Локальні LoRA-навички (Skill Adapters)

Memory OS за умовчанням працює через готові моделі (локальний Ollama, безкоштовні хмарні рівні — див. [compaction.md](compaction.md) та [core/llm_service.py](src/memory_os/core/llm_service.py)). Модуль `src/memory_os/lora/` додає окремий, повністю офлайн шар: підготовку датасетів і тренувальних скриптів для **власних маленьких LoRA-адаптерів**, заточених під конкретні навички (виклик тулзів Memory OS, обробка приватних документів, стиль).

Memory OS **нічого не тренує сам**. Цей модуль готує те, що потрібно для тренування (датасет + Python-скрипт), а саме тренування відбувається на машині з NVIDIA GPU — це може бути інша машина, ніж та, де працює агент.

`lora/` — перший і єдиний поки backend ширшої підсистеми, яку `agent_context/IMPORTANT_PROPOSAL.md` §13 формально називає **Neural Capability Manager**: LoRA-специфічних класів тут навмисно мало (`SkillAdapterSpec.adapter_kind="lora"` — поле, не назва модуля), щоб другий backend (DoRA, IA3, ...), якщо колись знадобиться, був новим значенням, а не переписуванням.

---

## 1. Навіщо це і коли LoRA, а не просто system prompt

Чим довший system prompt (правила інструментів, формат викликів, стиль), тим більше токенів він займає в кожному запиті й тим імовірніші помилки на маржі. LoRA переносить частину цих знань із промпта у ваги маленького адаптера (десятки-сотні МБ), який накладається на базову модель без зміни її основних ваг.

Практичний сценарій: один адаптер на одну навичку, а не одна універсальна модель на все:
- `memory.lora` — виклики `read_memory`/`write_memory`/`compress_memory` у форматі цього проєкту.
- `terminal.lora` — bash/git/docker команди в стилі, який очікує цей агент.
- `docs.lora` — резюмування/витяг фактів із приватних документів проєкту (security-аудити, `DEV_STRATEGY.md`) без зайвих відмов хмарної моделі на технічний/гострий контент, який ніколи не залишає цю машину.
- `creative.lora` — тон, гумор, стиль.

Перемикання адаптерів у реальному часі найдешевше робити через PEFT (`model.set_adapter("docs")` — базова модель лишається в VRAM, міняються лише малі ваги), а не через Ollama Modelfile `ADAPTER` (це фактично перезавантаження моделі).

## 2. Апаратні вимоги

QLoRA (4-bit) для 7-8B моделей реалістичне на споживчих картах із 8 ГБ VRAM (наприклад RTX 3060 Ti); 13-14B — на межі, потребує малого batch size й gradient checkpointing. Стек: `transformers` + `trl` (`SFTTrainer` — попри назву "Reinforcement Learning", сьогодні переважно використовується для SFT) + `peft` (реалізація LoRA) + `unsloth` (прискорені ядра, 2-5x швидше, менше VRAM).

Якщо тренувальна машина на Windows — WSL2 з CUDA passthrough дає майже нативну продуктивність без дуал-буту.

## 3. Формат датасету

Один приклад — словник `{"messages": [...]}` у форматі, який `SFTTrainer` розуміє напряму (`role`/`content`, опціонально `tool_calls`):

```json
{"messages": [
  {"role": "system", "content": "..."},
  {"role": "user", "content": "..."},
  {"role": "assistant", "tool_calls": [{"type": "function", "function": {"name": "read_file", "arguments": {"path": "README.md"}}}]}
]}
```

Це породжує клас [ToolCallExample](src/memory_os/lora/types.py) методом `to_trl_dict()`.

## 4. Джерела прикладів (`ExampleSource`)

[src/memory_os/lora/dataset.py](src/memory_os/lora/dataset.py) визначає інтерфейс `ExampleSource.examples()` і три реалізації:

- **[CapsuleToolCallSource](src/memory_os/lora/dataset.py)** — читає `agent_context/task_capsules.jsonl`, перетворює капсули з полем `action` на приклади виклику тулза. Природне джерело для `memory.lora`/`terminal.lora`.
- **[SqliteGraphSource](src/memory_os/lora/dataset.py)** — читає `graph_nodes` із `memory/memory_os.db`, тим самим SQLite-дзеркалом, яке вже підтримує `memory_os sync` (див. [database.md](database.md)). Бере лише `status='verified'` ноди (вони вже пройшли перевірку схеми й evidence в `LifecycleManager.transition()`) і впорядковує за `access_count` — отже найчастіше використовувані факти домінують у датасеті. Це **не нова база даних**, а перевикористання вже існуючого шару.
- **[LocalDocumentSource](src/memory_os/lora/dataset.py)** — глобить локальні файли (`--doc-root`/`--doc-glob`) і вставляє їхній текст **без редагування/цензури** як user-повідомлення з інструкцією (резюмувати, витягти факти тощо). Це навмисно: дані для `docs.lora` беруться з документів, які вже приватні й ніколи не йдуть у хмару (див. `.gitattributes` export-ignore у цьому проєкті) — тренування локальної моделі на них прибирає тертя від надмірно обережної модерації хмарного провайдера на власному технічному/security-контенті. Це **не** інструмент для зняття safety-поведінки моделі щодо реально шкідливих категорій (зброя, насильство тощо) — лише для того, щоб локальна модель не відмовлялась читати ваші ж приватні нотатки. Підключайте лише ті документи, які ви маєте право обробляти.

`DatasetBuilder` об'єднує кілька джерел в один JSONL-файл.

## 5. Конфігурація тренування і рендер скрипта

[LoraTrainingConfig](src/memory_os/lora/training_config.py) — dataclass з гіперпараметрами (`base_model`, `rank`, `alpha`, `target_modules`, `batch_size`, `epochs`, ...), що 1:1 відповідають аргументам Unsloth/TRL/PEFT. `render_script()`/`write_script()` генерує готовий `.py`-файл — текст скрипта, без виконання.

`method` (`--method` у CLI) обирає, який trainer TRL рендерити:

- **`sft`** (за умовчанням) — `SFTTrainer`. Єдина стадія, потрібна для більшості action-адаптерів: навчити формат/синтаксис виклику тулза. Рендерений скрипт явно встановлює `assistant_only_loss=True` у `SFTConfig` — без цього модель також вчиться передбачати токени системного промпта й результатів тулзів, які їй щойно показали, а не лише власну відповідь. Назва цього поля рухалась між релізами `trl` (раніше — окремий `DataCollatorForCompletionOnlyLM`) — перевіряйте проти встановленої версії.
- **`dpo`** — `DPOTrainer`. Друга стадія *після* `sft`-проходу: ранжує повні відповіді "обрана проти відхиленої" замість навчання синтаксису з нуля. Очікує колонки датасету `prompt`/`chosen`/`rejected`.
- **`grpo`** — `GRPOTrainer`. Group-relative policy optimization: для кожного `prompt` семплюється група відгуків, переваги рахуються відносно середнього в групі через reward-функцію. Рендерений action-verifier приймає plain-text і conversational completions, вимагає точний JSON-об'єкт `{"action": string, "args": object}` і перевіряє `action` проти `<available_actions>` відповідного prompt. Невалідний JSON, зайві поля, невідома дія або prompt без словника отримують `0.0`; валідний in-vocabulary виклик — `1.0`.

```bash
memory_os lora script render --adapter memory --base-model Qwen/Qwen3-8B \
  --dataset data/lora/memory.jsonl --output-dir data/lora/memory_out \
  --script-out data/lora/memory_train.py --method sft

memory_os lora script render --adapter memory --base-model Qwen/Qwen3-8B \
  --dataset data/lora/memory_pref.jsonl --output-dir data/lora/memory_dpo_out \
  --script-out data/lora/memory_dpo_train.py --method dpo
```

`SkillAdapterSpec.training_method` записує, яким методом натреновано кожну зареєстровану версію — декларативний облік (як `adapter_kind`), нічого не читає це поле для зміни поведінки під час виконання.

Перевіряйте поля бібліотек (`unsloth`, `trl`, `peft`) на момент запуску — ці API еволюціонують швидше, ніж цей шаблон встигає за ними.

**Перший реальний прогін (2026-06-27, Ubuntu `memoryos`, RTX 3060 Ti):** весь pipeline (dataset build → script render → реальне тренування на GPU → збережені ваги адаптера) уперше пройдений end-to-end, не лише як інтерфейс. Знахідки:
- **Python 3.14 несумісний із `dill`/`datasets`** на момент цього прогону: `datasets.load_dataset()` хешує конфігурацію через `dill`, а CPython 3.14 змінив сигнатуру внутрішнього `pickle.Pickler._batch_setitems` — найновіший `dill==0.4.1` (PyPI) ще не виправлений. Рішення: окремий `.venv-train` на Python 3.12 (через `uv python install 3.12`, без sudo) лише для тренувального стеку; основний легкий `.venv` лишається на 3.14.
- **`unsloth==2026.6.9` (з `trl==0.24.0`) не обробляє сирий стовпець `"messages"` автоматично** — `SFTTrainer._prepare_dataset` розпізнає лише `labels`/`input_ids`/`prompt`+`completion`/`text`, інакше вимагає `formatting_func`. Шаблон у `training_config.py` тепер сам розгортає `messages` у стовпець `"text"` через `tokenizer.apply_chat_template()` (з ручним fallback-форматуванням `role`/`content`, якщо базова модель не має `chat_template` — типово для не-Instruct баз).
- **Наслідок:** `assistant_only_loss=True` прибрано з рендереного SFT-шаблону — після розгортання в плаский `"text"` немає per-token розмітки ролей, тож маскування лосса на самі лише asсistant-токени неможливе цим шляхом. Тренування йде на повну послідовність (system+user+assistant). Для multi-turn tool-call датасетів, де маскування важливе, потрібна версія trl/transformers, яка веде `messages` нативно — переглянути перед масштабуванням з docs.lora на memory.lora/terminal.lora.
- Перевірений прогін: `docs.lora` v002, база `Qwen/Qwen2.5-Coder-1.5B` (BASE, не Instruct), 31 приклад (агрегація `agent_context/**/*.md`), 3 епохи, `train_loss` впав до 2.045, реальний `adapter_model.safetensors` (17 МБ) збережено в `data/lora/docs_out/adapter/`.

## 6. Реєстр адаптерів: версії, promote/reject

[AdapterRegistry](src/memory_os/lora/registry.py) зберігає в `data/lora_adapters.json` **кожну версію** кожного адаптера (`v001`, `v002`, ...), не лише останню. `register()` (виклик `memory_os lora script render`) завжди створює нову версію зі статусом `candidate` — і **ніколи** не підмінює те, що вже працює. Просування відбувається лише явним викликом:

```bash
memory_os lora registry versions --adapter tool_router      # вся історія версій
memory_os lora registry promote --adapter tool_router --version v002   # тільки після eval
memory_os lora registry reject  --adapter tool_router --version v001   # eval сказав, що гірше
```

Це прямий стоп-кран проти "нові дані → авто-донавчити → авто-замінити модель": нова версія завжди `candidate`, `lora list`/`get()` повертають останню **promoted**, доки явний `promote()` не скаже інакше. Старі promoted-версії при просуванні нової стають `retired` (історія лишається доступною через `versions`), а не видаляються.

**Маніфест-контракт адаптера** (Unix-подібний принцип: плагін з явним контрактом, не "магічний файл"): `SkillAdapterSpec.capabilities` (теги задач: `"sql"`, `"uk_slang"`), `compatible_with`/`incompatible_with` (інші адаптери, з якими відомо поєднується/конфліктує), `metrics` (числа після eval — `lora registry metrics --adapter X --version vNNN --set accuracy=0.91`). Усе декларативне: ніщо зараз не завантажує два адаптери одночасно, щоб перевірити `incompatible_with`, і жодна політика не блокує `promote()` за низькими метриками — контракт існує окремо від виконання, як `evidence` в `nodes.jsonl` декларативний, доки `LifecycleManager.transition()` його не перевірить. Повний розбір — `agent_context/IMPORTANT_PROPOSAL.md` §13.

```bash
memory_os lora list --capability sql                                    # фільтр за тегом
memory_os lora registry compatible --adapter-a sql --adapter-b terminal # декларативна перевірка
memory_os lora registry metrics --adapter sql --version v001 --set accuracy=0.91 --set latency_ms=340
```

## 7. Багаторівнева стратегія сховища: SQLite → local Postgres → cloud Postgres

"Local-first" не означає "ніколи нічого, крім SQLite" — означає: спочатку найдешевший локальний варіант, і лише коли він **вимірювано** не справляється, явно й усвідомлено переходимо на наступний рівень. Той самий принцип, що вже працює для LLM-провайдерів ([core/llm_service.py](src/memory_os/core/llm_service.py): Ollama → безкоштовна хмара → платна хмара), застосовано до сховища через [StorageTierAdvisor](src/memory_os/core/storage_tier.py):

- **Рівень 1 — SQLite** (зараз, за умовчанням). Достатньо для одного локального агента; межа SQLite сама по собі — терабайти, тож тригер для переходу — не "багато даних", а конкретні вимірювані сигнали: розмір `memory_os.db`, зростання WAL (= writes не встигають дренуватись, тобто write-contention, не просто розмір) і кількість активних swarm-лізів у `data/swarm_leases.json` (= скільки агентів зараз одночасно пишуть).
- **Рівень 2 — local Postgres.** Коли вищевказані сигнали перевищують пороги ([DEFAULT_TIER_THRESHOLDS](src/memory_os/core/storage_tier.py)) — типово коли кілька swarm-воркерів (codex/agy/claude) пишуть одночасно і SQLite-блокування однописьменника починає створювати затори.
- **Рівень 3 — cloud Postgres** (наприклад безкоштовний рівень Neon). Лише якщо рівень 2 виправданий, але локального `psql` не знайдено — тоді хмарний варіант практичніший, ніж піднімати локальний сервер.

`memory_os storage advise` лише **рекомендує** рівень із поясненням сигналів — нічого не мігрує і нічого не створює автоматично. Перехід на рівень 2/3 — свідоме рішення користувача, не побічний ефект команди.

Інші пропозиції з тієї ж дискусії (DuckDB, Qdrant) уже є опційними адаптерами в цьому проєкті ([adapters/duckdb_adapter.py](src/memory_os/adapters/duckdb_adapter.py) для аналітики, [adapters/qdrant_adapter.py](src/memory_os/adapters/qdrant_adapter.py) для векторів) — нічого додавати не треба. Neo4j лишається свідомо поза цим проєктом (не "ніколи через принцип", а тому що [search.py:traverse_graph](src/memory_os/modules/search.py#L38-L70) вже розв'язує обхід графа без JVM-сервера, і жоден вимірюваний сигнал поки не каже інакше) — конкуруючий концепт "Mimir" обрав саме цей шлях, тут навмисно інший. Parquet і LanceDB — кандидати на той самий ладер ("рівень 2" для архівів/семантичного пошуку відповідно), якщо колись `StorageTierAdvisor`-подібні сигнали для них покажуть реальну потребу; поки що жодних вимірюваних ознак цього немає.

## 8. Безперервне самовдосконалення адаптерів: що вже реально, що ще ні

Ідея з обговорення: система сама помічає повторювані помилки виклику тулзів, збирає їх у датасет, тренує нову версію адаптера, оцінює і просуває її, якщо краще, відхиляє, якщо гірше. **Eval-ворота для цього вже реальні, не лише ідея:**

- **Версії й promote/reject — реалізовано.** [AdapterRegistry](src/memory_os/lora/registry.py) (розділ 6) реєструє кожну версію як `candidate` і просуває лише за явним `promote()`/`reject()` — точна паралель тому, що `LifecycleManager.transition()` вже робить для memory-нод (`draft` → `verified`, edge `overrides` від нової версії до старої — [lifecycle.py:157-184](src/memory_os/modules/lifecycle.py#L157-L184)).
- **Суддя — реалізовано.** Новий eval suite `agent-action-validity` ([toolkit/evals/agent-action-validity/](src/memory_os/toolkit/evals/agent-action-validity/), запускається через `memory_os eval run agent-action-validity`) проганяє фікстурні задачі через `LocalLLMActionBrain` і перевіряє, чи модель/адаптер обирає правильну дію. `memory_os eval compare` (вже існуючий, без змін) порівнює baseline/candidate прогони — рівно той механізм, що потрібен для "версія 2 краща за версію 1".
- **Чого досі не існує:** автоматичного збору прикладів помилок із живої роботи агента. `task_capsules.jsonl` не позначає успіх/невдачу виклику — без цього сигналу "збираємо приклади помилок" робиться вручну (через `lora dataset build --source sqlite/--source capsules`), а не самостійно системою.

Отже не реалізовано лише останній крок цикла — авто-збір прикладів-помилок; цикл "candidate → eval → promote/reject" вже робочий end-to-end на цьому Маку (без жодної моделі, через `ScriptedActionBrain`/`agent-action-validity` skip-шлях), і готовий працювати по-справжньому, щойно з'явиться перший натренований адаптер.

**Практична порада для першого прогону на GPU-машині:** почати не з 7-8B, а з малої базової моделі (`Qwen2.5-Coder-1.5B-Base`, `Qwen2.5-Coder-3B-Base`, `Qwen3-4B-Base`) — швидший і дешевший спосіб перевірити, що весь pipeline (dataset → QLoRA → eval → promote) працює, перш ніж витрачати час на 7B/8B.

## 9. CLI

```bash
# 1. Зібрати датасет (capsules, sqlite verified-ноди, і/або локальні документи — комбінуються)
memory_os lora dataset build --adapter memory --source capsules --source sqlite --out data/lora/memory.jsonl
memory_os lora dataset build --adapter docs --source docs --doc-root agent_context --doc-glob '*.md' \
  --instruction "Витягни правила й факти, варті запам'ятовування." --out data/lora/docs.jsonl

# 2. Рендернути тренувальний скрипт і зареєструвати адаптер
memory_os lora script render --adapter memory --base-model Qwen/Qwen3-8B \
  --dataset data/lora/memory.jsonl --output-dir data/lora/memory_out \
  --script-out data/lora/memory_train.py --description "tool-call adapter"

# 3. Перенести data/lora/memory.jsonl + memory_train.py на GPU-машину,
#    встановити unsloth/trl/peft/bitsandbytes, запустити memory_train.py там.
#    Це реєструє адаптер як 'candidate' (v001) — нічого ще не "активне".

# 4. Оцінити candidate (тут: --model на ollama-тег натренованого адаптера)
memory_os eval run agent-action-validity --format json

# 5а. Якщо краще — просунути
memory_os lora registry promote --adapter memory --version v001
# 5б. Якщо гірше — відхилити, попередня promoted-версія (якщо була) лишається активною
memory_os lora registry reject --adapter memory --version v001

# 6. Перевірити стан реєстру
memory_os lora list                              # поточна (promoted) версія кожного адаптера
memory_os lora registry versions --adapter memory # повна історія версій
```

Усі команди офлайн і безпечні для запуску на машині без GPU — вони лише готують файли й ведуть облік версій; саме тренування й виконання `eval run agent-action-validity` з реальною моделлю відбувається там, де ця модель є.
