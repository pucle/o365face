/* Logic thuần (không đụng DOM) cho HUD hướng dẫn xoay đầu và cò check-in ở cửa.
 * Chạy được cả trong trình duyệt (window.Guide) lẫn Node (tests/guide.test.js).
 *
 * Quy ước góc = InsightFace, giống server (common/posebins.py):
 *   pitch < 0: cúi,  yaw > 0: mặt quay sang TRÁI của chính người đó (bên phải của ảnh gốc).
 * Xem trước trên màn hình được lật gương, nên "trái của người đó" cũng là bên TRÁI trên màn hình.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Guide = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var YAW_EDGES = [-30, -12, 12, 30], YAW_NAMES = ['R2', 'R1', 'C', 'L1', 'L2'];
  var DOWN_EDGES = [-8, 12, 28], PITCH_NAMES = ['up', 'level', 'down1', 'down2'];
  var YAW_CENTER = { R2: -42, R1: -20, C: 0, L1: 20, L2: 42 };
  var DOWN_CENTER = { up: -16, level: 2, down1: 20, down2: 38 };

  function binOf(v, edges) {
    for (var i = 0; i < edges.length; i++) if (v < edges[i]) return i;
    return edges.length;
  }
  function cellOf(pitch, yaw) {
    return { p: PITCH_NAMES[binOf(-pitch, DOWN_EDGES)], y: YAW_NAMES[binOf(yaw, YAW_EDGES)] };
  }

  var STEP_TEXT = {
    'level|C': 'Nhìn thẳng vào camera',
    'level|L1': 'Quay mặt nhẹ sang TRÁI của bạn',
    'level|R1': 'Quay mặt nhẹ sang PHẢI của bạn',
    'level|L2': 'Quay hẳn sang TRÁI (nhìn nghiêng)',
    'level|R2': 'Quay hẳn sang PHẢI (nhìn nghiêng)',
    'down1|C': 'Cúi đầu nhẹ (như nhìn xuống bàn)',
    'down1|L1': 'Cúi nhẹ và quay sang TRÁI',
    'down1|R1': 'Cúi nhẹ và quay sang PHẢI',
    'down1|L2': 'Cúi nhẹ và quay hẳn sang TRÁI',
    'down1|R2': 'Cúi nhẹ và quay hẳn sang PHẢI',
    'down2|C': 'Cúi đầu nhiều (như camera nhìn từ trần xuống)',
    'down2|L1': 'Cúi nhiều và quay sang TRÁI',
    'down2|R1': 'Cúi nhiều và quay sang PHẢI',
    'up|C': 'Ngẩng đầu nhẹ'
  };
  var PITCH_LABEL = { up: 'Ngẩng', level: 'Ngang', down1: 'Cúi nhẹ', down2: 'Cúi nhiều' };
  var YAW_LABEL = { R2: 'Phải sâu', R1: 'Phải', C: 'Thẳng', L1: 'Trái', L2: 'Trái sâu' };

  function step(p, y, need) {
    return { id: p + '|' + y, p: p, y: y, text: STEP_TEXT[p + '|' + y], need: need || 3,
             label: PITCH_LABEL[p] + ' · ' + YAW_LABEL[y] };
  }
  // Các hồ sơ phải khớp PROFILES ở server (door/room); 'extra' chỉ để có thêm mẫu nghiêng sâu.
  var PROFILES = {
    door: [['level', 'C'], ['level', 'L1'], ['level', 'R1'], ['down1', 'C'], ['up', 'C']],
    room: [['down1', 'C'], ['down1', 'L1'], ['down1', 'R1'], ['down2', 'C'], ['down2', 'L1'], ['down2', 'R1']],
    extra: [['level', 'L2'], ['level', 'R2'], ['down1', 'L2'], ['down1', 'R2']]
  };
  var MIRROR = { R1: 'L1', R2: 'L2' };

  /* Tạo kế hoạch các bước. useFlip: bỏ các bước phía PHẢI vì server tự lưu bản lật (yaw đảo dấu) của bước TRÁI. */
  function plan(profile, opts) {
    opts = opts || {};
    var names = profile === 'full' ? ['door', 'room'] : [profile];
    var out = [], seen = {};
    names.forEach(function (n) {
      (PROFILES[n] || []).forEach(function (c) {
        var id = c[0] + '|' + c[1];
        if (seen[id]) return;
        seen[id] = 1;
        if (opts.useFlip && MIRROR[c[1]] && (PROFILES[n] || []).some(function (d) { return d[0] === c[0] && d[1] === MIRROR[c[1]]; })) return;
        out.push(step(c[0], c[1], opts.need));
      });
    });
    return out;
  }

  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  /* Hướng dẫn cho bước hiện tại. Trả về {ok, arrow:{x,y}, text, dyaw, ddown}; arrow.x=-1: sang trái màn hình (lật gương). */
  function guidance(st, pitch, yaw) {
    var c = cellOf(pitch, yaw);
    if (c.p === st.p && c.y === st.y) return { ok: true, arrow: { x: 0, y: 0 }, text: 'Đúng rồi, giữ yên…', dyaw: 0, ddown: 0 };
    var ddown = DOWN_CENTER[st.p] - (-pitch), dyaw = YAW_CENTER[st.y] - yaw;
    // Chỉ cần lệch ra ngoài ô nào thì chỉnh trục đó; ưu tiên trục lệch nhiều hơn
    var needYaw = c.y !== st.y, needDown = c.p !== st.p;
    var ry = needYaw ? Math.abs(dyaw) / 15 : 0, rp = needDown ? Math.abs(ddown) / 12 : 0;
    var arrow = { x: 0, y: 0 }, text = '';
    if (ry >= rp && needYaw) {
      arrow.x = dyaw > 0 ? -1 : 1;
      text = dyaw > 0 ? 'Quay thêm sang TRÁI của bạn' : 'Quay thêm sang PHẢI của bạn';
      if (needDown) { arrow.y = ddown > 0 ? 1 : -1; }
    } else if (needDown) {
      arrow.y = ddown > 0 ? 1 : -1;
      text = ddown > 0 ? 'Cúi đầu thêm' : 'Ngẩng đầu lên một chút';
      if (needYaw) arrow.x = dyaw > 0 ? -1 : 1;
    }
    return { ok: false, arrow: arrow, text: text, dyaw: dyaw, ddown: ddown };
  }

  /* Vị trí chấm trên mặt số, [-1,1]. mirror=true: xem trước lật gương. */
  function dial(pitch, yaw, mirror) {
    var x = clamp(yaw / 50, -1, 1), y = clamp(-pitch / 45, -1, 1);
    return { x: mirror === false ? x : -x, y: y };
  }
  function targetDial(st, mirror) {
    var x = YAW_CENTER[st.y] / 50, y = DOWN_CENTER[st.p] / 45;
    return { x: mirror === false ? x : -x, y: y };
  }

  var REJECT_TEXT = {
    no_face: 'Không thấy mặt — nhìn vào camera, đủ sáng.',
    small_or_unsure: 'Mặt quá nhỏ/không chắc — lại gần camera hơn.',
    blurry: 'Ảnh bị mờ — giữ đầu yên và thêm ánh sáng.',
    extreme_pose: 'Góc quá lệch — quay/cúi bớt một chút.',
    duplicate: 'Ảnh giống mẫu đã có — nhúc nhích nhẹ giữa các lần chụp.',
    limit: 'Đã đủ số ảnh tối đa cho người này.',
    no_embedding: 'Không trích được đặc trưng mặt — thử lại.'
  };

  /* Phiên đăng ký. update() nhận quan sát của một khung hình và quyết định có chụp không;
   * caller gửi ảnh lên server rồi gọi result(). */
  function Session(steps, opts) {
    opts = opts || {};
    this.steps = steps;
    this.idx = 0;
    this.got = steps.map(function () { return 0; });
    this.holdMs = opts.holdMs || 500;
    this.cooldownMs = opts.cooldownMs || 600;
    this.minWidth = opts.minWidth || 80;
    this.dupDone = opts.dupDone || 2;
    this.holdSince = null;
    this.lastShot = -1e9;
    this.pending = false;
    this.dups = 0;
    this.lastReject = null;
  }
  Session.prototype.current = function () { return this.idx < this.steps.length ? this.steps[this.idx] : null; };
  Session.prototype.finished = function () { return this.idx >= this.steps.length; };
  Session.prototype.total = function () {
    return this.steps.reduce(function (a, s) { return a + s.need; }, 0);
  };
  Session.prototype.progress = function () {
    var done = 0, self = this;
    this.steps.forEach(function (s, i) { done += Math.min(s.need, self.got[i]); });
    return this.total() ? done / this.total() : 1;
  };
  Session.prototype.goto = function (i) {
    this.idx = clamp(i, 0, this.steps.length); this.holdSince = null; this.dups = 0; this.pending = false;
  };
  Session.prototype.skip = function () { this.goto(this.idx + 1); };
  Session.prototype.back = function () { this.goto(Math.max(0, this.idx - 1)); this.got[this.idx] = 0; };
  Session.prototype.restart = function () { this.got = this.steps.map(function () { return 0; }); this.goto(0); };

  Session.prototype.update = function (obs, now) {
    var st = this.current();
    if (!st) return { phase: 'done', text: 'Hoàn tất!', hold: 1, shot: false };
    var f = obs && obs.face;
    var base = { step: st, hold: 0, shot: false, arrow: { x: 0, y: 0 } };
    if (!f) { this.holdSince = null; return mix(base, { phase: 'noface', text: 'Không thấy mặt. Nhìn vào camera.' }); }
    if (obs.faces > 1) { this.holdSince = null; return mix(base, { phase: 'multi', text: 'Có nhiều hơn một người trong khung. Chỉ để mình bạn.' }); }
    if (f.width < this.minWidth) { this.holdSince = null; return mix(base, { phase: 'small', text: 'Lại gần camera hơn.' }); }
    if (f.pitch == null || f.yaw == null) { this.holdSince = null; return mix(base, { phase: 'noface', text: 'Chưa đo được góc đầu.' }); }
    var g = guidance(st, f.pitch, f.yaw);
    if (!g.ok) { this.holdSince = null; return mix(base, { phase: 'adjust', text: g.text, arrow: g.arrow, guide: g }); }
    if (this.pending) return mix(base, { phase: 'saving', text: 'Đang lưu…', guide: g, hold: 1 });
    if (this.holdSince == null) this.holdSince = now;
    var hold = clamp((now - this.holdSince) / this.holdMs, 0, 1);
    if (hold >= 1 && now - this.lastShot >= this.cooldownMs) {
      this.lastShot = now; this.pending = true; this.holdSince = null;
      return mix(base, { phase: 'shoot', text: 'Chụp!', guide: g, hold: 1, shot: true });
    }
    return mix(base, { phase: 'hold', text: g.text, guide: g, hold: hold });
  };

  /* Báo kết quả của lần chụp vừa rồi. Trả về {advanced, stepDone, finished, text}. */
  Session.prototype.result = function (accepted, reason) {
    this.pending = false;
    var i = this.idx, st = this.steps[i];
    if (!st) return { advanced: false, stepDone: false, finished: true, text: '' };
    var counted = false;
    if (accepted) { this.got[i]++; this.dups = 0; this.lastReject = null; counted = true; }
    else {
      this.lastReject = reason || null;
      if (reason === 'duplicate') { this.dups++; if (this.dups >= this.dupDone) { this.got[i]++; this.dups = 0; counted = true; } }
      if (reason === 'limit') { this.got[i] = st.need; counted = true; }
    }
    var stepDone = this.got[i] >= st.need;
    if (stepDone) { this.goto(i + 1); this.lastShot = -1e9; }
    return { advanced: stepDone, stepDone: stepDone, counted: counted, finished: this.finished(),
             text: accepted ? 'Đã lưu' : (REJECT_TEXT[reason] || 'Ảnh bị từ chối: ' + reason) };
  };


  /* ====================== Quét liên tục kiểu Face ID ======================
   * Người dùng "vẽ vòng tròn bằng mũi" quanh một tâm. Mỗi tầng (stage) có một tâm cúi khác nhau
   * (0°, 18°, 34°… để mô phỏng cam trần nhìn từ trên xuống). Vòng được chia N cung; chạm cung nào là chụp ngay,
   * không cần giữ yên. Thêm ô "tâm" (mặt thẳng ở tầng đó) và 2 ô nghiêng đầu (roll) hai phía.
   * Toạ độ cung theo MÀN HÌNH lật gương: sx = -yaw, sy = (cúi - tâm cúi). */
  var SCAN_PRESETS = {
    quick:    { label: 'Nhanh',  stages: [0],          sectors: 12, perCell: 1, tilt: true },
    standard: { label: 'Chuẩn',  stages: [0, 18],      sectors: 16, perCell: 1, tilt: true },
    thorough: { label: 'Kỹ (cho cam trần góc cao)', stages: [0, 18, 34], sectors: 16, perCell: 2, tilt: true }
  };

  function sectorAt(stageDown, pitch, yaw, N, rmin, rmax) {
    var sx = -yaw, sy = (-pitch) - stageDown, r = Math.sqrt(sx * sx + sy * sy);
    var th = Math.atan2(sy, sx);                       // (-pi, pi], 0 = phải màn hình, pi/2 = xuống
    var k = Math.floor(((th + Math.PI) / (2 * Math.PI)) * N) % N;
    return { sector: k, r: r, ring: r >= rmin && r <= rmax, center: r < rmin, sx: sx, sy: sy, theta: th };
  }
  function sectorAngles(k, N) {                        // góc đầu/cuối của cung k theo hệ canvas
    var a0 = -Math.PI + (k / N) * 2 * Math.PI, a1 = -Math.PI + ((k + 1) / N) * 2 * Math.PI;
    return [a0, a1];
  }

  function Sweep(opts) {
    opts = opts || {};
    var pr = SCAN_PRESETS[opts.preset || 'standard'];
    this.stages = (opts.stages || pr.stages).slice();
    this.N = opts.sectors || pr.sectors;
    this.perCell = opts.perCell || pr.perCell;
    this.tilt = opts.tilt != null ? opts.tilt : pr.tilt;
    this.minW = opts.minWidth || 55;
    this.rmin = opts.rmin || 9;
    this.rmax = opts.rmax || 42;
    this.tiltDeg = opts.tiltDeg || 14;
    this.maxPending = opts.maxPending || 4;
    this.minGapMs = opts.minGapMs || 110;
    this.minMoveDeg = opts.minMoveDeg || 3;
    this.maxTries = opts.maxTries || 5;
    this.restart();
  }
  Sweep.prototype.restart = function () {
    var self = this;
    this.stage = 0;
    this.ring = this.stages.map(function () { return new Array(self.N).fill(0); });
    this.center = this.stages.map(function () { return 0; });
    this.tiltGot = { a: 0, b: 0 };
    this.skipped = {};
    this.tries = {};
    this.pending = {};
    this.lastShot = -1e9;
    this.lastPose = {};
    this.flashStage = false;
  };
  Sweep.prototype.finished = function () { return this.stage >= this.stages.length; };
  Sweep.prototype.stageDown = function () { return this.stages[Math.min(this.stage, this.stages.length - 1)]; };
  Sweep.prototype.tiltNeeded = function () { return this.tilt && this.stage === 0; };
  Sweep.prototype.total = function () {
    return this.stages.length * (this.N + 1) * this.perCell + (this.tilt ? 2 * this.perCell : 0);
  };
  Sweep.prototype.done = function () {
    var d = 0, self = this, p = this.perCell;
    this.ring.forEach(function (r) { r.forEach(function (n) { d += Math.min(n, p); }); });
    this.center.forEach(function (n) { d += Math.min(n, p); });
    if (this.tilt) d += Math.min(this.tiltGot.a, p) + Math.min(this.tiltGot.b, p);
    return d;
  };
  Sweep.prototype.progress = function () { return this.total() ? Math.min(1, this.done() / this.total()) : 1; };
  Sweep.prototype.stageFilled = function (i) {
    var p = this.perCell, n = 0; this.ring[i].forEach(function (c) { n += c >= p ? 1 : 0; });
    return n;
  };
  Sweep.prototype._stageComplete = function () {
    var p = this.perCell, i = this.stage;
    if (!this.ring[i].every(function (c) { return c >= p; })) return false;
    if (this.center[i] < p) return false;
    if (this.tiltNeeded() && (this.tiltGot.a < p || this.tiltGot.b < p)) return false;
    return true;
  };
  Sweep.prototype.skipStage = function () { this.stage++; this.pending = {}; };
  Sweep.prototype.back = function () { if (this.stage > 0) this.stage--; };

  /* obs: {face:{pitch,yaw,roll,width}|null, faces:n}. Trả về {phase, text, shot:{id,kind,cell}|null, ...} */
  Sweep.prototype.update = function (obs, now) {
    if (this.finished()) return { phase: 'done', text: 'Hoàn tất!', shot: null };
    var f = obs && obs.face, base = { shot: null, stage: this.stage, sx: null, sy: null };
    if (!f) return mix(base, { phase: 'noface', text: 'Không thấy mặt. Nhìn vào camera.' });
    if (obs.faces > 1) return mix(base, { phase: 'multi', text: 'Chỉ để mình bạn trong khung.' });
    if (f.width < this.minW) return mix(base, { phase: 'small', text: 'Lại gần camera hơn.' });
    if (f.pitch == null || f.yaw == null) return mix(base, { phase: 'noface', text: 'Chưa đo được góc đầu.' });
    var pos = sectorAt(this.stageDown(), f.pitch, f.yaw, this.N, this.rmin, this.rmax);
    base.sx = pos.sx; base.sy = pos.sy; base.r = pos.r;
    var npend = Object.keys(this.pending).length;
    var cand = [];                                      // các ô có thể chụp ở tư thế hiện tại
    var i = this.stage, p = this.perCell;
    if (pos.center && this.center[i] < p) cand.push({ id: 'c' + i, kind: 'center' });
    if (pos.ring && this.ring[i][pos.sector] < p) cand.push({ id: 'r' + i + '_' + pos.sector, kind: 'ring', sector: pos.sector });
    if (this.tiltNeeded() && f.roll != null && pos.r <= this.rmax) {
      if (f.roll >= this.tiltDeg && this.tiltGot.a < p) cand.push({ id: 'ta', kind: 'tilt', side: 'a' });
      if (f.roll <= -this.tiltDeg && this.tiltGot.b < p) cand.push({ id: 'tb', kind: 'tilt', side: 'b' });
    }
    var hint = this._hint(pos, f);
    base.hint = hint;
    for (var k = 0; k < cand.length; k++) {
      var c = cand[k];
      if (this.pending[c.id]) continue;
      var lp = this.lastPose[c.id];
      if (lp && Math.hypot(lp[0] - f.pitch, lp[1] - f.yaw) < this.minMoveDeg) continue;   // lần chụp thứ 2 trong cùng ô phải khác tư thế
      if (npend >= this.maxPending || now - this.lastShot < this.minGapMs) break;
      this.pending[c.id] = true; this.lastShot = now; this.lastPose[c.id] = [f.pitch, f.yaw];
      return mix(base, { phase: 'shoot', text: hint, shot: c });
    }
    return mix(base, { phase: 'scan', text: hint });
  };
  Sweep.prototype._hint = function (pos, f) {
    var i = this.stage, p = this.perCell, self = this;
    var ringDone = this.ring[i].every(function (c) { return c >= p; });
    if (this.center[i] < p && !ringDone && this.stageFilled(i) === 0) return 'Nhìn vào giữa vòng tròn, rồi từ từ xoay mũi theo vòng tròn.';
    if (!ringDone) {
      var left = this.N - this.stageFilled(i);
      return 'Xoay đầu chậm theo vòng tròn — còn ' + left + ' cung';
    }
    if (this.center[i] < p) return 'Quay về giữa vòng tròn.';
    if (this.tiltNeeded() && (this.tiltGot.a < p || this.tiltGot.b < p)) {
      return this.tiltGot.a < p && this.tiltGot.b < p ? 'Nghiêng đầu sang một bên (tai chạm vai), rồi sang bên kia.' : 'Nghiêng đầu sang bên ngược lại.';
    }
    return '';
  };
  Sweep.prototype.result = function (id, accepted, reason) {
    delete this.pending[id];
    var st = this.stage, cnt = false;
    this.tries[id] = (this.tries[id] || 0) + 1;
    if (accepted || reason === 'duplicate' || reason === 'limit') cnt = true;
    else if (this.tries[id] >= this.maxTries) { cnt = true; this.skipped[id] = reason || 'x'; }
    if (cnt) {
      var m;
      if ((m = /^r(\d+)_(\d+)$/.exec(id))) this.ring[+m[1]][+m[2]]++;
      else if ((m = /^c(\d+)$/.exec(id))) this.center[+m[1]]++;
      else if (id === 'ta') this.tiltGot.a++;
      else if (id === 'tb') this.tiltGot.b++;
    }
    var advanced = false;
    if (!this.finished() && this._stageComplete()) { this.stage++; this.pending = {}; advanced = true; }
    return { counted: cnt, advanced: advanced, finished: this.finished(),
             text: accepted ? 'Đã lưu' : (REJECT_TEXT[reason] || String(reason || '')) };
  };

  /* Độ phủ quét của một thành viên tính từ danh sách tư thế [pitch,yaw] đã lưu (tổng số vùng phụ thuộc kế hoạch quét, không cố định). */
  function scanCoverage(poses, preset) {
    var pr = SCAN_PRESETS[preset || 'thorough'], N = pr.sectors, rmin = 9, rmax = 42, out = [], filled = 0, total = 0;
    pr.stages.forEach(function (down) {
      var arr = new Array(N).fill(0), ctr = 0;
      (poses || []).forEach(function (p) {
        var s = sectorAt(down, p[0], p[1], N, rmin, rmax);
        if (s.center) ctr = 1; else if (s.ring) arr[s.sector] = 1;
      });
      var f = arr.reduce(function (a, b) { return a + b; }, 0) + ctr;
      out.push({ down: down, arcs: arr, center: ctr, filled: f, total: N + 1 }); filled += f; total += N + 1;
    });
    return { stages: out, filled: filled, total: total, ratio: total ? filled / total : 0, N: N };
  }


  /* ---------------- Quy trình CLB: chính diện, quay trái/phải ~45°, ngẩng/cúi ~45° (khớp posebins.CLUB_* ở server) ---------------- */
  var CLUB_DIRS = ['front', 'left', 'right', 'up', 'down'];
  var CLUB_LABELS = { front: 'Chính diện', left: 'Quay trái 45°', right: 'Quay phải 45°', up: 'Ngẩng 45°', down: 'Cúi 45°' };
  var CLUB_SHORT = { front: 'Thẳng', left: 'Trái', right: 'Phải', up: 'Ngẩng', down: 'Cúi' };
  var CLUB_WINDOWS = {   // [pitchMin, pitchMax, yawMin, yawMax]
    front: [-12, 12, -14, 14], left: [-25, 25, 28, 75], right: [-25, 25, -75, -28], up: [15, 65, -27, 27], down: [-65, -15, -27, 27]
  };
  var CLUB_TARGETS = { front: [0, 0], left: [0, 45], right: [0, -45], up: [30, 0], down: [-30, 0] };
  var CLUB_TEXT = {
    front: 'Nhìn thẳng vào camera', left: 'Quay mặt sang TRÁI của bạn (khoảng 45°)', right: 'Quay mặt sang PHẢI của bạn (khoảng 45°)',
    up: 'Ngẩng đầu lên (khoảng 45°)', down: 'Cúi đầu xuống (khoảng 45°)'
  };
  var CLUB_STATE_TEXT = {
    no_face: 'Chưa thấy mặt: ngồi chính giữa khung hình', multi: 'Có 2 người trong khung: chỉ một người thôi',
    far: 'Lại gần camera hơn', unsure: 'Mặt chưa rõ: thêm ánh sáng, bỏ khẩu trang/kính che', blurry: 'Hình bị nhòe: giữ đầu chậm lại',
    clipped: 'Mặt bị cắt khỏi khung: lùi ra hoặc đưa mặt vào giữa', other_person: 'Có vẻ là người khác: chỉ người đang đăng ký ở trước camera',
    bad_image: 'Không đọc được ảnh'
  };
  function clubDir(pitch, yaw) {
    if (pitch == null || yaw == null) return null;
    for (var i = 0; i < CLUB_DIRS.length; i++) {
      var w = CLUB_WINDOWS[CLUB_DIRS[i]];
      if (pitch >= w[0] && pitch <= w[1] && yaw >= w[2] && yaw <= w[3]) return CLUB_DIRS[i];
    }
    return null;
  }
  /* Hướng dẫn xoay tới cửa sổ của hướng `dir`. Mũi tên theo MÀN HÌNH LẬT GƯƠNG: x=-1 sang trái màn hình, y=-1 lên. */
  function clubGuide(dir, pitch, yaw) {
    var w = CLUB_WINDOWS[dir], ax = 0, ay = 0, dx = 0, dy = 0;
    if (yaw < w[2]) { ax = -1; dx = w[2] - yaw; } else if (yaw > w[3]) { ax = 1; dx = yaw - w[3]; }
    if (pitch < w[0]) { ay = -1; dy = w[0] - pitch; } else if (pitch > w[1]) { ay = 1; dy = pitch - w[1]; }
    if (!ax && !ay) return { ok: true, arrow: { x: 0, y: 0 }, text: 'Giữ nguyên' };
    var txt;
    if (dx >= dy) txt = ax < 0 ? 'Quay sang TRÁI thêm' : 'Quay sang PHẢI thêm';
    else txt = ay < 0 ? 'Ngẩng thêm' : 'Cúi thêm';
    if (dir === 'front') txt = dx >= dy ? (ax < 0 ? 'Quay mặt lại gần giữa (hơi sang phải)' : 'Quay mặt lại gần giữa (hơi sang trái)') : (ay < 0 ? 'Ngẩng lên một chút' : 'Cúi xuống một chút');
    return { ok: false, arrow: { x: ax, y: ay }, text: txt };
  }

  /* Máy trạng thái 5 chặng. Mỗi chặng thu khung liên tục đến khi đủ `need` khung tốt (và đã giữ >= minDwell) hoặc hết `timeout`. */
  function ClubScan(opts) {
    opts = opts || {};
    this.order = (opts.order || CLUB_DIRS).slice();
    this.needFront = opts.needFront || 12; this.needOther = opts.needOther || 6;
    this.minDwell = opts.minDwell != null ? opts.minDwell : 1800; this.timeout = opts.timeout || 9000;
    this.weakBelow = opts.weakBelow || 3;
    this.idx = 0; this.got = {}; this.state = {}; this.t0 = null;
    var self = this; this.order.forEach(function (d) { self.got[d] = 0; self.state[d] = 'todo'; });
  }
  ClubScan.prototype.current = function () { return this.idx < this.order.length ? this.order[this.idx] : null; };
  ClubScan.prototype.finished = function () { return this.idx >= this.order.length; };
  ClubScan.prototype.need = function (d) { return d === 'front' ? this.needFront : this.needOther; };
  ClubScan.prototype.begin = function (now) { this.t0 = now; var d = this.current(); if (d) this.state[d] = 'active'; };
  ClubScan.prototype.progress = function () {
    var self = this, tot = 0, done = 0;
    this.order.forEach(function (d) { tot += self.need(d); done += Math.min(self.need(d), self.got[d]); });
    return tot ? done / tot : 1;
  };
  ClubScan.prototype.phaseProgress = function () { var d = this.current(); return d ? Math.min(1, this.got[d] / this.need(d)) : 1; };
  ClubScan.prototype.restartPhase = function (now) { var d = this.current(); if (d) { this.got[d] = 0; this.state[d] = 'active'; this.t0 = now; } };
  ClubScan.prototype.restartAll = function (now) { var self = this; this.idx = 0; this.order.forEach(function (d) { self.got[d] = 0; self.state[d] = 'todo'; }); this.begin(now); };
  ClubScan.prototype.redo = function (dirs, now) {   // chỉ làm lại các hướng yếu
    var self = this; this.order = dirs.slice(); this.idx = 0; this.got = {}; this.state = {};
    this.order.forEach(function (d) { self.got[d] = 0; self.state[d] = 'todo'; }); this.begin(now);
  };
  /* obs: kết quả server cho một khung {state, dir, pitch, yaw, kept}. Trả về {dir, hint, arrow, good, advanced, finished, phase}. */
  ClubScan.prototype.update = function (obs, now) {
    var d = this.current();
    if (!d) return { dir: null, finished: true, hint: '', arrow: { x: 0, y: 0 }, good: false, advanced: false };
    if (this.t0 == null) this.begin(now);
    var good = false, hint, arrow = { x: 0, y: 0 };
    if (obs && obs.state === 'ok' && obs.dir === d) {
      hint = 'Tốt, giữ nguyên'; if (obs.kept) { this.got[d]++; good = true; }
    } else if (obs && CLUB_STATE_TEXT[obs.state]) {
      hint = CLUB_STATE_TEXT[obs.state];
    } else if (obs && obs.pitch != null) {
      var g = clubGuide(d, obs.pitch, obs.yaw); hint = g.ok ? CLUB_TEXT[d] : g.text; arrow = g.arrow;
    } else hint = CLUB_TEXT[d];
    var el = now - this.t0, advanced = false;
    if ((this.got[d] >= this.need(d) && el >= this.minDwell)) { this.state[d] = 'done'; advanced = true; }
    else if (el >= this.timeout) { this.state[d] = this.got[d] >= this.weakBelow ? 'done' : 'weak'; advanced = true; }
    if (advanced) { this.idx++; this.t0 = now; var nd = this.current(); if (nd) this.state[nd] = 'active'; }
    return { dir: d, hint: hint, arrow: arrow, good: good, advanced: advanced, finished: this.finished(), phase: d };
  };

  function mix(a, b) { for (var k in b) a[k] = b[k]; return a; }

  /* Cò check-in cửa: đủ điều kiện "có người đến check-in" thì bắn một burst.
   * Điều kiện: một mặt đủ to (>= minWidth px trên khung đang gửi), nhìn khá thẳng, ổn định >= stableMs. */
  function DoorTrigger(opts) {
    opts = opts || {};
    this.minWidth = opts.minWidth || 90;
    this.stableMs = opts.stableMs || 700;
    this.maxYaw = opts.maxYaw || 35;
    this.maxDown = opts.maxDown || 25;
    this.cool = opts.cool || { checkin: 20000, checkout: 20000, already: 15000, unknown: 4000, no_usable_face: 2000 };
    this.since = null;
    this.until = 0;
  }
  DoorTrigger.prototype.update = function (face, nFaces, now) {
    if (now < this.until) return { state: 'cooldown', left: this.until - now };
    var ok = face && nFaces === 1 && face.width >= this.minWidth && Math.abs(face.yaw || 0) <= this.maxYaw &&
             Math.abs(face.pitch || 0) <= this.maxDown;
    if (!ok) {
      this.since = null;
      return { state: face ? (face.width < this.minWidth ? 'far' : (nFaces > 1 ? 'multi' : 'turned')) : 'idle' };
    }
    if (this.since == null) this.since = now;
    var p = clamp((now - this.since) / this.stableMs, 0, 1);
    if (p >= 1) { this.since = null; return { state: 'fire', progress: 1 }; }
    return { state: 'arming', progress: p };
  };
  DoorTrigger.prototype.result = function (status, now) {
    var ms = this.cool[status] != null ? this.cool[status] : 5000;
    this.until = now + ms; this.since = null;
  };

  return { clubDir: clubDir, clubGuide: clubGuide, ClubScan: ClubScan, CLUB_DIRS: CLUB_DIRS, CLUB_LABELS: CLUB_LABELS, CLUB_SHORT: CLUB_SHORT,
           CLUB_WINDOWS: CLUB_WINDOWS, CLUB_TARGETS: CLUB_TARGETS, CLUB_TEXT: CLUB_TEXT, CLUB_STATE_TEXT: CLUB_STATE_TEXT,
           binOf: binOf, cellOf: cellOf, plan: plan, guidance: guidance, dial: dial, targetDial: targetDial,
           Session: Session, DoorTrigger: DoorTrigger, Sweep: Sweep, scanCoverage: scanCoverage, SCAN_PRESETS: SCAN_PRESETS, sectorAt: sectorAt, sectorAngles: sectorAngles, REJECT_TEXT: REJECT_TEXT, PROFILES: PROFILES,
           YAW_NAMES: YAW_NAMES, PITCH_NAMES: PITCH_NAMES, YAW_LABEL: YAW_LABEL, PITCH_LABEL: PITCH_LABEL };
});
