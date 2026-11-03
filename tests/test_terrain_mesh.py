"""The terrain mesh the studio builds again (studio/build/terrain_mesh.py), held to
what the game's own cubes are like, so it draws without holes. Two ways it did not,
found 2026-11-03 as pale sheets of sky in a mission whose camp was levelled:
a mirrored cube of the level's, rewritten, kept the game's strips with its faces
turned round; and cut points inside a cube's square were fixed, so faces turned
over as the cube was seen from further off."""
import pathlib, unittest

from studio.build import terrain_mesh as T

LEVEL2 = pathlib.Path("D:/IGI1/missions/location0/level2/terrain")


def inside(v):
    return not (v[0] in (0, 48) or v[1] in (0, 48))


def far(m):
    """Every sliding point merged into its fixed one."""
    return T.Mesh([m.verts[v[4]] if i >= m.nfixed else v for i, v in enumerate(m.verts)], m.nfixed, m.tris)


def covered(meshes):
    """How much of the square the faces cover, looking down: 1 is all of it once."""
    total = 0
    for m in meshes:
        for a, b, c, _ in m.tris:
            total += abs(T._area2(m.verts[a], m.verts[b], m.verts[c]))
    return total / (48 * 48 * 2.0)


class MirrorTests(unittest.TestCase):
    def mesh(self):
        # the game's own plain cube: eight faces in two strips
        verts = [[x, y, 20, 0, T.SLIDE9.get(k, 0)] for k, (x, y) in enumerate(T.GRID9)]
        return T.Mesh(verts, 4, [[a, b, c, T.STRIP8[i]] for i, (a, b, c) in enumerate(T.TRIS8)])

    def test_a_mirrored_cube_turned_round_draws_each_face_on_its_own(self):
        for trans in range(8):
            m = T.oriented(self.mesh(), trans)
            for a, b, c, _ in m.tris:
                self.assertGreater(T._area2(m.verts[a], m.verts[b], m.verts[c]), 0, "transform %d: a face faces down" % trans)
            if trans & 4:
                self.assertEqual({t[3] for t in m.tris}, {0xF0}, "transform %d keeps strips" % trans)
            else:
                self.assertEqual([t[3] for t in m.tris], list(T.STRIP8), "transform %d lost its strips" % trans)


class CutCubeTests(unittest.TestCase):
    # the ground rising through the ceiling of the cube below and on into the one
    # above: three corners low, one high, the middle in between
    Z9_LOW = [10, 30, 20, 90, 20, 15, 60, 55, 40]

    def cubes(self, z9):
        s = T.step3(T.LEAF)
        z3 = [z * s for z in z9]
        below = T.cube_mesh(z3, 0, T.LEAF)
        above = T.cube_mesh(z3, 48 * s, T.LEAF)
        return below, above

    def test_no_fixed_point_inside_the_square(self):
        for m in self.cubes(self.Z9_LOW):
            self.assertIsNotNone(m)
            self.assertEqual([v[:3] for v in m.verts[:m.nfixed] if inside(v)], [])

    def test_no_face_turns_over_from_far_off(self):
        for m in self.cubes(self.Z9_LOW):
            self.assertEqual(T.far_flips(m), [])

    def test_the_two_cubes_cover_the_square_near_and_far(self):
        below, above = self.cubes(self.Z9_LOW)
        self.assertAlmostEqual(covered([below, above]), 1.0, places=2)
        self.assertAlmostEqual(covered([far(below), far(above)]), 1.0, places=2)

    def test_many_shapes(self):
        """Many ways the nine heights can cross the plane between two cubes: all
        of the square is covered, no face turns over from far off, and every fixed
        point is on the square's edge. (How much is covered once every point has
        merged is not held to here: for made-up shapes like these the studio left
        as much open before the change as after, and the game's own level and a
        rebuilt camp are covered whole.)"""
        import itertools
        s = T.step3(T.LEAF)
        bad = []
        for z9 in itertools.product((14, 34, 62, 82), repeat=4):
            z = list(z9) + [(z9[0] + z9[1]) // 2, (z9[0] + z9[2]) // 2, (z9[1] + z9[3]) // 2, (z9[2] + z9[3]) // 2,
                            sum(z9) // 4]
            z = [z[0], z[1], z[2], z[3], z[5], z[4], z[6], z[7], z[8]]
            if any(v % 48 == 0 for v in z):
                continue                # settle never leaves a point on a floor, where it is in both cubes
            ms = [m for m in (T.cube_mesh([v * s for v in z], 0, T.LEAF), T.cube_mesh([v * s for v in z], 48 * s, T.LEAF)) if m]
            near_cov, far_cov = covered(ms), covered([far(m) for m in ms])
            flips = sum(len(T.far_flips(m)) for m in ms)
            fixed_in = sum(1 for m in ms for v in m.verts[:m.nfixed] if inside(v))
            if abs(near_cov - 1) > 0.01 or flips or fixed_in:
                bad.append((z9, round(near_cov, 3), round(far_cov, 3), flips, fixed_in))
        self.assertEqual(bad, [])


@unittest.skipUnless((LEVEL2 / "terrain.ctr").exists(), "no game here")
class LevelTests(unittest.TestCase):
    def test_a_levelled_area_on_level_2(self):
        """The mission where it was found: a camp levelled on a slope under a cliff."""
        tree0 = T.Tree.load(LEVEL2)
        gi0, gi1, gj0, gj1 = 30690 // 4, 30830 // 4, -9300 // 4, -9200 // 4
        own = T.Heights(tree0, (gi0 - 2, gi1 + 2, gj0 - 2, gj1 + 2))
        flat = 42828.1 * 4096 * 3
        targets = {(i, j): flat for i in range(gi0, gi1 + 1) for j in range(gj0, gj1 + 1) if own(i, j) is not None}
        moved = T.settle(targets, own)
        tree1, rep = T.rebuild(tree0, own, moved)
        old = set(bytes(tree0.cmd[n[4]:n[4] + T.Mesh.size_at(tree0.cmd, n[4])]) for n in tree0.nodes[1:])
        new = [m for m in (tree1.mesh(i) for i in range(1, len(tree1.nodes))) if m.encode() not in old]
        self.assertGreater(len(new), 50)
        self.assertEqual(sum(1 for m in new for v in m.verts[:m.nfixed] if inside(v) and
                             any(not inside(u) for u in m.verts[:m.nfixed])), 0)
        self.assertEqual(sum(len(T.far_flips(m)) for m in new), 0)
        x0, x1, y0, y1 = [v * T.GRID for v in (gi0 - 4, gi1 + 4, gj0 - 4, gj1 + 4)]
        self.assertEqual(dict(T.seams(tree1, gi0 - 4, gi1 + 4, gj0 - 4, gj1 + 4)).get("sides", 0),
                         dict(T.seams(tree0, gi0 - 4, gi1 + 4, gj0 - 4, gj1 + 4)).get("sides", 0))


if __name__ == "__main__":
    unittest.main()
