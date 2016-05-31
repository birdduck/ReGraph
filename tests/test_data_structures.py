"""Test data structures of graph rewriting."""

from nose.tools import assert_equals
from nose.tools import raises

from regraph.library.data_structures import TypedDiGraph
from regraph.library.data_structures import Homomorphism

from regraph.library.primitives import cast_node, remove_edge


class TestDataStructures(object):
    """Class for testing data structures with Python nose tests."""

    def __init__(self):
        self.graph_ = TypedDiGraph()
        self.graph_.add_node(1, 'agent',
                             {'name': 'EGFR', 'state': 'p'})
        self.graph_.add_node(2, 'action', attrs={'name': 'BND'})
        self.graph_.add_node(3, 'agent',
                             {'name': 'Grb2', 'aa': 'S', 'loc': 90})
        self.graph_.add_node(4, 'region', attrs={'name': 'SH2'})
        self.graph_.add_node(5, 'agent', attrs={'name': 'EGFR'})
        self.graph_.add_node(6, 'action', attrs={'name': 'BND'})
        self.graph_.add_node(7, 'agent', attrs={'name': 'Grb2'})

        self.graph_.add_node(8, 'agent', attrs={'name': 'WAF1'})
        self.graph_.add_node(9, 'action', {'name': 'BND'})
        self.graph_.add_node(10, 'agent', {'name': 'G1-S/CDK', 'state': 'p'})

        self.graph_.add_node(11, 'agent')
        self.graph_.add_node(12, 'agent')
        self.graph_.add_node(13, 'agent')

        edges = [
            (1, 2),
            (4, 2),
            (4, 3),
            (5, 6),
            (7, 6),
            (8, 9),
            (10, 9),
            (11, 12),
            (12, 11),
            (12, 13),
            (13, 12),
            (11, 13),
            (13, 11),
            (5, 2)
        ]

        self.graph_.add_edges_from(edges)

        # later you can add some attributes to the edge

        self.graph_.set_edge(1, 2, {'s': 'p'})
        self.graph_.set_edge(4, 2, {'s': 'u'})
        self.graph_.set_edge(5, 6, {'s': 'p'})
        self.graph_.set_edge(7, 6, {'s': 'u'})
        self.graph_.set_edge(5, 2, {'s': 'u'})

        self.LHS_ = TypedDiGraph()

        self.LHS_.add_node(1, 'agent', {'name': 'EGFR'})
        self.LHS_.add_node(2, 'action', {'name': 'BND'})
        self.LHS_.add_node(3, 'region')
        self.LHS_.add_node(4, 'agent', {'name': 'Grb2'})
        self.LHS_.add_node(5, 'agent', {'name': 'EGFR'})
        self.LHS_.add_node(6, 'action', {'name': 'BND'})
        self.LHS_.add_node(7, 'agent', {'name': 'Grb2'})

        self.LHS_.add_edges_from([(1, 2), (3, 2), (3, 4), (5, 6), (7, 6)])

        self.LHS_.set_edge(1, 2, {'s': 'p'})
        self.LHS_.set_edge(5, 6, {'s': 'p'})


    def test_homorphism_init(self):
        # Test homomorphisms functionality
        mapping = {1: 1,
                   2: 2,
                   3: 4,
                   4: 3,
                   5: 5,
                   6: 6,
                   7: 7}
        Homomorphism(self.LHS_, self.graph_, mapping)

    @raises(ValueError)
    def test_homomorphism_not_covered(self):
        mapping = {1: 1,
                   2: 2,
                   3: 4,
                   4: 3,
                   5: 5,
                   6: 6}
        Homomorphism(self.LHS_, self.graph_, mapping)

    @raises(ValueError)
    def test_homomorphism_type_mismatch(self):
        mapping = {1: 1,
                   2: 2,
                   3: 4,
                   4: 3,
                   5: 5,
                   6: 6,
                   7: 7}
        cast_node(self.LHS_, 1, 'other_type')
        Homomorphism(self.LHS_, self.graph_, mapping)

    @raises(ValueError)
    def test_homomorphism_attributes_mismatch(self):
        mapping = {1: 1,
                   2: 2,
                   3: 4,
                   4: 3,
                   5: 5,
                   6: 6,
                   7: 7}
        self.LHS_.node[1].attrs_.update({'new_attr': 0})
        Homomorphism(self.LHS_, self.graph_, mapping)

    @raises(ValueError)
    def test_homomorphism_connectivity_fails(self):
        mapping = {1: 1,
                   2: 2,
                   3: 4,
                   4: 3,
                   5: 5,
                   6: 6,
                   7: 7}
        remove_edge(self.graph_, 4, 5)
        Homomorphism(self.LHS_, self.graph_, mapping)

    @raises(ValueError)
    def test_homomorphism_edge_attributes_mismatch(self):
        mapping = {1: 1,
                   2: 2,
                   3: 4,
                   4: 3,
                   5: 5,
                   6: 6,
                   7: 7}
        self.LHS_.edge[5][6].update({'new_attr': 0})
        Homomorphism(self.LHS_, self.graph_, mapping)

    def test_homomorphism(self):
        new_pattern = TypedDiGraph()
        new_pattern.add_node(34, "agent")
        new_pattern.add_node(35, "agent")
        new_pattern.add_node(36, "action")
        new_pattern.add_edges_from([(34, 36), (35, 36)])
        mapping = {34: 5,
                   35: 5,
                   36: 6}
        h = Homomorphism(new_pattern, self.graph_, mapping)
        assert_equals(h.is_monic(), False)