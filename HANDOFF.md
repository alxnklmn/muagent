# Oblivion Bot handoff

Краткий контекст для следующего агента/Claude. Проект — Telegram Business AI assistant на Python + aiogram + OpenAI-compatible LLM через OpenRouter.

## Текущий статус

Основная точка входа: `src/bot.py`.

База: `src/db.py`, SQLite файл `src/db.sqlite3`.

Бот сейчас умеет:

- проходить onboarding владельца;
- отвечать в Telegram Business-чатах от имени владельца;
- вести owner DM как “штаб” ассистента;
- сохранять Business-контакты, когда человек пишет в доступный Business-чат;
- включать/выключать память через `/memory`;
- помнить/вспоминать/забывать факты через skills;
- создавать задачи и напоминания;
- отправлять напоминания с кнопкой `Готово`;
- начислять task points за закрытие задач;
- готовить outbound-сообщение контакту и отправлять только после подтверждения;
- иметь proactive settings, quiet hours, daily budget и ручной запрос треков;
- показывать inline-кнопки для отправки outbound draft, отмены и memory toggle.

## Последние крупные изменения

### Onboarding

Переписан onboarding flow:

- greeting стал живее;
- первый вопрос: имя, возраст, пол;
- дальше: работа/проекты/хобби;
- дальше: стиль общения;
- дальше: важный контекст;
- финал onboarding теперь deterministic через `ONBOARDING_DONE_REPLY`, а не генерируется LLM.

Финальный текст намеренно без usernames и конкретных примеров:

- 💬 отвечать за тебя в чатах;
- 🧠 запоминать факты/контакты/контекст;
- ✅ создавать задачи и напоминания;
- 🔔 напоминать с кнопкой “готово”;
- 📨 готовить и отправлять сообщения после подтверждения;
- 🎵 скидывать треки;
- 👀 иногда писать сам;
- отдельно говорит, что память по умолчанию выключена и включается через `/memory`.

### Memory

Добавлен skills engine в `src/skills/`:

- `remember`;
- `recall`;
- `forget`;
- `registry`.

Память gated через setting `memory_consent`.

Команда `/memory` работает в owner DM и показывает inline-кнопку:

- `memory:on`;
- `memory:off`.

Если память выключена, ответы должны вести пользователя к `/memory`.

### Contacts + outbound send

Когда приходит `business_message`, бот сохраняет контакт:

- `chat_id`;
- `user_id`;
- `username`;
- `first_name`;
- `last_name`;
- `full_name`;
- `business_connection_id`;
- `last_seen_at`.

Если owner пишет что-то вроде:

```text
напиши моему начальнику пожелания хорошо провести отпуск
```

router классифицирует это как `send`, бот:

1. ищет recipient через facts;
2. резолвит contact;
3. генерирует draft;
4. показывает inline-кнопки `Отправить` / `Отмена`;
5. отправляет через `bot.send_message(..., business_connection_id=...)` только после подтверждения.

### Tasks + scheduler

Добавлена таблица `tasks`.

Поддерживаются фразы:

```text
напомни через минуту купить молочка
напомни завтра купить молока
что у меня по делам?
готово 1
```

Scheduler живёт внутри polling-процесса:

- каждые 15 секунд проверяет due tasks;
- отправляет owner DM;
- добавляет кнопку `Готово`;
- после нажатия закрывает задачу и начисляет очки.

Есть LLM formatter для task microcopy: `TASK_VOICE_SYSTEM`.

Важный фикс: `через минуту` теперь парсится как 1 минута. Фразы без содержательной задачи вроде `через минуту напомни пожалуйста` не должны создавать задачу.

### Proactive / music

Добавлены settings:

- `proactive_enabled`;
- `music_enabled`;
- `gifs_enabled`;
- `daily_checkin_enabled`;
- `quiet_hours`;
- `proactive_daily_budget`.

Добавлен `proactive_log`.

Natural settings router понимает:

```text
можешь иногда писать сам
не пиши сам
без треков
можешь кидать треки
без гифок
пиши реже
можно чаще
скинь трек для фокуса
```

Треки пока curated в `src/assets/tracks.json`. Пользователь считает это временной заглушкой и хочет заменить на умный поиск музыки, возможно через внешний API. Важно: Telegram inline-ботов нельзя вызывать программно через Bot API как поиск.

## DB additions

В `src/db.py` добавлены structured tables:

- `facts`;
- `audit_log`;
- `tasks`;
- `proactive_log`.

И методы:

- facts: `add_fact`, `recall_facts`, `forget_facts`;
- audit: `append_audit_log`;
- tasks: `add_task`, `list_tasks`, `due_tasks`, `mark_task_reminded`, `complete_task`;
- proactive: `add_proactive_log`, `proactive_count_since`, `last_proactive`;
- contacts: `find_contact`.

## Важные user ids

Есть два owner-а в текущей базе:

- основной owner: `7694403892`;
- test owner / `falldkps`: `1864852861`.

Для `falldkps` onboarding был сброшен в конце работы:

- `state=awaiting_name`;
- identity удалена;
- onboarding history очищена;
- settings сброшены;
- tasks/facts/contacts очищены;
- business connection сохранён;
- fresh greeting отправлен.

## Как запускать

Из корня проекта:

```bash
source .venv/bin/activate
python src/bot.py
```

В этой сессии бот обычно запускается через long-running exec. Если нужно перезапустить:

```bash
ps aux | rg -i "(src/bot.py|python -u bot.py)" | rg -v "rg -i"
kill <pid>
.venv/bin/python src/bot.py
```

## Быстрые проверки

Компиляция:

```bash
.venv/bin/python -m py_compile src/bot.py src/db.py src/skills/*.py
```

Memory:

```text
/memory
@someone мой начальник
кто мой начальник?
```

Tasks:

```text
напомни через минуту купить молочка
что у меня по делам?
готово 1
```

Outbound:

1. contact должен сначала написать в доступный Business-чат;
2. owner включает memory через `/memory`;
3. owner сохраняет факт про контакт;
4. owner просит написать этому человеку;
5. бот даёт draft + кнопки.

Example:

```text
@falldkps мой начальник
напиши моему начальнику хорошего отпуска
```

Proactive/music:

```text
можешь иногда писать сам
не пиши сам
скинь трек для фокуса
без треков
```

## Известные ограничения

- Music сейчас через local curated JSON, не настоящий поиск.
- GIF support ещё не реализован, только setting.
- `chat_history` для Business всё ещё key-ится по `user_id`, не owner+chat. Для multi-owner лучше исправить.
- Scheduler живёт внутри polling-процесса, отдельного worker-а нет.
- Parsing дат простой: `через минуту`, `через N минут`, `через час`, `завтра`, `сегодня`, `послезавтра`.
- Proactive работает только если включён и не quiet hours. Quiet hours default: `23:00-09:00`.
- Inline buttons есть для memory, outbound confirm, task done.

## Git / worktree

На момент handoff изменений много и они не закоммичены. Перед коммитом обязательно посмотреть:

```bash
git status --short
git diff --stat
```

Не трогать `.env` и не коммитить `src/db.sqlite3`, `logs/`.
