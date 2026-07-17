/* ============================================================================
 * Компаньон-тур (онбординг «за ручку»). Гусь-помощник ведёт пользователя по
 * заранее заданному сценарию шагов: на каждом шаге подсвечивается конкретный
 * элемент страницы (spotlight-вырез), всё остальное затемняется, а рядом —
 * прямоугольная карточка с текстом и фото компаньона.
 *
 * Единый переиспользуемый движок (agent-workflow.md §4): бизнес-данные (шаги)
 * приходят снаружи, здесь только механика показа. Запуск:
 *
 *   CompanionTour.start(steps, {
 *     onStepEnter: function (step, index) { ... },  // напр. открыть вкладку настроек
 *     outro: { title, text, photo },                // финальное окно «бб»
 *     storageKey: 'companion_settings_seen',        // не показывать повторно сам собой
 *   });
 *
 * Формат шага:
 *   {
 *     target: 'css-селектор' | null,   // что подсветить; null → окно по центру
 *     title:  'Заголовок',
 *     text:   'Текст подсказки',
 *     photo:  '/static/.../goose_0.jpg',
 *     placement: 'auto' | 'right' | 'left' | 'top' | 'bottom' | 'center',
 *   }
 * ========================================================================== */
(function () {
    'use strict';

    var PAD = 8;         // отступ выреза вокруг подсвеченного элемента
    var GAP = 16;        // зазор между вырезом и карточкой

    var state = null;    // активный тур: { steps, opts, index, els }

    function el(tag, cls, html) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (html != null) n.innerHTML = html;
        return n;
    }

    // Строим DOM оверлея один раз на запуск тура.
    function buildOverlay() {
        var root = el('div', 'ctour-root');
        root.setAttribute('role', 'dialog');
        root.setAttribute('aria-modal', 'true');

        // Затемнение + подсветка одним элементом: «дырка» на подсвеченном элементе —
        // это прозрачный прямоугольник с гигантской box-shadow (заливает весь экран
        // полупрозрачным), плюс оранжевая обводка. Один элемент анимируется синхронно
        // (top/left/width/height), поэтому переход между шагами плавный, без «рванья»
        // (в отличие от 4 отдельных прямоугольников, которые ехали вразнобой).
        var spot = el('div', 'ctour-spot');

        // Карточка компаньона: фото + текст + управление.
        var card = el('div', 'ctour-card');
        card.innerHTML =
            '<button type="button" class="ctour-close" aria-label="Закрыть гайд">×</button>' +
            '<div class="ctour-card-body">' +
                '<img class="ctour-photo" alt="Компаньон" src="">' +
                '<div class="ctour-text">' +
                    '<div class="ctour-title"></div>' +
                    '<div class="ctour-desc"></div>' +
                '</div>' +
            '</div>' +
            '<div class="ctour-foot">' +
                '<span class="ctour-progress"></span>' +
                '<div class="ctour-actions">' +
                    '<button type="button" class="btn secondary btn-sm ctour-skip">Я знаю, бб</button>' +
                    '<button type="button" class="btn secondary btn-sm ctour-prev">Назад</button>' +
                    '<button type="button" class="btn btn-sm ctour-next">Далее</button>' +
                '</div>' +
            '</div>';

        root.appendChild(spot);
        root.appendChild(card);
        document.body.appendChild(root);

        return {
            root: root, spot: spot, card: card,
            photo: card.querySelector('.ctour-photo'),
            title: card.querySelector('.ctour-title'),
            desc: card.querySelector('.ctour-desc'),
            progress: card.querySelector('.ctour-progress'),
            close: card.querySelector('.ctour-close'),
            skip: card.querySelector('.ctour-skip'),
            prev: card.querySelector('.ctour-prev'),
            next: card.querySelector('.ctour-next'),
        };
    }

    // Позиционируем единый spotlight-вырез и карточку под текущий целевой элемент.
    // Один элемент (spot) → синхронная плавная анимация всех сторон, без «рванья».
    function layout() {
        var els = state.els;
        var step = state.steps[state.index];
        var vw = window.innerWidth, vh = window.innerHeight;
        var target = step.target ? document.querySelector(step.target) : null;
        var placement = step.placement || 'auto';

        if (!target || placement === 'center') {
            // Окно по центру: вырез схлопнут в точку в центре экрана (тень заливает
            // всё → сплошное затемнение), карточка — по центру.
            els.root.classList.add('ctour-centered');
            css(els.spot, { top: vh / 2, left: vw / 2, width: 0, height: 0 });
            centerCard(els);
            return;
        }

        els.root.classList.remove('ctour-centered');
        var r = target.getBoundingClientRect();
        var box = {
            top: Math.max(0, r.top - PAD),
            left: Math.max(0, r.left - PAD),
            width: Math.min(vw, r.right + PAD) - Math.max(0, r.left - PAD),
            height: Math.min(vh, r.bottom + PAD) - Math.max(0, r.top - PAD),
        };
        css(els.spot, box);
        placeCard(els, box, placement, vw, vh);
    }

    function css(node, o) {
        for (var k in o) node.style[k] = (typeof o[k] === 'number' ? o[k] + 'px' : o[k]);
    }

    function centerCard(els) {
        var c = els.card;
        c.style.top = ''; c.style.left = ''; c.style.right = ''; c.style.bottom = '';
        c.classList.add('ctour-card-center');
    }

    // Ставим карточку рядом с вырезом; при нехватке места — авто-выбор стороны.
    function placeCard(els, box, placement, vw, vh) {
        var c = els.card;
        c.classList.remove('ctour-card-center');
        c.style.top = ''; c.style.left = ''; c.style.right = ''; c.style.bottom = '';
        var cw = c.offsetWidth || 360, ch = c.offsetHeight || 200;

        var order = placement === 'auto'
            ? ['right', 'left', 'bottom', 'top']
            : [placement, 'right', 'left', 'bottom', 'top'];

        for (var i = 0; i < order.length; i++) {
            var side = order[i];
            var pos = trySide(side, box, cw, ch, vw, vh);
            if (pos) { c.style.top = pos.top + 'px'; c.style.left = pos.left + 'px'; return; }
        }
        // Никуда не влезло — центрируем.
        c.style.top = Math.max(GAP, (vh - ch) / 2) + 'px';
        c.style.left = Math.max(GAP, (vw - cw) / 2) + 'px';
    }

    function trySide(side, box, cw, ch, vw, vh) {
        var top, left;
        if (side === 'right') { left = box.left + box.width + GAP; top = clamp(box.top, GAP, vh - ch - GAP); if (left + cw > vw - GAP) return null; }
        else if (side === 'left') { left = box.left - cw - GAP; top = clamp(box.top, GAP, vh - ch - GAP); if (left < GAP) return null; }
        else if (side === 'bottom') { top = box.top + box.height + GAP; left = clamp(box.left, GAP, vw - cw - GAP); if (top + ch > vh - GAP) return null; }
        else if (side === 'top') { top = box.top - ch - GAP; left = clamp(box.left, GAP, vw - cw - GAP); if (top < GAP) return null; }
        return { top: top, left: left };
    }

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    var RESUME_KEY = 'companion_resume'; // sessionStorage: {tourId, index}

    // Текущая страница совпадает с url шага? (сравниваем pathname без хоста/квери).
    function samePage(url) {
        if (!url) return true;
        var a = document.createElement('a');
        a.href = url;
        return a.pathname === window.location.pathname;
    }

    // Сохранить прогресс, чтобы продолжить тур после перехода на другую страницу.
    function persist(index) {
        if (!state.opts.tourId) return;
        try {
            sessionStorage.setItem(RESUME_KEY, JSON.stringify({ tourId: state.opts.tourId, index: index }));
        } catch (e) {}
    }
    function clearPersist() {
        try { sessionStorage.removeItem(RESUME_KEY); } catch (e) {}
    }

    // Рендер текущего шага (данные + позиция + видимость кнопок).
    function render() {
        var step = state.steps[state.index];

        // Межстраничный шаг: если он живёт на ДРУГОЙ странице — сохраняем прогресс и
        // переходим туда. Тур продолжится сам после загрузки (CompanionTour.resume в
        // base.html подхватит сохранённый прогресс). Карточку на текущей странице не
        // показываем — мы уже уходим.
        if (step.url && !samePage(step.url)) {
            persist(state.index);
            window.location.assign(step.url);
            return;
        }
        // На всякий случай держим прогресс актуальным и внутри одной страницы (если
        // юзер перезагрузит вручную — продолжим с этого шага). В финальном окне не
        // сохраняем — тур уже завершён.
        if (!state.showingOutro) persist(state.index);

        var els = state.els;
        els.photo.src = step.photo || '';
        els.title.textContent = step.title || '';
        els.desc.textContent = step.text || '';
        els.progress.textContent = (state.index + 1) + ' / ' + state.steps.length;
        els.prev.style.visibility = state.index === 0 ? 'hidden' : 'visible';
        els.next.textContent = state.index === state.steps.length - 1 ? 'Готово' : 'Далее';

        // Хук: дать вызывающему подготовить экран (напр. открыть нужную вкладку
        // настроек). Позиционируемся СРАЗУ (подсвечиваемая цель — обычно кнопка-вкладка,
        // она уже в DOM и не двигается от загрузки панели), поэтому вырез плавно едет к
        // ней немедленно. Если хук вернул Promise (догрузка AJAX-панели) — по его
        // завершении делаем ещё один layout на случай, если размеры страницы изменились.
        var maybe = state.opts.onStepEnter ? state.opts.onStepEnter(step, state.index) : null;
        relayoutSoon();
        if (maybe && typeof maybe.then === 'function') {
            maybe.then(function () { if (state) relayoutSoon(); });
        }
    }

    // Готовим позицию к следующему layout. Ключ к плавности: НЕ анимируем скролл
    // (иначе вырез считается по «едущему» rect и прыгает). Скроллим мгновенно и только
    // если цель реально не влезает в вьюпорт; затем один кадр — и layout, а сам переход
    // выреза/карточки анимирует CSS-transition уже от прежнего к новому положению.
    function relayoutSoon() {
        var step = state.steps[state.index];
        var target = step.target ? document.querySelector(step.target) : null;
        if (target) {
            var r = target.getBoundingClientRect();
            var fullyVisible = r.top >= 0 && r.bottom <= window.innerHeight;
            if (!fullyVisible) target.scrollIntoView({ block: 'center', behavior: 'auto' });
        }
        requestAnimationFrame(function () { if (state) layout(); });
    }

    function go(delta) {
        var next = state.index + delta;
        if (next < 0) return;
        if (next >= state.steps.length) { finish(false); return; }
        state.index = next;
        render();
    }

    // Завершение тура. Финальное окно РАЗНОЕ в зависимости от того, как закончили:
    //   - skipped=true (крестик / «я знаю, бб» / Esc) → opts.interrupted («вопросов зеро…»);
    //   - дошли до последнего шага          → opts.outro («ну вот и всё…»).
    // Показывается один раз; на нём кнопки навигации скрыты, только «Закрыть».
    function finish(skipped) {
        if (state.opts.storageKey) {
            try { localStorage.setItem(state.opts.storageKey, '1'); } catch (e) {}
        }
        var final = skipped ? state.opts.interrupted : state.opts.outro;
        if (final && !state.showingOutro) {
            state.showingOutro = true;
            state.steps = [Object.assign({ placement: 'center', target: null }, final)];
            state.index = 0;
            state.opts = Object.assign({}, state.opts, { onStepEnter: null, outro: null, interrupted: null });
            state.els.skip.style.display = 'none';
            state.els.prev.style.display = 'none';
            state.els.next.textContent = 'Закрыть';
            clearPersist(); // тур логически закончен — возобновлять после перехода нечего
            render();
            return;
        }
        destroy();
    }

    function destroy() {
        if (!state) return;
        clearPersist();
        window.removeEventListener('resize', layout);
        window.removeEventListener('scroll', layout, true);
        document.removeEventListener('keydown', onKey, true);
        if (state.els.root.parentNode) state.els.root.parentNode.removeChild(state.els.root);
        state = null;
    }

    function onKey(e) {
        if (!state) return;
        if (e.key === 'Escape') { e.preventDefault(); finish(true); }
        else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); go(1); }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1); }
    }

    var CompanionTour = {
        start: function (steps, opts) {
            if (state) destroy();
            if (!steps || !steps.length) return;
            opts = opts || {};
            var startAt = Math.min(Math.max(0, opts.startAt || 0), steps.length - 1);
            state = { steps: steps.slice(), opts: opts, index: startAt, els: buildOverlay(), showingOutro: false };

            state.els.next.addEventListener('click', function (e) {
                // stopPropagation: иначе клик всплывёт до общего «клик = вперёд» и шаг
                // перескочит дважды. На финальном окне «Далее» превращается в «Закрыть».
                e.stopPropagation();
                if (state.showingOutro) { destroy(); return; }
                go(1);
            });
            state.els.prev.addEventListener('click', function () { go(-1); });
            state.els.skip.addEventListener('click', function (e) { e.stopPropagation(); finish(true); });
            state.els.close.addEventListener('click', function (e) { e.stopPropagation(); finish(true); });
            // «Назад» не должен триггерить общий «клик = вперёд».
            state.els.prev.addEventListener('click', function (e) { e.stopPropagation(); });

            // Клик ГДЕ УГОДНО по экрану → следующий шаг (кроме кнопок управления, у них
            // stopPropagation выше). На финальном окне — закрывает тур.
            state.els.root.addEventListener('click', function () {
                if (state.showingOutro) { destroy(); return; }
                go(1);
            });

            window.addEventListener('resize', layout);
            window.addEventListener('scroll', layout, true);
            document.addEventListener('keydown', onKey, true);

            render();
        },
        active: function () { return !!state; },

        // Возобновление после межстраничного перехода. Вызывается на загрузке КАЖДОЙ
        // страницы (base.html). resolver(tourId) должен вернуть { steps, opts } нужного
        // тура (или null). Если сохранённого прогресса нет — ничего не делает.
        // Возвращает true, если тур возобновлён (чтобы вызывающий не запускал автозапуск).
        resume: function (resolver) {
            var saved = null;
            try { saved = JSON.parse(sessionStorage.getItem(RESUME_KEY) || 'null'); } catch (e) {}
            if (!saved || typeof saved.index !== 'number') return false;
            var cfg = resolver(saved.tourId);
            if (!cfg || !cfg.steps || !cfg.steps.length) { clearPersistStatic(); return false; }
            // Если сохранённый шаг за пределами (набор шагов изменился) — сбрасываем.
            if (saved.index >= cfg.steps.length) { clearPersistStatic(); return false; }
            CompanionTour.start(cfg.steps, Object.assign({}, cfg.opts, { tourId: saved.tourId, startAt: saved.index }));
            return true;
        },
    };

    function clearPersistStatic() { try { sessionStorage.removeItem('companion_resume'); } catch (e) {} }

    window.CompanionTour = CompanionTour;
})();
