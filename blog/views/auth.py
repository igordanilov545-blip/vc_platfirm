"""Вьюхи домена «auth». Часть пакета blog.views (см. README.md).

Общие хелперы/импорты — из ._common (is_ajax, modal_form_response, captcha,
dc=data_controller, logger, декораторы). Здесь только вьюхи этого домена.
"""
from ._common import *  # noqa: F401,F403


def _post_tg_login_redirect(request, user):
    """Куда отправить пользователя сразу после входа через Telegram. Если аккаунт
    ещё не «заполнен» (нет ФИО) — на дозаполнение профиля, сохранив исходный next,
    чтобы после заполнения вернуть человека туда, куда он шёл (напр. подача заявки)."""
    target = _safe_next(request)
    if not account_is_complete(user):
        return reverse('complete_profile') + f'?next={quote(target)}'
    return target

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    from django.conf import settings

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = authenticate(
            request,
            login=form.cleaned_data['login'],
            password=form.cleaned_data['password'],
        )
        if user is not None:
            auth_login(request, user)
            logger.info('Веб-вход по логину/паролю успешен: user=%s login=%s', user.id, user.login)
            return redirect(_safe_next(request))
        logger.warning('Неудачная попытка веб-входа: login=%r', form.cleaned_data.get('login'))
        messages.error(request, 'Неверный логин или пароль.')

    return render(request, 'blog/login.html', {
        'form': form,
        'next': request.GET.get('next', ''),
        'tg_bot_username': settings.TG_BOT_USERNAME,
        # Абсолютный URL коллбэка Login Widget — Telegram шлёт данные на data-auth-url.
        'tg_widget_auth_url': request.build_absolute_uri(reverse('telegram_login_callback')),
    })

def register_view(request):
    """Самостоятельная веб-регистрация без Telegram (см. RegisterForm docstring и
    coding-principles.md §3 — правило "аккаунт всегда через telegram_id" ослаблено:
    веб-регистрация создаёт аккаунт со служебным telegram_id `web_register:<uuid>`,
    как import:* у Excel-импорта, до подтверждения через бота.

    Если находится совпадение по ФИО/Telegram/телефону с уже существующим
    пользователем — не блокируем, создаём новый аккаунт и после входа показываем
    плашку с просьбой подтвердить личность через бота (см. dashboard, messages)."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    from blog.services.applications import find_matching_user
    import uuid as uuid_lib

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        existing = find_matching_user(
            telegram_username=data['telegram_username'], phone=data['phone'],
            first_name=data['first_name'], last_name=data['last_name'],
        )
        user = User.objects.create_user(
            telegram_id=f'web_register:{uuid_lib.uuid4()}',
            first_name=data['first_name'], last_name=data['last_name'], middle_name=data['middle_name'],
            telegram_username=data['telegram_username'], phone=data['phone'], birthday=data['birthday'],
            login=data['login'],
        )
        user.set_password(data['password'])
        user.web_credentials_set_at = timezone.now()
        user.save()
        logger.info('Веб-регистрация: создан user=%s login=%s matched_existing=%s', user.id, user.login, existing.id if existing else None)

        auth_login(request, user, backend='blog.auth_backends.WebLoginBackend')
        if existing:
            from django.conf import settings
            messages.warning(
                request,
                'Мы нашли похожий профиль в системе (по ФИО/Telegram/телефону). '
                'Чтобы объединить историю мероприятий с этим аккаунтом, подтвердите себя '
                f'через Telegram-бота: https://t.me/{settings.TG_BOT_USERNAME}',
            )
        messages.success(request, 'Регистрация завершена. Добро пожаловать!')
        return redirect('dashboard')

    return render(request, 'blog/register.html', {'form': form})

@csrf_exempt
def telegram_login_callback(request):
    """Коллбэк Telegram Login Widget (браузерный вход вне Mini App): виджет
    редиректит сюда с подписанными полями пользователя. Проверяем HMAC и логиним.

    `csrf_exempt` по тем же причинам, что и `webapp_auth`: подлинность подтверждается
    подписью Telegram, а не CSRF-токеном (у клиента ещё нет сессии)."""
    from blog.services.telegram_auth import validate_login_widget
    from data_base import data_controller as dc

    data = {k: v for k, v in request.GET.items() if k != 'next'}
    payload = validate_login_widget(data)
    if not payload or not payload.get('id'):
        logger.warning('Login Widget: не удалось подтвердить подпись Telegram.')
        messages.error(request, 'Не удалось подтвердить вход через Telegram. Попробуйте ещё раз.')
        return redirect('login')

    user, created = dc.get_or_create_user_by_telegram_id(
        payload['id'], payload.get('username'),
        first_name=payload.get('first_name'), last_name=payload.get('last_name'),
    )
    if user.status == 'blacklisted':
        logger.warning('Login Widget: вход заблокированного пользователя отклонён user=%s', user.id)
        messages.error(request, 'Доступ ограничен — обратитесь к менеджеру центра.')
        return redirect('login')

    auth_login(request, user, backend='blog.auth_backends.TelegramWebAppBackend')
    logger.info('Веб-вход через Telegram Login Widget: user=%s created=%s', user.id, created)
    return redirect(_post_tg_login_redirect(request, user))

@login_required
@require_POST
def verify_telegram_start(request):
    """ЛК → «Подтвердить телеграм»: создаём одноразовый токен и уводим пользователя в
    бота по deep-link `?start=verify_<token>`. Дальнейшее — в боте (подтверждение да/нет),
    см. blog.services.telegram_verify и хендлер common.cmd_start."""
    from blog.services.telegram_verify import issue_verify_token

    bot_username = (settings.TG_BOT_USERNAME or '').lstrip('@')
    if not bot_username:
        messages.error(request, 'Бот не сконфигурирован — обратитесь к менеджеру центра.')
        return redirect('profile_edit')

    token = issue_verify_token(request.user)
    deep_link = f'https://t.me/{bot_username}?start=verify_{token.token}'
    logger.info('Запущено подтверждение Telegram из ЛК: user=%s', request.user.id)
    return redirect(deep_link)

def tg_link_login(request, token):
    """Вход по одноразовой ссылке из бота (deep-link `?start=weblogin`): проверяем
    токен (не использован и не старше 5 минут), логиним и гасим токен."""
    from blog.services.web_auth import consume_auth_token

    user = consume_auth_token(str(token))
    if user is None:
        messages.error(request, 'Ссылка для входа недействительна или устарела. Запросите новую в боте.')
        return redirect('login')
    if user.status == 'blacklisted':
        messages.error(request, 'Доступ ограничен — обратитесь к менеджеру центра.')
        return redirect('login')

    auth_login(request, user, backend='blog.auth_backends.TelegramWebAppBackend')
    return redirect(_post_tg_login_redirect(request, user))

def logout_view(request):
    auth_logout(request)
    return redirect('login')

def webapp_entry(request):
    """Страница-лоадер, открываемая кнопкой Mini App в боте: достаёт `initData` из
    Telegram WebApp JS SDK на клиенте и отправляет на `webapp_auth`.

    Единственная страница, которой разрешено встраиваться в `<iframe>` (десктопный
    Telegram-клиент открывает Mini App именно так) — остальной сайт по-прежнему
    защищён от clickjacking через глобальный `XFrameOptionsMiddleware` (DENY).
    """
    response = render(request, 'blog/webapp_entry.html')
    response['X-Frame-Options'] = 'ALLOWALL'
    return response

@csrf_exempt
def webapp_auth(request):
    """Проверяет `initData`, логинит (или создаёт как гостя) пользователя по
    `telegram_id` через обычную Django-сессию — без пароля.

    `csrf_exempt` обоснован: подлинность запроса здесь подтверждается HMAC-подписью
    Telegram (`validate_init_data`), а не CSRF-токеном — на этот момент у клиента ещё
    нет сессии/csrf-cookie (это первый запрос Mini App), так что обычная CSRF-защита
    в принципе неприменима, как и для вебхуков внешних сервисов.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)

    from blog.services.telegram_auth import validate_init_data
    from data_base import data_controller as dc

    init_data = request.POST.get('init_data', '')
    payload = validate_init_data(init_data)
    if not payload or not payload.get('user') or not payload['user'].get('id'):
        logger.warning('Mini App auth: невалидный или устаревший initData.')
        return JsonResponse({'error': 'Не удалось подтвердить данные Telegram.'}, status=400)

    tg_user = payload['user']
    user, created = dc.get_or_create_user_by_telegram_id(
        tg_user['id'], tg_user.get('username'),
        first_name=tg_user.get('first_name'), last_name=tg_user.get('last_name'),
    )
    if user.status == 'blacklisted':
        logger.warning('Mini App auth: вход заблокированного пользователя отклонён user=%s', user.id)
        return JsonResponse({'error': 'Доступ ограничен — обратитесь к менеджеру центра.'}, status=403)

    auth_login(request, user, backend='blog.auth_backends.TelegramWebAppBackend')
    logger.info('Вход через Mini App: user=%s created=%s', user.id, created)
    # Флаг в сессии: запросы из Mini App разрешено встраивать в <iframe> (десктопный
    # Telegram-клиент), обычный веб-вход по логину/паролю — по-прежнему DENY против
    # clickjacking. Читается в TelegramWebAppFrameMiddleware.
    request.session['is_webapp_session'] = True
    return JsonResponse({'redirect': _post_tg_login_redirect(request, user)})
