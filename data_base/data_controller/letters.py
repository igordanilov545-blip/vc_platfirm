"""Доступ к данным: шаблоны благодарственных писем и шрифты для них
(конструктор писем, letter-templates.md).

Тонкий CRUD (coding-principles §1): загрузка PDF-фона/шрифта, чтение/запись
конфигурации полей (`fields_json`), список шрифтов. Рендер PDF и бизнес-логика —
в blog.services.letter_render, не здесь.
"""
from typing import Optional, List

from blog.models import ThankYouLetterTemplate, LetterFont, User
from ._base import logger, actor


# --- Шаблоны писем -----------------------------------------------------------

def letter_templates_qs():
    """Ленивый queryset шаблонов писем (для настроек/выбора в форме меро)."""
    return ThankYouLetterTemplate.objects.all()


def get_letter_template_by_id(template_id) -> Optional[ThankYouLetterTemplate]:
    return ThankYouLetterTemplate.objects.filter(pk=template_id).first()


def create_letter_template(title: str, actor_user: Optional[User] = None) -> ThankYouLetterTemplate:
    tpl = ThankYouLetterTemplate.objects.create(title=title)
    logger.info('Создан шаблон письма: template=%s title=%r by=%s', tpl.id, title, actor(actor_user))
    return tpl


def set_letter_background(
    template: ThankYouLetterTemplate, pdf_bytes: bytes, filename: str,
    width_pt: float, height_pt: float, actor_user: Optional[User] = None,
) -> ThankYouLetterTemplate:
    """Загружает/заменяет PDF-фон шаблона и сохраняет размеры страницы-эталона."""
    template.background_pdf = pdf_bytes
    template.background_filename = filename
    template.page_width_pt = width_pt
    template.page_height_pt = height_pt
    template.save(update_fields=[
        'background_pdf', 'background_filename', 'page_width_pt', 'page_height_pt',
    ])
    logger.info('Загружен PDF-фон письма: template=%s file=%r by=%s',
                template.id, filename, actor(actor_user))
    return template


def set_letter_fields(template: ThankYouLetterTemplate, fields: list,
                      actor_user: Optional[User] = None) -> ThankYouLetterTemplate:
    """Сохраняет конфигурацию полей-заглушек (координаты/шрифт/кегль/цвет)."""
    template.fields_json = fields
    template.save(update_fields=['fields_json'])
    logger.info('Обновлены поля шаблона письма: template=%s count=%s by=%s',
                template.id, len(fields or []), actor(actor_user))
    return template


def update_letter_template_title(template: ThankYouLetterTemplate, title: str,
                                 actor_user: Optional[User] = None) -> ThankYouLetterTemplate:
    template.title = title
    template.save(update_fields=['title'])
    logger.info('Переименован шаблон письма: template=%s title=%r by=%s',
                template.id, title, actor(actor_user))
    return template


def delete_letter_template(template: ThankYouLetterTemplate, actor_user: Optional[User] = None) -> None:
    tid = template.id
    template.delete()
    logger.info('Удалён шаблон письма: template=%s by=%s', tid, actor(actor_user))


# --- Шрифты ------------------------------------------------------------------

def letter_fonts_qs():
    return LetterFont.objects.all()


def get_letter_fonts() -> List[LetterFont]:
    return list(LetterFont.objects.order_by('name'))


def get_letter_font_by_id(font_id) -> Optional[LetterFont]:
    return LetterFont.objects.filter(pk=font_id).first()


def get_letter_font_by_name(name: str) -> Optional[LetterFont]:
    return LetterFont.objects.filter(name=name).first()


def create_letter_font(name: str, data: bytes, filename: str = '',
                       is_builtin: bool = False, actor_user: Optional[User] = None) -> LetterFont:
    font = LetterFont.objects.create(
        name=name, font_file=data, filename=filename, is_builtin=is_builtin,
    )
    logger.info('Добавлен шрифт письма: font=%s name=%r builtin=%s by=%s',
                font.id, name, is_builtin, actor(actor_user))
    return font


def delete_letter_font(font: LetterFont, actor_user: Optional[User] = None) -> None:
    fid = font.id
    font.delete()
    logger.info('Удалён шрифт письма: font=%s by=%s', fid, actor(actor_user))
