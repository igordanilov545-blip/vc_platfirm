/*
 * static/blog/js/calendar-utils.js
 * Единый источник истины для дат во всех календарях проекта (одиночный
 * data-datepicker и Date Range Picker). Раньше жил инлайном в <head> base.html —
 * вынесен, но по-прежнему подключается РАНО (в <head>), т.к. скрипты внутри
 * content дочерних шаблонов могут выполняться до основного JS в конце body.
 */
window.CalendarUtils = window.CalendarUtils || {
    MONTHS: ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'],
    DOW: ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'],
    parseISO: function (s) {
        if (!s) return null;
        var p = s.split('-');
        if (p.length !== 3) return null;
        return new Date(+p[0], +p[1] - 1, +p[2]);
    },
    toISO: function (d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); },
    fmt: function (d) { return String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' + d.getFullYear(); },
    sameDay: function (a, b) { return a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); },
};
