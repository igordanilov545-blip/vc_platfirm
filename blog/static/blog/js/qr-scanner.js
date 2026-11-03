/* Сканирование локально: изображение с камеры/файла не отправляется на сервер. */
var qrDecoderReady;
function loadQrDecoder() {
    if (window.jsQR) return Promise.resolve();
    if (!qrDecoderReady) qrDecoderReady = new Promise(function (resolve, reject) {
        var script = document.createElement('script');
        script.src = VC_URLS.qrDecoder;
        script.onload = resolve;
        script.onerror = function () { qrDecoderReady = null; reject(new Error('Не удалось загрузить сканер QR.')); };
        document.head.appendChild(script);
    });
    return qrDecoderReady;
}
function initQrScanner(root) {
    root.querySelectorAll('[data-qr-scanner]').forEach(function (panel) {
        if (panel.dataset.qrInit) return;
        panel.dataset.qrInit = '1';
        var video = panel.querySelector('[data-qr-video]');
        var status = panel.querySelector('[data-qr-status]');
        var start = panel.querySelector('[data-qr-start]');
        var stop = panel.querySelector('[data-qr-stop]');
        var file = panel.querySelector('[data-qr-file]');
        var stream = null, frame = null, token = null, busy = false;
        var scanTicket = null, pending = {}, saving = false, visitingProfile = false, updating = false, closeRequested = false;
        var storageKey = 'vc:qr-window:' + panel.dataset.operatorId;
        var canvas = document.createElement('canvas');
        var context = canvas.getContext('2d', {willReadFrequently: true});
        var csrf = panel.querySelector('[name=csrfmiddlewaretoken]').value;

        function stopCamera() {
            if (frame) cancelAnimationFrame(frame);
            frame = null;
            if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
            stream = null;
            video.srcObject = null;
            video.hidden = true;
            stop.hidden = true;
            start.disabled = false;
        }
        async function post(url, values, keepalive) {
            var response = await fetch(url, {
                method: 'POST', credentials: 'same-origin', keepalive: !!keepalive,
                headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'},
                body: new URLSearchParams(values)
            });
            var html = await response.text();
            if (!response.ok) throw new Error(response.status === 403 ? 'Нет права на это действие.' : html);
            if (!html.includes('data-qr-result')) throw new Error('Войдите в систему заново.');
            return html;
        }
        function remember() {
            if (!token || !scanTicket) return;
            try { sessionStorage.setItem(storageKey, JSON.stringify({token: token, ticket: scanTicket, pending: pending})); } catch (_) {}
        }
        function forget() {
            try { sessionStorage.removeItem(storageKey); } catch (_) {}
        }
        function resetWindow() {
            forget(); token = null; scanTicket = null; pending = {}; visitingProfile = false; closeRequested = false;
        }
        async function saveWindow(close, keepalive) {
            if (saving || !token) return;
            var changes = Object.values(pending);
            if (!changes.length) { if (close) closeModal(true); return; }
            saving = true;
            remember();
            var card = modalBody.querySelector('[data-qr-result]');
            var controls = card ? Array.from(card.querySelectorAll('input, select, button')) : [];
            var previousDisabled = controls.map(function (control) { return control.disabled; });
            controls.forEach(function (control) { control.disabled = true; });
            var currentToken = token;
            try {
                await post(VC_URLS.qrCommit, {token: token, scan_ticket: scanTicket, changes: JSON.stringify(changes)}, keepalive);
                if (token === currentToken) {
                    pending = {}; forget();
                    if (close && modalBody.querySelector('[data-qr-result]')) closeModal(true);
                }
            } catch (error) {
                if (card && card.isConnected) {
                    card.querySelector('[data-qr-mark-status]').textContent = 'Не удалось сохранить: ' + error.message;
                    controls.forEach(function (control, index) { control.disabled = previousDisabled[index]; });
                }
            } finally { saving = false; }
        }
        function beforeClose(event) {
            if (!modalBody.querySelector('[data-qr-result]') || !token) return;
            if (busy || updating) { event.preventDefault(); closeRequested = true; return; }
            if (saving || Object.keys(pending).length) {
                event.preventDefault();
                if (!saving) saveWindow(true, false);
            }
        }
        modalBackdrop.addEventListener('modal:before-close', beforeClose);
        modalBackdrop.addEventListener('modal:closed', resetWindow);
        function bindMarks() {
            var card = modalBody.querySelector('[data-qr-result]');
            scanTicket = card.dataset.scanTicket;
            var cardToken = token;
            async function updateCard(url, values, checkbox) {
                updating = true;
                var controls = Array.from(card.querySelectorAll('input, select, button'));
                var disabled = controls.map(function (control) { return control.disabled; });
                controls.forEach(function (control) { control.disabled = true; });
                card.setAttribute('aria-busy', 'true');
                var message = card.querySelector('[data-qr-mark-status]');
                message.textContent = '';
                try {
                    values.token = cardToken;
                    values.scan_ticket = scanTicket;
                    var html = await post(url, values);
                    if (card.isConnected && token === cardToken) {
                        modalBody.innerHTML = html;
                        bindMarks();
                    }
                } catch (error) {
                    if (checkbox) checkbox.checked = false;
                    message.textContent = error.message;
                    controls.forEach(function (control, index) { control.disabled = disabled[index]; });
                } finally {
                    card.removeAttribute('aria-busy');
                    updating = false;
                    if (closeRequested) { closeRequested = false; saveWindow(true, false); }
                }
            }
            card.querySelectorAll('[data-qr-mark]').forEach(function (checkbox) {
                var key = checkbox.dataset.qrMark + ':' + checkbox.dataset.shiftId;
                if (checkbox.disabled) delete pending[key];
                else if (pending[key] || checkbox.dataset.qrMark === 'in' && checkbox.dataset.shiftId === card.dataset.suggestedEntry) {
                    checkbox.checked = true;
                    pending[key] = {kind: checkbox.dataset.qrMark, shift_id: Number(checkbox.dataset.shiftId)};
                }
                checkbox.addEventListener('change', function () {
                    if (checkbox.checked) pending[key] = {kind: checkbox.dataset.qrMark, shift_id: Number(checkbox.dataset.shiftId)};
                    else delete pending[key];
                    showDraft();
                });
            });
            function showDraft() {
                card.querySelectorAll('[data-qr-mark]').forEach(function (checkbox) {
                    var key = checkbox.dataset.qrMark + ':' + checkbox.dataset.shiftId;
                    checkbox.closest('td').classList.toggle('qr-mark-pending', !!pending[key]);
                    var preview = checkbox.parentElement.querySelector('[data-qr-pending-time]');
                    if (preview) preview.remove();
                    if (pending[key] && ['in', 'out'].includes(checkbox.dataset.qrMark)) {
                        preview = document.createElement('time');
                        preview.dataset.qrPendingTime = '';
                        preview.className = 'qr-mark-time';
                        preview.textContent = new Date(card.dataset.scanTime).toLocaleTimeString('ru-RU', {timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit'});
                        checkbox.parentElement.appendChild(preview);
                    }
                });
                card.querySelector('[data-qr-draft-status]').textContent = Object.keys(pending).length ? 'Выбрано отметок: ' + Object.keys(pending).length + '. Сохранятся при закрытии окна.' : '';
                remember();
            }
            card.querySelectorAll('a[href]').forEach(function (link) {
                link.addEventListener('click', function (event) {
                    if (saving || updating) { event.preventDefault(); return; }
                    if (event.ctrlKey || event.metaKey || event.shiftKey || link.target === '_blank') return;
                    remember();
                    visitingProfile = true;
                });
            });
            showDraft();
            var form = card.querySelector('[data-qr-enroll]');
            if (form) form.addEventListener('submit', function (event) {
                event.preventDefault();
                if (!form.reportValidity()) return;
                updateCard(VC_URLS.qrEnroll, {shift_id: form.elements.shift_id.value});
            });
        }
        async function found(value, ticket, choices) {
            if (busy) return;
            busy = true;
            stopCamera();
            token = value;
            visitingProfile = false;
            pending = choices || {};
            try {
                var html = await post(VC_URLS.qrScan, {token: token, scan_ticket: ticket || ''});
                openModal('Регистрация участника');
                modalBody.innerHTML = html;
                bindMarks();
                status.textContent = 'QR прочитан. Можно сканировать следующего участника.';
            } catch (error) {
                status.textContent = error.message;
            } finally {
                busy = false;
                if (closeRequested) { closeRequested = false; saveWindow(true, false); }
            }
        }
        function restoreWindow() {
            var saved;
            try { saved = JSON.parse(sessionStorage.getItem(storageKey)); } catch (_) {}
            if (saved && saved.token && saved.ticket) found(saved.token, saved.ticket, saved.pending);
        }
        function decode(image, width, height) {
            canvas.width = width;
            canvas.height = height;
            context.drawImage(image, 0, 0, width, height);
            var pixels = context.getImageData(0, 0, width, height);
            return jsQR(pixels.data, width, height, {inversionAttempts: 'dontInvert'});
        }
        function readFrame() {
            if (!stream || !panel.isConnected) return stopCamera();
            if (video.readyState >= 2 && video.videoWidth) {
                var width = Math.min(800, video.videoWidth);
                var code = decode(video, width, Math.round(video.videoHeight * width / video.videoWidth));
                if (code) { found(code.data); return; }
            }
            frame = requestAnimationFrame(readFrame);
        }
        start.addEventListener('click', async function () {
            stopCamera();
            start.disabled = true;
            try {
                await loadQrDecoder();
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('Для камеры нужен HTTPS или localhost. Можно выбрать фото QR.');
                stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}, audio: false});
                if (!panel.isConnected) return stopCamera();
                video.srcObject = stream;
                video.hidden = false;
                stop.hidden = false;
                await video.play();
                status.textContent = 'Наведите камеру на QR-код.';
                readFrame();
            } catch (error) { stopCamera(); status.textContent = error.message; }
        });
        stop.addEventListener('click', stopCamera);
        file.addEventListener('change', async function () {
            if (!file.files[0]) return;
            stopCamera();
            var bitmap;
            try {
                await loadQrDecoder();
                bitmap = await createImageBitmap(file.files[0]);
                var code = decode(bitmap, bitmap.width, bitmap.height);
                if (!code) throw new Error('QR-код на фото не найден.');
                await found(code.data);
            } catch (error) { status.textContent = error.message; }
            finally { if (bitmap) bitmap.close(); file.value = ''; }
        });
        var observer = new MutationObserver(function () {
            if (!panel.isConnected) {
                stopCamera();
                modalBackdrop.removeEventListener('modal:before-close', beforeClose);
                modalBackdrop.removeEventListener('modal:closed', resetWindow);
                window.removeEventListener('pagehide', onPageHide);
                window.removeEventListener('pageshow', onPageShow);
                if (!visitingProfile && Object.keys(pending).length) saveWindow(false, true);
                observer.disconnect();
            }
        });
        observer.observe(document.body, {childList: true, subtree: true});
        function onPageHide() {
            stopCamera();
            if (!visitingProfile && Object.keys(pending).length) saveWindow(false, true);
        }
        function onPageShow(event) {
            if (!event.persisted) return;
            visitingProfile = false;
            // BFCache уже хранит живую карточку и обработчики; не заменяем её
            // параллельным запросом, который мог бы пересечься с закрытием.
            if (token && modalBody.querySelector('[data-qr-result]')) return;
            restoreWindow();
        }
        window.addEventListener('pagehide', onPageHide);
        window.addEventListener('pageshow', onPageShow);
        restoreWindow();
    });
}
initQrScanner(document);
