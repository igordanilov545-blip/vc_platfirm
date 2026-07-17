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

        // Затемнение — 4 прямоугольника вокруг выреза (top/right/bottom/left),
        // чтобы «дырка» на подсвеченном элементе оставалась кликабельной/видимой.
        var mask = el('div', 'ctour-mask');
        ['top', 'right', 'bottom', 'left'].forEach(function (side) {
            mask.appendChild(el('div', 'ctour-mask-part ctour-mask-' + side));
        });
        // Рамка-обводка вокруг подсвеченного элемента.
        var ring = el('div', 'ctour-ring');

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

        root.appendChild(mask);
        root.appendChild(ring);
        root.appendChild(card);
        document.body.appendChild(root);

        return {
            root: root, mask: mask, ring: ring, card: card,
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

    // Позиционируем маску, кольцо и карточку под текущий целевой элемент.
    function layout() {
        var els = state.els;
        var step = state.steps[state.index];
        var vw = window.innerWidth, vh = window.innerHeight;
        var target = step.target ? document.querySelector(step.target) : null;
        var placement = step.placement || 'auto';

        if (!target || placement === 'center') {
            // Окно по центру, без выреза — сплошное затемнение.
            els.root.classList.add('ctour-centered');
            els.ring.style.display = 'none';
            setMask(els, { top: 0, left: 0, width: 0, height: 0, empty: true });
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
        setMask(els, box);

        els.ring.style.display = 'block';
        els.ring.style.top = box.top + 'px';
        els.ring.style.left = box.left + 'px';
        els.ring.style.width = box.width + 'px';
        els.ring.style.height = box.height + 'px';

        placeCard(els, box, placement, vw, vh);
    }

    // Четыре прямоугольника затемнения вокруг выреза box.
    function setMask(els, box) {
        var vw = window.innerWidth, vh = window.innerHeight;
        var parts = {
            top: els.mask.querySelector('.ctour-mask-top'),
            right: els.mask.querySelector('.ctour-mask-right'),
            bottom: els.mask.querySelector('.ctour-mask-bottom'),
            left: els.mask.querySelector('.ctour-mask-left'),
        };
        if (box.empty) {
            // Сплошное затемнение: верхняя часть на весь экран, остальные пустые.
            css(parts.top, { top: 0, left: 0, width: vw, height: vh });
            [parts.right, parts.bottom, parts.left].forEach(function (p) { css(p, { width: 0, height: 0 }); });
            return;
        }
        css(parts.top, { top: 0, left: 0, width: vw, height: box.top });
        css(parts.bottom, { top: box.top + box.height, left: 0, width: vw, height: Math.max(0, vh - box.top - box.height) });
        css(parts.left, { top: box.top, left: 0, width: box.left, height: box.height });
        css(parts.right, { top: box.top, left: box.left + box.width, width: Math.max(0, vw - box.left - box.width), height: box.height });
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

    // Рендер текущего шага (данные + позиция + видимость кнопок).
    function render() {
        var els = state.els;
        var step = state.steps[state.index];
        els.photo.src = step.photo || '';
        els.title.textContent = step.title || '';
        els.desc.textContent = step.text || '';
        els.progress.textContent = (state.index + 1) + ' / ' + state.steps.length;
        els.prev.style.visibility = state.index === 0 ? 'hidden' : 'visible';
        els.next.textContent = state.index === state.steps.length - 1 ? 'Готово' : 'Далее';

        // Хук: дать вызывающему подготовить экран (напр. открыть нужную вкладку
        // настроек) ДО позиционирования. Может вернуть Promise — тогда ждём.
        var maybe = state.opts.onStepEnter ? state.opts.onStepEnter(step, state.index) : null;
        if (maybe && typeof maybe.then === 'function') {
            maybe.then(function () { if (state) relayoutSoon(); });
        } else {
            relayoutSoon();
        }
    }

    // Небольшая задержка перед layout: элемент вкладки мог только что смениться
    // (AJAX-панель настроек), даём кадр на перерисовку и подскролл к цели.
    function relayoutSoon() {
        var step = state.steps[state.index];
        var target = step.target ? document.querySelector(step.target) : null;
        if (target) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        requestAnimationFrame(function () { setTimeout(function () { if (state) layout(); }, 60); });
    }

    function go(delta) {
        var next = state.index + delta;
        if (next < 0) return;
        if (next >= state.steps.length) { finish(false); return; }
        state.index = next;
        render();
    }

    // Завершение: skipped=true — нажали «я знаю, бб»/крестик; иначе дошли до конца.
    // В обоих случаях (если задан outro) показываем финальное окно один раз.
    function finish(skipped) {
        if (state.opts.storageKey) {
            try { localStorage.setItem(state.opts.storageKey, '1'); } catch (e) {}
        }
        if (state.opts.outro && !state.showingOutro) {
            state.showingOutro = true;
            state.steps = [Object.assign({ placement: 'center', target: null }, state.opts.outro)];
            state.index = 0;
            state.opts = Object.assign({}, state.opts, { onStepEnter: null, outro: null });
            state.els.skip.style.display = 'none';
            state.els.prev.style.display = 'none';
            state.els.next.textContent = 'Закрыть';
            render();
            return;
        }
        destroy();
    }

    function destroy() {
        if (!state) return;
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
            state = { steps: steps.slice(), opts: opts || {}, index: 0, els: buildOverlay(), showingOutro: false };

            state.els.next.addEventListener('click', function () {
                // На финальном окне «Далее» превращается в «Закрыть».
                if (state.showingOutro) { destroy(); return; }
                go(1);
            });
            state.els.prev.addEventListener('click', function () { go(-1); });
            state.els.skip.addEventListener('click', function () { finish(true); });
            state.els.close.addEventListener('click', function () { finish(true); });

            window.addEventListener('resize', layout);
            window.addEventListener('scroll', layout, true);
            document.addEventListener('keydown', onKey, true);

            render();
        },
        active: function () { return !!state; },
    };

    window.CompanionTour = CompanionTour;
})();
