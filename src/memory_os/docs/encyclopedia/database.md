# Розділ 3: Схема даних та Зберігання

Memory OS використовує гібридну систему зберігання даних:
1. **SQLite база даних (`memory_os.db`)**: Використовується для транзакційного логування метрик, телеметрії викликів LLM, вимірювання швидкодії алгоритмів та швидкого збереження ключових спостережень.
2. **Файли JSONLines (`.jsonl`)**: Використовуються для репрезентації графу знань (вузли, ребра, події та лог виконаних задач). Це спрощує аудит змін за допомогою систем контролю версій (наприклад, `git diff`).

---

## 1. База даних SQLite

SQLite файл бази даних за замовчуванням розташовується за шляхом `memory/memory_os.db` (або `src/memory_os/data/memory_os.db`). База містить три головні таблиці:

### Таблиця `memory_os_telemetry`
Записує детальні метрики кожного виклику LLM для подальшого аналізу та оптимізації маршрутів.

| Стовпець | Тип | Опис |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | Унікальний автоінкрементний ідентифікатор запису |
| `prompt_name` | TEXT NOT NULL | Назва шаблону промпту (наприклад, `compactor.system`) |
| `prompt_version` | TEXT NOT NULL | Версія промпту (наприклад, `v1.2`) |
| `prompt_hash` | TEXT NOT NULL | Короткий SHA-256 хеш промпту для контролю цілісності |
| `provider_id` | TEXT NOT NULL | Ідентифікатор провайдера (наприклад, `gemini`, `openrouter`) |
| `model_id` | TEXT NOT NULL | Ідентифікатор моделі (наприклад, `gemini-2.0-flash`) |
| `input_tokens` | INTEGER | Кількість вхідних токенів |
| `output_tokens` | INTEGER | Кількість вихідних токенів |
| `cached_tokens` | INTEGER | Кількість закешованих токенів (якщо підтримується провайдером) |
| `latency_ms` | INTEGER | Тривалість запису в мілісекундах |
| `cost` | REAL | Розрахункова вартість виклику в USD |
| `status` | TEXT NOT NULL | Статус виклику (`success`, `error`) |
| `created_at` | TEXT | Локальний час створення запису |

*Індекси*:
* `idx_telemetry_name_ver` на `(prompt_name, prompt_version)`
* `idx_telemetry_created` на `(created_at)`

---

### Таблиця `memories`
Таблиця для швидкого збереження короткочасних або високопріоритетних спостережень та фактів.

| Стовпець | Тип | Опис |
| :--- | :--- | :--- |
| `id` | TEXT PRIMARY KEY | Унікальний рядковий ідентифікатор пам'яті |
| `type` | TEXT NOT NULL | Тип запису (`rule`, `fact`, `variable` тощо) |
| `content` | TEXT NOT NULL | Повний зміст спостереження |
| `summary` | TEXT | Стислий опис |
| `importance` | REAL | Оцінка важливості (вага) для сортування (0.0 .. 1.0) |
| `timestamp` | INTEGER NOT NULL | Час збереження (Unix timestamp) |

*Індекси*:
* `idx_memories_type` на `(type)`
* `idx_memories_importance` на `(importance DESC)`

---

### Таблиця `memory_os_performance`
Використовується для вимірювання внутрішньої продуктивності алгоритмів Memory OS (наприклад, час виконання RAG-пошуку чи побудови індексу).

| Стовпець | Тип | Опис |
| :--- | :--- | :--- |
| `id` | INTEGER PRIMARY KEY | Автоінкрементний ідентифікатор |
| `algorithm_name` | TEXT NOT NULL | Назва алгоритму (наприклад, `MemorySearcher.search_memory`) |
| `duration_ms` | INTEGER NOT NULL | Час виконання в мілісекундах |
| `metadata` | TEXT | Додаткові дані у форматі JSON-рядка |
| `created_at` | TEXT | Локальний час створення |

---

## 2. Граф знань у JSONL файлах

Граф знань серіалізується у три JSONL-файли в директорії `memory/`:

### 2.1. Вузли знань (`nodes.jsonl`)
Описує елементи бази знань. Кожен рядок є JSON-об'єктом:
```json
{
  "id": "provider.openrouter.free_only",
  "type": "policy",
  "summary": "Використовувати безкоштовні моделі OpenRouter для задач складності L1-L4",
  "evidence": ["workflows/chat.nano.toml", "src/memory_os/core/llm_service.py"],
  "status": "verified",
  "freshness": "2026-06-04T18:30:15",
  "trust": "verified",
  "related_nodes": ["workflows.routing"]
}
```
* Валідні типи вузлів (`type`): `rule`, `fact`, `variable`, `connector`, `config`, `policy`.
* Валідні статуси (`status`): `draft`, `observed`, `verified`, `stale`, `superseded`.
* Докази (`evidence`): Список шляхів до файлів або URL, які підтверджують це знання. Валідатор перевіряє фізичну наявність цих файлів на диску!

### 2.2. Зв'язки графу (`edges.jsonl`)
Описує спрямовані ребра між вузлами знань:
```json
{"source": "provider.openrouter.free_only", "target": "workflows.routing", "type": "configures"}
```
* Валідні типи зв'язків (`type`): `depends_on`, `triggers`, `refutes`, `overrides`, `configures`, `secures`.
* Заборонено створювати зв'язки з неіснуючими вузлами (dangling edges) або циклічні посилання на самого себе (self-referential).

### 2.3. Журнал подій (`events.jsonl`)
Зберігає аудит усіх змін у базі знань:
```json
{
  "timestamp": "2026-06-04T19:40:02",
  "event": "memory.node.verified",
  "node_id": "provider.openrouter.free_only",
  "claim": "Verified node: Використовувати безкоштовні моделі OpenRouter...",
  "evidence": ["workflows/chat.nano.toml"],
  "validator": "lifecycle_manager",
  "status": "accepted"
}
```
* Валідні статуси подій: `accepted`, `rejected`, `pending`, `in_progress`.

---

## 3. Файли логування задач та пропозицій

### 3.1. Капсули задач (`task_capsules.jsonl`)
Накопичувальний лог завершених операцій. Слугує джерелом знань для компактора.
```json
{
  "timestamp": "2026-06-04T19:12:00Z",
  "task": "Налаштувати лінивий імпорт LLM фабрики",
  "workflow": "memory_os",
  "step_name": "micro",
  "step_score": 2,
  "files_modified": ["src/memory_os/core/llm_service.py"],
  "files_viewed": ["src/memory_os/core/interfaces.py"],
  "context_tokens": 1200,
  "tools_used": ["view_file", "replace_file_content"],
  "hurdles_regression": "Виникали циклічні імпорти при прямій побудові LLMClientFactory",
  "resolution": "Перенесено імпорт фабрики безпосередньо всередину методу call_llm",
  "lessons_learned": "Lazy-import хост-компонентів запобігає circular dependency під час ініціалізації ядра."
}
```

### 3.2. Вхідні пропозиції (`admin_proposals.jsonl` або `giant_scan_proposals.jsonl`)
Чернетка для системних інсайтів чи архітектурних виправлень, які очікують на схвалення розробником:
```json
{
  "id": "os-perf:optimization_cache",
  "ts": 1780654302000,
  "role": "system",
  "type": "feature",
  "status": "draft",
  "priority": "high",
  "el": "os-perf:recommendation:cache_algorithm",
  "src": "memory_os.toolkit.analyzer",
  "desc": "Алгоритм пошуку MemorySearcher.search_memory викликається часто і триває понад 150мс. Рекомендовано додати кешування результатів для незмінних графів."
}
```

---

## 4. Контроль цілісності (`manifest.json`)

Файл [manifest.json](src/memory_os/memory/manifest.json) генерується автоматично під час завершення циклу обробки знань. Він містить агреговані лічильники елементів та SHA-256 хеші файлів для запобігання пошкодженню даних:
```json
{
  "generated_at": "2026-06-04T19:54:20Z",
  "counts": {
    "nodes": 42,
    "node_statuses": {
      "verified": 35,
      "draft": 2,
      "superseded": 5
    },
    "edges": 12,
    "events": 150
  },
  "checksums": {
    "nodes.jsonl": "8f39b1a...23a",
    "edges.jsonl": "2c90fa1...b45",
    "events.jsonl": "f5a021e...89d"
  }
}
```
Розробник або системи CI/CD можуть швидко виявити ручне несанкціоноване редагування файлів графу, порівнявши поточні хеші з хешами в маніфесті.
