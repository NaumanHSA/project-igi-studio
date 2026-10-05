import os, struct, tempfile, unittest

from studio.build import graphs as GE

# the 30-byte header of a shipped graph of 100 nodes (level 6's graph1.dat)
HEAD = bytes.fromhex("ccddeeff04e63a0d000005056400000004 0dde0f00000a000a0580380100".replace(" ", ""))


def template():
    f = tempfile.NamedTemporaryFile(suffix=".dat", delete=False)
    f.write(HEAD + GE.NO_ROUTE * (100 * 100))
    f.close()
    return f.name


class FreshGraphTests(unittest.TestCase):
    def setUp(self):
        self.path = template()

    def tearDown(self):
        os.unlink(self.path)

    def route(self, g, data, a, b):
        return struct.unpack_from("<if", data, GE.HEADER + (a * g.max_nodes + b) * 8)

    def test_a_chain_routes_both_ways_through_its_middle(self):
        pts = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 0.0)]
        g, ids, data = GE.fresh(self.path, pts, [(0, 1), (1, 2)], pts[0])
        self.assertEqual(ids, [1, 2, 3])
        self.assertEqual(self.route(g, data, 1, 3)[0], 2)       # 1 -> 3: the node before 3 is 2
        self.assertEqual(self.route(g, data, 3, 1)[0], 2)
        self.assertAlmostEqual(self.route(g, data, 1, 3)[1], 20 * GE.SCALE, delta=1)
        self.assertEqual(self.route(g, data, 2, 2), (-1, -1.0))  # the diagonal: no route, as shipped

    def test_it_reads_back_as_written(self):
        pts = [(5.0, 5.0, 1.0), (15.0, 5.0, 1.5), (15.0, 15.0, 2.0), (5.0, 15.0, 1.0)]
        g, ids, data = GE.fresh(self.path, pts, [(0, 1), (1, 2), (2, 3), (3, 0)], pts[0], radius=4.0)
        with open(self.path, "wb") as f:
            f.write(data)
        back = GE.Graph(self.path)
        self.assertEqual(len(back.nodes), 4)
        self.assertEqual(len(back.edges), 4)
        self.assertEqual(back.nodes[2]["x"], 10.0 * GE.SCALE)    # relative to the first point
        self.assertEqual(back.nodes[0]["radius"], 4.0)

    def test_a_long_route_grows_the_graph(self):
        pts = [(float(i) * 10, 0.0, 0.0) for i in range(150)]
        g, ids, data = GE.fresh(self.path, pts, [(i, i + 1) for i in range(149)], pts[0])
        self.assertEqual(g.max_nodes, 200)
        self.assertEqual(struct.unpack_from("<i", data, 12)[0], 200)            # capacity
        self.assertEqual(struct.unpack_from("<I", data, 26)[0], 200 * 200 * 8)  # the table's size


if __name__ == "__main__":
    unittest.main()
