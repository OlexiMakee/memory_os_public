# Енциклопедія розробника Memory OS

Ласкаво просимо до **Енциклопедії розробника Memory OS**! Цей збірник документації розроблений для того, щоб провести вас шляхом від ентузіаста до експерта у створенні, розширенні та оптимізації ядра керування пам'яттю та координації агентів Memory OS.

## Що таке Memory OS?

**Memory OS** — це високодекопльоване, автономне ядро довготривалої пам'яті та оркестрації для AI-агентів. Воно розроблене за принципом **local-first** комп'ютингу і працює без зовнішніх залежностей (використовує виключно стандартну бібліотеку Python та опціональні ліниві адаптери LLM).

Основні функції системи включають:
* **Граф знань**: Зберігання та зв'язування правил, фактів, політик та конфігурацій.
* **Квантування задач**: Розрахунок складності задач за 12-рівневою шкалою для вибору оптимальних моделей та стратегій виконання.
* **Compaction (Ущільнення)**: Накопичення логів виконання (task capsules) та періодичне ущільнення їх у постійні знання за допомогою LLM.
* **Semantic Compression (Стиснення графу)**: Об'єднання дублікатів та семантично схожих правил для усунення розростання контексту.
* **Автомат життєвого циклу**: Валідація та перехід знань із чернеток у перевірені та застарілі стани.
* **Універсальний пошук (RAG)**: Швидке вилучення знань за допомогою лексичного пошуку та аналізу залежностей кодової бази.

---

## Розділи Енциклопедії

Для глибокого вивчення кожної концепції перейдіть до відповідного розділу:

### 1. [Філософія та Стратегія](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/philosophy.md)
Концепція Local-First, захист ресурсів розробника (Resource Politeness), LLM як вузькоспеціалізований диспетчер та детальний розбір **12-рівневої шкали складності задач** (від `nano` до `giant`).

### 2. [Архітектура та DIP (Dependency Inversion Principle)](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/architecture.md)
Аналіз модульної структури проєкту, використання принципу інверсії залежностей, детальний розбір головних інтерфейсів ([IMemoryOSConfig](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/interfaces.py#L6), [IMemoryStorage](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/interfaces.py#L23), [ILlmProviderService](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/interfaces.py#L42)) та їхнього розширення.

### 3. [Схема даних та Зберігання](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/database.md)
Опис схеми SQLite-бази даних [memory_os.db](file:///Users/oleksii/Documents/memory_os/src/memory_os/memory/memory_os.db) (таблиці телеметрії, пам'яті та швидкодії алгоритмів) та структури серіалізації файлів графу знань (`nodes.jsonl`, `edges.jsonl`, `events.jsonl`, `task_capsules.jsonl`).

### 4. [Автомат життєвого циклу знань](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/lifecycle.md)
Як працює перехід станів пам'яті: від чернетки (`draft`) та спостережуваних фактів до перевірених правил (`verified`) та їхнього витіснення/застарівання (`superseded`, `stale`) за допомогою репутації та перевірки файлів-доказів (evidence).

### 5. [LLM Compaction та Semantic Compression](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/compaction.md)
Розрахунок ущільнення сирих капсул задач у знання, робота в різних режимах навантаження процесора (`quiet`, `normal`, `max`) та семантичне стиснення графу (злиття подібних правил із вибудовуванням ребер `overrides`).

### 6. [Пошук, Індексація та RAG](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/search.md)
Аналіз роботи [ContextRegistry](file:///Users/oleksii/Documents/memory_os/src/memory_os/modules/context.py#L8), вилучення символів коду (класів, функцій, залежностей) через AST-аналіз, пошук зв'язків у коді (implicit coupling) та ранжування результатів пошуку для надання контексту LLM.

### 7. [CLI та Інструментарій розробника](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/cli_tools.md)
Детальний довідник CLI-команд [cli.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/cli.py) (19+ підкоманд), робота з аудитором [auditor.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/toolkit/auditor.py), аналізатором продуктивності [analyzer.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/toolkit/analyzer.py) та зчитувачем логів розробника [transcript_ingestor.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/toolkit/transcript_ingestor.py).

---

## Навігаційна карта кодової бази

Для швидкого орієнтування в коді використовуйте наступну карту файлів:
* **Публічний інтерфейс**: [__init__.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/__init__.py)
* **Головний CLI інтерфейс**: [cli.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/cli.py)
* **Ядро та Підключення**: [core.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/core.py)
* **Сервіс LLM**: [llm_service.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/llm_service.py)
* **Конфігурація**: [config.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/config.py)
* **Модуль Compactor**: [compactor.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/modules/compactor.py)
* **Модуль Lifecycle**: [lifecycle.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/modules/lifecycle.py)
* **Модуль Search**: [search.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/modules/search.py)
