/* Рендерер интерактивных CJM-деревьев продукта «DnD DM Assistant».
 *
 * Данные: window.CJM_DATA = { title, subtitle, nodes: [...], edges: [...] }
 *   node = { id, title, code?, kind?: 'root'|'stage'|'leaf'|'warn'|'proact',
 *            emo: 'fuck'|'ok'|'wow',            // эмоция пользователя в этой точке
 *            screen: "что видит/делает пользователь",
 *            menu?: ["Кнопка 1", ...],
 *            why?: "почему именно такая эмоция",
 *            fix?: "как превратить fuck/ok в wow" (для index не обязателен) }
 *   edge = { from, to, action: "действие пользователя", kind?: 'act'|'warn'|'proact', note? }
 *
 * ОДИНАРНЫЙ клик по узлу — выделяет его. ДВОЙНОЙ клик — раскрывает боковую панель
 * с подробным описанием (экран, эмоция + почему, ветки, идея wow-фикса). Двойной
 * клик по ребру — открывает родительский узел с подсветкой этой ветки.
 */
(function () {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const NODE_W = 250;
  const NODE_H = 100;
  const H_GAP = 90;
  const V_GAP = 210;
  // Ориентация: false = сверху-вниз, true = слева-направо (выход справа / вход слева).
  let HORIZ = false;
  const KIND_TAG = { act: 'действие', warn: 'предупреждение', proact: 'система сама' };
  // Эмоции пользователя.
  const EMO = {
    fuck: { emoji: '😤', label: 'FUCK', title: 'Фрустрация' },
    ok:   { emoji: '🙂', label: 'OK',   title: 'Нейтрально' },
    wow:  { emoji: '🤩', label: 'WOW',  title: 'Восторг' },
  };
  function emoOf(node) { return EMO[node && node.emo] ? node.emo : 'ok'; }

  function el(tag, attrs, children) {
    const n = document.createElementNS(SVG_NS, tag);
    if (attrs) for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (children) for (const c of children) n.appendChild(c);
    return n;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]));
  }
  function wrapText(text, maxChars) {
    const words = String(text).replace(/\n/g, ' ⏎ ').split(/\s+/);
    const lines = [];
    let cur = '';
    for (const w of words) {
      if (w === '⏎') { lines.push(cur); cur = ''; continue; }
      if ((cur + ' ' + w).trim().length > maxChars) { if (cur) lines.push(cur); cur = w; }
      else cur = (cur + ' ' + w).trim();
    }
    if (cur) lines.push(cur);
    return lines;
  }

  let DATA = null, BYID = null, KEY_CTX = null;

  /* ---- Боковая панель точки CJM ---- */
  function ensurePanel() {
    let panel = document.querySelector('.cjm-panel');
    if (panel) return panel;
    panel = document.createElement('div');
    panel.className = 'cjm-panel';
    panel.innerHTML = `
      <div class="cjm-panel-head">
        <div class="titles"><div class="code"></div><p class="step"></p></div>
        <button class="cjm-panel-close" title="Закрыть">×</button>
      </div>
      <div class="cjm-panel-body"></div>`;
    document.querySelector('.cjm-stage-wrap').appendChild(panel);
    panel.querySelector('.cjm-panel-close').addEventListener('click', hidePanel);
    return panel;
  }
  function hidePanel() {
    const panel = document.querySelector('.cjm-panel');
    if (panel) panel.classList.remove('open');
    document.querySelectorAll('.node-card.selected').forEach(n => n.classList.remove('selected'));
    document.querySelectorAll('.edge-group.selected, .edge-badge-hit.selected').forEach(n => n.classList.remove('selected'));
  }

  function selectNodeEl(id) {
    document.querySelectorAll('.node-card.selected').forEach(n => n.classList.remove('selected'));
    const g = document.querySelector(`.node-card[data-id="${id}"]`);
    if (g) g.classList.add('selected');
  }

  function showState(id, highlightEdgeId) {
    const node = BYID.get(id);
    if (!node) return;
    const panel = ensurePanel();
    panel.querySelector('.code').textContent = node.code || '';
    panel.querySelector('.step').textContent = node.title || '';

    const outEdges = DATA.edges.filter(e => e.from === id);
    const ek = emoOf(node), em = EMO[ek];
    let html = `<div class="emo-line emo-${ek}"><span class="big">${em.emoji}</span> ${em.label} · ${em.title}</div>`;
    // Экран продукта.
    html += `<div class="sect"><h4>🖥️ Что на экране / что делает пользователь</h4><div class="screen-bubble">${esc(node.screen || node.bot || '—')}</div>`;
    if (node.menu && node.menu.length) {
      html += `<div class="screen-menu">${node.menu.map(m => `<span class="btn">${esc(m)}</span>`).join('')}</div>`;
    }
    html += `</div>`;
    // Почему такая эмоция.
    if (node.why) {
      const cls = ek === 'fuck' ? 'pain' : (ek === 'wow' ? 'wow' : '');
      html += `<div class="sect"><h4>${em.emoji} Почему «${em.label}»</h4><div class="why-emo ${cls}">${esc(node.why)}</div></div>`;
    }
    // Как сделать wow.
    if (node.fix) {
      html += `<div class="sect"><h4>✨ Как превратить в WOW</h4><div class="fix-box">${esc(node.fix)}</div></div>`;
    }
    // Ветки-переходы.
    if (outEdges.length) {
      html += `<div class="sect"><h4>➡️ Что дальше — ветки из этого состояния</h4><div class="branch-list">`;
      for (const e of outEdges) {
        const to = BYID.get(e.to);
        const kind = e.kind || 'act';
        html += `<button class="branch ${kind}" data-goto="${esc(e.to)}">
          <div class="branch-tagrow"><span class="tag">${KIND_TAG[kind] || kind}</span><span class="act">${esc(e.action || '→')}</span></div>
          <div class="to">→ ${esc(to ? to.title : e.to)}</div>
          ${e.note ? `<div class="note">${esc(e.note)}</div>` : ''}
        </button>`;
      }
      html += `</div></div>`;
    } else {
      html += `<div class="sect"><div class="cjm-panel-empty">Конечное состояние — выход или начало нового цикла.</div></div>`;
    }
    const body = panel.querySelector('.cjm-panel-body');
    body.innerHTML = html;
    body.querySelectorAll('.branch[data-goto]').forEach(b => {
      b.addEventListener('click', () => {
        const target = b.getAttribute('data-goto');
        selectNodeEl(target);
        showState(target);
      });
    });
    panel.classList.add('open');
    selectNodeEl(id);
    document.querySelectorAll('.edge-group.selected, .edge-badge-hit.selected').forEach(n => n.classList.remove('selected'));
    if (highlightEdgeId != null) {
      // Подсвечиваем и линию (слой рёбер), и её плашку (слой подписей).
      document.querySelectorAll(`.edge-group[data-eid="${highlightEdgeId}"], .edge-badge-hit[data-eid="${highlightEdgeId}"]`)
        .forEach(eg => eg.classList.add('selected'));
    }
  }

  /* ---- Раскладка (BFS-глубина + центрирование родителя над детьми) ----
     Надёжна к: нескольким точкам входа (мультиролевые деревья), циклам/возвратам
     (в т.ч. «возврат на свой же вход»), несвязным компонентам и осиротевшим узлам.
     Все узлы гарантированно получают конечные координаты (никаких NaN). */
  function layout(nodes, edges) {
    const byId = new Map(nodes.map(n => [n.id, Object.assign({}, n, { children: [], depth: 0 })]));
    const inDeg = new Map(nodes.map(n => [n.id, 0]));
    for (const e of edges) {
      const p = byId.get(e.from), c = byId.get(e.to);
      if (p && c) { p.children.push(c); inDeg.set(c.id, inDeg.get(c.id) + 1); }
    }

    // Кандидаты в корни — узлы с нулевым in-degree. Их может быть несколько (мультивход).
    const zeroIn = nodes.filter(n => inDeg.get(n.id) === 0).map(n => byId.get(n.id));

    const crossSlot = HORIZ ? (NODE_H + V_GAP) : (NODE_W + H_GAP);
    const mainStep  = HORIZ ? (NODE_W + H_GAP) : (NODE_H + V_GAP);

    let maxDepth = 0;
    const depthDone = new Set();
    function setDepth(node, d, stack) {
      node.depth = Math.max(node.depth || 0, d);
      maxDepth = Math.max(maxDepth, node.depth);
      depthDone.add(node.id);
      stack.add(node.id);
      for (const ch of node.children) {
        if (stack.has(ch.id)) continue;            // обратное ребро (цикл) — не углубляем
        setDepth(ch, d + 1, stack);
      }
      stack.delete(node.id);
    }
    // 1) от «чистых» корней. 2) добираем все ещё не посещённые узлы (компоненты,
    // где вход только через цикл, и осиротевшие) — так глубину получают ВСЕ.
    zeroIn.forEach(r => setDepth(r, 0, new Set()));
    for (const n of byId.values()) if (!depthDone.has(n.id)) setDepth(n, 0, new Set());

    let cursor = 0;
    const placed = new Set();
    function place(node) {
      if (placed.has(node.id)) return;
      placed.add(node.id);
      const kids = node.children.filter(c => !placed.has(c.id));
      if (kids.length === 0) { node.x = cursor * crossSlot; cursor += 1; }
      else {
        kids.forEach(place);
        const xs = node.children.map(c => c.x).filter(x => x !== undefined);
        node.x = (Math.min(...xs) + Math.max(...xs)) / 2;
      }
    }
    // Раскладываем: сначала чистые корни, затем ЛЮБЫЕ ещё не размещённые узлы —
    // так каждая роль/компонента и осиротевший узел получают своё место.
    zeroIn.forEach(r => { place(r); cursor += 1; });
    for (const n of byId.values()) { if (!placed.has(n.id)) { place(n); cursor += 1; } }
    // node.x — поперечная координата, node.depth*mainStep — продольная.
    for (const n of byId.values()) {
      if (HORIZ) { n.px = n.depth * mainStep; n.py = n.x; }
      else       { n.px = n.x;                n.py = n.depth * mainStep; }
    }
    return { byId, roots: zeroIn };
  }

  function render(data) {
    DATA = data;
    const { byId } = layout(data.nodes, data.edges);
    BYID = byId;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of byId.values()) {
      minX = Math.min(minX, n.px); minY = Math.min(minY, n.py);
      maxX = Math.max(maxX, n.px + NODE_W); maxY = Math.max(maxY, n.py + NODE_H);
    }
    const PAD = 80;
    const GUTTER = 240; // запас под боковой желоб обходных/обратных рёбер
    // Вертикаль: желоб уходит вправо → запас по ширине. Горизонталь: вниз → по высоте.
    const world = {
      x: minX - PAD, y: minY - PAD,
      w: (maxX - minX) + PAD * 2 + (HORIZ ? 0 : GUTTER),
      h: (maxY - minY) + PAD * 2 + (HORIZ ? GUTTER : 0),
    };
    const svg = document.getElementById('stage');
    svg.setAttribute('viewBox', `${world.x} ${world.y} ${world.w} ${world.h}`);

    // Три слоя: линии (снизу) → блоки → плашки подписей (поверх всего).
    // Плашки в отдельном верхнем слое => текст подписи никогда не оказывается под линией.
    const gEdges = el('g', { class: 'edges' });
    const gNodes = el('g', { class: 'nodes' });
    const gLabels = el('g', { class: 'labels' });
    svg.appendChild(gEdges); svg.appendChild(gNodes); svg.appendChild(gLabels);

    // Индексация рёбер: исходящие у родителя (разносим точки выхода снизу) и
    // входящие в цель (разносим точки входа сверху + подписи у входа).
    const outList = new Map(), inList = new Map();
    data.edges.forEach((e) => {
      (outList.get(e.from) || outList.set(e.from, []).get(e.from)).push(e);
      (inList.get(e.to) || inList.set(e.to, []).get(e.to)).push(e);
    });

    // Своя горизонтальная «шина» (Y в коридоре между рядами) для каждого ребра —
    // чтобы горизонтальные сегменты разных рёбер не ложились друг на друга.
    let busSeq = 0;

    // Универсальная ортогональная маршрутизация в осях «поток/поперёк».
    // Вертикаль: поток = Y (вниз), поперёк = X. Выход снизу, вход сверху.
    // Горизонталь: поток = X (вправо), поперёк = Y. Выход справа, вход слева.
    function orthPath(e) {
      const p = byId.get(e.from), c = byId.get(e.to);
      if (!p || !c) return null;
      const outs = outList.get(e.from) || [e];
      const ins = inList.get(e.to) || [e];
      const oi = outs.indexOf(e), oc = outs.length;
      const ii = ins.indexOf(e), ic = ins.length;
      const forward = c.depth > p.depth;

      // Разнос точек выхода/входа поперёк потока.
      const crossSize = HORIZ ? NODE_H : NODE_W;
      const oSpread = Math.min(crossSize - 40, oc * 26);
      const oCross = (oc > 1 ? (oi - (oc - 1) / 2) * (oSpread / Math.max(1, oc - 1)) : 0);
      const iSpread = Math.min(crossSize - 24, Math.max(0, ic - 1) * 54);
      const iCross = (ic > 1 ? (ii - (ic - 1) / 2) * (iSpread / Math.max(1, ic - 1)) : 0);

      let d, ix, iy;
      if (!HORIZ) {
        // — вертикальная ориентация —
        const ox = p.px + NODE_W / 2 + oCross, oy = p.py + NODE_H;
        ix = c.px + NODE_W / 2 + iCross; iy = c.py;
        const busY = oy + 24 + (busSeq++ % 7) * 16;
        if (forward && Math.abs(ix - ox) < 1) d = `M ${ox} ${oy} L ${ix} ${iy}`;
        else if (forward) d = `M ${ox} ${oy} L ${ox} ${busY} L ${ix} ${busY} L ${ix} ${iy}`;
        else {
          const gutter = Math.max(p.px, c.px) + NODE_W + 46 + (busSeq % 5) * 24;
          const downY = oy + 20, upY = iy - 30;
          d = `M ${ox} ${oy} L ${ox} ${downY} L ${gutter} ${downY} L ${gutter} ${upY} L ${ix} ${upY} L ${ix} ${iy}`;
        }
      } else {
        // — горизонтальная ориентация (выход справа / вход слева) —
        const ox = p.px + NODE_W, oy = p.py + NODE_H / 2 + oCross;
        ix = c.px; iy = c.py + NODE_H / 2 + iCross;
        const busX = ox + 24 + (busSeq++ % 7) * 16;
        if (forward && Math.abs(iy - oy) < 1) d = `M ${ox} ${oy} L ${ix} ${iy}`;
        else if (forward) d = `M ${ox} ${oy} L ${busX} ${oy} L ${busX} ${iy} L ${ix} ${iy}`;
        else {
          const gutter = Math.max(p.py, c.py) + NODE_H + 46 + (busSeq % 5) * 24;
          const rightX = ox + 20, leftX = ix - 30;
          d = `M ${ox} ${oy} L ${rightX} ${oy} L ${rightX} ${gutter} L ${leftX} ${gutter} L ${leftX} ${iy} L ${ix} ${iy}`;
        }
      }
      return { d, ix, iy, ii, ic };
    }

    data.edges.forEach((e, idx) => {
      const r = orthPath(e);
      if (!r) return;
      const kind = e.kind || 'act';
      const g = el('g', { class: 'edge-group edge-kind-' + kind, 'data-eid': idx });
      g.__edge = { e, idx };
      g.appendChild(el('path', { class: 'edge edge-kind-' + kind, d: r.d }));
      g.appendChild(el('path', { class: 'edge-hit', d: r.d }));
      gEdges.appendChild(g);

      // Подпись перехода — у СВОЕЙ точки входа, пришита к линии «поводком».
      // Точные координаты (с учётом ширины текста и анти-наложения) считаем ниже.
      const labelText = e.action ? String(e.action) : '';
      if (!labelText) return;
      const badge = el('g', { class: 'edge-badge-hit edge-kind-' + kind, 'data-eid': idx });
      badge.__edge = { e, idx };
      const leash = el('line', { class: 'edge-leash' });
      const rect = el('rect', { class: 'edge-badge-bg', rx: 9 });
      const lt = el('text', { class: 'edge-label', 'text-anchor': 'middle' });
      lt.textContent = labelText;
      badge.appendChild(leash); badge.appendChild(rect); badge.appendChild(lt);
      badge.__fit = { rect, lt, leash, ix: r.ix, iy: r.iy, to: e.to };
      gLabels.appendChild(badge);
    });

    // Размещение подписей — ЛОКАЛЬНО у своей точки входа, без растягивания дерева.
    // Подпись всегда сидит в коридоре перед целевым блоком (там и так проходит линия),
    // поэтому на блоки не наезжает. Разносим ТОЛЬКО против других подписей того же блока,
    // малым шагом и с жёстким лимитом — чтобы плашка не «улетала» далеко от своей линии.
    const placedByTo = new Map();           // to -> массив занятых прямоугольников
    const badges = Array.from(gLabels.querySelectorAll('.edge-badge-hit'))
      .sort((a, b) => HORIZ ? (a.__fit.iy - b.__fit.iy) : (a.__fit.ix - b.__fit.ix));
    for (const badge of badges) {
      const fit = badge.__fit; if (!fit) continue;
      let w = 40; try { w = fit.lt.getBBox().width; } catch (_) {}
      const padX = 12, bw = Math.max(24, w + padX * 2), bh = 22, gap = 5;
      const arr = placedByTo.get(fit.to) || [];

      // Базовая позиция: вплотную к входу, в коридоре перед блоком.
      let bx = HORIZ ? (fit.ix - 12 - bw / 2) : fit.ix;
      let by = HORIZ ? fit.iy : (fit.iy - 15);

      // Локальный разнос против уже стоящих подписей ЭТОГО же блока (не против всех).
      let step = 0;
      const MAX_STEP = 6;                    // не дальше 6 малых сдвигов — иначе не улетаем
      while (step < MAX_STEP) {
        const x1 = bx - bw / 2, x2 = bx + bw / 2, y1 = by - bh / 2, y2 = by + bh / 2;
        const clash = arr.some(r => !(x2 + gap < r.x1 || x1 - gap > r.x2 || y2 + gap < r.y1 || y1 - gap > r.y2));
        if (!clash) break;
        step++;
        if (HORIZ) by += (step % 2 ? 1 : -1) * Math.ceil(step / 2) * (bh + gap); // ±вверх/вниз у грани
        else       by -= (bh + gap);                                            // стопкой вверх
      }
      arr.push({ x1: bx - bw / 2, x2: bx + bw / 2, y1: by - bh / 2, y2: by + bh / 2 });
      placedByTo.set(fit.to, arr);

      fit.rect.setAttribute('x', bx - bw / 2);
      fit.rect.setAttribute('y', by - bh / 2);
      fit.rect.setAttribute('width', bw);
      fit.rect.setAttribute('height', bh);
      fit.lt.setAttribute('x', bx);
      fit.lt.setAttribute('y', by + 4);
      // Поводок от края плашки к точке входа (короткий, вдоль потока).
      if (HORIZ) { fit.leash.setAttribute('x1', bx + bw / 2); fit.leash.setAttribute('y1', by); }
      else       { fit.leash.setAttribute('x1', bx);          fit.leash.setAttribute('y1', by + bh / 2); }
      fit.leash.setAttribute('x2', fit.ix); fit.leash.setAttribute('y2', fit.iy);
    }

    for (const n of byId.values()) {
      const kind = n.kind || 'leaf';
      const ek = emoOf(n);
      const g = el('g', { class: `node-card node-${kind} emo-${ek}`, 'data-id': n.id, 'data-emo': ek, transform: `translate(${n.px} ${n.py})` });
      g.__nodeId = n.id;
      g.appendChild(el('rect', { class: 'node-rect', x: 0, y: 0, width: NODE_W, height: NODE_H, rx: 11 }));
      // Эмоциональная полоса слева.
      g.appendChild(el('line', { class: 'node-emobar', x1: 2.5, y1: 12, x2: 2.5, y2: NODE_H - 12 }));
      // Эмоция в правом верхнем углу: эмодзи + подпись.
      const emo = EMO[ek];
      const et = el('text', { class: 'node-emo', x: NODE_W - 40, y: 22, 'text-anchor': 'middle' });
      et.textContent = emo.emoji; g.appendChild(et);
      const el2 = el('text', { class: 'node-emo-label', x: NODE_W - 12, y: 20, 'text-anchor': 'end' });
      el2.textContent = emo.label; g.appendChild(el2);
      // Детальные элементы (код, превью экрана, подсказка) — прячутся в компактном режиме.
      const det = el('g', { class: 'node-details' });
      let ty = 20;
      if (n.code) { const t = el('text', { class: 'node-code', x: 14, y: ty }); t.textContent = n.code; det.appendChild(t); }
      ty += n.code ? 16 : 2;
      // Заголовок — всегда виден. В компактном режиме поднимаем его к центру карточки.
      const titleLines = wrapText(n.title, 24);
      const gTitle = el('g', { class: 'node-title-g' });
      let tty = ty;
      for (let i = 0; i < titleLines.length && i < 2; i++) { const t = el('text', { class: 'node-title', x: 14, y: tty }); t.textContent = titleLines[i]; gTitle.appendChild(t); tty += 15; }
      ty = tty;
      // Превью текста экрана (2 строки).
      const scr = n.screen || n.bot || '';
      const botLines = wrapText(scr, 40);
      for (let i = 0; i < botLines.length && i < 2; i++) {
        const t = el('text', { class: 'node-bot', x: 14, y: ty });
        t.textContent = (i === 1 && botLines.length > 2) ? botLines[i].slice(0, 34) + '…' : botLines[i];
        det.appendChild(t); ty += 13;
      }
      const tap = el('text', { class: 'node-tap', x: 14, y: NODE_H - 9 }); tap.textContent = '👆👆 двойной клик — подробно';
      det.appendChild(tap);
      g.appendChild(det);
      g.appendChild(gTitle);
      gNodes.appendChild(g);
    }

    function handleTap(target, isDouble) {
      let node = target;
      while (node && node !== svg) {
        if (node.classList && node.classList.contains('node-card') && node.__nodeId) {
          if (isDouble) showState(node.__nodeId); else selectNodeEl(node.__nodeId);
          return;
        }
        if (node.__edge && (node.classList.contains('edge-group') || node.classList.contains('edge-badge-hit'))) {
          if (isDouble) { const { e, idx } = node.__edge; showState(e.from, idx); }
          return;
        }
        node = node.parentNode;
      }
      if (isDouble) hidePanel();
    }

    // Hover-связка «линия ↔ подпись»: наведение на любой из них подсвечивает всю пару
    // (линия + плашка + поводок) и приглушает остальные — видно, откуда куда переход.
    function setHL(eid, on) {
      if (eid == null) return;
      gEdges.classList.toggle('dim', on);
      gLabels.classList.toggle('dim', on);
      document.querySelectorAll(`.edge-group[data-eid="${eid}"], .edge-badge-hit[data-eid="${eid}"]`)
        .forEach(x => x.classList.toggle('hl', on));
    }
    [gEdges, gLabels].forEach(layer => {
      layer.addEventListener('mouseover', (ev) => {
        let n = ev.target;
        while (n && n !== layer) { if (n.__edge) { setHL(n.getAttribute('data-eid'), true); return; } n = n.parentNode; }
      });
      layer.addEventListener('mouseout', (ev) => {
        let n = ev.target;
        while (n && n !== layer) { if (n.__edge) { setHL(n.getAttribute('data-eid'), false); return; } n = n.parentNode; }
      });
    });

    setupInteractions(svg, world, handleTap);
    if (data.title) { const h = document.querySelector('.cjm-topbar h1'); if (h) h.textContent = data.title; }
    if (data.subtitle) { const s = document.querySelector('.cjm-topbar .sub'); if (s) s.textContent = data.subtitle; }
    setupEmoUI(data);
  }

  /* ---- Панель эмоций: отдельный тумблер видимости на каждую эмоцию ---- */
  function setupEmoUI(data) {
    const c = { fuck: 0, ok: 0, wow: 0 };
    data.nodes.forEach(n => { c[emoOf(n)]++; });
    const bar = document.querySelector('.cjm-topbar');
    if (!bar) return;
    const nav = bar.querySelector('.cjm-nav');
    const wrap = document.querySelector('.cjm-stage-wrap');

    // Кнопки-таблетки: клик по эмоции — скрыть/показать все её узлы (и связанные рёбра).
    const box = document.createElement('div');
    box.className = 'emo-toggles';
    box.innerHTML = `<span class="lbl">эмоции:</span>` + ['fuck', 'ok', 'wow'].map(k =>
      `<button class="emo-pill emo-${k} on" data-emo="${k}">${EMO[k].emoji} <b>${EMO[k].label}</b> <i>${c[k]}</i></button>`
    ).join('');
    if (nav) bar.insertBefore(box, nav); else bar.appendChild(box);

    function applyEdgeVisibility() {
      // Ребро (линия + его плашка) видно, только если видны оба конца.
      document.querySelectorAll('.edge-group, .edge-badge-hit').forEach(g => {
        const e = g.__edge && g.__edge.e; if (!e) return;
        const from = document.querySelector(`.node-card[data-id="${e.from}"]`);
        const to = document.querySelector(`.node-card[data-id="${e.to}"]`);
        const hidden = (from && from.classList.contains('emo-hidden')) || (to && to.classList.contains('emo-hidden'));
        g.classList.toggle('emo-hidden', !!hidden);
      });
    }
    box.querySelectorAll('.emo-pill').forEach(btn => {
      btn.addEventListener('click', () => {
        const k = btn.getAttribute('data-emo');
        const on = btn.classList.toggle('on');
        document.querySelectorAll(`.node-card.emo-${k}`).forEach(nc => nc.classList.toggle('emo-hidden', !on));
        applyEdgeVisibility();
      });
    });

    // Тумблер ориентации дерева: сверху-вниз ⇄ слева-направо (полный re-render).
    const oriBox = document.createElement('button');
    oriBox.className = 'emo-filter ori-toggle';
    oriBox.innerHTML = HORIZ
      ? `↔ ориентация: <b>слева-направо</b>`
      : `↕ ориентация: <b>сверху-вниз</b>`;
    if (nav) bar.insertBefore(oriBox, nav); else bar.appendChild(oriBox);
    oriBox.addEventListener('click', () => { window.CJM_TREE.setOrientation(!HORIZ); });

    // Тумблер режима отображения: обзор (только названия) ⇄ подробно.
    const modeBox = document.createElement('label');
    modeBox.className = 'emo-filter mode-toggle';
    modeBox.innerHTML = `<input type="checkbox" id="mode-compact">
      <span>режим <b>«только названия»</b> — обзор пути издалека</span>`;
    if (nav) bar.insertBefore(modeBox, nav); else bar.appendChild(modeBox);
    modeBox.querySelector('#mode-compact').addEventListener('change', (ev) => {
      wrap.classList.toggle('compact', ev.target.checked);
    });
  }

  /* ---- Панорама/зум + распознавание одиночного/двойного клика ---- */
  function setupInteractions(svg, world, onTap) {
    let vb = { x: world.x, y: world.y, w: world.w, h: world.h };
    const fit = { ...vb };
    function apply() { svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`); }
    function clientToWorld(cx, cy) {
      const r = svg.getBoundingClientRect();
      return { x: vb.x + (cx - r.left) / r.width * vb.w, y: vb.y + (cy - r.top) / r.height * vb.h };
    }
    function zoomAt(cx, cy, factor) {
      const before = clientToWorld(cx, cy);
      vb.w *= factor; vb.h *= factor;
      const minW = fit.w * 0.12, maxW = fit.w * 4;
      if (vb.w < minW) { const k = minW / vb.w; vb.w *= k; vb.h *= k; }
      if (vb.w > maxW) { const k = maxW / vb.w; vb.w *= k; vb.h *= k; }
      const after = clientToWorld(cx, cy);
      vb.x += before.x - after.x; vb.y += before.y - after.y; apply();
    }
    svg.addEventListener('wheel', (ev) => { ev.preventDefault(); zoomAt(ev.clientX, ev.clientY, ev.deltaY > 0 ? 1.12 : 1 / 1.12); }, { passive: false });
    const DRAG_THRESHOLD = 5;
    let dragging = false, last = null, downAt = null, downTarget = null, moved = false;
    let pendingSingle = null; // таймер одиночного клика
    svg.addEventListener('pointerdown', (ev) => {
      dragging = true; moved = false; last = { x: ev.clientX, y: ev.clientY };
      downAt = { x: ev.clientX, y: ev.clientY }; downTarget = ev.target;
      svg.classList.add('grabbing'); svg.setPointerCapture(ev.pointerId);
    });
    svg.addEventListener('pointermove', (ev) => {
      if (!dragging) return;
      if (!moved && downAt && Math.hypot(ev.clientX - downAt.x, ev.clientY - downAt.y) > DRAG_THRESHOLD) moved = true;
      const r = svg.getBoundingClientRect();
      vb.x -= (ev.clientX - last.x) / r.width * vb.w;
      vb.y -= (ev.clientY - last.y) / r.height * vb.h;
      last = { x: ev.clientX, y: ev.clientY }; apply();
    });
    function resolveTarget(ev) {
      let tgt = downTarget;
      if (ev && (tgt === svg || !tgt) && document.elementFromPoint) { const e2 = document.elementFromPoint(ev.clientX, ev.clientY); if (e2) tgt = e2; }
      return tgt;
    }
    function endDrag(ev) {
      const wasDragging = dragging; dragging = false; svg.classList.remove('grabbing');
      if (wasDragging && !moved && onTap) {
        const tgt = resolveTarget(ev);
        // Различаем одиночный и двойной клик: одиночный — с задержкой, двойной — сразу.
        if (pendingSingle) {
          clearTimeout(pendingSingle); pendingSingle = null;
          onTap(tgt, true);   // двойной
        } else {
          pendingSingle = setTimeout(() => { pendingSingle = null; onTap(tgt, false); }, 240);
        }
      }
      downTarget = null; downAt = null; moved = false;
    }
    svg.addEventListener('pointerup', endDrag);
    svg.addEventListener('pointercancel', () => { dragging = false; svg.classList.remove('grabbing'); });
    // Резервный обработчик нативного dblclick (на случай тачпадов/мышей).
    svg.addEventListener('dblclick', (ev) => {
      if (pendingSingle) { clearTimeout(pendingSingle); pendingSingle = null; }
      let tgt = ev.target;
      if ((tgt === svg || !tgt) && document.elementFromPoint) { const e2 = document.elementFromPoint(ev.clientX, ev.clientY); if (e2) tgt = e2; }
      onTap(tgt, true);
    });
    function centerOf() { const r = svg.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }
    document.getElementById('zoom-in').onclick = () => { const c = centerOf(); zoomAt(c.x, c.y, 1 / 1.25); };
    document.getElementById('zoom-out').onclick = () => { const c = centerOf(); zoomAt(c.x, c.y, 1.25); };
    document.getElementById('zoom-fit').onclick = () => { vb = { ...fit }; apply(); };
    // keydown вешаем один раз на window; актуальные vb/zoom берём из текущего рендера.
    KEY_CTX = { zoomAt, centerOf, get vb() { return vb; }, set vb(v) { vb = v; }, fit, apply };
    if (!window.__cjmKeydown) {
      window.__cjmKeydown = (ev) => {
        const K = KEY_CTX; if (!K) return;
        const c = K.centerOf();
        if (ev.key === '+' || ev.key === '=') K.zoomAt(c.x, c.y, 1 / 1.2);
        else if (ev.key === '-') K.zoomAt(c.x, c.y, 1.2);
        else if (ev.key === '0') { K.vb = { ...K.fit }; K.apply(); }
        else if (ev.key === 'ArrowLeft') { K.vb.x -= K.vb.w * 0.08; K.apply(); }
        else if (ev.key === 'ArrowRight') { K.vb.x += K.vb.w * 0.08; K.apply(); }
        else if (ev.key === 'ArrowUp') { K.vb.y -= K.vb.h * 0.08; K.apply(); }
        else if (ev.key === 'ArrowDown') { K.vb.y += K.vb.h * 0.08; K.apply(); }
      };
      window.addEventListener('keydown', window.__cjmKeydown);
    }
    apply();
  }

  function rerender() {
    // Клонируем svg без слушателей, чтобы обработчики не накапливались при повторных рендерах.
    const old = document.getElementById('stage');
    const fresh = old.cloneNode(false);
    old.parentNode.replaceChild(fresh, old);
    document.querySelectorAll('.emo-toggles, .emo-filter, .cjm-panel').forEach(n => n.remove());
    if (DATA) render(DATA);
  }

  window.CJM_TREE = { render, setOrientation: (h) => { HORIZ = !!h; rerender(); }, isHoriz: () => HORIZ };
  document.addEventListener('DOMContentLoaded', () => { if (window.CJM_DATA) render(window.CJM_DATA); });
})();
