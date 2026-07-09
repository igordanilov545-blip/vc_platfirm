"""Рендер графиков в PNG (matplotlib) для встраивания в PDF-отчёты как <img data:...>
(reports_template.md, WeasyPrint не умеет canvas/JS-графики — только растровые/SVG картинки).
"""
import base64
import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False


def _to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    encoded = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def bar_chart(labels, values, title='', xlabel='', ylabel='', figsize=(7, 3.5), color='#2f6bff') -> str:
    fig, ax = plt.subplots(figsize=figsize)
    ax.bar(labels, values, color=color)
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(axis='y', alpha=0.3)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    return _to_data_uri(fig)


def line_chart(x, y, title='', xlabel='', ylabel='', figsize=(7, 3.5), color='#2f6bff') -> str:
    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(x, y, marker='o', linewidth=2, color=color)
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    return _to_data_uri(fig)


def funnel_chart(stages: list, title='Воронка набора', figsize=(7, 3.5)) -> str:
    """stages: [(label, value), ...] по убыванию."""
    labels = [s[0] for s in stages]
    values = [s[1] for s in stages]
    fig, ax = plt.subplots(figsize=figsize)
    ax.barh(labels[::-1], values[::-1], color='#2f6bff')
    ax.set_title(title)
    plt.tight_layout()
    return _to_data_uri(fig)


def histogram_chart(labels, counts, threshold_label=None, title='', figsize=(7, 3.5)) -> str:
    fig, ax = plt.subplots(figsize=figsize)
    colors = ['#c9503f' if threshold_label and lbl == threshold_label else '#2f6bff' for lbl in labels]
    ax.bar(labels, counts, color=colors)
    if title:
        ax.set_title(title)
    ax.grid(axis='y', alpha=0.3)
    plt.xticks(rotation=30, ha='right')
    plt.tight_layout()
    return _to_data_uri(fig)


def event_timeline_chart(milestones: list, applications: list, figsize=(9, 3.0)) -> str:
    """График «Жизнь мероприятия» (reports_template.md): вертикальные засечки событий
    меро + точки заявок снизу, с кластеризацией близких по времени точек.

    milestones: [(label, x_hours, color), ...] — засечки событий относительно нуля (создание меро).
    applications: [(x_hours, status_color), ...] — подачи заявок; близкие по времени (окно
    ~1.5% ширины оси) объединяются в один кружок с числом внутри.
    """
    fig, ax = plt.subplots(figsize=figsize)

    max_x = max([m[1] for m in milestones] + [a[0] for a in applications] + [1])
    ax.axhline(0, color='#999', linewidth=1.5, zorder=1)

    for label, x, color in milestones:
        ax.axvline(x, color=color, linewidth=1.5, alpha=0.8, zorder=2)
        ax.text(x, 0.15, label, rotation=45, ha='right', va='bottom', fontsize=8, color=color)

    # Кластеризация точек заявок, близких по времени.
    window = max_x * 0.015 if max_x else 0.1
    applications_sorted = sorted(applications, key=lambda a: a[0])
    clusters = []
    for x, color in applications_sorted:
        if clusters and x - clusters[-1]['x_last'] <= window:
            clusters[-1]['xs'].append(x)
            clusters[-1]['x_last'] = x
            clusters[-1]['colors'].append(color)
        else:
            clusters.append({'xs': [x], 'x_last': x, 'colors': [color]})

    for c in clusters:
        cx = sum(c['xs']) / len(c['xs'])
        n = len(c['xs'])
        size = 60 + min(n, 20) * 15
        dominant_color = max(set(c['colors']), key=c['colors'].count)
        ax.scatter([cx], [-0.15], s=size, color=dominant_color, zorder=3, edgecolors='white', linewidths=0.8)
        if n > 1:
            ax.text(cx, -0.15, str(n), ha='center', va='center', fontsize=7, color='white', fontweight='bold', zorder=4)

    ax.set_ylim(-0.6, 0.6)
    ax.set_xlim(-max_x * 0.03, max_x * 1.05)
    ax.get_yaxis().set_visible(False)
    ax.set_xlabel('Время (часы от создания мероприятия)')
    for spine in ('top', 'right', 'left'):
        ax.spines[spine].set_visible(False)
    plt.tight_layout()
    return _to_data_uri(fig)
