# Workflows

> **CRITICAL AGENT RULE**: Ти МОЖЕШ вносити зміни в код локально (редагувати файли в `src/`, `scripts/` тощо). Проте, всі ці зміни ти маєш пушити **тільки в гілку `public`**. Гілка `public` виступає як середовище для твоїх "proposals" (пропозицій). Розробник згодом прочитає ці пропозиції з гілки `public` і самостійно імплементує їх у головному репозиторії. Ніколи не пуш напряму в головні гілки (наприклад, `main`), окрім `public`!


Use two explicit workstreams:
- `product`: customer-facing product work.
- `memory_os`: internal shorthand for agent workflow, telemetry, repo analysis, and self-improvement tools.

Naming guard: `memory_os` is the internal command/workflow alias.

Step scale: 1 nano, 2 micro, 3 tiny, 4 little, 5 pretty little, 6 light mid,
7 mid, 8 high mid, 9 mid high, 10 big, 11 large, 12 giant.
