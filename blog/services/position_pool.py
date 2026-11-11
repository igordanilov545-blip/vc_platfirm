"""Пул функций и типовых позиций забегов: базовый набор, подсказки и классификация.

Функции (EventCategory) переиспользуются между мероприятиями: на любом забеге есть
проверка справок, выдача пакетов, дистанция. К функции в пуле привязаны типовые
позиции (PositionTemplate) — подсказки названия при создании позиции.
Решение пользователя от 2026-11-11 заменило прежние тематические категории.
"""
import re
import unicodedata

from data_base import data_controller as dc


# Функции — названия блоков колонки B реальных ФиП 2026 (решение пользователя
# 2026-11-11: «названия из ФиП»). Порядок важен: первая совпавшая функция побеждает.
# Ключевое слово сравнивается с НАЧАЛОМ слова (регистр, ё/е, дефисы не важны).
# Позиции — типовые строки «Позиция» этих ФиП; полная таблица — position-pool.md.
DEFAULT_FUNCTIONS = [
    ('Волонтёры-медики', ('медик', 'медицинской помощ'), [
        'Тим-лидер волонтёров-медиков', 'Волонтёр-медик']),
    ('Волонтёры-атташе и волонтёры отеля-партнёра', ('атташе', 'элит', 'отел', 'спу', 'тренеров'), [
        'Тим-лидер волонтёров-атташе и отеля-партнёра', 'Волонтёр-атташе элитных спортсменов',
        'Волонтёр сервисов для элитных спортсменов в отеле', 'Волонтёр выдачи СПУ элитным спортсменам',
        'Программа для тренеров (отель)']),
    ('Организация сервисов для отдельных клиентских групп',
     ('vip', 'вип', 'гостеприим', 'шлагбаум', 'отдельных клиентских', 'пресс', 'сми', 'трансляц', 'болельщ', 'раздевал'), [
        'Тим-лидер волонтёров организации сервисов для отдельных клиентских групп', 'Волонтёр VIP-финиша',
        'Волонтёр финиша VIP участников', 'Волонтёр парковки для VIP-гостей', 'Волонтёр зоны гостеприимства',
        'Волонтёр раздевалок в стартовом городке', 'Ассистент пресс-центра', 'Ассистент пресс-службы забега',
        'Ассистент трансляции', 'Волонтёр парковки для СМИ и телевещателей', 'Волонтёр выдачи атрибутики болельщика']),
    ('Волонтёры режиссёрской группы', ('режисс', 'награ', 'финишной ленты', 'конкурс', 'анимац', 'грамот', 'мониторинг'), [
        'Тим-лидер волонтёров режиссёрской группы', 'Ассистент режиссёрской группы',
        'Волонтёр финишной ленты и церемонии награждения', 'Волонтёр церемонии награждения',
        'Волонтёр выдачи наград в возрастных категориях', 'Волонтёр печати грамот', 'Волонтёр детского забега']),
    ('Волонтёры специальных стартов', ('эстафет', 'специальных стартов', 'пункт передачи', 'пунктах передачи'), [
        'Тим-лидер волонтёров корпоративной эстафеты', 'Волонтёр корпоративной эстафеты',
        'Тим-лидер волонтёров организации старта и финиша эстафетных команд',
        'Волонтёр организации старта и финиша для эстафетных команд', 'Волонтёр пункта передачи эстафеты']),
    ('Реализация волонтёрской программы и организация работы волонтёров',
     ('сервисов для волонт', 'волонтерской программ', 'штаб', 'рекрут', 'тренер', 'фотограф', 'наставник', 'офис'), [
        'Тим-лидер организации сервисов для волонтёров', 'Помощник тим-лидера организации сервисов для волонтёров',
        'Волонтёр-фотограф', 'Рекрутер', 'Тренер волонтёров', 'Ассистент в офисе']),
    ('Волонтёры дистанции', ('дистанц', 'освежени', '(по', '(пп', 'обдув'), [
        'Тим-лидер волонтёров пункта освежения', 'Волонтёр пункта освежения',
        'Тим-лидер волонтёров пункта питания на дистанции', 'Волонтёр пункта питания на дистанции',
        'Волонтёр зоны обдува и умывания']),
    ('Организация сервисов для спортсменов и зрителей', ('стюард', 'колокол', 'атрибут', 'шатр', 'зрител'), [
        'Тим-лидер волонтёров организации сервисов для спортсменов и зрителей', 'Стюард парка',
        'Волонтёр колокола финишёра', 'Волонтёр выдачи атрибутики', 'Волонтёры шатра марафона']),
    ('Волонтёры финиша', ('медал', 'воды', 'вода', 'термонакид', 'питания на финише', 'значк', 'разбор', 'финиш'), [
        'Тим-лидер волонтёров выдачи медалей', 'Волонтёр выдачи медалей',
        'Тим-лидер волонтёров выдачи воды', 'Волонтёр выдачи воды',
        'Тим-лидер волонтёров пункта питания на финише', 'Волонтёр выдачи питания на финише',
        'Тим-лидер волонтёров выдачи термонакидок', 'Волонтёр выдачи термонакидок',
        'Волонтёр выдачи медалей детского старта', 'Волонтёр выдачи воды детского старта',
        'Волонтёр выдачи значков', 'Волонтёр разбора медалей']),
    ('Волонтёры старта', ('старт', 'маршал', 'спортивной программ'), [
        'Тим-лидер волонтёров старта', 'Ассистент маршала кластера', 'Ассистент маршала кластера на старте',
        'Ассистент спортивной программы на старте']),
    ('Волонтёры старта и финиша', (), []),
    ('Организация выдачи пакетов участников',
     ('справ', 'ксерокоп', 'выдач', 'номер', 'футбол', 'магазин', 'хостес', 'регистрац', 'планшет', 'пакет'), [
        'Тим-лидер зоны проверки справок', 'Ассистент проверки медицинских справок', 'Хостес зоны проверки справок',
        'Волонтёр для контроля ксерокопирования', 'Тим-лидер зоны выдачи номеров', 'Хостес зоны выдачи номеров',
        'Ассистент выдачи номеров', 'Ассистент выдачи номеров и пакетов участника',
        'Ассистент выдачи номеров и пакетов участника — детский забег', 'Тим-лидер волонтёров зоны выдачи футболок',
        'Ассистент выдачи футболок', 'Ассистент выдачи футболок и пакетов участника',
        'Тим-лидер волонтёров зоны фирменного магазина', 'Хостес в зоне магазина', 'Ассистент фирменного магазина',
        'Тим-лидер волонтёров зоны регистрации и информации', 'Ассистент регистрации новых участников',
        'Ассистент с планшетом', 'Хостес']),
    ('Волонтёры информации и навигации', ('навигац', 'ашер', 'транспортн', 'информац', 'досмотр', 'парков'), [
        'Тим-лидер волонтёров транспортного хаба', 'Ашер в городе', 'Волонтёр навигации', 'Волонтёр точки информации',
        'Волонтёр велопарковки', 'Волонтёр пункта досмотра']),
]

# Прежние названия пула (заход 2026-11-11) → функции ФиП; миграция 0051 переносит связи.
RENAMED_FUNCTIONS = {
    'Проверка медицинских справок': 'Организация выдачи пакетов участников',
    'Детский забег': 'Волонтёры финиша',
    'Эстафеты и спецстарты': 'Волонтёры специальных стартов',
    'Атташе и элитные спортсмены': 'Волонтёры-атташе и волонтёры отеля-партнёра',
    'Пресс-центр и СМИ': 'Организация сервисов для отдельных клиентских групп',
    'VIP и гостеприимство': 'Организация сервисов для отдельных клиентских групп',
    'Режиссёрская группа и награждение': 'Волонтёры режиссёрской группы',
    'Медицинская помощь': 'Волонтёры-медики',
    'Подготовка и разбор медалей': 'Волонтёры финиша',
    'Дистанция': 'Волонтёры дистанции',
    'Старт': 'Волонтёры старта',
    'Финиш': 'Волонтёры финиша',
    'Навигация и стюарды': 'Волонтёры информации и навигации',
    'Регистрация и информация': 'Организация выдачи пакетов участников',
    'Выдача стартовых пакетов': 'Организация выдачи пакетов участников',
    'Штаб и сервисы для волонтёров': 'Реализация волонтёрской программы и организация работы волонтёров',
}

# Прежние тематические категории из seed_data; удаляются, только если не используются.
LEGACY_DEFAULT_CATEGORIES = ['Спорт', 'Культура', 'Экология', 'Образование', 'Социальная помощь']


def _key(text):
    value = unicodedata.normalize('NFKC', str(text or '')).casefold().replace('ё', 'е')
    value = re.sub(r'[‐‑‒–—―−-]', ' ', value)
    return ' ' + re.sub(r'\s+', ' ', value).strip()


def matching_keyword(text):
    """(функция, ключевое слово) по началу слова; None, если не распознано."""
    value = _key(text)
    for name, keywords, _ in DEFAULT_FUNCTIONS:
        for keyword in keywords:
            needle = _key(keyword).strip()
            if re.search(r'(?<![0-9a-zа-я])' + re.escape(needle), value):
                return name, keyword
    return None


def classify(*texts):
    """Название функции пула по тексту позиции (затем — по названию функции ФиП)."""
    for text in texts:
        found = matching_keyword(text)
        if found:
            return found[0]
    return None


def function_name(raw):
    """Название функции из колонки B ФиП: без примечаний «*с последующим …» и лишних
    пробелов; совпадение с пулом — без учёта регистра, ё/е и дефисов."""
    text = re.sub(r'\s+', ' ', str(raw or '').split('*')[0]).strip(' -—')
    wanted = _key(text)
    for name, _, _ in DEFAULT_FUNCTIONS:
        if _key(name) == wanted:
            return name
    return text


def _has_kind(model):
    return any(field.name == 'kind' for field in model._meta.get_fields())


def ensure_default_pool(category_model, template_model, map_model=None, *, drop_legacy=True):
    """Базовый пул; принимает модели, чтобы работать и в миграции, и в seed_data.
    Прежние названия переносятся на функции ФиП вместе с позициями и связями."""
    created = 0
    targets = {}
    extra = {'defaults': {'kind': 'function'}} if _has_kind(category_model) else {}
    for name, _, positions in DEFAULT_FUNCTIONS:
        category, made = category_model.objects.get_or_create(name=name, **extra)
        targets[name] = category
        created += int(made)
        for title in positions:
            template_model.objects.get_or_create(category=category, name=title)
    for old_name, new_name in RENAMED_FUNCTIONS.items():
        old = category_model.objects.filter(name=old_name).first()
        if old is None:
            continue
        target = targets[new_name]
        for template in template_model.objects.filter(category=old):
            if template_model.objects.filter(category=target, name=template.name).exists():
                template.delete()
            else:
                template.category = target
                template.save(update_fields=['category'])
        if map_model is not None:
            for link in map_model.objects.filter(category=old):
                if map_model.objects.filter(event_id=link.event_id, category=target).exists():
                    link.delete()
                else:
                    link.category = target
                    link.save(update_fields=['category'])
        old.delete()
    if drop_legacy:
        category_model.objects.filter(name__in=LEGACY_DEFAULT_CATEGORIES, event_map__isnull=True).delete()
    return created


def pool_choices():
    """Подсказки для поля названия позиции: [(название, функция)]."""
    return [(item.name, item.category.name) for item in
            dc.position_templates_qs().select_related('category').order_by('category__name', 'name')]


def function_category(name, operator=None):
    """Функция пула по названию (из ФиП или введённая человеком); новая — создаётся
    и сразу получает категории по умолчанию по словам названия."""
    name = function_name(name)[:100]
    if not name:
        return None
    found = next((c for c in dc.event_functions_qs() if _key(c.name) == _key(name)), None)
    if found is not None:
        return found
    function = dc.create_event_category(name, kind='function')
    dc.set_function_default_categories(function, [category_by_name(n) for n in default_category_names(name)])
    return function


def position_function(event):
    """Функция позиции — её функция из пула (связь вида function)."""
    if not event.pk:
        return None
    link = event.category_map.filter(category__kind='function').select_related('category').order_by('pk').first()
    return link.category if link else None


# --- Категории забегов (2026-11-11) --------------------------------------------
# Тематические категории беговых мероприятий: по ним считаются достижения и отчёты.
# Функция при выборе сама проставляет свои категории по умолчанию
# (EventCategory.default_categories), их можно поменять вручную.
DEFAULT_CATEGORIES = [
    'Старт', 'Финиш', 'Дистанция', 'Выдача стартовых пакетов', 'Информация и навигация',
    'Медицина', 'VIP и гости', 'Церемонии и шоу', 'Эстафеты и спецстарты',
    'Сервисы для бегунов и зрителей', 'Штаб и волонтёрская программа',
]

# Функции ФиП → категории по умолчанию.
FUNCTION_CATEGORIES = {
    'Волонтёры-медики': ['Медицина'],
    'Волонтёры-атташе и волонтёры отеля-партнёра': ['VIP и гости'],
    'Организация сервисов для отдельных клиентских групп': ['VIP и гости'],
    'Волонтёры режиссёрской группы': ['Церемонии и шоу'],
    'Волонтёры специальных стартов': ['Эстафеты и спецстарты'],
    'Реализация волонтёрской программы и организация работы волонтёров': ['Штаб и волонтёрская программа'],
    'Волонтёры дистанции': ['Дистанция'],
    'Организация сервисов для спортсменов и зрителей': ['Сервисы для бегунов и зрителей'],
    'Волонтёры финиша': ['Финиш'],
    'Волонтёры старта': ['Старт'],
    'Волонтёры старта и финиша': ['Старт', 'Финиш'],
    'Организация выдачи пакетов участников': ['Выдача стартовых пакетов'],
    'Волонтёры информации и навигации': ['Информация и навигация'],
}

# Для новых функций (вписанных человеком): регулярные выражения по названию (ё → е).
CATEGORY_PATTERNS = [
    ('Старт', r'\bстарт(а|е|у|ом)?\b'),
    ('Финиш', r'\bфиниш'),
    ('Дистанция', r'\bдистанц|\bпункт(а|ы)? (питания|освежения)'),
    ('Выдача стартовых пакетов', r'\bпакет|\bвыдач[аи] номер|\bрегистрац|\bсправ'),
    ('Информация и навигация', r'\bинформац|\bнавигац'),
    ('Медицина', r'\bмедик|\bмедиц'),
    ('VIP и гости', r'\bvip\b|\bвип\b|\bатташе|\bгост|\bклиентск'),
    ('Церемонии и шоу', r'\bрежисс|\bнаграж|\bцеремон|\bшоу\b'),
    ('Эстафеты и спецстарты', r'\bэстафет|\bспециальн'),
    ('Сервисы для бегунов и зрителей', r'\bзрител|\bстюард|\bспортсмен'),
    ('Штаб и волонтёрская программа', r'\bштаб|\bпрограмм|\bрекрут'),
]


def default_category_names(function_title):
    """Категории по умолчанию для функции: из таблицы ФиП, иначе по словам названия."""
    known = {_key(name): cats for name, cats in FUNCTION_CATEGORIES.items()}
    if _key(function_title) in known:
        return list(known[_key(function_title)])
    text = _key(function_title)
    return [name for name, pattern in CATEGORY_PATTERNS if re.search(pattern, text)]


def category_by_name(name):
    """Категория пула по названию; новая — создаётся."""
    found = next((c for c in dc.event_categories_qs() if _key(c.name) == _key(name)), None)
    return found or dc.create_event_category(name, kind='category')


def ensure_default_categories(category_model, map_model=None):
    """Категории забегов и связь «функция → категории по умолчанию»; принимает модели,
    чтобы работать и в миграции, и в seed_data. С map_model — проставляет категории
    позициям, у которых уже есть функция (данные до этого изменения)."""
    by_key = {}
    for name in DEFAULT_CATEGORIES:
        category, _ = category_model.objects.get_or_create(name=name, defaults={'kind': 'category'})
        by_key[_key(name)] = category
    for function in category_model.objects.filter(kind='function'):
        if not function.default_categories.exists():
            wanted = [by_key.get(_key(n)) or category_model.objects.get_or_create(name=n, defaults={'kind': 'category'})[0]
                      for n in default_category_names(function.name)]
            function.default_categories.set(wanted)
        if map_model is not None:
            for link in map_model.objects.filter(category=function):
                for category in function.default_categories.all():
                    map_model.objects.get_or_create(event_id=link.event_id, category=category)
    return by_key


def assign_function(event, *texts, operator=None, category=None):
    """Привязать позиции функцию, если её нет: явную, иначе по ключевым словам."""
    current = position_function(event)
    if current is not None:
        return current
    if category is None:
        name = classify(event.title, *texts)
        category = function_category(name) if name else None
    if category is not None:
        dc.set_event_function(event, category)
        apply_default_categories(event, category)
    return category


def apply_default_categories(event, function):
    """Добавить позиции категории по умолчанию её функции (свои — не снимаем)."""
    defaults = list(function.default_categories.all()) if function is not None else []
    if defaults:
        current = dc.event_categories_for_event(event)
        dc.sync_event_categories(event, current + [c for c in defaults if c not in current])


def remember_positions(plan, operator=None):
    """Запомнить позиции ФиП в пуле под их функцией (колонка B): позиции
    переиспользуются между мероприятиями и подсказываются при создании новых."""
    added = 0
    for direction in plan.get('directions', []):
        category = function_category(direction.get('function') or direction['name'], operator)
        if category is None:
            continue
        for position in direction.get('positions', []):
            name = re.sub(r'\s+', ' ', str(position.get('base_name') or position.get('name') or '')).strip(' —-')
            if name and not name.casefold().startswith('итого'):
                dc.ensure_position_template(category, name, operator)
                added += 1
    return added


# Цвет функции в таблицах (2026-11-11): родственные функции — один тон, как
# заливки блоков в ФиП. Индекс → CSS-класс fn-tone-N (nexus.css).
FUNCTION_TONES = (
    (('старт', 'финиш'), 0),
    (('дистанц',), 1),
    (('пакет', 'выдач'), 2),
    (('атташе', 'клиентск', 'отел', 'vip', 'вип'), 3),
    (('медик', 'медиц'), 4),
    (('информац', 'навигац', 'спортсмен', 'зрител'), 5),
    (('режисс', 'специальн'), 6),
    (('реализац', 'программ', 'штаб'), 7),
)


def function_tone(name):
    key = _key(name or '')
    if not key:
        return None
    for words, tone in FUNCTION_TONES:
        if any(word in key for word in words):
            return tone
    return sum(map(ord, key)) % 8
