/* Рендерер интерактивных деревьев ФУНКЦИОНАЛА ТГ-бота (n-арное дерево, неск. корней).
 *
 * Данные: window.BOT_DATA = { title, subtitle, nodes: [...], edges: [...] }
 *   node = { id, title, code?, kind?: 'root'|'stage'|'leaf', bot: "текст ответа бота",
 *            menu?: ["Кнопка 1", ...] }
 *   edge = { from, to, action: "нажал ...", kind?: 'act'|'warn'|'proact', note? }
 *
 * Клик по УЗЛУ (состояние бота) — открывает панель: полный текст ответа бота, кнопки
 * его меню и список веток (действий), ведущих в следующие состояния. Клик по ветке в
 * панели — переходит к соответствующему состоянию. Клик по ребру/бейджу — то же, что
 * по родительскому состоянию с подсветкой ветки. Панорама/зум/вписать — как в CJM.
 */
(function () {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const NODE_W = 250;
  const NODE_H = 92;
  const H_GAP = 40;
  const V_GAP = 140;
  const KIND_TAG = { act: 'действие', warn: 'предупреждение', proact: 'бот сам' };

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

  let DATA = null, BYID = null;

  /* ---- Панель состояния бота ---- */
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
    document.querySelectorAll('.edge-group.selected').forEach(n => n.classList.remove('selected'));
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
    let html = '';
    // Экран бота.
    html += `<div class="sect"><h4>💬 Что отвечает бот</h4><div class="bot-bubble">${esc(node.bot || '—')}</div>`;
    if (node.menu && node.menu.length) {
      html += `<div class="bot-menu">${node.menu.map(m => `<span class="btn">${esc(m)}</span>`).join('')}</div>`;
    }
    html += `</div>`;
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
      html += `<div class="sect"><div class="cjm-panel-empty">Конечное состояние — дальнейших веток нет.</div></div>`;
    }
    const body = panel.querySelector('.cjm-panel-body');
    body.innerHTML = html;
    body.querySelectorAll('.branch[data-goto]').forEach(b => {
      b.addEventListener('click', () => {
        const target = b.getAttribute('data-goto');
        selectNodeEl(target);
        showState(target);
        const g = document.querySelector(`.node-card[data-id="${target}"]`);
        if (g) g.scrollIntoView && g.scrollIntoView({ block: 'nearest' });
      });
    });
    panel.classList.add('open');
    selectNodeEl(id);
    document.querySelectorAll('.edge-group.selected').forEach(n => n.classList.remove('selected'));
    if (highlightEdgeId != null) {
      const eg = document.querySelector(`.edge-group[data-eid="${highlightEdgeId}"]`);
      if (eg) eg.classList.add('selected');
    }
  }

  /* ---- Раскладка (как в CJM: BFS-глубина + центрирование родителя над детьми) ---- */
  function layout(nodes, edges) {
    const byId = new Map(nodes.map(n => [n.id, Object.assign({}, n, { children: [] })]));
    const hasParent = new Set();
    for (const e of edges) {
      const p = byId.get(e.from), c = byId.get(e.to);
      if (p && c) { p.children.push(c); hasParent.add(c.id); }
    }
    const roots = nodes.filter(n => !hasParent.has(n.id)).map(n => byId.get(n.id));
    let maxDepth = 0;
    const visited = new Set();
    function setDepth(node, d) {
      node.depth = Math.max(node.depth || 0, d);
      maxDepth = Math.max(maxDepth, node.depth);
      const key = node.id + ':' + d;
      if (visited.has(key)) return;
      visited.add(key);
      node.children.forEach(ch => setDepth(ch, d + 1));
    }
    roots.forEach(r => setDepth(r, 0));

    let cursor = 0;
    const slot = NODE_W + H_GAP;
    const placed = new Set();
    function place(node) {
      if (placed.has(node.id)) return;
      placed.add(node.id);
      const kids = node.children.filter(c => !placed.has(c.id));
      if (kids.length === 0) { node.x = cursor * slot; cursor += 1; }
      else {
        kids.forEach(place);
        const xs = node.children.map(c => c.x).filter(x => x !== undefined);
        node.x = (Math.min(...xs) + Math.max(...xs)) / 2;
      }
    }
    roots.forEach(r => { place(r); cursor += 1; });
    for (const n of byId.values()) { if (n.x === undefined) { n.x = cursor * slot; cursor += 1; } }
    for (const n of byId.values()) { n.px = n.x; n.py = n.depth * (NODE_H + V_GAP); }
    return { byId, roots };
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
    const world = { x: minX - PAD, y: minY - PAD, w: (maxX - minX) + PAD * 2, h: (maxY - minY) + PAD * 2 };
    const svg = document.getElementById('stage');
    svg.setAttribute('viewBox', `${world.x} ${world.y} ${world.w} ${world.h}`);

    const gEdges = el('g', { class: 'edges' });
    const gNodes = el('g', { class: 'nodes' });
    svg.appendChild(gEdges); svg.appendChild(gNodes);

    data.edges.forEach((e, idx) => {
      const p = byId.get(e.from), c = byId.get(e.to);
      if (!p || !c) return;
      const x1 = p.px + NODE_W / 2, y1 = p.py + NODE_H;
      const x2 = c.px + NODE_W / 2, y2 = c.py;
      const my = (y1 + y2) / 2;
      const d = `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`;
      const kind = e.kind || 'act';
      const g = el('g', { class: 'edge-group edge-kind-' + kind, 'data-eid': idx });
      g.__edge = { e, idx };
      g.appendChild(el('path', { class: 'edge edge-kind-' + kind, d }));
      g.appendChild(el('path', { class: 'edge-hit', d }));
      const bx = (x1 + x2) / 2, by = my;
      const labelText = e.action ? String(e.action) : '';
      const badgeW = labelText ? Math.min(240, 20 + labelText.length * 6.0) : 20;
      const badge = el('g', { class: 'edge-badge-hit' });
      badge.appendChild(el('rect', { class: 'edge-badge-bg', x: bx - badgeW / 2, y: by - 11, width: badgeW, height: 22, rx: 9 }));
      if (labelText) {
        const lt = el('text', { class: 'edge-label', x: bx, y: by + 3.5, 'text-anchor': 'middle' });
        lt.textContent = labelText;
        badge.appendChild(lt);
      }
      g.appendChild(badge);
      gEdges.appendChild(g);
    });

    for (const n of byId.values()) {
      const kind = n.kind || 'leaf';
      const g = el('g', { class: `node-card node-${kind}`, 'data-id': n.id, transform: `translate(${n.px} ${n.py})` });
      g.__nodeId = n.id;
      g.appendChild(el('rect', { class: 'node-rect', x: 0, y: 0, width: NODE_W, height: NODE_H, rx: 11 }));
      let ty = 18;
      if (n.code) { const t = el('text', { class: 'node-code', x: 14, y: ty }); t.textContent = n.code; g.appendChild(t); ty += 16; }
      else ty += 2;
      const titleLines = wrapText(n.title, 30);
      for (let i = 0; i < titleLines.length && i < 2; i++) { const t = el('text', { class: 'node-title', x: 14, y: ty }); t.textContent = titleLines[i]; g.appendChild(t); ty += 15; }
      // Превью текста бота (2 строки).
      const botLines = wrapText(n.bot || '', 40);
      for (let i = 0; i < botLines.length && i < 2; i++) {
        const t = el('text', { class: 'node-bot', x: 14, y: ty });
        t.textContent = (i === 1 && botLines.length > 2) ? botLines[i].slice(0, 34) + '…' : botLines[i];
        g.appendChild(t); ty += 13;
      }
      const tap = el('text', { class: 'node-tap', x: 14, y: NODE_H - 8 }); tap.textContent = '👆 открыть ответ бота и ветки';
      g.appendChild(tap);
      gNodes.appendChild(g);
    }

    function handleTap(target) {
      let node = target;
      while (node && node !== svg) {
        if (node.classList && node.classList.contains('node-card') && node.__nodeId) { showState(node.__nodeId); return; }
        if (node.classList && node.classList.contains('edge-group') && node.__edge) {
          const { e, idx } = node.__edge; showState(e.from, idx); return;
        }
        node = node.parentNode;
      }
      hidePanel();
    }

    setupInteractions(svg, world, handleTap);
    if (data.title) { const h = document.querySelector('.cjm-topbar h1'); if (h) h.textContent = data.title; }
    if (data.subtitle) { const s = document.querySelector('.cjm-topbar .sub'); if (s) s.textContent = data.subtitle; }
  }

  /* ---- Панорама/зум (идентично CJM) ---- */
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
    function endDrag(ev) {
      const wasDragging = dragging; dragging = false; svg.classList.remove('grabbing');
      if (wasDragging && !moved && onTap) {
        let tgt = downTarget;
        if (ev && (tgt === svg || !tgt) && document.elementFromPoint) { const e2 = document.elementFromPoint(ev.clientX, ev.clientY); if (e2) tgt = e2; }
        onTap(tgt);
      }
      downTarget = null; downAt = null; moved = false;
    }
    svg.addEventListener('pointerup', endDrag);
    svg.addEventListener('pointercancel', () => { dragging = false; svg.classList.remove('grabbing'); });
    function centerOf() { const r = svg.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }
    document.getElementById('zoom-in').onclick = () => { const c = centerOf(); zoomAt(c.x, c.y, 1 / 1.25); };
    document.getElementById('zoom-out').onclick = () => { const c = centerOf(); zoomAt(c.x, c.y, 1.25); };
    document.getElementById('zoom-fit').onclick = () => { vb = { ...fit }; apply(); };
    window.addEventListener('keydown', (ev) => {
      const c = centerOf();
      if (ev.key === '+' || ev.key === '=') zoomAt(c.x, c.y, 1 / 1.2);
      else if (ev.key === '-') zoomAt(c.x, c.y, 1.2);
      else if (ev.key === '0') { vb = { ...fit }; apply(); }
      else if (ev.key === 'ArrowLeft') { vb.x -= vb.w * 0.08; apply(); }
      else if (ev.key === 'ArrowRight') { vb.x += vb.w * 0.08; apply(); }
      else if (ev.key === 'ArrowUp') { vb.y -= vb.h * 0.08; apply(); }
      else if (ev.key === 'ArrowDown') { vb.y += vb.h * 0.08; apply(); }
    });
    apply();
  }

  window.BOT_TREE = { render };
  document.addEventListener('DOMContentLoaded', () => { if (window.BOT_DATA) render(window.BOT_DATA); });
})();
