"""Табличка желающих: общая страница, добавление сообщения, правка, «забрал»/«снять».

Вьюхи тонкие: правила и ACL — в blog/services/volunteer_wishes.py
(documentation/volunteer-wishes.md)."""
from ._common import *  # noqa: F401,F403
from blog.forms import VolunteerWishAddForm, VolunteerWishEditForm, VolunteerWishTakeShiftForm
from blog.services import volunteer_wishes as wishes


def _require_staff(request):
    if not wishes.can_manage_wishes(request.user):
        raise PermissionDenied('Табличка желающих доступна тим-лидерам и менеджерам.')


def _raise_for(error):
    if error == 'forbidden':
        raise PermissionDenied('Нет прав на это действие с табличкой желающих.')
    if error == 'not_found':
        raise Http404('Строка таблички желающих не найдена.')


@login_required
def volunteer_wishes(request):
    """Общая табличка (кнопка в профиле ТЛ/менеджера) с фильтром по статусу."""
    _require_staff(request)
    status = request.GET.get('status', 'active')
    if status not in wishes.WISH_FILTERS:
        status = 'active'
    hide_taken = request.GET.get('hide_taken') == '1'
    return render(request, 'blog/volunteer_wishes.html', {
        'wishes': wishes.wishes_list(request.user, status, hide_taken=hide_taken),
        'status': status,
        'hide_taken': hide_taken,
        'filters': wishes.WISH_FILTERS,
        'hide_days': wishes.hide_days(),
    })


@login_required
def volunteer_wish_add(request):
    """Вставить сообщение о желающих (модалка); разбор — в сервисе."""
    _require_staff(request)
    form = VolunteerWishAddForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        created, error = wishes.add_wishes_from_message(request.user, form.cleaned_data['text'], source='web')
        if error == 'forbidden':
            _raise_for(error)
        if error == 'no_people':
            form.add_error('text', 'Не нашёл ни @юзернейма, ни телефона, ни ФИО рядом со словом «хочет».')
        else:
            fresh = sum(not row.is_duplicate for row in created)
            messages.success(request, f'Записано новых: {fresh}, уже были в табличке: {len(created) - fresh}.')
            return modal_form_response(request, '', {}, success_redirect=reverse('volunteer_wishes') + '?status=mine')
    return modal_form_response(request, 'blog/volunteer_wish_form.html', {
        'form': form, 'title': 'Добавить желающих', 'submit_label': 'Записать',
    })


@login_required
def volunteer_wish_edit(request, wish_id):
    _require_staff(request)
    wish = get_object_or_404(dc.volunteer_wishes_qs(), pk=wish_id)
    if not wishes.can_edit_wish(request.user, wish):
        raise PermissionDenied('Править строку может автор или менеджер.')
    initial = {
        'user': wish.user_id, 'telegram_username': wish.telegram_username, 'phone': wish.phone,
        'full_name': wish.full_name, 'event_group': wish.event_group_id, 'event_hint': wish.event_hint,
        'wish_date': wish.wish_date, 'position_hint': wish.position_hint,
    }
    form = VolunteerWishEditForm(request.POST or None, initial=initial, current_group=wish.event_group)
    if request.method == 'POST' and form.is_valid():
        _, error = wishes.update_wish(request.user, wish, form.cleaned_data)
        if error == 'duplicate':
            form.add_error(None, 'Такая строка уже есть: этот человек на это мероприятие в этот день.')
        else:
            _raise_for(error)
            return modal_form_response(request, '', {}, success_redirect=_safe_next(request, 'volunteer_wishes'))
    import json
    selected = form['user'].value() if form.is_bound else wish.user_id
    preselect = ''
    if selected:
        person = dc.users_qs().filter(pk=selected).first()
        if person:
            preselect = json.dumps([{'id': person.pk, 'label': person.full_name}], ensure_ascii=False)
    return modal_form_response(request, 'blog/volunteer_wish_form.html', {
        'form': form, 'title': 'Желающий: изменить', 'raw_text': wish.raw_text, 'edit_mode': True,
        'user_preselect': preselect,
    }, partial_template='blog/partials/_volunteer_wish_form.html')


@login_required
@require_POST
def volunteer_wish_delete(request, wish_id):
    _raise_for(wishes.delete_wish(request.user, wish_id))
    return redirect(_safe_next(request, 'volunteer_wishes'))


@login_required
@require_POST
def volunteer_wish_take(request, wish_id):
    """«✓ Забрали» без деталей: ТЛ сам договорился с человеком. Мероприятие — со
    страницы, где нажали (`group`), иначе из ссылки строки."""
    group_id = request.POST.get('group') or None
    if group_id and not str(group_id).isdigit():
        raise Http404('Неверное мероприятие.')
    _, error = wishes.mark_wish_taken(request.user, wish_id, int(group_id) if group_id else None)
    _raise_for(error)
    return redirect(_safe_next(request, 'volunteer_wishes'))


TAKE_SHIFT_ERRORS = {
    'no_name': 'Человека нет на платформе и не указано ФИО — привяжите аккаунт или впишите ФИО через ✎.',
    'bad_role': 'Такой роли нет в плане этой смены.',
}


@login_required
def volunteer_wish_take_shift(request, wish_id):
    """«В смену…»: выбрать смену (и роль) — человек получает одобренную заявку на неё
    и попадает в таблицу явки; строка становится «Забрали»."""
    _require_staff(request)
    wish = get_object_or_404(dc.volunteer_wishes_qs(), pk=wish_id)
    group_id = request.GET.get('group') or request.POST.get('group')
    group = dc.event_groups_qs().filter(pk=group_id).first() if str(group_id or '').isdigit() else None
    shifts = wishes.shift_choices(request.user, wish, group)
    preferred = wishes.default_shift(wish, shifts)
    form = VolunteerWishTakeShiftForm(request.POST or None, shifts=shifts,
                                      initial={'shift': preferred.pk if preferred else None})
    if request.method == 'POST' and form.is_valid():
        _, error = wishes.take_wish_into_shift(request.user, wish.pk, form.cleaned_data['shift'],
                                               role=form.cleaned_data['role'])
        if error in TAKE_SHIFT_ERRORS:
            form.add_error(None, TAKE_SHIFT_ERRORS[error])
        else:
            _raise_for(error)
            messages.success(request, f'«{wish.display_name}» — в смене, заявка одобрена.')
            return modal_form_response(request, '', {}, success_redirect=_safe_next(request, 'volunteer_wishes'))
    return modal_form_response(request, 'blog/volunteer_wish_form.html', {
        'form': form, 'title': f'Забрать в смену: {wish.display_name}', 'take_mode': True, 'wish': wish,
        'has_shifts': bool(shifts), 'group': group, 'next_url': request.GET.get('next') or request.POST.get('next', ''),
    }, partial_template='blog/partials/_volunteer_wish_form.html')


@login_required
@require_POST
def volunteer_wish_untake(request, wish_id):
    _, error = wishes.unmark_wish_taken(request.user, wish_id)
    _raise_for(error)
    return redirect(_safe_next(request, 'volunteer_wishes'))
