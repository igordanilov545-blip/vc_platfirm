/*
 * letter_editor.js — конструктор благодарственных писем (letter-templates.md).
 *
 * Подложка = PNG первой страницы PDF-фона; поверх — перетаскиваемые/ресайзимые
 * прямоугольники-поля (ФИО/меро/часы/подпись/текст). Координаты храним в ДОЛЯХ [0..1]
 * от размера сцены (устойчиво к масштабу/DPI) — те же доли сервер переводит в PDF-пункты
 * при штамповке (blog.services.letter_render). Навешивается по data-letter-editor.
 *
 * Всё локально, без внешних библиотек (CSP запрещает CDN): drag/resize — на нативных
 * pointer-событиях.
 */
(function () {
    'use strict';

    function csrf() {
        var el = document.querySelector('[name=csrfmiddlewaretoken]');
        return el ? el.value : '';
    }

    function initLetterEditor(root) {
        (root || document).querySelectorAll('[data-letter-editor]').forEach(function (host) {
            if (host.dataset.leInit) return;
            host.dataset.leInit = '1';
            new LetterEditor(host);
        });
    }

    function LetterEditor(host) {
        this.host = host;
        this.stage = host.querySelector('[data-le-stage]');
        this.bg = host.querySelector('[data-le-bg]');
        this.layer = host.querySelector('[data-le-fields]');
        this.props = host.querySelector('[data-le-props]');
        this.status = host.querySelector('[data-le-status]');

        this.saveUrl = host.getAttribute('data-save-url');
        this.fontUploadUrl = host.getAttribute('data-font-upload-url');
        this.fonts = safeJson(host.getAttribute('data-fonts'), []);
        this.fieldKeys = safeJson(host.getAttribute('data-field-keys'), {});
        this.fields = safeJson(host.getAttribute('data-fields'), []);
        this.selected = null;   // индекс выбранного поля
        this.els = [];          // DOM-узлы полей по индексу

        this.bg.src = host.getAttribute('data-bg-url');
        this.buildFontOptions();
        this.bindToolbar();
        this.bindProps();
        this.render();
    }

    LetterEditor.prototype.buildFontOptions = function () {
        var sel = this.host.querySelector('[data-le-prop-font]');
        if (!sel) return;
        sel.innerHTML = '';
        this.fonts.forEach(function (f) {
            var o = document.createElement('option');
            o.value = f.id; o.textContent = f.name;
            sel.appendChild(o);
        });
    };

    LetterEditor.prototype.defaultFontId = function () {
        return this.fonts.length ? this.fonts[0].id : null;
    };

    LetterEditor.prototype.bindToolbar = function () {
        var self = this;
        this.host.querySelectorAll('[data-le-add]').forEach(function (btn) {
            btn.addEventListener('click', function () { self.addField(btn.getAttribute('data-le-add')); });
        });
        var saveBtn = this.host.querySelector('[data-le-save]');
        if (saveBtn) saveBtn.addEventListener('click', function () { self.save(); });

        var uploadFontBtn = this.host.querySelector('[data-le-upload-font]');
        if (uploadFontBtn) uploadFontBtn.addEventListener('click', function () { self.uploadFont(); });
    };

    // Новое поле — по центру сцены, дефолтный размер/шрифт.
    LetterEditor.prototype.addField = function (key) {
        var f = {
            key: key,
            x: 0.15, y: 0.4, w: 0.5, h: 0.08,
            font_id: this.defaultFontId(),
            size: 20, color: '#000000', align: 'left'
        };
        if (key === 'custom') f.text = 'Текст';
        this.fields.push(f);
        this.render();
        this.select(this.fields.length - 1);
    };

    LetterEditor.prototype.render = function () {
        var self = this;
        this.layer.innerHTML = '';
        this.els = [];
        this.fields.forEach(function (f, i) {
            var box = document.createElement('div');
            box.className = 'le-field';
            box.style.left = (f.x * 100) + '%';
            box.style.top = (f.y * 100) + '%';
            box.style.width = (f.w * 100) + '%';
            box.style.height = (f.h * 100) + '%';
            box.style.textAlign = f.align || 'left';
            box.style.color = f.color || '#000';

            var label = document.createElement('span');
            label.className = 'le-field-label';
            label.textContent = self.fieldPreviewText(f);
            box.appendChild(label);

            var handle = document.createElement('div');
            handle.className = 'le-resize';
            box.appendChild(handle);

            box.addEventListener('pointerdown', function (e) {
                if (e.target === handle) return; // ресайз — своим хендлером
                self.select(i);
                self.startDrag(e, i, box);
            });
            handle.addEventListener('pointerdown', function (e) {
                e.stopPropagation();
                self.select(i);
                self.startResize(e, i, box);
            });

            self.layer.appendChild(box);
            self.els[i] = box;
        });
        this.highlightSelected();
    };

    LetterEditor.prototype.fieldPreviewText = function (f) {
        if (f.key === 'custom') return f.text || 'Текст';
        return this.fieldKeys[f.key] || f.key;
    };

    // --- Перетаскивание -----------------------------------------------------
    LetterEditor.prototype.startDrag = function (e, i, box) {
        e.preventDefault();
        var self = this, f = this.fields[i];
        var rect = this.stage.getBoundingClientRect();
        var startX = e.clientX, startY = e.clientY;
        var ox = f.x, oy = f.y;
        box.setPointerCapture(e.pointerId);

        function move(ev) {
            var dx = (ev.clientX - startX) / rect.width;
            var dy = (ev.clientY - startY) / rect.height;
            f.x = clamp(ox + dx, 0, 1 - f.w);
            f.y = clamp(oy + dy, 0, 1 - f.h);
            box.style.left = (f.x * 100) + '%';
            box.style.top = (f.y * 100) + '%';
        }
        function up(ev) {
            box.releasePointerCapture(e.pointerId);
            box.removeEventListener('pointermove', move);
            box.removeEventListener('pointerup', up);
        }
        box.addEventListener('pointermove', move);
        box.addEventListener('pointerup', up);
    };

    // --- Ресайз (правый нижний угол) ----------------------------------------
    LetterEditor.prototype.startResize = function (e, i, box) {
        e.preventDefault();
        var self = this, f = this.fields[i];
        var rect = this.stage.getBoundingClientRect();
        var startX = e.clientX, startY = e.clientY;
        var ow = f.w, oh = f.h;
        box.setPointerCapture(e.pointerId);

        function move(ev) {
            var dw = (ev.clientX - startX) / rect.width;
            var dh = (ev.clientY - startY) / rect.height;
            f.w = clamp(ow + dw, 0.03, 1 - f.x);
            f.h = clamp(oh + dh, 0.02, 1 - f.y);
            box.style.width = (f.w * 100) + '%';
            box.style.height = (f.h * 100) + '%';
        }
        function up() {
            box.releasePointerCapture(e.pointerId);
            box.removeEventListener('pointermove', move);
            box.removeEventListener('pointerup', up);
        }
        box.addEventListener('pointermove', move);
        box.addEventListener('pointerup', up);
    };

    // --- Выбор поля и панель свойств ----------------------------------------
    LetterEditor.prototype.select = function (i) {
        this.selected = i;
        this.highlightSelected();
        this.fillProps();
    };

    LetterEditor.prototype.highlightSelected = function () {
        var self = this;
        this.els.forEach(function (el, i) {
            el.classList.toggle('is-selected', i === self.selected);
        });
    };

    LetterEditor.prototype.bindProps = function () {
        var self = this;
        var typeBox = this.host.querySelector('[data-le-prop-type]');
        var text = this.host.querySelector('[data-le-prop-text]');
        var font = this.host.querySelector('[data-le-prop-font]');
        var size = this.host.querySelector('[data-le-prop-size]');
        var color = this.host.querySelector('[data-le-prop-color]');
        var align = this.host.querySelector('[data-le-prop-align]');
        var del = this.host.querySelector('[data-le-delete-field]');

        function cur() { return self.selected == null ? null : self.fields[self.selected]; }
        function apply(k, v) { var f = cur(); if (f) { f[k] = v; self.render(); } }

        if (text) text.addEventListener('input', function () { apply('text', text.value); });
        if (font) font.addEventListener('change', function () { apply('font_id', parseInt(font.value, 10)); });
        if (size) size.addEventListener('input', function () { apply('size', parseFloat(size.value) || 12); });
        if (color) color.addEventListener('input', function () { apply('color', color.value); });
        if (align) align.addEventListener('change', function () { apply('align', align.value); });
        if (del) del.addEventListener('click', function () {
            if (self.selected == null) return;
            self.fields.splice(self.selected, 1);
            self.selected = null;
            self.props.hidden = true;
            self.render();
        });
        this._typeBox = typeBox;
    };

    LetterEditor.prototype.fillProps = function () {
        var f = this.selected == null ? null : this.fields[this.selected];
        if (!f) { this.props.hidden = true; return; }
        this.props.hidden = false;
        if (this._typeBox) this._typeBox.textContent = this.fieldKeys[f.key] || f.key;

        var customWrap = this.host.querySelector('[data-le-custom-wrap]');
        if (customWrap) customWrap.hidden = (f.key !== 'custom');
        setVal(this.host, '[data-le-prop-text]', f.text || '');
        setVal(this.host, '[data-le-prop-font]', f.font_id != null ? String(f.font_id) : '');
        setVal(this.host, '[data-le-prop-size]', f.size);
        setVal(this.host, '[data-le-prop-color]', f.color || '#000000');
        setVal(this.host, '[data-le-prop-align]', f.align || 'left');
    };

    // --- Сохранение ---------------------------------------------------------
    LetterEditor.prototype.save = function () {
        var self = this;
        this.setStatus('Сохранение…', false);
        fetch(this.saveUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify(this.fields)
        }).then(function (r) { return r.json().catch(function () { return { ok: r.ok }; }); })
          .then(function (d) {
              if (d && d.ok) self.setStatus('Сохранено ✓', false);
              else self.setStatus('Ошибка сохранения', true);
          })
          .catch(function () { self.setStatus('Ошибка сети', true); });
    };

    LetterEditor.prototype.setStatus = function (text, isError) {
        if (!this.status) return;
        this.status.hidden = false;
        this.status.textContent = text;
        this.status.classList.toggle('is-error', !!isError);
    };

    // --- Загрузка своего шрифта (AJAX) --------------------------------------
    LetterEditor.prototype.uploadFont = function () {
        var self = this;
        var name = window.prompt('Название шрифта (как будет в списке):');
        if (!name) return;
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = '.ttf,.otf';
        input.addEventListener('change', function () {
            if (!input.files.length) return;
            var fd = new FormData();
            fd.append('csrfmiddlewaretoken', csrf());
            fd.append('name', name);
            fd.append('font_upload', input.files[0]);
            fetch(self.fontUploadUrl, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                body: fd
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d.ok) {
                      self.fonts.push({ id: d.id, name: d.name });
                      self.buildFontOptions();
                      var f = self.selected == null ? null : self.fields[self.selected];
                      if (f) { f.font_id = d.id; self.fillProps(); self.render(); }
                      self.setStatus('Шрифт «' + d.name + '» добавлен', false);
                  } else {
                      var msg = collectErrors(d.errors) || 'Не удалось загрузить шрифт';
                      window.alert(msg);
                  }
              })
              .catch(function () { window.alert('Ошибка сети при загрузке шрифта'); });
        });
        input.click();
    };

    // --- helpers ------------------------------------------------------------
    function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
    function safeJson(s, fallback) { try { return JSON.parse(s); } catch (e) { return fallback; } }
    function setVal(root, sel, v) { var el = root.querySelector(sel); if (el) el.value = v; }
    function collectErrors(errors) {
        if (!errors) return '';
        var out = [];
        Object.keys(errors).forEach(function (k) {
            (errors[k] || []).forEach(function (e) { out.push(e.message || e); });
        });
        return out.join(' ');
    }

    window.initLetterEditor = initLetterEditor;
    initLetterEditor(document);
})();
