"""Фоновые загрузки миграции: люди базы и колонки — с процентом и отменой.

Celery/Redis в проекте нет (coding-principles §0). Задача выполняется в отдельном
потоке веб-процесса, работа идёт порциями в коротких транзакциях, а состояние —
строка MigrationJob в БД: страница опрашивает её, пользователь может уходить на
другие страницы. Если процесс перезапустился посреди задачи, она перестаёт
обновляться и показывается «прервана» — запустите загрузку заново: повтор
продолжается с того места (уже связанные строки и загруженные ячейки не дублируются).

Отмена («Да, отменить»):
- люди — удаляются аккаунты, созданные задачей, связи строк базы и расхождения/
  заметки этой задачи; уже существовавшие профили, у которых были дополнены пустые
  поля, остаются с дополненными полями;
- колонки — откатываются загруженные этой задачей колонки (как «Откатить»).
"""
from datetime import timedelta
import logging
import threading

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections, transaction
from django.utils import timezone

from data_base import data_controller as dc
from blog.services import legacy_migration as lm
from blog.services.roles import has_manager_access

logger = logging.getLogger('vc.web.migration_jobs')

PEOPLE_CHUNK = 250
COLUMN_CHUNK = 150
STALE_AFTER = timedelta(minutes=3)


def _manager(operator):
    if not has_manager_access(operator):
        raise PermissionDenied('Загрузками миграции управляет менеджер.')


def is_stale(job):
    return job.status == 'running' and timezone.now() - job.updated_at > STALE_AFTER


def active_jobs():
    return [job for job in dc.migration_jobs_qs().filter(status='running').select_related('base', 'event_group')
            if not is_stale(job)]


def _ensure_free():
    running = active_jobs()
    if running:
        raise ValidationError(f'Уже идёт загрузка: {describe(running[0])}. Дождитесь её окончания или отмените.')


def describe(job):
    if job.kind == 'people':
        return f'люди базы {job.base.year}' if job.base_id else 'люди базы'
    return f'колонки «{job.event_group.title}»' if job.event_group_id else 'колонки'


def status(job):
    percent = int(job.done * 100 / job.total) if job.total else (100 if job.status == 'done' else 0)
    state = 'stale' if is_stale(job) else job.status
    labels = {'running': f'Идёт загрузка: {describe(job)} — {percent}%', 'done': f'Готово: {describe(job)}',
              'cancelled': f'Отменено: {describe(job)}', 'failed': f'Ошибка: {describe(job)}',
              'stale': f'Загрузка прервана: {describe(job)} — запустите её снова, она продолжится'}
    return {'id': job.pk, 'status': state, 'percent': percent, 'done': job.done, 'total': job.total,
            'label': labels[state], 'message': job.message, 'cancel_requested': job.cancel_requested}


def start_people(operator, base):
    _manager(operator)
    _ensure_free()
    total = len(lm.pending_people_rows(base))
    job = dc.create_migration_job(kind='people', operator=operator, base=base, total=total)
    _spawn(job.pk)
    return job


def start_columns(operator, group, columns):
    _manager(operator)
    _ensure_free()
    contexts = [lm.prepare_column(column) for column in columns]  # проверка готовности до запуска
    if not contexts:
        raise ValidationError('Нет готовых колонок для загрузки.')
    job = dc.create_migration_job(kind='columns', operator=operator, event_group=group,
                                  column_ids=[c['column'].pk for c in contexts],
                                  total=sum(len(c['rows']) for c in contexts))
    _spawn(job.pk)
    return job


def request_cancel(operator, job):
    _manager(operator)
    if job.status != 'running':
        return job
    if is_stale(job):
        # Поток уже не работает (перезапуск процесса) — откатить сразу.
        _rollback(job)
        return dc.save_migration_job(job, status='cancelled', cancel_requested=True, message='Загрузка отменена.')
    return dc.save_migration_job(job, cancel_requested=True)


def _spawn(job_id):
    if getattr(settings, 'MIGRATION_JOBS_INLINE', False):
        run(job_id)
        return
    # Поток стартует после фиксации строки задачи, иначе он её не увидит.
    transaction.on_commit(lambda: threading.Thread(
        target=_thread, args=(job_id,), name=f'migration-job-{job_id}', daemon=True).start())


def _thread(job_id):
    close_old_connections()
    try:
        run(job_id)
    finally:
        connections.close_all()


def _cancelled(job):
    return dc.migration_jobs_qs().filter(pk=job.pk, cancel_requested=True).exists()


def run(job_id):
    job = dc.migration_jobs_qs().select_related('base', 'event_group', 'created_by').get(pk=job_id)
    try:
        finished = _run_people(job) if job.kind == 'people' else _run_columns(job)
        if not finished:
            _rollback(job)
            dc.save_migration_job(job, status='cancelled', message='Загрузка отменена, изменения этой загрузки удалены.')
    except Exception as error:  # noqa: BLE001 — задача должна завершиться с понятной ошибкой
        logger.exception('migration job failed: job=%s', job.pk)
        text = ' '.join(error.messages) if isinstance(error, ValidationError) else f'{type(error).__name__}: {error}'
        try:
            _rollback(job)
        finally:
            dc.save_migration_job(job, status='failed', message=f'{text} Изменения этой загрузки удалены.')


def _run_people(job):
    operator, base = job.created_by, dc.legacy_bases_qs().get(pk=job.base_id)
    rows = lm.pending_people_rows(base)
    dc.save_migration_job(job, total=len(rows))
    known, result = {}, lm.new_people_result()
    for start in range(0, len(rows), PEOPLE_CHUNK):
        if _cancelled(job):
            return False
        with transaction.atomic():
            lm.load_people_rows(operator, base, rows[start:start + PEOPLE_CHUNK], known, result)
        dc.save_migration_job(job, done=min(start + PEOPLE_CHUNK, len(rows)), result=result)
    if _cancelled(job):
        return False
    with transaction.atomic():
        lm.finish_people(operator, base, result)
    dc.save_migration_job(job, status='done', done=len(rows), result=result, message=(
        f'Новых людей: {result["created"]}, найдено существующих: {result["existing"]}, обновлено полей: '
        f'{result["updated"]}, уточнений у людей: {result["conflicts"]}, пропущено строк без ФИО: {result["skipped"]}.'))
    return True


def _run_columns(job):
    operator = job.created_by
    result, affected, loaded = lm.new_columns_result(), {}, []
    done = 0
    for column_id in job.column_ids:
        context = lm.prepare_column(dc.legacy_base_columns_qs().get(pk=column_id))
        loaded.append(column_id)
        dc.save_migration_job(job, result={'columns': loaded})
        for start in range(0, len(context['rows']), COLUMN_CHUNK):
            if _cancelled(job):
                return False
            chunk = context['rows'][start:start + COLUMN_CHUNK]
            with transaction.atomic():
                lm.load_column_rows(operator, context, chunk, result, affected)
                lm.recalc_affected(affected)
            done += len(chunk)
            dc.save_migration_job(job, done=done)
        with transaction.atomic():
            lm.finish_column(operator, context)
    conflicts = len(result['conflicts'])
    dc.save_migration_job(job, status='done', done=job.total, result={'columns': loaded}, message=(
        f'Загружено участий: {result["participations"]}, перенесено: {result["moved"]}, новых тим-лидеров: '
        f'{result["team_leads"]}' + (f', не перенесено (правили сотрудники): {conflicts}.' if conflicts else '.')))
    return True


def _rollback(job):
    job = dc.migration_jobs_qs().get(pk=job.pk)
    operator = job.created_by
    if job.kind == 'people':
        result = job.result or {}
        base = dc.legacy_bases_qs().defer('content').get(pk=job.base_id)
        with transaction.atomic():
            rows = result.get('rows', [])
            touched = list(dc.legacy_base_people_qs().filter(base=base, row_number__in=rows).values_list('user_id', flat=True))
            dc.delete_job_profile_notes(touched, job.created_at, f'База {base.year}', operator)
            dc.delete_legacy_base_rows(base, rows, operator)
            dc.delete_users_created_by_job(result.get('created_ids', []), operator)
        return
    for column_id in (job.result or {}).get('columns', []):
        column = dc.legacy_base_columns_qs().get(pk=column_id)
        lm.unload_column(operator, column)
