// node tests/guide.test.js   (không cần thư viện; khớp với common/posebins.py qua tests/posebins_grid.json nếu có)
const assert = require('assert');
const fs = require('fs'), path = require('path');
const G = require('../server/static/guide.js');
let n = 0; const t = (name, f) => { f(); n++; console.log('ok  ' + name); };

t('cellOf: quy ước góc', () => {
  assert.deepStrictEqual(G.cellOf(0, 0), { p: 'level', y: 'C' });
  assert.deepStrictEqual(G.cellOf(-20, 0), { p: 'down1', y: 'C' });      // pitch âm = cúi
  assert.deepStrictEqual(G.cellOf(-35, 20), { p: 'down2', y: 'L1' });    // yaw dương = trái của người đó
  assert.deepStrictEqual(G.cellOf(-5, -45), { p: 'level', y: 'R2' });
  assert.deepStrictEqual(G.cellOf(15, 0), { p: 'up', y: 'C' });
});
t('cellOf khớp posebins.py trên lưới', () => {
  const f = path.join(__dirname, 'posebins_grid.json');
  if (!fs.existsSync(f)) { console.log('    (bỏ qua: chưa có posebins_grid.json)'); return; }
  for (const [pitch, yaw, p, y] of JSON.parse(fs.readFileSync(f))) assert.deepStrictEqual(G.cellOf(pitch, yaw), { p, y }, `${pitch},${yaw}`);
});
t('plan: door/room/full và useFlip', () => {
  assert.strictEqual(G.plan('door').length, 5);
  assert.strictEqual(G.plan('room').length, 6);
  assert.strictEqual(G.plan('full').length, 10);
  const q = G.plan('room', { useFlip: true });
  assert.deepStrictEqual(q.map(s => s.id), ['down1|C', 'down1|L1', 'down2|C', 'down2|L1']);
  assert.ok(G.plan('door', { useFlip: true }).every(s => s.y !== 'R1'));
  assert.ok(G.plan('door', { need: 5 }).every(s => s.need === 5));
});
t('guidance: hướng mũi tên', () => {
  const st = { p: 'level', y: 'L1' };
  assert.strictEqual(G.guidance(st, 0, 20).ok, true);
  let g = G.guidance(st, 0, 0);                       // cần quay trái
  assert.deepStrictEqual([g.ok, g.arrow.x, g.arrow.y], [false, -1, 0]);
  g = G.guidance(st, 0, 50);                          // quay quá, về phải
  assert.strictEqual(g.arrow.x, 1);
  const d = { p: 'down2', y: 'C' };
  g = G.guidance(d, 0, 0); assert.deepStrictEqual([g.arrow.x, g.arrow.y], [0, 1]); assert.match(g.text, /Cúi/);
  g = G.guidance({ p: 'level', y: 'C' }, -30, 0); assert.strictEqual(g.arrow.y, -1); assert.match(g.text, /Ngẩng/);
});
t('dial lật gương', () => {
  assert.strictEqual(G.dial(0, 25, true).x < 0, true);      // quay trái -> chấm sang trái màn hình
  assert.strictEqual(G.dial(0, 25, false).x > 0, true);
  assert.strictEqual(G.dial(-30, 0).y > 0, true);           // cúi -> chấm xuống
  assert.strictEqual(G.dial(0, 500).x, -1);
});
const face = (pitch, yaw, width = 150) => ({ pitch, yaw, width });
t('Session: giữ đủ lâu mới chụp, rồi sang bước tiếp', () => {
  const s = new G.Session(G.plan('door', { need: 2 }), { holdMs: 500, cooldownMs: 600 });
  let r = s.update({ face: face(0, 0), faces: 1 }, 0);
  assert.strictEqual(r.phase, 'hold');
  r = s.update({ face: face(0, 0), faces: 1 }, 400); assert.strictEqual(r.shot, false);
  r = s.update({ face: face(0, 0), faces: 1 }, 520); assert.strictEqual(r.shot, true);
  r = s.update({ face: face(0, 0), faces: 1 }, 540); assert.strictEqual(r.phase, 'saving');   // chờ server
  assert.strictEqual(s.result(true).advanced, false);
  // lần chụp thứ hai
  s.update({ face: face(0, 0), faces: 1 }, 1200); r = s.update({ face: face(0, 0), faces: 1 }, 1750);
  assert.strictEqual(r.shot, true);
  const res = s.result(true); assert.strictEqual(res.advanced, true);
  assert.strictEqual(s.current().id, 'level|L1');
});
t('Session: mất mặt / nhiều mặt / mặt nhỏ / sai góc đặt lại thời gian giữ', () => {
  const s = new G.Session(G.plan('door'), {});
  s.update({ face: face(0, 0), faces: 1 }, 0);
  assert.strictEqual(s.update({ face: null, faces: 0 }, 100).phase, 'noface');
  assert.strictEqual(s.update({ face: face(0, 0), faces: 2 }, 200).phase, 'multi');
  assert.strictEqual(s.update({ face: face(0, 0, 40), faces: 1 }, 300).phase, 'small');
  assert.strictEqual(s.update({ face: face(-30, 0), faces: 1 }, 400).phase, 'adjust');
  const r = s.update({ face: face(0, 0), faces: 1 }, 450); assert.strictEqual(r.phase, 'hold'); assert.ok(r.hold < 0.1);
});
t('Session: duplicate liên tiếp được tính là đủ, bị từ chối khác thì không', () => {
  const s = new G.Session([{ id: 'level|C', p: 'level', y: 'C', need: 2, text: '' }], { dupDone: 2 });
  s.pending = true; assert.strictEqual(s.result(false, 'blurry').counted, false);
  s.pending = true; s.result(true);
  s.pending = true; assert.strictEqual(s.result(false, 'duplicate').counted, false);
  s.pending = true; const r = s.result(false, 'duplicate');
  assert.strictEqual(r.counted, true); assert.strictEqual(r.finished, true);
  assert.strictEqual(s.progress(), 1);
});
t('Session: skip/back/restart/progress', () => {
  const s = new G.Session(G.plan('door', { need: 1 }), {});
  s.skip(); assert.strictEqual(s.idx, 1);
  s.back(); assert.strictEqual(s.idx, 0);
  s.pending = true; s.result(true); assert.ok(s.progress() > 0 && s.progress() < 1);
  s.restart(); assert.strictEqual(s.progress(), 0);
  for (let i = 0; i < 5; i++) s.skip();
  assert.strictEqual(s.finished(), true);
  assert.strictEqual(s.update({ face: face(0, 0), faces: 1 }, 0).phase, 'done');
});
t('DoorTrigger: cần ổn định, cooldown theo kết quả', () => {
  const d = new G.DoorTrigger({ minWidth: 90, stableMs: 700 });
  assert.strictEqual(d.update(null, 0, 0).state, 'idle');
  assert.strictEqual(d.update(face(0, 0, 50), 1, 100).state, 'far');
  assert.strictEqual(d.update(face(0, 60, 150), 1, 200).state, 'turned');
  assert.strictEqual(d.update(face(0, 0, 150), 2, 300).state, 'multi');
  assert.strictEqual(d.update(face(0, 0, 150), 1, 1000).state, 'arming');
  assert.strictEqual(d.update(face(0, 0, 150), 1, 1400).state, 'arming');
  assert.strictEqual(d.update(face(0, 0, 150), 1, 1750).state, 'fire');
  d.result('checkin', 1750);
  assert.strictEqual(d.update(face(0, 0, 150), 1, 5000).state, 'cooldown');
  assert.strictEqual(d.update(face(0, 0, 150), 1, 22000).state, 'arming');
  d.result('unknown', 22000);
  assert.strictEqual(d.update(face(0, 0, 150), 1, 27000).state, 'arming');
});

t('Sweep: vẽ vòng tròn phủ hết các cung rồi nghiêng đầu -> xong tầng', () => {
  const sw = new G.Sweep({ preset: 'quick' });          // 1 tầng, 12 cung
  let now = 0, shots = [], iter = 0;
  const feed = (pitch, yaw, roll = 0) => {
    now += 150; const r = sw.update({ face: { pitch, yaw, roll, width: 150 }, faces: 1 }, now);
    if (r.shot) { shots.push(r.shot.id); sw.result(r.shot.id, true); }
    return r;
  };
  feed(0, 0);                                           // tâm
  assert.ok(shots.includes('c0'));
  for (let a = 0; a < 2 * Math.PI * 1.1; a += 0.05) feed(-(22 * Math.sin(a)), -22 * Math.cos(a));   // vòng bán kính 22°
  assert.strictEqual(sw.stageFilled(0), 12);
  assert.strictEqual(sw.finished(), false);             // còn nghiêng
  feed(0, 0, 20); feed(0, 0, -20);
  assert.strictEqual(sw.finished(), true);
  assert.strictEqual(shots.length, sw.total());         // mỗi ô chụp đúng 1 lần (không chụp thừa)
  assert.strictEqual(sw.progress(), 1);
});
t('Sweep: kiểm tra hướng cung theo màn hình lật gương', () => {
  const a = G.sectorAt(0, 0, 25, 16, 9, 42);            // quay TRÁI người (yaw>0) -> trái màn hình (sx<0)
  assert.ok(a.sx < 0 && Math.abs(a.sy) < 1e-9);
  const b = G.sectorAt(0, -25, 0, 16, 9, 42);           // cúi -> xuống màn hình (sy>0)
  assert.ok(b.sy > 0);
  assert.strictEqual(G.sectorAt(0, 0, 3, 16, 9, 42).center, true);
  assert.strictEqual(G.sectorAt(0, 0, 60, 16, 9, 42).ring, false);     // quá xa
  assert.strictEqual(G.sectorAt(18, -18, 0, 16, 9, 42).center, true);  // tầng cúi 18°: tâm dịch xuống
});
t('Sweep: nhiều tầng, perCell=2 cần tư thế khác nhau, ràng buộc pending', () => {
  const sw = new G.Sweep({ preset: 'thorough' });
  assert.deepStrictEqual(sw.stages, [0, 18, 34]);
  assert.strictEqual(sw.total(), 3 * 17 * 2 + 4);
  let r = sw.update({ face: { pitch: 0, yaw: 0, roll: 0, width: 150 }, faces: 1 }, 1000);
  assert.strictEqual(r.shot.id, 'c0');
  r = sw.update({ face: { pitch: 0, yaw: 0, roll: 0, width: 150 }, faces: 1 }, 1300); assert.strictEqual(r.shot, null);   // đang chờ kết quả
  sw.result('c0', true);
  r = sw.update({ face: { pitch: 0, yaw: 0.5, roll: 0, width: 150 }, faces: 1 }, 1600); assert.strictEqual(r.shot, null); // chưa khác tư thế
  r = sw.update({ face: { pitch: -4, yaw: 0, roll: 0, width: 150 }, faces: 1 }, 1900); assert.strictEqual(r.shot && r.shot.id, 'c0');
});
t('Sweep: bị từ chối nhiều lần thì bỏ qua ô; duplicate tính là đủ; skipStage', () => {
  const sw = new G.Sweep({ preset: 'quick', maxTries: 3 });
  for (let i = 0; i < 3; i++) { sw.pending.c0 = true; sw.result('c0', false, 'blurry'); }
  assert.strictEqual(sw.center[0], 1); assert.ok(sw.skipped.c0);
  sw.pending.r0_0 = true; sw.result('r0_0', false, 'duplicate'); assert.strictEqual(sw.ring[0][0], 1);
  sw.skipStage(); assert.strictEqual(sw.finished(), true);
  assert.strictEqual(sw.update({ face: null, faces: 0 }, 0).phase, 'done');
});
t('Sweep: không thấy mặt / nhiều mặt / quá nhỏ', () => {
  const sw = new G.Sweep({});
  assert.strictEqual(sw.update({ face: null, faces: 0 }, 0).phase, 'noface');
  assert.strictEqual(sw.update({ face: { pitch: 0, yaw: 0, width: 150 }, faces: 2 }, 0).phase, 'multi');
  assert.strictEqual(sw.update({ face: { pitch: 0, yaw: 0, width: 20 }, faces: 1 }, 0).phase, 'small');
});
t('clubDir khớp posebins.club_dir trên lưới', () => {
  const f = path.join(__dirname, 'posebins_grid.json');
  for (const [pitch, yaw, , , club] of JSON.parse(fs.readFileSync(f))) assert.strictEqual(G.clubDir(pitch, yaw), club, `${pitch},${yaw}`);
  assert.strictEqual(G.clubDir(null, 0), null);
});
t('club: cửa sổ khớp Python (hằng số)', () => {
  const py = require('child_process').execFileSync('python3', ['-c',
    "import sys,json;sys.path.insert(0,'.');from common import posebins as p;print(json.dumps({'w':p.CLUB_WINDOWS,'t':p.CLUB_TARGETS,'d':p.CLUB_DIRS,'l':p.CLUB_LABELS}))"], { cwd: path.join(__dirname, '..') });
  const j = JSON.parse(py);
  assert.deepStrictEqual(G.CLUB_DIRS, j.d); assert.deepStrictEqual(G.CLUB_WINDOWS, j.w);
  assert.deepStrictEqual(G.CLUB_TARGETS, j.t); assert.deepStrictEqual(G.CLUB_LABELS, j.l);
});
t('clubGuide: mũi tên theo màn hình lật gương', () => {
  let g = G.clubGuide('left', 0, 0);  assert.deepStrictEqual([g.ok, g.arrow.x, g.arrow.y], [false, -1, 0]); assert.match(g.text, /TRÁI/);
  g = G.clubGuide('right', 0, 0);     assert.strictEqual(g.arrow.x, 1);
  g = G.clubGuide('up', 0, 0);        assert.deepStrictEqual([g.arrow.x, g.arrow.y], [0, -1]); assert.match(g.text, /Ngẩng/);
  g = G.clubGuide('down', 0, 0);      assert.strictEqual(g.arrow.y, 1);
  g = G.clubGuide('left', 0, 90);     assert.strictEqual(g.arrow.x, 1);                    // quay quá: về lại
  assert.strictEqual(G.clubGuide('front', 0, 3).ok, true);
});
t('ClubScan: 5 chặng tuần tự, cần đủ khung tốt và thời gian giữ tối thiểu', () => {
  const sc = new G.ClubScan({}); sc.begin(0);
  assert.strictEqual(sc.current(), 'front');
  const T = (d) => G.CLUB_TARGETS[d];
  const good = (d, kept = true) => ({ state: 'ok', dir: d, pitch: T(d)[0], yaw: T(d)[1], kept });
  let t = 0, r;
  for (let i = 0; i < 12; i++) { t += 50; r = sc.update(good('front'), t); }
  assert.strictEqual(r.advanced, false);                          // đủ 12 khung nhưng mới 600 ms < minDwell
  t = 1900; r = sc.update(good('front'), t);
  assert.strictEqual(r.advanced, true); assert.strictEqual(sc.current(), 'left');
  for (const d of ['left', 'right', 'up', 'down']) {
    for (let i = 0; i < 6; i++) sc.update(good(d), t += 400);
    r = sc.update(good(d), t += 400);
    assert.strictEqual(sc.state[d], 'done', d);
  }
  assert.strictEqual(sc.finished(), true); assert.strictEqual(sc.progress(), 1);
});
t('ClubScan: khung không được giữ / sai hướng không tính; hết giờ thì đánh dấu yếu', () => {
  const sc = new G.ClubScan({ timeout: 3000 }); sc.begin(0);
  let r = sc.update({ state: 'ok', dir: 'front', pitch: 0, yaw: 0, kept: false }, 100); assert.strictEqual(sc.got.front, 0);
  r = sc.update({ state: 'ok', dir: 'left', pitch: 0, yaw: 40, kept: true }, 200); assert.strictEqual(sc.got.front, 0);
  assert.strictEqual(r.arrow.x, 1);                                // đang quay trái trong khi cần thẳng -> về phải
  r = sc.update({ state: 'no_face' }, 300); assert.match(r.hint, /chưa thấy mặt/i);
  r = sc.update({ state: 'multi' }, 400); assert.match(r.hint, /2 người/);
  r = sc.update({ state: 'no_face' }, 3500);
  assert.strictEqual(r.advanced, true); assert.strictEqual(sc.state.front, 'weak');
  assert.strictEqual(sc.current(), 'left');
});
t('ClubScan: làm lại hướng yếu / làm lại chặng / làm lại từ đầu', () => {
  const sc = new G.ClubScan({}); sc.begin(0);
  sc.got.front = 5; sc.restartPhase(10); assert.strictEqual(sc.got.front, 0);
  sc.redo(['up', 'down'], 20); assert.deepStrictEqual(sc.order, ['up', 'down']); assert.strictEqual(sc.current(), 'up');
  assert.ok(Math.abs(sc.phaseProgress()) < 1e-9);
  sc.restartAll(30); assert.strictEqual(sc.current(), 'up');
});
console.log(`\n${n} nhóm test đạt`);
