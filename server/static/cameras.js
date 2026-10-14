/* Trang "Camera": chọn camera riêng cho đăng ký / cửa / nhận diện + nguồn cho client Python. */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  function A() { return window.__app; }
  var ids = [['camEnroll', 'pvEnroll'], ['camDoor', 'pvDoor'], ['camLab', 'pvLab']], cams = {}, bound = false;

  function refresh() { return Promise.all(ids.map(function (p) { return A().fillDevices($(p[0])); })); }
  function stopAll() { Object.keys(cams).forEach(function (k) { cams[k].stop(); }); }

  function preview(selId, vId) {
    var sel = $(selId);
    stopAll();   // một camera một lúc: nhiều trình duyệt không mở được hai camera cùng lúc
    cams[vId] = cams[vId] || new (A().Cam)($(vId));
    cams[vId].start(sel.value || undefined).then(function () { return refresh(); })
      .then(function () { $('camMsg').textContent = ''; }).catch(function (e) { $('camMsg').textContent = e.message || String(e); });
  }

  function loadServer() {
    return A().api('/api/cameras').then(function (c) {
      $('srcDoor').value = (c.door && c.door.source) || ''; $('lblDoor').value = (c.door && c.door.label) || '';
      $('srcRoom').value = (c.room && c.room.source) || ''; $('lblRoom').value = (c.room && c.room.label) || '';
    }).catch(A().fail);
  }

  function bind() {
    if (bound) return; bound = true;
    $('camPerm').onclick = function () {
      stopAll();
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { $('camMsg').textContent = 'Trình duyệt không cho dùng camera: mở trang qua HTTPS hoặc localhost.'; return; }
      navigator.mediaDevices.getUserMedia({ video: true, audio: false }).then(function (s) {
        s.getTracks().forEach(function (t) { t.stop(); }); return refresh();
      }).then(function () { $('camMsg').textContent = 'Đã cập nhật danh sách.'; }).catch(function (e) { $('camMsg').textContent = 'Không được cấp quyền camera: ' + (e.message || e); });
    };
    Array.prototype.forEach.call(document.querySelectorAll('button.pv'), function (b) { b.onclick = function () { preview(b.dataset.for, b.dataset.v); }; });
    $('camSave').onclick = function () {
      A().api('/api/cameras', { json: { door: { source: $('srcDoor').value, label: $('lblDoor').value }, room: { source: $('srcRoom').value, label: $('lblRoom').value } } })
        .then(function () { $('camSaveMsg').textContent = 'Đã lưu.'; A().toast('Đã lưu nguồn camera.'); }).catch(A().fail);
    };
  }

  window.CamerasPage = { init: function () { bind(); refresh(); loadServer(); }, stop: stopAll };
})();
