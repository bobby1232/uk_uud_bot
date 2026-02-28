# УК Bot (Telegram) — заявки на платные услуги

## Что внутри
- Telegram bot на **aiogram 3**
- Postgres через **asyncpg**
- Автосоздание таблиц и seed услуг при старте (idempotent)
- Постинг карточек заявок в рабочую группу + кнопки статусов
- Оценка 1–5 + комментарий → архив

## Быстрый старт локально
1) Создайте Postgres и получите DATABASE_URL
2) Скопируйте `.env.example` → `.env` и заполните
3) Запуск:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python -m app.main
   ```

## Railway
- Добавьте сервис (Deploy from GitHub или Upload)
- Добавьте Railway Postgres (Plugin)
- В Variables задайте:
  - `BOT_TOKEN`
  - `DATABASE_URL` (Railway выдаст)
  - `GROUP_CHAT_ID` (ID группы, куда бот постит заявки)
  - опционально `ADMIN_IDS` (список админов через запятую)
- Убедитесь, что бот добавлен в группу и имеет право писать сообщения.

## Примечания
- `GROUP_CHAT_ID` должен быть в формате `-100...`
- Если хотите управлять админами из БД — добавьте их в таблицу `admin_users` или через env `ADMIN_IDS`.
