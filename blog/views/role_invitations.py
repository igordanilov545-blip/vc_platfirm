from ._common import *  # noqa: F401,F403
from django.contrib.auth.views import redirect_to_login
from django.views.decorators.cache import never_cache
from blog.forms import RoleInvitationForm
from blog.services import role_invitations as invitations


@manager_required
def role_invitation_list(request):
    return render(request, 'blog/role_invitations.html', {'invitations': invitations.invitation_rows(request.user)})


@manager_required
def role_invitation_detail(request, invitation_id):
    return modal_form_response(request, 'blog/role_invitation_detail.html',
                               invitations.invitation_detail(request.user, invitation_id),
                               partial_template='blog/partials/_role_invitation_detail.html')


@manager_required
def role_invitation_create(request):
    form = RoleInvitationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        invitation, token = invitations.create_invitation(request.user, form.cleaned_data['role'], form.cleaned_data['hours'])
        response = modal_form_response(request, 'blog/role_invitation_created.html', {
            'invitation': invitation, 'invitation_url': request.build_absolute_uri(reverse('role_invitation_accept', args=[token])),
        }, partial_template='blog/partials/_role_invitation_created.html')
        response['Cache-Control'] = 'private, no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response
    return modal_form_response(request, 'blog/role_invitation_form.html', {'form': form, 'title': 'Создать ссылку приглашения'})


@never_cache
def role_invitation_accept(request, token):
    try:
        invitation = invitations.get_invitation(token)
        if not request.user.is_authenticated:
            request.session['role_invitation_next'] = reverse('role_invitation_accept', args=[token])
            return redirect_to_login(request.get_full_path())
        invitations.claim_invitation(request.user, token)
    except ValidationError as error:
        return render(request, 'blog/role_invitation_status.html', {'invitation_message': error.messages[0]})
    messages.success(request, f'Вы получили права: {invitation.get_role_display()}.')
    response = redirect('dashboard')
    response['Referrer-Policy'] = 'no-referrer'
    return response


@manager_required
@require_POST
def role_invitation_revoke(request, invitation_id):
    invitations.revoke_invitation(request.user, invitation_id)
    return redirect('role_invitation_list')
