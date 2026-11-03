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
        async function post(url, values) {
            var response = await fetch(url, {
                method: 'POST', credentials: 'same-origin',
                headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'},
                body: new URLSearchParams(values)
            });
            var html = await response.text();
            if (!response.ok) throw new Error(response.status === 403 ? 'Нет права на это действие.' : html);
            if (!html.includes('data-qr-result')) throw new Error('Войдите в систему заново.');
            return html;
        }
        function bindMarks() {
            modalBody.querySelectorAll('[data-qr-mark]').forEach(function (button) {
                button.addEventListener('click', async function () {
                    modalBody.querySelectorAll('[data-qr-mark]').forEach(function (other) { other.disabled = true; });
                    try {
                        modalBody.innerHTML = await post(VC_URLS.qrMark, {token: token, shift_id: button.dataset.shiftId, action: button.dataset.qrMark});
                        bindMarks();
                    } catch (error) {
                        var message = modalBody.querySelector('[data-qr-mark-status]');
                        if (message) message.textContent = error.message;
                        modalBody.querySelectorAll('[data-qr-mark]').forEach(function (other) { other.disabled = false; });
                    }
                });
            });
        }
        async function found(value) {
            if (busy) return;
            busy = true;
            stopCamera();
            token = value;
            try {
                var html = await post(VC_URLS.qrScan, {token: token});
                openModal('Регистрация участника');
                modalBody.innerHTML = html;
                bindMarks();
                status.textContent = 'QR прочитан. Можно сканировать следующего участника.';
            } catch (error) {
                status.textContent = error.message;
            } finally { busy = false; }
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
            if (!panel.isConnected) { stopCamera(); token = null; observer.disconnect(); }
        });
        observer.observe(document.body, {childList: true, subtree: true});
        window.addEventListener('pagehide', stopCamera, {once: true});
    });
}
initQrScanner(document);
