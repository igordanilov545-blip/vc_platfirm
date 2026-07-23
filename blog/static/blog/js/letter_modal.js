/*
 * letter_modal.js — просмотр благодарственного письма в модалке поверх страницы.
 *
 * Ссылка «открыть письмо» (data-letter-modal, значение = URL письма) открывает PDF в
 * iframe внутри окна ~80% экрана. На узких экранах (телефон) iframe с PDF неудобен и
 * местами не рендерится — поэтому там письмо открывается напрямую нативным вьюером
 * браузера (новая вкладка), это лучший мобильный UX. Клик по фону, ✕ или Esc — закрыть.
 *
 * Навешивается делегированием на document (работает и для ссылок, подгруженных
 * soft-навигацией), поэтому отдельного init на каждый элемент не нужно.
 */
(function () {
    'use strict';

    var MOBILE_MAX = 640; // ширина, ниже которой открываем PDF напрямую, а не в iframe

    var backdrop = document.getElementById('letter-modal-backdrop');
    var frame = document.getElementById('letter-modal-frame');
    var closeBtn = document.getElementById('letter-modal-close');
    var downloadLink = document.getElementById('letter-modal-download');
    var titleEl = document.getElementById('letter-modal-title');

    function isMobile() {
        return window.matchMedia && window.matchMedia('(max-width: ' + MOBILE_MAX + 'px)').matches;
    }

    function openLetter(url, title) {
        if (!backdrop || !frame) { window.open(url, '_blank'); return; }
        if (titleEl && title) titleEl.textContent = title;
        if (downloadLink) downloadLink.setAttribute('href', addParam(url, 'download', '1'));
        frame.src = url;
        backdrop.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    function closeLetter() {
        if (!backdrop) return;
        backdrop.hidden = true;
        // Сбрасываем src, чтобы PDF выгрузился (не держим память/не печатал скрыто).
        if (frame) frame.src = 'about:blank';
        document.body.style.overflow = '';
    }

    function addParam(url, key, value) {
        return url + (url.indexOf('?') === -1 ? '?' : '&') + key + '=' + value;
    }

    // Делегированный клик по ссылке письма.
    document.addEventListener('click', function (event) {
        var link = event.target.closest('[data-letter-modal]');
        if (!link) return;
        event.preventDefault();
        var url = link.getAttribute('data-letter-modal') || link.getAttribute('href');
        if (!url) return;
        // Телефон — открываем PDF напрямую (нативный вьюер удобнее зажатого iframe).
        if (isMobile()) {
            window.open(url, '_blank');
            return;
        }
        openLetter(url, link.getAttribute('data-letter-title'));
    });

    if (closeBtn) closeBtn.addEventListener('click', closeLetter);
    if (backdrop) backdrop.addEventListener('click', function (event) {
        if (event.target === backdrop) closeLetter();
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && backdrop && !backdrop.hidden) closeLetter();
    });
})();
