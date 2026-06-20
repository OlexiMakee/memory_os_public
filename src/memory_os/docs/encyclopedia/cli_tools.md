# Розділ 7: CLI та Інструментарій розробника

Memory OS постачається зі зручним та потужним CLI-інтерфейсом [cli.py](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/cli.py) та набором інструментів автоматизації. Вони дозволяють керувати базою знань, оцінювати складність завдань та проводити аудит стану проєкту безпосередньо з терміналу.

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
Запускає LLM-компактори для обробки неущільнених капсул задач та генерації нових draft-вузлів і ребер у графі пам'яті.

### 1.9. `compress`
Аналізує граф верифікованих знань та виконує семантичне стиснення (злиття дублікатів через ребра `overrides`).

### 1.10. `prune`
Переносить застарілі (`stale`, `superseded`) вузли в архів та очищує пошкоджені або неактивні зв'язки.

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
Здійснює пошук за графом пам'яті та кодовою базою (з урахуванням AST-символів та дерева залежностей).
* **Аргументи**: `query` (слово або назва символу), `--depth` (глибина пошуку), `--json` (вивід у форматі JSON).

### 1.18. `analyze-os`
Аналізує внутрішню швидкодію алгоритмів Memory OS за даними таблиці `memory_os_performance` та формує пропозиції щодо оптимізації коду ядра.

### 1.19. `giant-scan`
Запускає глибокий аудит усього проєкту. Збирає повний вихідний код проєкту та граф пам'яті, надсилає до великої моделі (наприклад, `gemini-2.5-pro`) та формує список архітектурних пропозицій.

---

## 2. OS Performance Analyzer (Аналізатор Швидкодії)

Клас [OSPerformanceAnalyzer](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/toolkit/analyzer.py#L31) використовується для самоперевірки продуктивності ядра:
1. Зчитує середню тривалість викликів LLM та обробки алгоритмів із таблиць SQLite.
2. Формує текстовий звіт про роботу системи (Digest).
3. Надсилає його до моделі Gemini з інструкцією [ADVISOR_PROMPT](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/toolkit/analyzer.py#L11).
4. Отримані рекомендації зберігаються у файлі `agent_proposals/admin_proposals.jsonl` зі статусом `draft` для подальшого схвалення розробником.

---

## 3. Transcript Ingestor (Зчитувач логів) та Важливе Зауваження Розробнику

Клас [TranscriptIngestor](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/toolkit/transcript_ingestor.py#L37) розпізнає успішно завершені завдання з Conv-Log сесій.

> [!IMPORTANT]
> **Увага розробника (Runtime Mismatch)**:
> У поточній реалізації методу [ingest()](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/toolkit/transcript_ingestor.py#L68) присутня помилка виклику інтерфейсу LLM:
> * На рядку 76 використовується виклик `self.llm.generate(...)`.
> * Проте інтерфейс [ILlmProviderService](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/core/interfaces.py#L42) та клас [DefaultLlmProviderService](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/core/llm_service.py#L69) мають виключно метод `call_llm(...)`.
> * **Виправлення**: При кастомізації або використанні цього інструменту в коді, змініть виклик на:
>   ```python
>   result_text = self.llm.call_llm(
>       user_message=prompt,
>       system_prompt="You are a helper...",
>       provider=provider,
>       model=model
>   )
>   ```

---

## 4. Автоматизація Аудитора (Auditor) та Запуск Тестів

Клас [auditor.py](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/toolkit/auditor.py) виконує не лише пасивний збір статистики, а й активну верифікацію пропозицій (пропозиції типу `proposal.<номер>`):

### Процес автоматичної верифікації пропозицій:
1. Метод [auto_transition_proposals()](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/toolkit/auditor.py#L176) знаходить у `nodes.jsonl` верифіковані вузли, ідентифікатор яких починається з `proposal.`.
2. Система шукає відповідний запис у файлі пропозицій `agent_proposals/admin_proposals.jsonl` зі статусом `active`.
3. З масиву `evidence` цього вузла вибираються Python файли тестів (що знаходяться в директоріях `tests/` або `scratch/`).
4. Для кожного файлу тесту запускається ізольована команда тестування через `subprocess`:
   `python -m unittest tests/test_file.py`
5. Якщо всі тести завершилися з кодом повернення `0` (успішно):
   * Статус пропозиції в `admin_proposals.jsonl` змінюється на `done`.
   * До журналу `events.jsonl` додається подія завершення пропозиції `memory.proposal.completed` із переліком запущених тестів.
   * Автоматично перекомпілюється маніфест знань.
   
Це дозволяє реалізувати повністю автоматизований цикл: *LLM пропонує фічу -> Агент пише код та тести -> Компактор фіксує знання -> Аудитор проганяє тести і закриває пропозицію.*
