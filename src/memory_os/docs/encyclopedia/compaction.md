# Розділ 5: LLM Compaction та Semantic Compression

Оскільки AI-агенти працюють безперервно, кількість сирих логів та капсул задач швидко збільшується. Для перетворення цього потоку інформації на структуровані правила та вилучення цінного досвіду Memory OS використовує два LLM-алгоритми: **Compaction (Ущільнення)** та **Semantic Graph Compression (Стиснення графу)**.

---

## 1. Процес ущільнення знань (Compaction)

Метод [compact_capsules](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/modules/compactor.py#L115) класу [MemoryCompactor](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/modules/compactor.py#L86) реалізує покрокове вилучення знань:

### Крок 1: Виявлення неущільнених капсул
Система зчитує всі капсули з файлу `agent_context/task_capsules.jsonl`. Далі вона сканує `events.jsonl` на наявність подій типу `memory.task_capsules.compacted` та збирає масив уже оброблених міток часу (`compacted_timestamps`). Капсули, чиї мітки часу відсутні в цьому масиві, визначаються як **неущільнені** (new/uncompacted).

### Крок 2: Пакетна обробка та ресурси
Залежно від налаштування `resource_mode` у `MemoryOSConfig` розраховується розмір пакета:
* `quiet`: Пакети по 2 капсули. Після кожного запиту до LLM потік зупиняється на 5 секунд (`time.sleep(5)`), щоб дати CPU відпочити.
* `normal`: Пакети по 5 капсул. Пауз немає.
* `max`: Пакети по 10 капсул.

### Крок 3: Запит до LLM (Knowledge Compactor)
Для кожного пакета формується повідомлення, що містить список існуючих вузлів (тільки `id`, `type`, `summary` для економії токенів) та детальний опис нових неущільнених задач. 
LLM за допомогою [SYSTEM_PROMPT](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/modules/compactor.py#L17) повертає JSON із пропозиціями нових вузлів та зв'язків.

```json
{
  "nodes": [
    {
      "id": "module.auth.jwt_rotation",
      "type": "rule",
      "summary": "JWT токени мають оновлюватися кожні 15 хвилин для запобігання сесійного дрейфу",
      "evidence": ["src/auth/jwt.py"]
    }
  ],
  "edges": [
    {
      "source": "module.auth.jwt_rotation",
      "target": "security.policy.tokens",
      "type": "depends_on"
    }
  ]
}
```

### Крок 4: Обробка та валідація результатів
* Якщо запропонований вузол уже існує в базі, пропозиція відхиляється.
* Шляхи до файлів у `evidence` перевіряються на фізичну наявність. Файл `task_capsules.jsonl` автоматично додається до списку доказів.
* Нові вузли записуються до `nodes.jsonl` зі статусом `draft` та рівнем довіри `unverified`.
* В `events.jsonl` додається подія `memory.node.proposed` зі статусом `pending`.
* Ребра записуються до `edges.jsonl` за умови, що обидва пов'язані вузли існують.
* До `events.jsonl` записується подія успішного ущільнення пакета `memory.task_capsules.compacted` із масивом оброблених міток часу.

### Крок 5: Пост-компакшн конвеєр
Після завершення обробки всіх неущільнених капсул автоматично запускаються наступні кроки:
1. `LifecycleManager.transition()` — переводить чернетки у статус `verified`.
2. `LifecycleManager.prune()` — прибирає застарілі та некоректні ребра й вузли.
3. `LifecycleManager.manifest()` — оновлює файли маніфесту та контрольні суми.
4. `self.archive_compacted_capsules()` — переносить капсули в архів.
5. Запуск `scripts/compact_memory.py --write` для оновлення локального контекстного зрізу.

---

## 2. Семантичне стиснення графу (Semantic Graph Compression)

Коли в системі накопичується багато верифікованих вузлів, деякі правила можуть дублювати або перекривати одне одного. Метод [compress_graph](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/modules/compactor.py#L374) вирішує цю проблему:

1. Збирає всі верифіковані вузли знань (`status == 'verified'`). Якщо їх менше двух, стиснення не запускається.
2. Передає їхній список до LLM із промптом [COMPRESSION_PROMPT](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/modules/compactor.py#L58).
3. LLM аналізує схожість та пропонує **новий об'єднаний вузол** (unified node) та ребра типу `overrides` від нового об'єднаного вузла до ВСІХ старих вузлів, які він заміщує.
4. Об'єднаний вузол додається як `draft`, а ребра `overrides` записуються в `edges.jsonl`.
5. Запуск циклу `transition()` переводить новий вузол у стан `verified`, а старі вузли автоматично маркує як `superseded`, після чого `prune()` переносить їх в архів.

---

## 3. Архівування капсул задач (Capsule Archival)

Для економії токенів розробника під час роботи агента, великі файли капсул мають очищуватися. Метод [archive_compacted_capsules](https://github.com/OlexiMakee/memory_os_public/blob/main/src/memory_os/modules/compactor.py#L485) працює так:

* Всі вже ущільнені капсули (чиї мітки часу є в масиві подій компактізації) переносяться з `task_capsules.jsonl` до файлу `agent_context/archived_task_capsules.jsonl`.
* Щоб зберегти плавний перехід контексту, в основному файлі `task_capsules.jsonl` залишаються всі неущільнені капсули плюс **останні 5 (`keep_recent=5`)** вже ущільнених капсул. Це дає агенту можливість бачити найновішу історію дій безпосередньо у поточному вікні роботи.
* Файл `task_capsules.jsonl` перезаписується у відсортованому за часом вигляді.
