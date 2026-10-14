/* Trang "Nhập dataset": gom file theo thư mục thành viên, cắt khung video trên trình duyệt, gửi /api/enroll/dataset. */
(function () {
  'use strict';
  var IMG = ['jpg', 'jpeg', 'png', 'bmp', 'webp'], VID = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v', '3gp'], BAD = ['heic', 'heif'];
  var $ = function (id) { return document.getElementById(id); };
  var A = function () { return window.__app; };
  var groups = [], running = false, stop = false;

  function ext(n) { var m = /\.([^.]+)$/.exec(n || ''); return m ? m[1].toLowerCase() : ''; }
  function norm(s) { return String(s || '').toLowerCase().replace(/đ/g, 'd').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]/g, ''); }
  function slug(s) { return String(s || '').toLowerCase().replace(/đ/g, 'd').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'member'; }
  function matchMember(folder, members) {
    var n = norm(folder), i;
    for (i = 0; i < members.length; i++) if (n && (n === norm(members[i].member_id) || n === norm(members[i].name))) return members[i];
    var c = members.filter(function (m) { var k = norm(m.name); return n && k.length >= 3 && (k.indexOf(n) >= 0 || n.indexOf(k) >= 0); });
    return c.length === 1 ? c[0] : null;
  }
  // files: [{file, path}] -> [{folder, imgs, vids, bad}]
  function group(files) {
    var deep = files.some(function (f) { return f.path.split('/').length >= 3; }), m = {};
    files.forEach(function (f) {
      var p = f.path.split('/'); if (p.length < 2) return;
      var k = deep ? p[1] : p[0]; (m[k] = m[k] || []).push(f.file);
    });
    return Object.keys(m).sort().map(function (k) {
      var fs = m[k].sort(function (a, b) { return a.name < b.name ? -1 : 1; });
      return { folder: k, imgs: fs.filter(function (f) { return IMG.indexOf(ext(f.name)) >= 0; }), vids: fs.filter(function (f) { return VID.indexOf(ext(f.name)) >= 0; }),
               bad: fs.filter(function (f) { return BAD.indexOf(ext(f.name)) >= 0; }) };
    });
  }

  function videoFrames(file, maxFrames, onProg) {
    return new Promise(function (ok) {
      var v = document.createElement('video'); v.muted = true; v.playsInline = true; v.preload = 'auto';
      var url = URL.createObjectURL(file), out = [];
      var done = function () { URL.revokeObjectURL(url); ok(out); };
      v.onerror = done;
      v.onloadedmetadata = function () {
        var dur = v.duration; if (!isFinite(dur) || dur <= 0 || !v.videoWidth) return done();
        var n = Math.max(6, Math.min(maxFrames, Math.round(dur / 0.3))), s = Math.min(1, 1280 / Math.max(v.videoWidth, v.videoHeight));
        var c = document.createElement('canvas'); c.width = Math.round(v.videoWidth * s); c.height = Math.round(v.videoHeight * s);
        var i = 0;
        (function next() {
          if (i >= n || stop) return done();
          var t = setTimeout(function () { i++; next(); }, 4000);              // dự phòng nếu seek không báo xong
          v.onseeked = function () {
            clearTimeout(t); c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
            c.toBlob(function (b) { if (b) out.push(new File([b], file.name + '#' + i + '.jpg', { type: 'image/jpeg' })); i++; onProg && onProg(i / n); next(); }, 'image/jpeg', 0.92);
          };
          v.currentTime = Math.min(dur - 0.05, dur * (i + 0.5) / n);
        })();
      };
      v.src = url;
    });
  }

  var REASON = { no_face: 'không thấy mặt', multiple_faces: 'có 2 mặt lớn', clipped: 'mặt bị cắt khỏi ảnh', low_det: 'mặt không chắc', small: 'mặt nhỏ',
    blurry: 'mờ', looks_like_other: 'giống người khác (bỏ nhầm thư mục?)', outlier: 'không giống người này', bad_image: 'file ảnh lỗi', no_embedding: 'không trích được đặc trưng' };

  function render() {
    var members = (A().state.members || []);
    $('iPreviewBox').classList.toggle('hidden', !groups.length);
    $('iPreview').innerHTML = '<table><tr><th>Thư mục</th><th>Thành viên</th><th>Ảnh</th><th>Video</th><th>Ghi chú</th></tr>' + groups.map(function (g, i) {
      var opts = members.map(function (m) { return '<option value="' + A().esc(m.member_id) + '"' + (g.target === m.member_id ? ' selected' : '') + '>' + A().esc(m.name) + ' (' + A().esc(m.member_id) + ')</option>'; }).join('');
      var neu = '<option value="__new"' + (g.target === '__new' ? ' selected' : '') + '>➕ Tạo mới: ' + A().esc(slug(g.folder)) + '</option>';
      var note = [];
      if (g.bad.length) note.push('<span class="tag warn">' + g.bad.length + ' HEIC bỏ qua</span>');
      if (!g.imgs.length && !g.vids.length) note.push('<span class="tag bad">không có ảnh/video</span>');
      if (g.imgs.length + g.vids.length * 10 < 8) note.push('<span class="tag warn">ít dữ liệu</span>');
      return '<tr><td>' + A().esc(g.folder) + '</td><td><select data-g="' + i + '"><option value="">— bỏ qua —</option>' + opts + neu + '</select></td><td>' + g.imgs.length + '</td><td>' + g.vids.length + '</td><td>' + note.join(' ') + '</td></tr>';
    }).join('') + '</table>';
    Array.prototype.forEach.call($('iPreview').querySelectorAll('select[data-g]'), function (s) { s.onchange = function () { groups[+s.dataset.g].target = s.value; }; });
  }

  function load(files, single) {
    A().loadMembers().then(function (members) {
      groups = group(files);
      groups.forEach(function (g) {
        var h = matchMember(g.folder, members || []);
        g.target = single ? '' : (h ? h.member_id : ($('iCreate').checked ? '__new' : ''));
      });
      $('iResultBox').classList.add('hidden'); render();
      if (!groups.length) A().toast('Không thấy thư mục thành viên nào. Chọn thư mục gốc có các thư mục con.', true);
    });
  }

  function importOne(g, st, row) {
    var id = g.target === '__new' ? slug(g.folder) : g.target;
    var name = g.target === '__new' ? g.folder.trim() : '';
    var warns = [], frames = 0, done = 0, total = 0, sid = null;
    var set = function (t) { row.querySelector('.st').textContent = t; };
    var blobs = g.imgs.slice(), chain = Promise.resolve();
    g.vids.forEach(function (v, vi) {
      chain = chain.then(function () { if (stop) return; set('cắt khung video ' + (vi + 1) + '/' + g.vids.length + '…'); return videoFrames(v, 40, null).then(function (fr) {
          frames += fr.length; blobs = blobs.concat(fr);
          if (!fr.length) warns.push('Video ' + v.name + ' không đọc được trên trình duyệt này (thử Chrome/Edge, xuất lại MP4 H.264/WebM, hoặc dùng tools/import_dataset.py).');
        }); });
    });
    return chain.then(function () {
      if (!blobs.length) throw new Error('không có ảnh/khung nào dùng được');
      return A().api('/api/enroll/session', { json: { member_id: id, name: name, mode: $('iMode').value, kind: 'dataset', source: $('iSource').value } });
    }).then(function (s) {
      sid = s.sid; total = blobs.length; var groupsOf8 = [];
      for (var i = 0; i < blobs.length; i += 8) groupsOf8.push(blobs.slice(i, i + 8));
      return groupsOf8.reduce(function (p, grp) {
        return p.then(function () {
          if (stop) return;
          var fd = new FormData(); grp.forEach(function (f) { fd.append('files', f, f.name); });
          return A().api('/api/enroll/session/' + sid + '/frames', { body: fd }).then(function (r) {
            done += grp.length; set('đã phân tích ' + done + '/' + total + ' (đang giữ ' + r.total + ' ứng viên)');
          });
        });
      }, Promise.resolve());
    }).then(function () {
      if (stop) { A().api('/api/enroll/session/' + sid, { method: 'DELETE' }).catch(function () {}); throw new Error('đã dừng'); }
      set('đang chọn mẫu tốt nhất…');
      return A().api('/api/enroll/session/' + sid + '/finish', { json: { commit: true, target: parseInt($('iTarget').value, 10) || 24, augment: $('iAug').value } });
    }).then(function (r) { return { g: g, id: id, report: r.report, committed: r.committed, summary: r.summary, warns: warns, frames: frames }; })
      .catch(function (e) { if (sid) A().api('/api/enroll/session/' + sid, { method: 'DELETE' }).catch(function () {}); throw e; });
  }

  function resultHtml(r) {
    var rep = r.report, lab = window.Guide.CLUB_LABELS;
    var sk = Object.keys(rep.rejected || {}).map(function (k) { return (REASON[k] || k) + ' ×' + rep.rejected[k]; }).join(', ') || '—';
    var dirs = window.Guide.CLUB_DIRS.map(function (d) { var n = (rep.per_dir_total || rep.per_dir || {})[d] || 0; return '<span class="chip ' + (n >= 2 ? 'ok' : 'low') + '">' + window.Guide.CLUB_SHORT[d] + ' <b>' + n + '</b></span>'; }).join(' ');
    var cls = rep.ok ? 'ok' : (rep.kept ? 'warn' : 'bad');
    var aug = rep.augmented ? ('<br><small>Augmentation (vì ' + A().esc((rep.augment_reasons || []).join('; ')) + '): +' + rep.aug + ' bản' +
      (rep.aug_dropped && Object.keys(rep.aug_dropped).length ? ', bỏ ' + A().esc(JSON.stringify(rep.aug_dropped)) : '') + '</small>') : '';
    return '<tr><td>' + A().esc(r.g.folder) + ' → <b>' + A().esc(r.id) + '</b></td><td><span class="tag ' + cls + '">' + (r.committed ? 'lưu ' + rep.kept + ' ảnh gốc' : 'không lưu') + '</span> ' +
      (rep.flips ? '<small>+ ' + rep.flips + ' bản lật</small> ' : '') + (r.frames ? '<small>(' + r.frames + ' khung video)</small>' : '') + aug +
      '<br><small>Bỏ qua: ' + A().esc(sk) + '</small>' + ((rep.warnings || []).concat(r.warns).length ? '<br><small>⚠ ' + A().esc((rep.warnings || []).concat(r.warns).join(' ')) + '</small>' : '') +
      '</td><td>' + dirs + '<br><b class="' + (rep.ok ? 'ok-text' : 'warn-text') + '">' + A().esc(rep.verdict) + '</b>' + (rep.ok ? '' : '<br><small>' + A().esc(rep.advice) + '</small>') + '</td></tr>';
  }

  function go() {
    if (running) return;
    var todo = groups.filter(function (g) { return g.target && (g.imgs.length || g.vids.length); });
    if (!todo.length) return A().toast('Chưa chọn thành viên nào để nhập.', true);
    running = true; stop = false; $('iGo').disabled = true; $('iResultBox').classList.remove('hidden');
    $('iResult').innerHTML = '<table><tr><th>Thư mục</th><th>Kết quả</th><th>Độ phủ 5 hướng · kết luận</th></tr>' + todo.map(function (g, i) { return '<tr id="iRow' + i + '"><td colspan="3">' + A().esc(g.folder) + ': <span class="st">đang chờ…</span></td></tr>'; }).join('') + '</table>';
    todo.reduce(function (p, g, i) {
      return p.then(function () {
        var row = $('iRow' + i); if (stop) { row.querySelector('.st').textContent = 'đã dừng'; return; }
        return importOne(g, null, row).then(function (r) { row.outerHTML = resultHtml(r).replace('<tr>', '<tr id="iRow' + i + '">'); })
          .catch(function (e) { row.querySelector('.st').textContent = 'lỗi: ' + e.message; });
      });
    }, Promise.resolve()).then(function () { running = false; $('iGo').disabled = false; A().loadMembers(); A().toast(stop ? 'Đã dừng.' : 'Nhập xong.'); });
  }

  var inited = false;
  window.ImportPage = {
    group: group, norm: norm, slug: slug, matchMember: matchMember,
    init: function () {
      if (inited) return; inited = true;
      $('iDir').onchange = function () {
        var fl = Array.prototype.map.call($('iDir').files, function (f) { return { file: f, path: f.webkitRelativePath || f.name }; });
        load(fl);
      };
      $('iFiles').onchange = function () {
        var fl = Array.prototype.map.call($('iFiles').files, function (f) { return { file: f, path: 'x/Một người/' + f.name }; });
        load(fl, true);
      };
      $('iGo').onclick = go; $('iCancel').onclick = function () { stop = true; };
    }
  };
})();
