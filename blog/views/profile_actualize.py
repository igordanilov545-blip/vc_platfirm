"""Человек уточняет расхождения своей анкеты со старыми базами (свой/из базы/новый)."""
from django.contrib.auth.decorators import login_required

from ._common import *  # noqa: F401,F403
from blog.services import profile_conflicts


@login_required
def profile_actualize(request):
    errors = {}
    if request.method == 'POST':
        errors = profile_conflicts.resolve_conflicts(request.user, request.POST)
        if not errors:
            messages.success(request, 'Спасибо! Данные профиля обновлены.')
            if not profile_conflicts.pending_conflicts(request.user).exists():
                return redirect('profile_detail', request.user.pk)
            return redirect('profile_actualize')
    conflicts = [{'conflict': c, 'label': profile_conflicts.FIELDS.get(c.field, c.field), 'error': errors.get(c.pk),
                  'choice': request.POST.get(f'choice_{c.pk}', ''), 'custom': request.POST.get(f'custom_{c.pk}', '')}
                 for c in profile_conflicts.pending_conflicts(request.user)]
    return render(request, 'blog/profile_actualize.html', {'conflicts': conflicts})
