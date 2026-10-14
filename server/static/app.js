/* Giao diện quản trị: vanilla JS, không cần build. Logic HUD nằm ở guide.js. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var G = window.Guide;
  var state = { members: [], timers: {}, cams: {} };

  // ------------------------------------------------------------------ tiện ích
  function tok() { try { return localStorage.getItem('apiToken') || ''; } catch (e) { return ''; } }
  function toast(msg, bad) {
    var d = document.createElement('div'); d.textContent = msg; if (bad) d.className = 'bad';
    $('toast').appendChild(d); setTimeout(function () { d.remove(); }, bad ? 6000 : 3000);
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function apiBase() {
    var b = ''; try { b = localStorage.getItem('apiBase') || ''; } catch (e) { /* */ }
    b = b || ((window.APP_CONFIG || {}).apiBase || '');
    return b.replace(/\/+$/, '');
  }
  function api(path, o) {
    o = o || {};
    var h = Object.assign({ 'X-API-Token': tok() }, o.headers || {});
    var body = o.body;
    if (o.json !== undefined) { body = JSON.stringify(o.json); h['Content-Type'] = 'application/json'; }
    return fetch(apiBase() + path, { method: o.method || (body ? 'POST' : 'GET'), headers: h, body: body }).then(function (r) {
      if (r.status === 401 || r.status === 403) { $('conn').className = 'dot bad'; return r.json().catch(function () { return {}; }).then(function (j) { throw new Error(j.detail || 'Sai hoặc thiếu API token (bấm nút Token).'); }); }
      if (o.raw) return r;
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : (j.detail ? JSON.stringify(j.detail) : 'Lỗi ' + r.status));
        return j;
      });
    });
  }
  function fail(e) { toast(e.message || String(e), true); }
  function fmtT(iso) { return iso ? iso.slice(11, 16) : ''; }
  function every(name, fn, ms) { clearInterval(state.timers[name]); fn(); state.timers[name] = setInterval(fn, ms); }
  function clearTimer(name) { clearInterval(state.timers[name]); }

  // ------------------------------------------------------------------ camera
  function Cam(video) { this.v = video; this.stream = null; this.c = document.createElement('canvas'); }
  Cam.prototype.start = function (deviceId) {
    var self = this; this.stop();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
      return Promise.reject(new Error('Trình duyệt không cho dùng camera: cần mở trang qua HTTPS hoặc localhost.'));
    var c = { video: deviceId ? { deviceId: { exact: deviceId }, width: { ideal: 1280 } } : { width: { ideal: 1280 }, facingMode: 'user' }, audio: false };
    return navigator.mediaDevices.getUserMedia(c).then(function (s) {
      self.stream = s; self.v.srcObject = s; self.v.classList.add('mirror');
      return self.v.play().then(function () { return new Promise(function (ok) { if (self.v.videoWidth) ok(); else self.v.onloadedmetadata = ok; }); });
    });
  };
  Cam.prototype.stop = function () {
    if (this.stream) this.stream.getTracks().forEach(function (t) { t.stop(); });
    this.stream = null; this.v.srcObject = null;
  };
  Cam.prototype.on = function () { return !!this.stream && this.v.videoWidth > 0; };
  Cam.prototype.frame = function (maxW, q) {
    var v = this.v, w = v.videoWidth, h = v.videoHeight, s = Math.min(1, maxW / w);
    this.c.width = Math.round(w * s); this.c.height = Math.round(h * s);
    this.c.getContext('2d').drawImage(v, 0, 0, this.c.width, this.c.height);
    var c = this.c;
    return new Promise(function (ok) { c.toBlob(ok, 'image/jpeg', q || 0.85); });
  };
  // Camera đã chọn cho từng vai trò (enroll/door/lab) lưu ở trình duyệt: { role: {id, label} }
  function camPrefs() { try { return JSON.parse(localStorage.getItem('camPrefs') || '{}') || {}; } catch (e) { return {}; } }
  function setCamPref(role, id, label) { var p = camPrefs(); p[role] = { id: id, label: label }; try { localStorage.setItem('camPrefs', JSON.stringify(p)); } catch (e) { /* */ } }
  function fillDevices(sel) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return Promise.resolve();
    var role = sel.dataset && sel.dataset.role;
    return navigator.mediaDevices.enumerateDevices().then(function (ds) {
      var cur = sel.value, pref = role ? camPrefs()[role] : null; sel.innerHTML = '<option value="">Mặc định</option>';
      ds.filter(function (d) { return d.kind === 'videoinput'; }).forEach(function (d, i) {
        var o = document.createElement('option'); o.value = d.deviceId; o.textContent = d.label || ('Camera ' + (i + 1)); sel.appendChild(o);
      });
      var want = cur;
      if (!want && pref) {   // deviceId có thể đổi giữa các lần cấp quyền: thử theo id, rồi theo tên
        var opts = Array.prototype.slice.call(sel.options);
        var hit = opts.filter(function (o) { return o.value && o.value === pref.id; })[0] || opts.filter(function (o) { return o.value && pref.label && o.textContent === pref.label; })[0];
        want = hit ? hit.value : '';
      }
      sel.value = want;
      if (!sel.value) sel.value = '';
      if (role && !sel._bound) { sel._bound = true; sel.addEventListener('change', function () { var o = sel.options[sel.selectedIndex]; setCamPref(role, sel.value, sel.value ? o.textContent : ''); }); }
    }).catch(function () {});
  }
  function fit(canvas, video) {   // canvas phủ cùng khung nhìn với video
    var w = video.videoWidth || video.naturalWidth || 640, h = video.videoHeight || video.naturalHeight || 480;
    if (canvas.width !== w) canvas.width = w; if (canvas.height !== h) canvas.height = h;
    return canvas.getContext('2d');
  }
  function mirrorStage(canvas, on) { canvas.parentNode.classList.toggle('mirror', on); }

  // ------------------------------------------------------------------ điều hướng
  var pages = ['status', 'members', 'enroll', 'import', 'lab', 'door', 'shifts', 'cameras', 'settings'];
  function route() {
    var p = (location.hash || '#status').slice(1); if (pages.indexOf(p) < 0) p = 'status';
    pages.forEach(function (n) { $('page-' + n).classList.toggle('on', n === p); });
    Array.prototype.forEach.call(document.querySelectorAll('#nav a'), function (a) { a.classList.toggle('on', a.getAttribute('href') === '#' + p); });
    var more = document.querySelector('#nav details.more'); if (more) { more.open = false; more.classList.toggle('on', p === 'lab' || p === 'door'); }
    ['status', 'labLoop', 'doorLoop'].forEach(clearTimer);
    stopCams();
    if (p === 'status') every('status', loadStatus, 5000);
    if (p === 'members') loadMembers();
    if (p === 'enroll' && window.EnrollPage) { loadMembers().then(function () { window.EnrollPage.init(state.enrollFor); }); }
    if (p === 'import' && window.ImportPage) window.ImportPage.init();
    if (p === 'lab') fillDevices($('lDevice'));
    if (p === 'door') fillDevices($('dDevice'));
    if (p === 'cameras' && window.CamerasPage) window.CamerasPage.init();
    if (p === 'shifts') { loadMembers().then(fillShiftMembers); loadShifts(); }
    if (p === 'settings') { loadSettings(); loadCalibration(); }
  }
  function stopCams() { Object.keys(state.cams).forEach(function (k) { state.cams[k].stop(); }); stopAll(); }
  function stopAll() { clearTimer('labLoop'); clearTimer('doorLoop'); labRun = false; doorRun = false; if (window.EnrollPage) window.EnrollPage.stop(); if (window.CamerasPage) window.CamerasPage.stop(); }

  // ------------------------------------------------------------------ tổng quan
  function loadStatus() {
    api('/api/status').then(function (s) {
      $('conn').className = 'dot ok';
      var room = s.room || {};
      $('stRoom').textContent = room.persons != null ? room.persons : '–';
      $('stRoomSub').textContent = room.persons != null ? ('nhận ra ' + ((room.identified || []).length) + ', người lạ ' + (room.strangers || 0) + (room.ts ? ' · ' + fmtT(room.ts) : '')) : 'chưa có cập nhật từ cam trần';
      $('stOpen').textContent = s.open ? 'Đang hoạt động' : 'Ngoài giờ'; $('stOpen').style.fontSize = '22px';
      $('stEngine').textContent = s.engine.model + ' · ' + s.engine.providers[0].replace('ExecutionProvider', '') + ' · giờ ' + s.settings.open_hour + '–' + s.settings.close_hour;
      $('stCounts').textContent = s.counts.members + ' / ' + s.counts.embeddings;
      $('stPeople').innerHTML = s.people.length ? s.people.map(function (p) {
        return '<div><span>' + esc(p.name) + (p.on_shift ? ' <span class="tag ok">đang trực</span>' : '') + '</span><span>' +
          (p.status === 'AWAY' ? '<span class="tag warn">vắng từ ' + fmtT(p.since) + '</span>' : '<span class="tag ok">có mặt</span>') + '</span></div>';
      }).join('') : '<div class="small">Chưa có ai.</div>';
      $('stShifts').innerHTML = s.shifts.length ? s.shifts.map(function (x) {
        var ab = x.absences.map(function (a) { return fmtT(a.from) + '–' + fmtT(a.to) + ' (' + Math.round(a.minutes) + ' ph)'; }).join(', ');
        return '<div><span>' + esc(x.name) + ' · ' + fmtT(x.start) + '–' + fmtT(x.end) + (ab ? '<br><small>Vắng: ' + ab + '</small>' : '') +
          '</span><span class="tag ' + (x.state === 'missed' ? 'bad' : x.state === 'active' ? 'ok' : '') + '">' + esc(x.state) + '</span></div>';
      }).join('') : '<div class="small">Không có ca nào hôm nay.</div>';
      $('hDb').textContent = (s.engine && s.engine.db === 'postgres') ? 'Postgres đám mây' : 'SQLite trên máy chủ';
      loadHistory();
    }).catch(function (e) { $('conn').className = 'dot bad'; fail(e); });
  }

  // ------------------------------------------------------------------ lịch sử & cảnh báo
  var evLabels = { checkin: 'check-in', return: 'quay lại', checkout: 'check-out', away: 'rời phòng / vắng mặt', left: 'đã rời CLB', back: 'quay lại',
    seen_without_checkin: 'thấy trong phòng nhưng chưa check-in', alert_unknown_door: 'NGƯỜI LẠ ở cửa', alert_stranger_room: 'NGƯỜI LẠ trong phòng' };
  function loadHistory() {
    var q = '?category=' + encodeURIComponent($('hCat').value) + '&limit=60' + ($('hDay').value ? '&day=' + $('hDay').value : '');
    return api('/api/events' + q).then(function (r) {
      $('stEvents').innerHTML = r.events.map(function (e) {
        var who = e.name ? esc(e.name) + ' · ' : '';
        return '<div><span>' + (e.alert ? '<span class="tag bad">cảnh báo</span> ' : '') + who + esc(evLabels[e.kind] || e.kind) + (e.detail ? '<br><small>' + esc(e.detail) + '</small>' : '') +
          '</span><span>' + e.ts.slice(5, 16).replace('T', ' ') + '</span></div>';
      }).join('') || '<div>Chưa có mục nào.</div>';
    }).catch(function () {});
  }

  // ------------------------------------------------------------------ thành viên
  var CLUB = ['front', 'left', 'right', 'up', 'down'];
  function clubChips(m) {
    return CLUB.map(function (d) {
      var n = (m.club || {})[d] || 0, ok = n >= 2;
      return '<span class="chip ' + (ok ? 'ok' : 'low') + '" title="' + esc(G.CLUB_LABELS[d]) + '">' + esc(G.CLUB_SHORT[d]) + ' <b>' + n + '</b></span>';
    }).join('');
  }
  function memberCard(m) {
    var pct = Math.round((m.progress || 0) * 100), miss = (m.club_missing || []).map(function (d) { return G.CLUB_LABELS[d]; });
    var status = m.complete ? '<span class="ok-text">Đủ mẫu</span>' : (m.real === 0 ? '<span class="bad-text">Chưa đăng ký</span>' : '<span class="warn-text">Cần bổ sung' + (miss.length ? ': ' + esc(miss.join(', ')) : '') + '</span>');
    return '<div class="panel member"><div><h4>' + esc(m.name) + ' <small class="small">(' + esc(m.member_id) + ')</small></h4>' +
      '<div class="prog"><div style="width:' + pct + '%"></div></div>' +
      '<div class="small"><b>' + m.real + '</b> / ' + m.target + ' mẫu gốc · ' + status + '</div>' +
      '<div class="chips">' + clubChips(m) + '</div>' +
      ((m.flips || m.aug) ? '<div class="small muted">+ ' + m.flips + ' bản lật' + (m.aug ? ', ' + m.aug + ' bản augmentation' : '') + ' (không tính vào tiến độ)</div>' : '') + '</div>' +
      '<div class="row"><button class="primary" data-enroll="' + esc(m.member_id) + '">' + (m.real ? 'Đăng ký thêm' : 'Đăng ký') + '</button>' +
      '<button class="ghost" data-clear="' + esc(m.member_id) + '">Xoá mẫu mặt</button>' +
      '<button class="ghost" data-del="' + esc(m.member_id) + '">Xoá người</button></div></div>';
  }
  function loadMembers() {
    return api('/api/members').then(function (r) {
      state.members = r.members;
      if ($('page-members').classList.contains('on')) {
        var list = r.members.slice().sort(function (a, b) { return (a.complete - b.complete) || ((a.progress || 0) - (b.progress || 0)) || a.name.localeCompare(b.name); });
        var full = list.filter(function (m) { return m.complete; }).length;
        $('memberList').innerHTML = list.map(memberCard).join('') || '<div class="panel">Chưa có thành viên.</div>';
        $('memberSummary').innerHTML = '<b>' + r.members.length + '</b> thành viên · <b>' + full + '</b> đủ mẫu · <b>' + (r.members.length - full) + '</b> cần đăng ký/bổ sung (hiện ở đầu danh sách).';
      }
      return r.members;
    }).catch(fail);
  }
  function memberOptions(sel, keep) {
    var cur = keep || sel.value;
    sel.innerHTML = state.members.map(function (m) { return '<option value="' + esc(m.member_id) + '">' + esc(m.name) + ' (' + esc(m.member_id) + ')</option>'; }).join('');
    if (cur) sel.value = cur;
  }
  function fillShiftMembers() { memberOptions($('sMember')); }

  function drawOverlay(canvas, video, r, faces, labels) {
    var x = fit(canvas, video), sx = canvas.width / r.w, sy = canvas.height / r.h;
    x.clearRect(0, 0, canvas.width, canvas.height); x.lineWidth = Math.max(2, canvas.width / 320); x.font = Math.round(canvas.width / 30) + 'px system-ui';
    faces.forEach(function (f, i) {
      var b = f.bbox, lab = labels ? labels[i] : null;
      x.strokeStyle = lab ? lab.color : '#38bdf8'; x.strokeRect(b[0] * sx, b[1] * sy, (b[2] - b[0]) * sx, (b[3] - b[1]) * sy);
      if (lab) {
        // chữ không bị lật vì canvas lật cùng video: vẽ ngược lại để đọc được
        x.save(); var tx = b[0] * sx, ty = Math.max(14, b[1] * sy - 6);
        if (canvas.parentNode.classList.contains('mirror')) { x.translate(tx + 0, ty); x.scale(-1, 1); x.textAlign = 'right'; } else { x.translate(tx, ty); x.textAlign = 'left'; }
        x.fillStyle = lab.color; x.fillText(lab.text, 0, 0); x.restore();
      }
    });
  }
  // ------------------------------------------------------------------ thử nhận diện
  var labRun = false, lcam = null, labBusy = false;
  state.cams.lab = { stop: function () { if (lcam) lcam.stop(); } };
  function labColor(f) { return f.member_id ? '#22c55e' : (f.reason === 'low_margin' || (f.best_id && f.score > 0.25)) ? '#f59e0b' : '#ef4444'; }
  function labShow(r, labelsOnly) {
    var faces = r.faces || [];
    var labels = faces.map(function (f) {
      return { color: labColor(f), text: (f.member_id ? f.name : (f.best_name ? '? ' + f.best_name : 'Lạ')) + ' ' + (f.score != null ? f.score.toFixed(2) : '') };
    });
    var src = $('lSource').value === 'cam' ? $('lVideo') : $('lImg');
    drawOverlay($('lOverlay'), src, r, faces, labels);
    var reasons = { ok: 'nhận ra', low_score: 'điểm thấp', low_margin: 'chưa phân biệt được với người khác', empty_gallery: 'chưa có dữ liệu' };
    $('lList').innerHTML = faces.map(function (f) {
      return '<div><span><b>' + esc(f.member_id ? f.name : (f.best_name ? 'giống ' + f.best_name : 'không rõ')) + '</b><br><small>' + esc(reasons[f.reason] || f.reason) +
        ' · điểm ' + f.score + ' (ngưỡng ' + f.threshold + ', lệch ' + f.margin + ' ≥ ' + f.margin_required + ')<br>pitch ' + f.pitch + '° · yaw ' + f.yaw + '° · rộng ' + f.width + 'px' +
        (f.high_angle ? ' · <b>góc cao/nghiêng</b>' : '') + '</small></span></div>';
    }).join('') || '<div class="small">Không thấy mặt.</div>';
  }
  function labPost(blob, stranger) {
    var fd = new FormData(); fd.append('file', blob, 'f.jpg'); var ctxs = $('lContext').value; fd.append('context', ctxs);
    if (stranger) fd.append('stranger', 'true');
    var rec = $('lRecord').checked && ctxs === 'room' && !stranger;
    if (rec) { fd = new FormData(); fd.append('file', blob, 'f.jpg'); }
    return api(rec ? '/api/room/frame' : '/api/recognize', { body: fd }).then(function (r) { if (!r.w && lcam && lcam.v.videoWidth) { r.w = lcam.v.videoWidth; r.h = lcam.v.videoHeight; } return r; });
  }
  function startLab() {
    stopAll(); if (lcam) lcam.stop();
    if ($('lSource').value === 'img') { $('lFile').click(); return; }
    $('lVideo').classList.remove('hidden'); $('lImg').classList.add('hidden');
    lcam = lcam || new Cam($('lVideo')); state.cams.lab = lcam;
    lcam.start($('lDevice').value).then(function () {
      fillDevices($('lDevice')); labRun = true; $('lOverlay').parentNode.classList.add('mirror');
      every('labLoop', function () {
        if (!labRun || labBusy || !lcam.on()) return; labBusy = true;
        lcam.frame($('lContext').value === 'room' ? 960 : 640, 0.85).then(function (b) { return labPost(b, false); }).then(function (r) {
          r.w = r.w || lcam.v.videoWidth; r.h = r.h || lcam.v.videoHeight; labShow(r);
        }).catch(fail).then(function () { labBusy = false; });
      }, 700);
    }).catch(fail);
  }
  function labFromFile(file) {
    $('lVideo').classList.add('hidden'); $('lImg').classList.remove('hidden'); $('lOverlay').parentNode.classList.remove('mirror');
    var img = $('lImg'); img.onload = function () {
      labPost(file, false).then(function (r) { labShow(r); }).catch(fail);
    };
    img.src = URL.createObjectURL(file);
  }

  // ------------------------------------------------------------------ thử check-in
  var doorRun = false, dcam = null, trig = null;
  state.cams.door = { stop: function () { if (dcam) dcam.stop(); } };
  function dBanner(t, cls) { $('dBanner').textContent = t; $('dBanner').className = 'banner ' + (cls || ''); }
  function startDoor() {
    stopAll(); dcam = dcam || new Cam($('dVideo')); state.cams.door = dcam; trig = new G.DoorTrigger({ minWidth: 90 });
    dcam.start($('dDevice').value).then(function () {
      fillDevices($('dDevice')); doorRun = true; $('dOverlay').parentNode.classList.add('mirror'); var busy = false;
      var names = { idle: 'Chờ có người đến…', far: 'Hãy lại gần hơn', multi: 'Một người một lần', turned: 'Nhìn thẳng vào camera', arming: 'Giữ yên…', cooldown: 'Nghỉ giữa các lần' };
      every('doorLoop', function () {
        if (!doorRun || busy || !dcam.on()) return; busy = true;
        dcam.frame(480, 0.7).then(function (b) { var fd = new FormData(); fd.append('file', b, 'f.jpg'); fd.append('size', '320'); return api('/api/pose', { body: fd }); }).then(function (r) {
          var faces = r.faces || [], f = faces[0] || null; drawOverlay($('dOverlay'), $('dVideo'), r, faces);
          var t = trig.update(f, faces.length, performance.now());
          $('dProg').style.width = Math.round((t.progress || 0) * 100) + '%';
          $('dState').textContent = (names[t.state] || t.state) + (t.left ? ' (' + Math.ceil(t.left / 1000) + 's)' : '');
          if (t.state !== 'fire') return;
          dBanner('Đang nhận diện…', '');
          var shots = []; var i = 0;
          return (function nx() { if (i++ >= 4) return Promise.resolve(); return dcam.frame(640, 0.9).then(function (bl) { shots.push(bl); return new Promise(function (k) { setTimeout(k, 150); }); }).then(nx); })()
            .then(function () { var fd = new FormData(); shots.forEach(function (s, k) { fd.append('files', s, 'f' + k + '.jpg'); }); return api('/api/checkin', { body: fd }); })
            .then(function (res) {
              trig.result(res.status === 'checkin' ? 'checkin' : res.status, performance.now());
              var msg = { checkin: 'Chào ' + res.name + '! Đã check-in ' + fmtT(res.time) + (res.on_shift ? ' (đang trong ca trực)' : ''),
                already: res.name ? res.name + ' đã check-in rồi' : 'Đã check-in rồi', unknown: 'Không nhận ra bạn — thử lại, nhìn thẳng và đủ sáng',
                no_usable_face: 'Chưa có mặt đủ rõ — lại gần/nhìn thẳng' };
              dBanner(msg[res.status] || res.status, res.status === 'checkin' ? 'ok' : (res.status === 'already' ? '' : 'warn'));
              $('dResult').insertAdjacentHTML('afterbegin', '<div><span>' + esc(new Date().toLocaleTimeString()) + ' · <b>' + esc(res.status) + '</b> ' + esc(res.name || '') +
                '<br><small>' + esc(JSON.stringify((res.frames || []).map(function (x) { return x.reason + (x.score != null ? ':' + x.score : ''); }))) + '</small></span></div>');
            });
        }).catch(fail).then(function () { busy = false; });
      }, 400);
    }).catch(fail);
  }

  // ------------------------------------------------------------------ ca trực & báo cáo
  function today() { var d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  function loadShifts() {
    var day = $('rDate').value || today(); $('rDate').value = day; if (!$('sDate').value) $('sDate').value = day;
    Promise.all([api('/api/shifts?day=' + day), api('/api/report?day=' + day)]).then(function (a) {
      var sh = a[0].shifts, rep = a[1], byKey = {}; rep.shifts.forEach(function (r) { byKey[r.member_id + r.shift[0]] = r; });
      $('rTable').innerHTML = '<table><tr><th>Thành viên</th><th>Ca</th><th>Trạng thái</th><th>Vắng mặt trong ca</th><th></th></tr>' + (sh.map(function (s) {
        var r = byKey[s.member_id + fmtT(s.start)] || { absences: [], total_minutes: 0 };
        var ab = r.absences.map(function (x) { return x.from + '–' + x.to + ' (' + Math.round(x.minutes) + ' ph)'; }).join('<br>') || '—';
        return '<tr><td>' + esc(s.name) + '</td><td>' + fmtT(s.start) + '–' + fmtT(s.end) + '</td><td><span class="tag">' + esc(s.state) + '</span></td><td>' + ab +
          (r.total_minutes ? '<br><b>Tổng ' + r.total_minutes + ' ph</b>' : '') + '</td><td><button class="ghost" data-delshift="' + s.id + '">Xoá</button></td></tr>';
      }).join('') || '<tr><td colspan="5" class="small">Không có ca nào.</td></tr>') + '</table>';
      $('rOcc').textContent = 'Đang trong phòng: ' + (rep.occupants_now.join(', ') || 'không ai');
    }).catch(fail);
  }

  // ------------------------------------------------------------------ cài đặt & hiệu chỉnh
  var calib = null, spec = null;
  function loadSettings() {
    api('/api/settings').then(function (r) {
      spec = r.spec;
      $('fSettings').innerHTML = Object.keys(spec).map(function (k) {
        var s = spec[k], step = s.type === 'int' ? 1 : 0.01;
        return '<div class="setrow"><label for="set_' + k + '">' + k + '</label><input id="set_' + k + '" data-k="' + k + '" type="number" step="' + step + '" min="' + s.min + '" max="' + s.max + '" value="' + r.values[k] + '"><small>' + esc(s.help) + '</small></div>';
      }).join('');
    }).catch(fail);
  }
  function loadCalibration() {
    api('/api/calibration').then(function (c) {
      calib = c; var cur = c.current || {}, sg = c.suggestion;
      var st = function (s) { return s ? 'min ' + s.min + ' · p5 ' + s.p5 + ' · trung vị ' + s.median + ' · max ' + s.max + ' (n=' + s.n + ')' : 'chưa có'; };
      $('cSummary').innerHTML = '<div class="small">' + c.members + ' người · ' + c.embeddings + ' mẫu · ' + c.strangers + ' mẫu người lạ</div>' +
        '<div class="small">Cùng người: ' + st(c.genuine) + '<br>Khác người/người lạ: ' + st(c.impostor) + '</div>' +
        '<div>Hiện tại: cửa <b>' + cur.door_threshold + '</b> · cam trần <b>' + cur.room_threshold + '</b> · góc cao <b>' + cur.room_threshold_high + '</b></div>' +
        (sg ? '<div>Đề xuất: cửa <b>' + sg.door_threshold + '</b> · cam trần <b>' + sg.room_threshold + '</b> · góc cao <b>' + sg.room_threshold_high + '</b></div>' : '');
      $('cApply').disabled = !sg;
      $('cWarn').innerHTML = (c.warnings || []).map(function (w) { return '<div>⚠ ' + esc(w) + '</div>'; }).join('');
      $('cView').innerHTML = '<b>Điểm giống theo góc nhìn</b> (so với ảnh thẳng):<br>' + (c.by_view || []).map(function (v) { return esc(v.label) + ': ' + (v.stats ? 'trung vị ' + v.stats.median + ', min ' + v.stats.min + ' (n=' + v.stats.n + ')' : '—'); }).join('<br>');
      drawHist(c);
    }).catch(fail);
  }
  function drawHist(c) {
    var cv = $('cHist'), x = cv.getContext('2d'), W = cv.width, H = cv.height; x.clearRect(0, 0, W, H);
    var g = c.hist && c.hist.genuine, im = c.hist && c.hist.impostor, any = g || im; if (!any) return;
    var bins = any.bins, mx = Math.max.apply(null, (g ? g.counts : [0]).concat(im ? im.counts : [0]).concat([1])), bw = (W - 20) / bins;
    function bars(h, col) { if (!h) return; x.fillStyle = col; h.counts.forEach(function (n, i) { var hh = (H - 30) * n / mx; x.fillRect(10 + i * bw + 1, H - 20 - hh, bw - 2, hh); }); }
    bars(im, '#ef444488'); bars(g, '#22c55e88');
    var lo = any.lo, hi = any.hi, px = function (v) { return 10 + (v - lo) / (hi - lo) * (W - 20); };
    x.fillStyle = getComputedStyle(document.body).color; x.font = '11px system-ui';
    for (var v = 0; v <= 1; v += 0.2) { x.fillText(v.toFixed(1), px(v) - 8, H - 6); }
    [['door_threshold', '#2563eb'], ['room_threshold_high', '#d97706']].forEach(function (p) {
      var t = (c.current || {})[p[0]]; if (t == null) return; x.strokeStyle = p[1]; x.lineWidth = 2; x.beginPath(); x.moveTo(px(t), 4); x.lineTo(px(t), H - 20); x.stroke();
    });
    x.fillText('xanh lá: cùng người · đỏ: khác người/người lạ · xanh dương: ngưỡng cửa · cam: ngưỡng góc cao', 10, 12);
  }

  // ------------------------------------------------------------------ sự kiện giao diện
  function bind() {
    window.addEventListener('hashchange', route);
    $('btnToken').onclick = function () { $('tokenInput').value = tok(); $('dlgToken').showModal(); };
    $('dlgToken').addEventListener('close', function () { var v = $('tokenInput').value.trim(); if (v) { try { localStorage.setItem('apiToken', v); } catch (e) { toast('Không lưu được token trong trình duyệt.', true); } } route(); });
    $('fMember').onsubmit = function (e) {
      e.preventDefault();
      api('/api/members', { json: { member_id: $('mId').value.trim(), name: $('mName').value.trim() } }).then(function () { toast('Đã lưu thành viên.'); $('fMember').reset(); loadMembers(); }).catch(fail);
    };
    $('memberList').onclick = function (e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.enroll) { state.enrollFor = b.dataset.enroll; location.hash = '#enroll'; }
      if (b.dataset.clear && confirm('Xoá toàn bộ mẫu mặt của người này?')) api('/api/members/' + encodeURIComponent(b.dataset.clear) + '/embeddings', { method: 'DELETE' }).then(loadMembers).catch(fail);
      if (b.dataset.del && confirm('Xoá thành viên và mọi ca trực của họ?')) api('/api/members/' + encodeURIComponent(b.dataset.del), { method: 'DELETE' }).then(loadMembers).catch(fail);
    };
    $('lStart').onclick = startLab; $('lStop').onclick = function () { labRun = false; clearTimer('labLoop'); if (lcam) lcam.stop(); };
    $('lSource').onchange = function () { stopAll(); };
    $('lFile').onchange = function () { if ($('lFile').files[0]) labFromFile($('lFile').files[0]); };
    $('lStranger').onclick = function () {
      if (!confirm('Lưu các mặt đang trong khung thành mẫu "người lạ" (người KHÔNG đăng ký)? Chỉ làm khi đúng như vậy.')) return;
      var p = $('lSource').value === 'cam' ? (lcam && lcam.on() ? lcam.frame(960, 0.9) : Promise.reject(new Error('Bật webcam trước.'))) : Promise.resolve($('lFile').files[0]);
      p.then(function (b) { return labPost(b, true); }).then(function (r) { toast('Đã lưu ' + (r.stranger_saved || 0) + ' mẫu người lạ.'); }).catch(fail);
    };
    $('dStart').onclick = startDoor; $('dStop').onclick = function () { doorRun = false; clearTimer('doorLoop'); if (dcam) dcam.stop(); dBanner('Đã tắt'); };
    $('rDate').onchange = loadShifts;
    $('fShift').onsubmit = function (e) {
      e.preventDefault(); var d = $('sDate').value;
      api('/api/shifts', { json: { member_id: $('sMember').value, start: d + 'T' + $('sStart').value + ':00', end: d + 'T' + $('sEnd').value + ':00' } })
        .then(function () { toast('Đã thêm ca.'); $('rDate').value = d; loadShifts(); }).catch(fail);
    };
    $('rTable').onclick = function (e) {
      var b = e.target.closest('[data-delshift]'); if (b && confirm('Xoá ca này?')) api('/api/shifts/' + b.dataset.delshift, { method: 'DELETE' }).then(loadShifts).catch(fail);
    };
    $('rCsv').onclick = function () {
      api('/api/report.csv?day=' + ($('rDate').value || today()), { raw: true }).then(function (r) { return r.blob(); }).then(function (b) {
        var a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'bao-cao-' + ($('rDate').value || today()) + '.csv'; a.click();
      }).catch(fail);
    };
    $('hCat').onchange = loadHistory; $('hDay').onchange = loadHistory;
    $('apiBase').value = (function () { try { return localStorage.getItem('apiBase') || ''; } catch (e) { return ''; } })();
    $('apiBaseSave').onclick = function () { try { localStorage.setItem('apiBase', $('apiBase').value.trim()); toast('Đã lưu địa chỉ server.'); } catch (e) { fail(e); } };
    $('apiPing').onclick = function () {
      var t0 = performance.now(); $('apiPingOut').textContent = 'Đang kiểm tra…';
      fetch(apiBase() + '/api/health').then(function (r) { return r.json(); }).then(function (h) {
        $('apiPingOut').textContent = 'Kết nối được (' + Math.round(performance.now() - t0) + ' ms). Model ' + h.model + ', ' + h.members + ' người, ' + h.embeddings + ' mẫu.';
        return api('/api/status').then(function () { $('apiPingOut').textContent += ' Token hợp lệ.'; });
      }).catch(function (e) { $('apiPingOut').textContent = 'Lỗi: ' + (e.message || e) + ' (nếu UI và server khác tên miền, server cần CORS_ORIGINS).'; });
    };
    $('sSave').onclick = function (e) {
      e.preventDefault(); var v = {}; Array.prototype.forEach.call($('fSettings').querySelectorAll('input'), function (i) { v[i.dataset.k] = i.value; });
      api('/api/settings', { json: v }).then(function () { toast('Đã lưu tham số.'); loadSettings(); loadCalibration(); }).catch(fail);
    };
    $('cApply').onclick = function () { if (calib && calib.suggestion) api('/api/settings', { json: calib.suggestion }).then(function () { toast('Đã áp dụng.'); loadSettings(); loadCalibration(); }).catch(fail); };
    $('cClear').onclick = function () { if (confirm('Xoá toàn bộ mẫu người lạ?')) api('/api/strangers', { method: 'DELETE' }).then(loadCalibration).catch(fail); };
    $('bBackup').onclick = function (e) {
      e.preventDefault(); api('/api/backup', { raw: true }).then(function (r) { return r.blob(); }).then(function (b) { var a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'club-backup.db'; a.click(); }).catch(fail);
    };
  }
  bind();
  // Chế độ chỉ thu thập khuôn mặt (APP_MODE=enroll): ẩn các mục chưa dùng
  fetch(apiBase() + '/api/health').then(function (r) { return r.json(); }).then(function (h) {
    if (h.mode !== 'enroll') return;
    ['#shifts', '#cameras'].forEach(function (x) { var a = document.querySelector('#nav a[href="' + x + '"]'); if (a) a.style.display = 'none'; });
    var m = document.querySelector('#nav details.more'); if (m) m.style.display = 'none';
    var b = document.querySelector('.brand'); if (b) b.textContent = 'Điểm danh CLB · giai đoạn thu thập khuôn mặt';
  }).catch(function () {});
  if (!tok()) { try { $('dlgToken').showModal(); } catch (e) { /* */ } } else route();
  window.__app = { camPrefs: camPrefs, setCamPref: setCamPref, Cam: Cam, fillDevices: fillDevices, memberOptions: memberOptions, route: route, api: api, toast: toast, fail: fail, esc: esc, loadMembers: loadMembers, state: state };
})();
