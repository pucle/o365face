import unittest

import numpy as np

import _path  # noqa: F401
from common import enrollselect as es
from common import posebins as pb

RNG = np.random.default_rng(7)
DIRS = list(pb.CLUB_DIRS)


def unit(v):
    return v / np.linalg.norm(v)


def person(seed=1):
    return unit(np.random.default_rng(seed).normal(size=512)).astype(np.float32)


def cand(fid, d, base, noise=0.35, rng=RNG, **kw):
    pitch, yaw = pb.CLUB_TARGETS[d] if d else (0.0, 0.0)
    pitch += float(rng.normal(0, 3)); yaw += float(rng.normal(0, 3))
    e = unit(base + noise * unit(rng.normal(size=512))).astype(np.float32)
    c = dict(fid=fid, dir=d, pitch=pitch, yaw=yaw, det=0.9, width=140, blur=120.0, light=128.0,
             clipped=False, nfaces=1, emb=e)
    c.update(kw)
    return c


def session(per_dir=14, base=None, seed=3):
    rng = np.random.default_rng(seed)
    base = person(1) if base is None else base
    out, i = [], 0
    for d in DIRS:
        for _ in range(per_dir):
            out.append(cand(i, d, base, rng=rng)); i += 1
    return out


class ClubProfileTests(unittest.TestCase):
    def test_club_dir_windows(self):
        self.assertEqual(pb.club_dir(0, 0), "front")
        self.assertEqual(pb.club_dir(0, 45), "left")
        self.assertEqual(pb.club_dir(0, -45), "right")
        self.assertEqual(pb.club_dir(30, 0), "up")
        self.assertEqual(pb.club_dir(-30, 0), "down")
        self.assertIsNone(pb.club_dir(0, 20))           # giữa chính diện và trái: không thuộc hướng nào
        self.assertIsNone(pb.club_dir(None, 0))

    def test_counts_missing(self):
        c = pb.club_counts([(0, 0), (0, 0), (0, 45), (None, None)])
        self.assertEqual(c["front"], 2); self.assertEqual(c["left"], 1)
        self.assertIn("left", pb.club_missing(c)); self.assertIn("up", pb.club_missing(c))
        self.assertNotIn("front", pb.club_missing(c))


class SelectTests(unittest.TestCase):
    def test_count_in_range_and_quotas(self):
        for target in (20, 24, 30):
            r = es.select(session(), target)
            self.assertEqual(len(r["chosen"]), target)
            self.assertEqual(r["weak"], [])
            self.assertFalse(r["below_min"] and target >= 20)
            for d in DIRS:
                self.assertGreaterEqual(r["per_dir"][d], 2)
        r = es.select(session(), 24)
        self.assertEqual(r["quotas"], {"front": 8, "left": 4, "right": 4, "up": 4, "down": 4})
        self.assertEqual(r["per_dir"], r["quotas"])

    def test_target_clamped(self):
        self.assertEqual(len(es.select(session(), 5)["chosen"]), 20)
        self.assertEqual(len(es.select(session(), 99)["chosen"]), 30)
        self.assertEqual(sum(es.quotas(27).values()), 27)

    def test_missing_direction_reported(self):
        cs = [c for c in session() if c["dir"] != "down"]
        r = es.select(cs, 24)
        self.assertIn("down", r["weak"])
        self.assertEqual(r["per_dir"]["down"], 0)
        self.assertEqual(len(r["chosen"]), 24)           # bù từ hướng khác nhưng vẫn báo thiếu

    def test_not_enough_total(self):
        r = es.select(session(per_dir=3), 24)
        self.assertEqual(len(r["chosen"]), 15)
        self.assertTrue(r["below_min"])

    def test_rejections(self):
        cs = session(per_dir=6)
        cs[0]["nfaces"] = 2; cs[1]["clipped"] = True; cs[2]["det"] = 0.2; cs[3]["width"] = 30
        r = es.select(cs, 24)
        self.assertEqual(r["rejected"], {"multiple_faces": 1, "clipped": 1, "low_det": 1, "small": 1})
        fids = {c["fid"] for c in r["chosen"]}
        self.assertFalse({0, 1, 2, 3} & fids)

    def test_prefers_quality(self):
        cs = session(per_dir=14)
        good = [c for c in cs if c["dir"] == "front"][0]
        good["blur"] = 400.0; good["width"] = 220; good["det"] = 0.99
        bad = [c for c in cs if c["dir"] == "front"][1]
        bad["blur"] = 2.0
        r = es.select(cs, 24)
        fids = {c["fid"] for c in r["chosen"]}
        self.assertIn(good["fid"], fids)
        self.assertNotIn(bad["fid"], fids)

    def test_diversity_drops_near_duplicates(self):
        base = person(2)
        dup = [cand(i, "front", base, noise=0.0, rng=np.random.default_rng(1)) for i in range(10)]
        for c in dup:
            c["emb"] = base.copy()
        varied = [cand(100 + i, "front", base, noise=0.5, rng=np.random.default_rng(10 + i)) for i in range(10)]
        r = es.select(dup + varied, 24)
        n_dup = sum(1 for c in r["chosen"] if c["fid"] < 100)
        self.assertLessEqual(n_dup, 1)                   # chỉ giữ tối đa 1 trong các khung trùng hệt

    def test_other_dir_only_when_allowed(self):
        cs = session(per_dir=3) + [cand(500 + i, None, person(1), rng=np.random.default_rng(i)) for i in range(20)]
        self.assertEqual(len(es.select(cs, 24)["chosen"]), 15)
        self.assertEqual(len(es.select(cs, 24, allow_other=True)["chosen"]), 24)


class AddModeTests(unittest.TestCase):
    def test_existing_samples_are_not_duplicated(self):
        base = person(1)
        cs = session(per_dir=10, base=base, seed=5)
        first = es.select(cs, 24)["chosen"]
        again = es.select(cs, 24, existing=first)["chosen"]
        ids_first = {c["fid"] for c in first}
        # đăng ký lại cùng dữ liệu: các khung đã có (embedding trùng hệt) không được chọn lần nữa
        self.assertFalse(ids_first & {c["fid"] for c in again})
        self.assertGreaterEqual(len(again), 20)


class OutlierTests(unittest.TestCase):
    def test_drops_other_person(self):
        cs = session(per_dir=6)
        stranger = person(99)
        extra = [cand(900 + i, "front", stranger, noise=0.1, rng=np.random.default_rng(50 + i)) for i in range(4)]
        keep, drop = es.drop_outliers(cs + extra)
        self.assertEqual({c["fid"] for c in drop}, {900, 901, 902, 903})
        self.assertEqual(len(keep), len(cs))

    def test_extra_ref_helps_small_sessions(self):
        base = person(1)
        mine = [cand(i, "front", base, rng=np.random.default_rng(i)) for i in range(3)]
        other = [cand(10, "front", person(5), noise=0.05, rng=np.random.default_rng(77))]
        keep, drop = es.drop_outliers(mine + other, extra_ref=np.stack([base] * 5))
        self.assertEqual([c["fid"] for c in drop], [10])

    def test_empty_inputs(self):
        self.assertEqual(es.drop_outliers([]), ([], []))
        r = es.select([], 24)
        self.assertEqual(r["chosen"], []); self.assertTrue(r["below_min"]); self.assertEqual(len(r["weak"]), 5)

    def test_prune_keeps_diverse(self):
        base = person(3)
        cs = [cand(i, "front", base, noise=0.4, rng=np.random.default_rng(i)) for i in range(30)]
        out = es.prune(cs, 12)
        self.assertEqual(len(out), 12)


class AugmentDecisionTests(unittest.TestCase):
    def test_needs_augment(self):
        full = {d: 4 for d in DIRS}
        self.assertEqual(es.needs_augment(24, full, 0.8), (False, []))
        ok, why = es.needs_augment(15, full, 0.8)
        self.assertTrue(ok); self.assertIn("ít ảnh gốc", why[0])
        ok, why = es.needs_augment(24, {**full, "up": 0}, 0.8)
        self.assertTrue(ok); self.assertIn("Ngẩng", why[0])
        ok, why = es.needs_augment(24, full, 0.3)
        self.assertTrue(ok); self.assertIn("nhất quán", why[0])
        self.assertEqual(es.needs_augment(24, full, None)[0], False)

    def test_budget_ratio_and_cap(self):
        self.assertEqual(es.augment_budget(10), 5)
        self.assertEqual(es.augment_budget(24), 12)
        self.assertEqual(es.augment_budget(50), 10)      # trần tổng 60
        self.assertEqual(es.augment_budget(60), 0)
        self.assertEqual(es.augment_budget(24, {"aug_max_ratio": 0.0}), 0)

    def test_plan_deterministic_and_bounded(self):
        r = es.select(session(per_dir=3), 24)
        ch = r["chosen"]
        p1 = es.plan_augment(ch, r["per_dir"], 7, 100)
        p2 = es.plan_augment(ch, r["per_dir"], 7, 100)
        self.assertEqual(p1, p2)
        self.assertEqual(len(p1), 7)
        self.assertLessEqual(max(sum(1 for i, _ in p1 if i == j) for j in range(len(ch))), 3)
        self.assertTrue(all(k in es.KINDS for _, k in p1))
        self.assertEqual(es.plan_augment(ch, r["per_dir"], 0, 10), [])
        self.assertEqual(len(es.plan_augment(ch[:2], r["per_dir"], 50, 50)), 6)   # 2 ảnh × tối đa 3 biến thể

    def test_plan_favours_weak_direction(self):
        cs = session(per_dir=4)
        cs = [c for c in cs if c["dir"] != "up"] + [c for c in cs if c["dir"] == "up"][:1]
        r = es.select(cs, 20)
        first_idx, _ = es.plan_augment(r["chosen"], r["per_dir"], 3, 3)[0]
        self.assertEqual(r["chosen"][first_idx]["dir"], "up")

    def test_consistency(self):
        base = person(1)
        tight = [unit(base + 0.1 * unit(RNG.normal(size=512))) for _ in range(8)]
        loose = [person(s) for s in range(8)]
        self.assertGreater(es.consistency(tight), 0.9)
        self.assertLess(es.consistency(loose), 0.5)
        self.assertIsNone(es.consistency(tight[:2]))


class LooTests(unittest.TestCase):
    def test_pass_and_fail(self):
        base = person(1)
        own = np.stack([unit(base + 0.3 * unit(RNG.normal(size=512))) for _ in range(12)])
        dirs = [DIRS[i % 5] for i in range(12)]
        others = np.stack([person(s) for s in range(10, 20)])
        r = es.loo_check(own, dirs, others, 0.45, 0.08)
        self.assertTrue(r["ok"]); self.assertEqual(r["weak_dirs"], [])
        # một hướng "lạ" (embedding nhìn như người khác) -> khuyên bổ sung hướng đó
        own2 = own.copy()
        for i in range(12):
            if dirs[i] == "up":
                own2[i] = person(300 + i)
        r2 = es.loo_check(own2, dirs, others, 0.45, 0.08)
        self.assertFalse(r2["ok"]); self.assertEqual(r2["weak_dirs"][0], "up")
        self.assertIn("Ngẩng", r2["advice"])

    def test_too_few(self):
        self.assertFalse(es.loo_check(np.stack([person(1)] * 2), ["front"] * 2, None, 0.45, 0.08)["ok"])

    def test_impostor_close_fails(self):
        base = person(1)
        own = np.stack([unit(base + 0.2 * unit(RNG.normal(size=512))) for _ in range(10)])
        r = es.loo_check(own, ["front"] * 10, np.stack([base]), 0.45, 0.08)   # người khác trùng hệt
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
