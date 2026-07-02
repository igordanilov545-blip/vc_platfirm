from django.urls import path

from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.dashboard, name='dashboard'),

    path('events/', views.event_list, name='event_list'),
    path('events/new/', views.event_create, name='event_create'),
    path('events/<int:event_id>/', views.event_detail, name='event_detail'),
    path('events/<int:event_id>/edit/', views.event_edit, name='event_edit'),
    path('events/<int:event_id>/publish/', views.event_publish, name='event_publish'),
    path('events/<int:event_id>/days/add/', views.event_day_add, name='event_day_add'),
    path('events/<int:event_id>/staff/assign/', views.event_assign_staff, name='event_assign_staff'),
    path('events/<int:event_id>/feedback/', views.event_feedback_add, name='event_feedback_add'),

    path('participations/<int:participation_id>/edit/', views.participation_edit, name='participation_edit'),

    path('applications/new/', views.application_create, name='application_create'),
    path('applications/pending/', views.pending_applications, name='pending_applications'),
    path('applications/<int:application_id>/process/', views.application_process, name='application_process'),
    path('applications/import/', views.import_preview, name='import_preview'),
    path('applications/import/commit/', views.import_commit, name='import_commit'),

    path('profile/<int:user_id>/', views.profile_detail, name='profile_detail'),
    path('profile/<int:user_id>/comment/', views.profile_comment_add, name='profile_comment_add'),
    path('profile/<int:user_id>/letters/<int:event_id>/', views.letter_view, name='letter_view'),

    path('reports/period/', views.report_period, name='report_period'),
    path('reports/period/export/', views.report_period_export, name='report_period_export'),
    path('organizations/', views.organizations_list, name='organizations_list'),
    path('organizations/new/', views.organization_create, name='organization_create'),
    path('organizations/<int:org_id>/', views.organization_detail, name='organization_detail'),

    path('users/', views.user_list, name='user_list'),
    path('organizers/', views.organizer_list, name='organizer_list'),
    path('organizers/new/', views.organizer_create, name='organizer_create'),
    path('organizers/<int:organizer_id>/', views.organizer_detail, name='organizer_detail'),
    path('settings/', views.settings_view, name='settings'),
]
