/* Trang "Đăng ký mặt" kiểu CLB: một màn hình, 5 chặng tự chạy, chụp liên tục, chọn 20–30 mẫu ở server.
 * Không thư viện, không bước build. Logic chặng nằm ở guide.js (ClubScan, kiểm thử bằng Node). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var A = function () { return window.__app; };
  var G = function () { return window.Guide; };
  var ARROWS = { '-1,0': '←', '1,0': '→', '0,-1': '↑', '0,1': '↓', '-1,-1': '↖', '1,-1': '↗', '-1,1': '↙', '1,1': '↘' };
  var SEND_W = 560, SEND_Q = 0.75, TIMEOUT_MS = 12000;

  var S = { running: false, busy: false, sid: null, scan: null, cam: null, member: null, last: null, thumbs: {}, thumbDir: {},
            report: null, saved: null, token: 0, dirty: false, dirtyDraw: false, mode: 'add' };

  function show(which) {
    ['enSetup', 'enStage', 'enResult'].forEach(function (id) { $(id).classList.toggle('hidden', id !== which); });
  }
  function speak(t) {
    if (!$('eVoice').checked || !window.speechSynthesis) return;
    if (speak.last === t) return; speak.last = t;
    try { speechSynthesis.cancel(); var u = new SpeechSynthesisUtterance(t); u.lang = 'vi-VN'; speechSynthesis.speak(u); } catch (e) { /* tuỳ chọn */ }
  }
  function camError(e) {
    var n = e && e.name;
    if (n === 'NotAllowedError' || n === 'SecurityError') return 'Chưa cho phép dùng camera: bấm biểu tượng ổ khoá cạnh thanh địa chỉ, chọn "Cho phép" camera rồi bấm Bắt đầu lại.';
    if (n === 'NotFoundError' || n === 'OverconstrainedError') return 'Không tìm thấy camera: cắm webcam hoặc chọn camera khác trong mục Nâng cao.';
    if (n === 'NotReadableError') return 'Camera đang được ứng dụng khác dùng: đóng Zoom/Meet/ứng dụng camera rồi thử lại.';
    return (e && e.message) || 'Không mở được camera.';
  }

  // ---------------------------------------------------------------- màn hình chọn người
  function stats(m) { return m ? m.real + '/' + m.target + ' mẫu gốc' + (m.complete ? ' · đủ' : (m.club_missing.length ? ' · thiếu ' + m.club_missing.map(function (d) { return G().CLUB_SHORT[d]; }).join(', ') : '')) : ''; }
  function orderedMembers() {
    return A().state.members.slice().sort(function (a, b) { return (a.complete - b.complete) || ((a.progress || 0) - (b.progress || 0)) || a.name.localeCompare(b.name); });
  }
  function fillMembers(pre) {
    var sel = $('eMember'), list = orderedMembers(), cur = pre || sel.value;
    sel.innerHTML = list.map(function (m) { return '<option value="' + A().esc(m.member_id) + '">' + A().esc(m.name) + ' (' + A().esc(m.member_id) + ') — ' + A().esc(stats(m)) + '</option>'; }).join('');
    if (cur && list.some(function (m) { return m.member_id === cur; })) sel.value = cur;
    cover();
    $('eStart').disabled = !list.length;
    if (!list.length) $('eCover').innerHTML = 'Chưa có thành viên nào: tạo ở trang <a href="#members">Thành viên</a> trước.';
  }
  function cover() {
    var id = $('eMember').value, m = A().state.members.filter(function (x) { return x.member_id === id; })[0];
    if (!m) return;
    var pct = Math.round((m.progress || 0) * 100);
    $('eCover').innerHTML = '<div class="prog"><div style="width:' + pct + '%"></div></div>' + A().esc(m.name) + ': <b>' + m.real + '</b>/' + m.target + ' mẫu gốc' +
      (m.real ? '. Đăng ký lại sẽ <b>bổ sung</b> thêm mẫu mới.' : '. Chưa có mẫu nào.');
  }

  // ---------------------------------------------------------------- chips 5 chặng
  function renderChips() {
    var g = G(), sc = S.scan, C = 2 * Math.PI * 12;
    $('eChips').innerHTML = sc.order.map(function (d) {
      var st = sc.state[d], p = st === 'done' ? 1 : Math.min(1, sc.got[d] / sc.need(d));
      var cls = 'pchip' + (st === 'active' ? ' active' : '') + (st === 'done' ? ' done' : '') + (st === 'weak' ? ' weak' : '');
      return '<div class="' + cls + '"><svg viewBox="0 0 30 30"><circle class="bg" cx="15" cy="15" r="12"/><circle class="fg" cx="15" cy="15" r="12" stroke-dasharray="' + C.toFixed(1) +
        '" stroke-dashoffset="' + (C * (1 - p)).toFixed(1) + '"/></svg><span>' + g.CLUB_LABELS[d] + (st === 'weak' ? ' (yếu)' : '') + '</span></div>';
    }).join('');
    $('eBar').style.width = Math.round(sc.progress() * 100) + '%';
  }
  function instr(text, arrow, cls) {
    var k = arrow ? arrow.x + ',' + arrow.y : '';
    $('eArrow').textContent = ARROWS[k] || (cls === 'ok' ? '✓' : '•');
    $('eText').textContent = text;
    $('eInstr').className = 'instr ' + (cls || '');
    speak(text);
  }

  // ---------------------------------------------------------------- bắt khung hình
  var cv = null, ocv = null;
  function capture() {
    var v = S.cam.v, w = v.videoWidth, h = v.videoHeight;
    if (!w) return Promise.resolve(null);
    var sc = Math.min(1, SEND_W / w), cw = Math.round(w * sc), ch = Math.round(h * sc);
    if (window.OffscreenCanvas) {
      ocv = ocv || new OffscreenCanvas(cw, ch); if (ocv.width !== cw) { ocv.width = cw; ocv.height = ch; }
      ocv.getContext('2d').drawImage(v, 0, 0, cw, ch);
      return ocv.convertToBlob({ type: 'image/jpeg', quality: SEND_Q });
    }
    cv = cv || document.createElement('canvas'); cv.width = cw; cv.height = ch;
    cv.getContext('2d').drawImage(v, 0, 0, cw, ch);
    return new Promise(function (ok) { cv.toBlob(ok, 'image/jpeg', SEND_Q); });
  }
  function thumbOf(dirKey) {
    var v = S.cam.v, c = document.createElement('canvas'), n = 72, w = v.videoWidth, h = v.videoHeight, s = Math.min(w, h);
    var f = S.last && S.last.box ? S.last.box : null, sx = (w - s) / 2, sy = (h - s) / 2, sw = s;
    if (f) { var cx = (f[0] + f[2]) / 2 * w, cy = (f[1] + f[3]) / 2 * h, side = Math.max(f[2] - f[0], f[3] - f[1]) * w * 1.5; sw = Math.min(side, w, h); sx = Math.max(0, Math.min(w - sw, cx - sw / 2)); sy = Math.max(0, Math.min(h - sw, cy - sw / 2)); }
    c.width = c.height = n; c.getContext('2d').drawImage(v, sx, sy, sw, sw, 0, 0, n, n);
    return c.toDataURL('image/jpeg', 0.6);
  }
  function nextFrame(cb) {
    if (document.hidden) { setTimeout(function () { nextFrame(cb); }, 300); return; }
    var v = S.cam && S.cam.v;
    if (v && v.requestVideoFrameCallback) v.requestVideoFrameCallback(function () { cb(); });
    else setTimeout(cb, 60);
  }
  function loop(tok) {
    if (!S.running || tok !== S.token) return;
    nextFrame(function () {
      if (!S.running || tok !== S.token) return;
      if (S.busy) return loop(tok);
      S.busy = true;
      var thumb = null;
      capture().then(function (blob) {
        if (!blob) return null;
        var fd = new FormData(); fd.append('files', blob, 'f.jpg');
        var ctl = new AbortController(), to = setTimeout(function () { ctl.abort(); }, TIMEOUT_MS);
        return fetchFrames(fd, ctl).finally(function () { clearTimeout(to); });
      }).then(function (r) {
        S.busy = false;
        if (!r || tok !== S.token || !S.running) return;
        handle(r.results[0] || { state: 'no_face' }, r);
        loop(tok);
      }).catch(function (e) {
        S.busy = false;
        if (tok !== S.token || !S.running) return;
        if (e && /404|hết hạn/.test(e.message || '')) { return abort('Phiên đăng ký đã hết hạn. Bấm Bắt đầu để làm lại.'); }
        instr('Mất kết nối tới server, đang thử lại…', null, 'bad');
        setTimeout(function () { loop(tok); }, 1200);
      });
    });
  }
  function fetchFrames(fd, ctl) {
    var base = ''; try { base = localStorage.getItem('apiBase') || ''; } catch (e) { /* */ }
    base = (base || (window.APP_CONFIG || {}).apiBase || '').replace(/\/+$/, '');
    var tok = ''; try { tok = localStorage.getItem('apiToken') || ''; } catch (e) { /* */ }
    return fetch(base + '/api/enroll/session/' + S.sid + '/frames', { method: 'POST', headers: { 'X-API-Token': tok }, body: fd, signal: ctl.signal }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(r.status === 404 ? '404 hết hạn' : (typeof j.detail === 'string' ? j.detail : 'Lỗi ' + r.status));
        return j;
      });
    });
  }

  function handle(obs, resp) {
    S.last = obs; S.dirtyDraw = true;
    var sc = S.scan, now = performance.now(), d = sc.current();
    if (obs.kept && obs.fid != null) {
      S.thumbs[obs.fid] = thumbOf();
      var ks = Object.keys(S.thumbs); if (ks.length > 160) delete S.thumbs[ks[0]];      // giới hạn bộ nhớ ảnh nhỏ
    }
    var res = sc.update(obs, now);
    if (resp.warning) { $('eInstr').className = 'instr bad'; $('eText').textContent = resp.warning; }
    // ok nếu đang đúng hướng (dù kept hay chưa) — xanh lá để người biết tư thế đúng
    else if (!res.finished) instr(res.hint, res.arrow, obs.state === 'ok' && obs.dir === res.dir ? 'ok' : (G().CLUB_STATE_TEXT[obs.state] ? 'bad' : ''));
    $('eStageBox').classList.toggle('good', !!res.good);
    if (res.good) { var f = $('eFlash'); f.classList.add('on'); setTimeout(function () { f.classList.remove('on'); }, 70); }
    renderChips();
    if (res.advanced && !res.finished) {
      var nextDir = sc.current();
      speak('Chuyển sang: ' + G().CLUB_TEXT[nextDir]);
      instr('➡ Chuyển sang: ' + G().CLUB_LABELS[nextDir], null, '');
    }
    if (res.finished) finishScan();
  }

  // ---------------------------------------------------------------- vẽ overlay (chỉ khi có dữ liệu mới)
  function draw() {
    if (S.dirtyDraw && S.cam) {
      S.dirtyDraw = false;
      var v = S.cam.v, c = $('eOverlay'), w = v.videoWidth || 640, h = v.videoHeight || 480;
      if (c.width !== w) c.width = w; if (c.height !== h) c.height = h;
      var x = c.getContext('2d'); x.clearRect(0, 0, w, h);
      var o = S.last, ok = o && o.state === 'ok' && S.scan && o.dir === S.scan.current();
      x.lineWidth = Math.max(3, w / 200); x.strokeStyle = ok ? '#22c55e' : '#f59e0b';
      if (o && o.box) { var b = o.box; x.strokeRect(b[0] * w, b[1] * h, (b[2] - b[0]) * w, (b[3] - b[1]) * h); }
      else { x.setLineDash([10, 10]); x.strokeStyle = '#ffffff88'; x.beginPath(); x.ellipse(w / 2, h / 2, w * 0.17, h * 0.3, 0, 0, 7); x.stroke(); x.setLineDash([]); }
    }
    if (S.running || S.counting) requestAnimationFrame(draw);
  }

  // ---------------------------------------------------------------- vòng đời
  function api() { return A().api.apply(null, arguments); }
  function start() {
    var id = $('eMember').value;
    if (!id) return A().toast('Chọn thành viên trước.', true);
    S.member = id; S.mode = $('eMode').value; S.thumbs = {}; S.last = null;
    $('eStart').disabled = true;
    var cam = S.cam = S.cam || new (A().Cam)($('eVideo'));
    A().state.cams.enroll = cam;
    cam.start($('eDevice').value || undefined).then(function () {
      A().fillDevices($('eDevice'));
      return api('/api/enroll/session', { json: { member_id: id, mode: S.mode, kind: 'live' } });
    }).then(function (r) {
      S.sid = r.sid; S.scan = new (G().ClubScan)({}); show('enStage'); renderChips();
      $('eStageBox').classList.add('mirror'); $('eVideo').classList.add('mirror');
      countdown(function () { S.scan.begin(performance.now()); S.running = true; S.token++; instr(G().CLUB_TEXT.front, null, ''); renderChips(); loop(S.token); requestAnimationFrame(draw); });
    }).catch(function (e) { $('eStart').disabled = false; cam.stop(); A().toast(e.name ? camError(e) : e.message, true); });
  }
  function countdown(done) {
    var n = 3, el = $('eCount'); S.counting = true; el.classList.remove('hidden');
    instr('Ngồi chính giữa, nhìn thẳng vào camera', null, '');
    (function tick() {
      if (!S.counting) return;
      if (n === 0) { el.classList.add('hidden'); S.counting = false; return done(); }
      el.textContent = n; speak(String(n)); n--; setTimeout(tick, 1000);
    })();
  }
  function stopLoop() { S.running = false; S.counting = false; S.token++; $('eCount').classList.add('hidden'); }
  function abort(msg) { stopLoop(); if (S.cam) S.cam.stop(); show('enSetup'); $('eStart').disabled = false; if (msg) A().toast(msg, true); }
  function stop() {   // rời trang / bấm Dừng: giải phóng camera, bộ nhớ ảnh nhỏ và phiên trên server
    stopLoop(); if (S.cam) S.cam.stop();
    if (S.sid) { var sid = S.sid; S.sid = null; api('/api/enroll/session/' + sid, { method: 'DELETE' }).catch(function () {}); }
    S.thumbs = {}; S.report = null;
  }
  function finishScan() {
    stopLoop(); instr('Đang chọn ảnh tốt nhất…', null, '');
    var body = { commit: false, target: parseInt($('eTarget').value, 10) || 24, flip: true, augment: 'off' };
    api('/api/enroll/session/' + S.sid + '/finish', { json: body }).then(function (r) { S.report = r.report; showResult(r.report); })
      .catch(function (e) { A().toast(e.message, true); show('enResult'); });
  }

  // ---------------------------------------------------------------- kết quả
  function showResult(rep) {
    show('enResult');
    var g = G(), tot = rep.per_dir_total || rep.per_dir;
    var cls = rep.ok ? 'ok' : (rep.kept ? 'warn' : 'bad');
    $('rTitle').textContent = 'Kết quả cho ' + S.member;
    $('rVerdict').className = 'verdict ' + cls; $('rVerdict').textContent = (rep.ok ? '✓ ' : '') + rep.verdict;
    var byFid = {}; (rep.chosen || []).forEach(function (c) { (byFid[c.dir || 'other'] = byFid[c.dir || 'other'] || []).push(c.fid); });
    $('rDirs').innerHTML = g.CLUB_DIRS.map(function (d) {
      var n = (rep.per_dir || {})[d] || 0, low = n < 2;
      return '<div class="rdir' + (low ? ' low' : '') + '"><div class="small">' + g.CLUB_LABELS[d] + '</div><b>' + n + '</b> mẫu' + (low ? ' <span class="warn-text">thiếu</span>' : '') +
        '<div class="thumbs">' + (byFid[d] || []).slice(0, 8).map(function (f) { return S.thumbs[f] ? '<img alt="" src="' + S.thumbs[f] + '">' : ''; }).join('') + '</div></div>';
    }).join('');
    var extra = [];
    if (rep.kept) extra.push('Giữ <b>' + rep.kept + '</b> ảnh gốc' + (rep.flips ? ' + ' + rep.flips + ' bản lật' : '') + ' (từ ' + rep.candidates + ' khung tốt).');
    if (rep.existing_real) extra.push('Đã có sẵn ' + rep.existing_real + ' mẫu: lần này được <b>bổ sung</b>.');
    if (rep.check && rep.check.n >= 3) extra.push('Kiểm tra chéo: ' + Math.round(rep.check.pass_rate * 100) + '% mẫu nhận đúng người (điểm trung vị ' + rep.check.genuine_median + ').');
    var rj = Object.keys(rep.rejected || {}).map(function (k) { return k + ': ' + rep.rejected[k]; });
    if (rj.length) extra.push('Khung bị loại: ' + A().esc(rj.join(', ')) + '.');
    (rep.warnings || []).forEach(function (w) { extra.push('<span class="warn-text">' + A().esc(w) + '</span>'); });
    if (!rep.ok) extra.push(A().esc(rep.advice));
    $('rInfo').innerHTML = extra.join('<br>');
    var weak = (rep.weak || []).concat((rep.check && rep.check.weak_dirs) || []).filter(function (d, i, a) { return a.indexOf(d) === i; });
    $('eRedoWeak').classList.toggle('hidden', !weak.length); $('eRedoWeak').dataset.dirs = weak.join(',');
    $('eSave').classList.toggle('hidden', !rep.kept); $('eSave').disabled = false;
    $('eNext').classList.add('hidden'); $('eUndo').classList.add('hidden'); $('eDiscard').classList.remove('hidden');
  }
  function save() {
    $('eSave').disabled = true;
    api('/api/enroll/session/' + S.sid + '/commit', { method: 'POST' }).then(function (r) {
      S.saved = r; S.sid = null; if (S.cam) S.cam.stop();
      A().toast('Đã lưu ' + r.report.kept + ' mẫu cho ' + S.member + '.');
      $('rTitle').textContent = 'Đã lưu';
      $('eSave').classList.add('hidden'); $('eRedoWeak').classList.add('hidden'); $('eDiscard').classList.add('hidden');
      $('eNext').classList.remove('hidden');
      if (S.mode === 'add') $('eUndo').classList.remove('hidden');
      return A().loadMembers().then(function () { fillMembers(S.member); });
    }).catch(function (e) { $('eSave').disabled = false; A().toast(e.message, true); });
  }
  function redoWeak() {
    var dirs = $('eRedoWeak').dataset.dirs.split(',').filter(Boolean); if (!dirs.length) return;
    S.scan = new (G().ClubScan)({ order: dirs }); show('enStage'); renderChips();
    S.cam.start($('eDevice').value || undefined).then(function () {
      return Promise.all(dirs.map(function (d) { return api('/api/enroll/session/' + S.sid + '/reset?direction=' + d, { method: 'POST' }); }));
    }).then(function () {
      countdown(function () { S.scan.begin(performance.now()); S.running = true; S.token++; instr(G().CLUB_TEXT[dirs[0]], null, ''); loop(S.token); requestAnimationFrame(draw); });
    }).catch(function (e) { abort(e.name ? camError(e) : e.message); });
  }
  function restartAll() {
    var sid = S.sid; stopLoop();
    var p = sid ? api('/api/enroll/session/' + sid + '/reset', { method: 'POST' }) : Promise.resolve();
    p.then(function () {
      S.thumbs = {}; S.scan = new (G().ClubScan)({}); show('enStage'); renderChips();
      return S.cam.start($('eDevice').value || undefined);
    }).then(function () {
      countdown(function () { S.scan.begin(performance.now()); S.running = true; S.token++; instr(G().CLUB_TEXT.front, null, ''); loop(S.token); requestAnimationFrame(draw); });
    }).catch(function (e) { abort(e.name ? camError(e) : e.message); });
  }
  function redoStep() {
    var d = S.scan && S.scan.current(); if (!d) return;
    api('/api/enroll/session/' + S.sid + '/reset?direction=' + d, { method: 'POST' }).then(function () {
      S.scan.restartPhase(performance.now()); renderChips();
    }).catch(A().fail);
  }
  function next() {
    var list = orderedMembers().filter(function (m) { return m.member_id !== S.member; });
    var pick = list.filter(function (m) { return !m.complete; })[0] || list[0];
    S.saved = null; show('enSetup'); $('eStart').disabled = false;
    fillMembers(pick ? pick.member_id : S.member);
  }
  function undo() {
    if (!S.saved) return;
    api('/api/enroll/undo', { json: { member_id: S.member, img_ids: S.saved.img_ids } }).then(function () {
      A().toast('Đã hoàn tác lần lưu vừa rồi.'); S.saved = null; $('eUndo').classList.add('hidden');
      return A().loadMembers().then(function () { fillMembers(S.member); });
    }).catch(A().fail);
  }

  var bound = false;
  function bind() {
    if (bound) return; bound = true;
    $('eStart').onclick = start; $('eMember').onchange = cover;
    $('eStop').onclick = function () { stop(); show('enSetup'); $('eStart').disabled = false; };
    $('eRedoStep').onclick = redoStep; $('eRedoAll').onclick = restartAll;
    $('eSave').onclick = save; $('eRedoWeak').onclick = redoWeak; $('eNext').onclick = next; $('eUndo').onclick = undo;
    $('eDiscard').onclick = restartAll;
    document.addEventListener('visibilitychange', function () { if (document.hidden && S.running) { /* vòng lặp tự tạm dừng khi tab ẩn (nextFrame) */ } });
    window.addEventListener('beforeunload', function () { if (S.cam) S.cam.stop(); });
  }
  window.EnrollPage = {
    init: function (pre) {
      bind(); stop(); show('enSetup'); $('eStart').disabled = false;
      A().fillDevices($('eDevice')); fillMembers(pre || A().state.enrollFor);
    },
    stop: function () { if (bound) stop(); },
    _state: S
  };
})();
