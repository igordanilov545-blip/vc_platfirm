/*
 * letter_modal.js — просмотр благодарственного письма лайтбоксом (как фото в ленте).
 *
 * Ссылка «открыть письмо» (data-letter-modal = URL письма) показывает письмо-КАРТИНКУ
 * (сервер отдаёт PNG на этот URL) по центру затемнённого фона, без панелей PDF-вьюера.
 * Работает одинаково удобно на десктопе и телефоне (обычное изображение, вписанное в
 * экран). Кнопка «скачать» отдаёт PDF (URL + ?download=1). Клик по фону, ✕ или Esc —
 * закрыть.
 *
 * Навешивается делегированием на document (работает и для ссылок из soft-навигации).
 */
(function () {
    'use strict';

    var backdrop = document.getElementById('letter-modal-backdrop');
    var img = document.getElementById('letter-modal-img');
    var spinner = document.getElementById('letter-modal-spinner');
    var closeBtn = document.getElementById('letter-modal-close');
    var downloadLink = document.getElementById('letter-modal-download');

    function openLetter(url) {
        if (!backdrop || !img) { window.open(url, '_blank'); return; }
        if (downloadLink) downloadLink.setAttribute('href', addParam(url, 'download', '1'));
        // Показать спиннер, спрятать старую картинку, начать загрузку новой.
        img.style.display = 'none';
        if (spinner) spinner.style.display = '';
        img.onload = function () {
            if (spinner) spinner.style.display = 'none';
            img.style.display = '';
        };
        img.onerror = function () {
            if (spinner) spinner.textContent = 'Не удалось загрузить письмо';
        };
        img.src = url;
        backdrop.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    function closeLetter() {
        if (!backdrop) return;
        backdrop.hidden = true;
        img.src = '';                 // освободить память
        if (spinner) { spinner.style.display = ''; spinner.textContent = 'Загрузка…'; }
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
        if (url) openLetter(url);
    });

    if (closeBtn) closeBtn.addEventListener('click', closeLetter);
    // Клик по фону (не по самой картинке/кнопкам) — закрыть.
    if (backdrop) backdrop.addEventListener('click', function (event) {
        if (event.target === backdrop || event.target.classList.contains('letter-lightbox-stage')) {
            closeLetter();
        }
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && backdrop && !backdrop.hidden) closeLetter();
    });
})();
