# `tg_bot/services/` — путеводитель по сервис-слою бота

Бывший `tg_bot/services.py` (868 строк, 53 функции) распилен по доменам. Это
**синхронный** бизнес-слой бота: хендлеры aiogram (async) зовут его через
`asgiref.sync.sync_to_async`. Фасад `__init__.py` реэкспортит всё — `services.<func>()`
в хендлерах работает как раньше.

## С чем работаешь → куда смотреть

Личный QR: `qr_attendance.py::qr_png_for_telegram`, реэкспорт через пакет;
хендлер `common.cmd_get_qr` отправляет PNG как фото без требования заполненной анкеты.

| Домен | Файл | Функции |
|---|---|---|
| **Пользователи** (первое касание, регистрация, профиль, подписки, узнавание аккаунта, роли, веб-креды, статистика) | [`users.py`](users.py) | `get_or_create_user`, `complete_registration`, `update_profile`, `toggle_*`, `recognize_by_telegram`, `confirm_recognized_account`, `user_*`, `set_web_credentials`, `user_stats` |
| **Веб-доступ / верификация** | [`web_auth.py`](web_auth.py) | `issue_web_login_link`, `verify_token_requester`, `confirm/reject_telegram_verification` |
| **Мероприятия** | [`events.py`](events.py) | `open_events`, `event_open_shifts`, `team_leader_events`, `active_events_with_organizers`, `unpublished_events`, `publish_event_from_bot`, `broadcast*` |
| **Заявки / явка** | [`applications.py`](applications.py) | `apply_to_event`, `my_active_applications`, `cancel/edit_own_application`, `submit_feedback`, `process_application*`, `mark_all_attended`, `all_applications`, ссылки на веб |
| **Табличка желающих** | [`volunteer_wishes.py`](volunteer_wishes.py) | `can_add_volunteer_wishes`, `add_volunteer_wishes`, `undo_volunteer_wishes`, `volunteer_wishes_summary`, `volunteer_wishes_web_link` (обёртки над blog/services/volunteer_wishes) |
| **Комментарии** | [`comments.py`](comments.py) | `add_user_comment` |
| **Очередь оценок** | [`feedback_queue.py`](feedback_queue.py) | `pending_feedback_requests`, `mark_feedback_requested` |
| **Инфраструктура очередей** (исходящие, снятие кнопок) | [`outbox.py`](outbox.py) | `schedule_button_removal`, `fetch_due_button_removals`, `fetch_pending_outbox`, `mark_outbox_*` |
| **Общие импорты** | [`_common.py`](_common.py) | `dc`, Django-утилиты, общие сервисы, `logger` |

## Правила (важно для бота)

- **Доступ к данным — только через `dc` (`data_controller`)**, не через `Model.objects`
  (coding-principles §1, tg-bot.md §9). Все модели переведены на контроллер, включая
  инфраструктуру бота (`BotOutbox`/`PendingButtonRemoval` в `outbox.py`, Django-`Session`
  в `users.py`) и техническую аналитику. Новый доступ к БД пиши через `dc`.
- Функции здесь **синхронные**; из async-хендлера зови через `sync_to_async`.
- Бизнес-правило, общее с вебом, бери из `blog/services/*` (они синхронные), не
  дублируй.
- Новую функцию → в подходящий доменный файл + **реэкспортируй** в `__init__.py`.
