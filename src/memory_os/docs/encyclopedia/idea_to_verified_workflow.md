# Розділ 8: Від ідеї до перевіреного результату — повний цикл

Цей розділ демонструє наскрізний цикл "engineering control plane", зібраний у Stages 0-14: від нечіткої ідеї до перевіреного, задокументованого результату. Усі команди нижче виконані реально з кореня репозиторію; вивід — справжній, не вигаданий.

---

## 1. `idea expand` — прояснення нечіткої ідеї

```bash
PYTHONPATH=src python3 -m memory_os idea expand --text "ship a faster in-memory cache layer" --dry-run
```

```
You are the Memory OS Idea Expansion agent. Your task is to expand the following raw idea:
ship a faster in-memory cache layer

Using the following project context if relevant:
{{project_context}}

Follow these core principles:
1. Local-First: Frame all suggestions around local capabilities.
2. Context selection: Select only relevant context. Do not dump the entire repo.
3. Verification: Require deterministic verification before confidence.
4. Evidence: Base decisions on concrete evidence rather than vibes.
5. No Secret Capture: Never extract or store secrets/API keys.

Produce a detailed discovery brief addressing:
- Problem statement
- Non-goals (what we will NOT do)
- ...

(rendered only — no LLM call was made; pass this prompt to a provider yourself)
```

Команда нічого не викликає мережею — це чистий рендеринг шаблону з `toolkit/prompts/idea_expand.md`. Результат призначений для подальшої передачі моделі, або для прямого використання людиною як чек-листа питань.

## 2. `spec init` — перетворення ідеї на специфікацію

```bash
PYTHONPATH=src python3 -m memory_os spec init "Tutorial Faster Cache"
```

```
Created spec workspace: specs/001-tutorial-faster-cache
- spec: specs/001-tutorial-faster-cache/spec.md
- plan: specs/001-tutorial-faster-cache/plan.md
- tasks: specs/001-tutorial-faster-cache/tasks.md
- checklist: specs/001-tutorial-faster-cache/checklist.md
```

Створені файли — це чисті plain-text шаблони з маркерами `[NEEDS CLARIFICATION: ...]`, які треба явно вирішити, перш ніж `spec analyze` пропустить специфікацію. Це навмисний "spec bottleneck"-гейт (P1 з DEV_STRATEGY.md): неясність має бути виявлена тут, а не під час імплементації.

## 3. Вирішення маркерів і `spec analyze`

Після ручного редагування `spec.md` (заповнення розділу Goal, вирішення маркера) та `plan.md` (заповнення `Rollback path:`):

```bash
PYTHONPATH=src python3 -m memory_os spec analyze 001-tutorial-faster-cache
```

```
# Spec Analysis

- OK: true
- Feature: 001-tutorial-faster-cache
- Requirements: FR-001
- Scenarios: SC-001
- Tasks: T001, T002, T003
```

`spec analyze` перевіряє не лише відсутність маркерів, а й структурні гейти: нумеровані вимоги (`FR-NNN`), сценарії прийняття (`SC-NNN`), Constitution Check, Verification Plan у плані, трасованість завдань.

## 4. `contract build` — машиночитаний контракт без LLM

```bash
PYTHONPATH=src python3 -m memory_os contract build 001-tutorial-faster-cache
```

```
# Contract: Tutorial Faster Cache

Risk class: migration-risk

## Objective
Replace the existing dict-based cache with an LRU-bounded in-memory cache to cut p95 lookup latency.

## Rollback Plan
Derived from Migration And Compatibility (plan.md):
revert the cache module commit; no data migration needed.

Wrote specs/001-tutorial-faster-cache/contract.md and specs/001-tutorial-faster-cache/contract.json
```

Зверніть увагу: `risk_class` визначився як `migration-risk` автоматично — це детерміністична евристика (`SpecManager._infer_risk_class`), яка дивиться, чи `plan.md` містить реальний (не порожній) Rollback path. Жодного звернення до LLM не було — увесь контракт виведений з уже існуючих текстових артефактів.

## 5. `context build` — цільовий пакет контексту, не дамп репозиторію

```bash
PYTHONPATH=src python3 -m memory_os context build --task "faster cache layer" --dry-run
```

Вибірка з реального виводу (топ за релевантністю):

```
relevant_files: 9 файлів, разом ≈ 8000 token_estimate
  specs/001-tutorial-faster-cache/contract.md   score=36
  specs/001-tutorial-faster-cache/spec.md       score=33
  specs/001-tutorial-faster-cache/plan.md       score=31
  src/memory_os/core/scheduler.py               score=25
  agent_context/IMPORTANT_PROPOSAL.md           score=26
  ...
excluded_noise: 151 файлів (irrelevant / over-budget / secret-policy)
```

**Важливе застереження, виявлене саме під час написання цього розділу:** перші прогони `context build` на цьому репозиторії (де `DEV_STRATEGY.md` та інші великі markdown-файли вже виросли до тисяч рядків) повертали пакет на **10 000+ рядків** — більший за частину самого репозиторію, що прямо суперечить меті Stage 4 ("не виливати весь репозиторій"). Причина: `relevant_files` вкладав повний (відредагований) текст кожного релевантного файлу без жодного обмеження на сумарний розмір пакету.

Це було виправлено в той самий момент написання цього walkthrough: `ContextPackBuilder.build()` отримав параметр `max_total_tokens` (за замовчуванням 8000). Файли обираються за `relevance_score` від найвищого, доки сумарний `token_estimate` не впритул наблизиться до бюджету; решта переносяться в `excluded_noise` з причиною `"over-budget"` (без втрати інформації про те, що вони існували — лише без повного тексту). Перший (найрелевантніший) файл завжди включається повністю, навіть якщо він сам перевищує бюджет — краще один великий релевантний файл, ніж порожній пакет.

## 6. `evidence` — фіксація реальних команд і їх результатів

```bash
PYTHONPATH=src python3 -m memory_os evidence init --task tutorial-faster-cache --risk-class low
PYTHONPATH=src python3 -m memory_os evidence add-command --task tutorial-faster-cache -- python3 -m memory_os validate
PYTHONPATH=src python3 -m memory_os evidence verify --task tutorial-faster-cache
```

```
Created evidence bundle for task 'tutorial-faster-cache' (risk class: low)
$ python3 -m memory_os validate
memory_os validation ok

exit code: 0
Evidence verify: OK (task tutorial-faster-cache)
```

`evidence verify` поверне ненульовий код виходу, якщо: жодної команди не записано, будь-яка записана команда завершилась з помилкою, або `risk_class` не встановлено. Це навмисний гейт — "готово" означає "перевірено", а не "згенеровано".

## 7. `review-pack` — збірка для рецензента

```bash
PYTHONPATH=src python3 -m memory_os review-pack --task tutorial-faster-cache
```

```
## Suggested Reviewer Focus
- touches 30 files (> 20) — consider splitting
- mixes 29 source/doc change(s) with 1 runtime/generated artifact change(s)
- risk class: low

## Not Verified
- no contract found at specs/tutorial-faster-cache/contract.json
- no context pack found at agent_context/context_packs/tutorial-faster-cache/pack.json
```

**Друга реальна деталь, варта уваги:** `review-pack --task <id>` шукає контракт за шляхом `specs/<id>/contract.json`, де `<id>` — це той самий рядок, що й `--task`. У цьому прогоні `--task` був `tutorial-faster-cache`, а реальний `feature_id` специфікації — `001-tutorial-faster-cache` (нумерація додається автоматично в `spec init`). Тому `review-pack` чесно показав "no contract found" — це не баг, а наслідок того, що `task_id` (evidence/review-pack) і `feature_id` (spec/contract) — на сьогодні дві окремі системи ідентифікаторів, які не зв'язуються автоматично. Якщо потрібно, щоб `review-pack` підхопив контракт і context pack, передавайте однаковий ідентифікатор у всі команди (`spec init --id <task_id>`, `evidence init --task <task_id>`, `context build` зі слагом, що відповідає `<task_id>`).

---

## Підсумок DNA Memory OS, продемонстрований цим циклом

1. **Local-first**: жодна команда вище не зробила мережевого виклику чи виклику LLM (усе з `--dry-run` або принципово безмодельне).
2. **Context is selected, not dumped**: пункт 5 показав і проблему, і її виправлення в реальному часі.
3. **Verification before confidence**: `evidence verify` блокує "готовність" без реальних перевірок.
4. **Evidence over vibes**: `review-pack` чесно показує "Not Verified", а не приховує прогалини.
5. **Small batches**: `review-pack` сам попереджає, коли зміна стає завеликою.
