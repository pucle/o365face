import unittest

import numpy as np

import _path  # noqa: F401
from common import enrollselect as es
from common import posebins as pb
from server import augment, enrolling


def emb(seed, noise=0.3, base=1):
    b = np.random.default_rng(base).normal(size=512)
    v = b / np.linalg.norm(b) + noise * np.random.default_rng(seed).normal(size=512) / 22
    return (v / np.linalg.norm(v)).astype(np.float32)


def cand(seed, d="front"):
    p, y = pb.CLUB_TARGETS[d]
    return dict(dir=d, pitch=p, yaw=y, det=0.9, width=140, blur=100.0, light=128.0, clipped=False, nfaces=1, emb=emb(seed))


class SessionTests(unittest.TestCase):
    def test_pool_cap_prunes_and_clears_pending(self):
        s = enrolling.Session("m", "M", "add", "live", "door")
        s.pending = {"x": 1}
        for i in range(enrolling.POOL_CAP_LIVE + 10):
            s.add(cand(i), {})
        self.assertEqual(len(s.pool["front"]), enrolling.POOL_CAP_LIVE)
        self.assertIsNone(s.pending)
        self.assertEqual(s.counts()["front"], enrolling.POOL_CAP_LIVE)
        self.assertEqual(s.total(), enrolling.POOL_CAP_LIVE)

    def test_reset_by_direction(self):
        s = enrolling.Session("m", "M", "add", "live", "door")
        for d in ("front", "left"):
            s.add(cand(1, d), {})
        s.reset("left")
        self.assertEqual((s.counts()["front"], s.counts()["left"]), (1, 0))
        s.reset()
        self.assertEqual(s.total(), 0)

    def test_centroid(self):
        s = enrolling.Session("m", "M", "add", "live", "door")
        self.assertIsNone(s.centroid())
        for i in range(5):
            s.add(cand(i), {})
        self.assertAlmostEqual(float(np.linalg.norm(s.centroid())), 1.0, places=4)

    def test_store_ttl_and_cap(self):
        st = enrolling.SessionStore(ttl=10, max_sessions=2)
        a = st.create("a", "A", "add", "live", "door")
        b = st.create("b", "B", "add", "live", "door")
        c = st.create("c", "C", "add", "live", "door")           # đầy -> bỏ phiên cũ nhất
        self.assertEqual(len(st.items), 2)
        self.assertIsNone(st.items.get(a.sid))
        self.assertEqual(st.sweep(now=c.touched + 100), 2)        # quá TTL -> dọn hết
        self.assertIsNone(st.get(b.sid))
        d = st.create("d", "D", "add", "live", "door")
        self.assertTrue(st.delete(d.sid)); self.assertFalse(st.delete(d.sid))

    def test_other_scores(self):
        mat = np.stack([emb(1, base=5), emb(2, base=6)])
        sc, who = enrolling.other_scores(np.stack([mat[1]]), mat, ["x", "y"])
        self.assertEqual(who, ["y"]); self.assertGreater(sc[0], 0.99)
        sc, who = enrolling.other_scores(np.stack([mat[1]]), np.zeros((0, 512), np.float32), [])
        self.assertEqual(who, [None])

    def test_normalize_caps_long_side(self):
        big = np.zeros((2000, 3000, 3), np.uint8)
        self.assertEqual(max(enrolling.normalize(big).shape[:2]), enrolling.POOL_MAX_SIDE)
        small = np.zeros((300, 400, 3), np.uint8)
        self.assertIs(enrolling.normalize(small), small)


class AugmentTests(unittest.TestCase):
    def setUp(self):
        self.img = np.random.default_rng(0).integers(0, 255, (240, 240, 3), dtype=np.uint8)
        self.kps = np.array([[90, 100], [150, 100], [120, 130], [100, 165], [140, 165]], dtype=np.float32)
        self.bbox = (60, 60, 180, 200)

    def test_seed_reproducible_for_all_kinds(self):
        for k in augment.KINDS:
            a, ka = augment.apply(self.img, self.kps, self.bbox, k, 7)
            b, kb = augment.apply(self.img, self.kps, self.bbox, k, 7)
            self.assertTrue((a == b).all(), k); self.assertTrue(np.allclose(ka, kb), k)
            self.assertEqual(a.shape, self.img.shape)

    def test_different_seed_differs_for_random_kinds(self):
        a, _ = augment.apply(self.img, self.kps, self.bbox, "noise", 1)
        b, _ = augment.apply(self.img, self.kps, self.bbox, "noise", 2)
        self.assertFalse((a == b).all())

    def test_does_not_modify_input(self):
        before = self.img.copy()
        augment.apply(self.img, self.kps, self.bbox, "occ_mask", 1)
        self.assertTrue((before == self.img).all())

    def test_geometric_kinds_move_keypoints_slightly(self):
        for k in ("rot_p", "rot_n", "scale"):
            _, kp = augment.apply(self.img, self.kps, self.bbox, k, 3)
            d = np.abs(kp - self.kps).max()
            self.assertGreater(d, 0.1, k); self.assertLess(d, 25, k)             # nhẹ: không "bẻ" tư thế

    def test_photometric_keeps_keypoints(self):
        for k in ("bright", "dark", "noise", "lowres", "blur", "occ_left", "occ_top"):
            _, kp = augment.apply(self.img, self.kps, self.bbox, k, 3)
            self.assertTrue(np.allclose(kp, self.kps), k)

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            augment.apply(self.img, self.kps, self.bbox, "warp3d", 1)

    def test_kinds_match_selector(self):
        self.assertEqual(tuple(augment.KINDS), tuple(es.KINDS))

    def test_seed_for_is_stable(self):
        self.assertEqual(augment.seed_for("a", 1, "x"), augment.seed_for("a", 1, "x"))
        self.assertNotEqual(augment.seed_for("a", 1, "x"), augment.seed_for("a", 2, "x"))


import cv2


class FakeEngine:
    """embed_with_kps giả: bản lật = embedding gốc; bad_aug=True thì mọi bản augment có cosine thấp so với ảnh gốc."""
    def __init__(self, bad_aug=False):
        self.calls = []
        self.bad_aug = bad_aug

    def embed_with_kps(self, img, kps, flip=False):
        self.calls.append(flip)
        if not flip and self.bad_aug:
            return emb(999, noise=40)                      # gần như ngẫu nhiên -> cosine thấp so với ảnh gốc
        return emb(1)


def full_cand(i, d="front", seed=None):
    c = cand(seed if seed is not None else i, d)
    img = np.full((120, 120, 3), 100, np.uint8)
    c.update(jpg=cv2.imencode(".jpg", img)[1].tobytes(), kps=np.array([[40, 50], [80, 50], [60, 70], [45, 90], [75, 90]], np.float32),
             bbox=(20, 20, 100, 110))
    return c


def make_session(n, kind="dataset", dirs=("front",)):
    s = enrolling.Session("m", "M", "add", kind, "door")
    for i in range(n):
        s.add(full_cand(i, dirs[i % len(dirs)]), {})
    return s


CFG = {"target": 24, "min_per_dir": 2, "min_real": 20, "aug_min_cos": 0.6, "aug_max_ratio": 0.5, "aug_cap_total": 60,
       "outlier_cos": 0.3, "min_det": 0.5, "min_w": 50, "min_blur": 5}
NOMAT = np.zeros((0, 512), np.float32)


class PlanTests(unittest.TestCase):
    def plan(self, sess, own=None, mat=NOMAT, ids=None, bad_aug=False, **opts):
        o = {"flip": True, "augment": "auto", "verify": True}; o.update(opts)
        return enrolling.build_plan(sess, FakeEngine(bad_aug), CFG, own or [], mat, ids or [], {}, o, 150, 0.45, 0.08)

    def test_dataset_few_samples_triggers_marked_augmentation_with_cap(self):
        r = self.plan(make_session(12, dirs=("front", "left", "right")))
        rep, rows = r["report"], r["rows"]
        aug_rows = [x for x in rows if "+aug-" in x["step"]]
        flip_rows = [x for x in rows if x["step"].endswith("+flip")]
        real_rows = [x for x in rows if "+" not in x["step"]]
        self.assertEqual(len(real_rows), rep["kept"]); self.assertEqual(len(flip_rows), rep["kept"])
        self.assertTrue(rep["augmented"]); self.assertGreater(len(aug_rows), 0)
        self.assertLessEqual(len(aug_rows), int(0.5 * rep["kept"]))           # trần 50% số mẫu gốc
        self.assertEqual(rep["aug"], len(aug_rows))
        self.assertTrue(all(x["step"].startswith("club-") for x in rows))
        self.assertFalse(rep["ok"]); self.assertIn("Nên bổ sung", rep["verdict"])

    def test_no_augmentation_when_enough_real_samples(self):
        sess = make_session(0)
        for d in pb.CLUB_DIRS:
            for i in range(8):
                sess.add(full_cand(100 + i + 10 * len(d), d, seed=100 + i + 10 * pb.CLUB_DIRS.index(d)), {})
        r = self.plan(sess)
        self.assertEqual(r["report"]["kept"], 24)
        self.assertFalse(r["report"]["augmented"]); self.assertEqual(r["report"]["aug"], 0)
        self.assertEqual(r["report"]["per_dir"], {"front": 8, "left": 4, "right": 4, "up": 4, "down": 4})

    def test_live_session_never_augments_by_default(self):
        r = self.plan(make_session(8, kind="live"))
        self.assertEqual(r["report"]["aug"], 0)
        self.assertFalse(any("+aug-" in x["step"] for x in r["rows"]))

    def test_augment_off_and_force(self):
        self.assertEqual(self.plan(make_session(8), augment="off")["report"]["aug"], 0)
        self.assertGreater(self.plan(make_session(8, kind="live"), augment="force")["report"]["aug"], 0)

    def test_low_cosine_augmentation_is_dropped(self):
        r = self.plan(make_session(8), bad_aug=True)
        self.assertEqual(r["report"]["aug"], 0)
        self.assertGreater(r["report"]["aug_dropped"].get("low_cos", 0), 0)

    def test_augmentation_that_looks_like_other_member_is_dropped(self):
        mat = np.stack([emb(1)])                                 # FakeEngine trả emb(1) cho mọi bản augment
        r = self.plan(make_session(8), mat=mat, ids=["other"], verify=False)
        self.assertEqual(r["report"]["aug"], 0)
        self.assertGreater(r["report"]["aug_dropped"].get("looks_like_other", 0), 0)

    def test_session_of_other_person_is_blocked(self):
        sess = make_session(10)
        r = self.plan(sess, mat=np.stack([emb(0)]), ids=["other"])
        self.assertEqual(r["rows"], [])
        self.assertEqual(r["report"]["kept"], 0)
        self.assertGreaterEqual(r["report"]["rejected"].get("looks_like_other", 0), 1)

    def test_add_mode_counts_existing_and_replace_ignores_it(self):
        own = [{"emb": emb(500 + i), "pitch": 0.0, "yaw": 0.0, "step": "club-front", "img": f"o{i}"} for i in range(5)]
        add = self.plan(make_session(10), own=own, augment="off")["report"]
        self.assertEqual(add["existing_real"], 5); self.assertEqual(add["total_real"], add["kept"] + 5)
        sess = make_session(10); sess.mode = "replace"
        rep = self.plan(sess, own=own, augment="off")["report"]
        self.assertEqual(rep["existing_real"], 0)

    def test_derived_existing_samples_do_not_count_as_real(self):
        own = [{"emb": emb(600 + i), "pitch": 0.0, "yaw": 0.0, "step": "club-front+aug-bright", "img": f"a{i}"} for i in range(5)]
        rep = self.plan(make_session(6), own=own, augment="off")["report"]
        self.assertEqual(rep["existing_real"], 0)

    def test_empty_session(self):
        r = self.plan(make_session(0))
        self.assertEqual(r["rows"], []); self.assertFalse(r["report"]["ok"])


if __name__ == "__main__":
    unittest.main()
