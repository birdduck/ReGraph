"""Neo4j driver for regraph."""
import time
import os
import json
import copy
import networkx as nx

from neo4j.v1 import GraphDatabase
from neo4j.exceptions import ConstraintError

from . import graphs
from . import cypher_utils as cypher
from regraph.exceptions import (HierarchyError,
                                InvalidHomomorphism,
                                RewritingError,
                                ReGraphError)
from regraph.utils import (normalize_attrs,
                           keys_by_value,
                           normalize_typing_relation,
                           attrs_from_json,
                           attrs_to_json)


class Neo4jHierarchy(object):
    """Class implementing Neo4j-based graph hierarchy.

    Skeleton + fused data graph

    Attributes
    ----------
    _driver : neo4j.v1.GraphDatabase
        Driver providing connection to a Neo4j database.
    _graph_label : str
        Label to use for skeleton nodes representing graphs.
    _typing_label : str
        Relation type to use for skeleton edges
        representing homomorphisms.
    _relation_label : str
        Relation type to use for skeleton edges
        representing relations.
    _graph_edge_label : str
        Relation type to use for all graph edges.
    _graph_typing_label : str
        Relation type to use for edges encoding homomorphisms.
    _graph_relation_label : str
        Relation type to use for edges encoding relations.
    """

    # factories of node/edge dictionaries
    graph_dict_factory = dict
    typing_dict_factory = dict
    rel_dict_factory = dict

    def __init__(self, uri=None, user=None, password=None,
                 driver=None,
                 graph_label="graph",
                 typing_label="homomorphism",
                 relation_label="binaryRelation",
                 graph_edge_label="edge",
                 graph_typing_label="typing",
                 graph_relation_label="relation"):
        """Initialize driver.

        Parameters
        ----------

        uri : str, optional
            Uri for Neo4j database connection
        user : str, optional
            Username for Neo4j database connection
        password : str, optional
            Password for Neo4j database connection
        driver : neo4j.v1.direct.DirectDriver, optional
            Driver providing connection to a Neo4j database.
        graph_label : str, optional
            Label to use for skeleton nodes representing graphs.
        typing_label : str, optional
            Relation type to use for skeleton edges
            representing homomorphisms.
        relation_label : str, optional
            Relation type to use for skeleton edges
            representing relations.
        graph_edge_label : str, optional
            Relation type to use for all graph edges.
        graph_typing_label : str, optional
            Relation type to use for edges encoding homomorphisms.
        graph_relation_label : str, optional
            Relation type to use for edges encoding relations.
        """
        # The following idea is cool but it's not so easy:
        # as we have two types of nodes in the hierarchy:
        # graphs and rules, as well as two types of edges:
        # homomorphisms and relations, and so far Neo4jGraph
        # supports only a single label for nodes and for edges
        # Neo4jGraph.__init__(
        #     self, uri=uri, user=user, password=password,
        #     node_label="hierarchyNode",
        #     edge_label="hierarchyEdge")

        if driver is None:
            self._driver = GraphDatabase.driver(
                uri, auth=(user, password))
        else:
            self._driver = driver

        self._graph_label = graph_label
        self._typing_label = typing_label
        self._relation_label = relation_label
        self._graph_edge_label = graph_edge_label
        self._graph_typing_label = graph_typing_label
        self._graph_relation_label = graph_relation_label

        query = "CREATE " + cypher.constraint_query(
            'n', self._graph_label, 'id')
        self.execute(query)

    def __str__(self):
        """String representation of the hierarchy."""
        res = ""
        res += "\nGraphs: \n"
        for n in self.graphs():
            res += " {} {}\n".format(n, self.get_graph_attrs(n))

        res += "\nTyping homomorphisms: \n"
        for n1, n2 in self.typings():
            res += "{} -> {}\n".format(n1, n2, self.get_typing_attrs(n1, n2))

        res += "\nRelations:\n"
        for n1, n2 in self.relations():
            res += "{}-{}: {}\n".format(
                n1, n2, self.get_relation_attrs(n1, n2))

        return res

    def close(self):
        """Close connection to the database."""
        self._driver.close()

    def execute(self, query):
        """Execute a Cypher query."""
        with self._driver.session() as session:
            if len(query) > 0:
                # print(query)
                result = session.run(query)
                return result

    def _clear(self):
        """Clear the hierarchy."""
        query = cypher.clear_graph()
        result = self.execute(query)
        # self.drop_all_constraints()
        return result

    def _clear_all(self):
        query = "MATCH (n) DETACH DELETE n"
        self.execute(query)

    def _drop_all_constraints(self):
        """Drop all the constraints on the hierarchy."""
        with self._driver.session() as session:
            for constraint in session.run("CALL db.constraints"):
                session.run("DROP " + constraint[0])

    def graphs(self):
        """Return a list of graphs in the hierarchy."""
        query = cypher.get_nodes(node_label=self._graph_label)
        result = self.execute(query)
        return [list(d.values())[0] for d in result]

    def typings(self):
        """Return a list of graph typing edges in the hierarchy."""
        query = cypher.get_edges(
            self._graph_label,
            self._graph_label,
            self._typing_label)
        result = self.execute(query)
        return [(d["n.id"], d["m.id"]) for d in result]

    # def rules(self):
    #     """Return a list of rules in the hierary."""
    #     pass

    def relations(self):
        """Return a list of relations."""
        query = cypher.get_edges(
            self._graph_label,
            self._graph_label,
            self._relation_label)
        result = self.execute(query)
        return [(d["n.id"], d["m.id"]) for d in result]

    def add_graph(self, graph_id, node_list=None, edge_list=None,
                  attrs=None):
        """Add a graph to the hierarchy.

        Parameters
        ----------
        graph_id : hashable
            Id of a new node in the hierarchy
        node_list : iterable
            Iterable containing a collection of nodes, optionally,
            with their attributes
        edge_list : iterable
            Iterable containing a collection of edges, optionally,
            with their attributes
        graph_attrs : dict
            Dictionary containing attributes of the new graph

        Raises
        ------
        HierarchyError
            If graph with provided id already exists in the hierarchy

        """
        try:
            # Create a node in the hierarchy
            query = "CREATE ({}:{} {{ id : '{}' }}) \n".format(
                'new_graph',
                self._graph_label,
                graph_id)
            if attrs is not None:
                normalize_attrs(attrs)
                query += cypher.set_attributes(
                    var_name='new_graph',
                    attrs=attrs)
            self.execute(query)
        except(ConstraintError):
            raise HierarchyError(
                "The graph '{}' is already in the database.".format(graph_id))
        g = graphs.Neo4jGraph(
            driver=self._driver,
            node_label=graph_id,
            unique_node_ids=True)
        if node_list is not None:
            g.add_nodes_from(node_list)
        if edge_list is not None:
            g.add_edges_from(edge_list)

    def duplicate_subgraph(self, graph_dict, attach_graphs=[]):
        old_graphs = self.graphs()
        for new_g in graph_dict.values():
            if new_g in old_graphs:
                raise HierarchyError(
                    "Graph with id '{}' already exists in the hierarchy".format(
                        new_g))
        # copy graphs
        for original, new in graph_dict.items():
            self.copy_graph(original, new, attach_graphs)

        # copy typing between them
        visited = set()
        for g in graph_dict.keys():
            preds = [
                p for p in self.predecessors(g)
                if p in graph_dict.keys() and (p, g) not in visited]
            sucs = [
                p for p in self.successors(g)
                if p in graph_dict.keys() and (g, p) not in visited]
            for s in sucs:
                # Remember that copy typing needs pairs of graphs to be equal
                self.add_typing(
                    graph_dict[g], graph_dict[s],
                    self.get_typing(g, s))
                # self.copy_typing(g, s, graphs_to_copy[g], graphs_to_copy[s])
                visited.add((g, s))
            for p in preds:
                # Remember that copy typing needs pairs of graphs to be equal
                self.add_typing(
                    graph_dict[p], graph_dict[g],
                    self.get_typing(p, g))
                visited.add((p, g))

    def copy_graph(self, graph_id, new_graph_id, attach_graphs=[]):
        """Duplicate a graph in a hierarchy."""
        if new_graph_id in self.graphs():
            raise HierarchyError(
                "Graph with id '{}' already exists in the hierarchy".format(
                    new_graph_id))
        self.add_graph(new_graph_id, attrs=self.get_graph_attrs(graph_id))
        copy_nodes_q = (
            "MATCH (n:{}) CREATE (n1:{}) SET n1=n\n".format(
                graph_id, new_graph_id)
        )
        self.execute(copy_nodes_q)
        copy_edges_q = (
            "MATCH (n:{})-[r:{}]->(m:{}), (n1:{}), (m1:{}) \n".format(
                graph_id, self._graph_edge_label, graph_id,
                new_graph_id, new_graph_id) +
            "WHERE n1.id=n.id AND m1.id=m.id \n" +
            "MERGE (n1)-[r1:{}]->(m1) SET r1=r\n".format(
                self._graph_edge_label)
        )
        self.execute(copy_edges_q)
        # copy all typings
        for g in attach_graphs:
            if g in self.successors(graph_id):
                self.add_typing(new_graph_id, g, self.get_typing(graph_id, g))
            if g in self.predecessors(graph_id):
                self.add_typing(g, new_graph_id, self.get_typing(g, graph_id))
            if g in self.adjacent_relations(graph_id):
                self.add_relation(g, new_graph_id, self.get_relation(g, graph_id))

    def add_empty_graph(self, graph_id, attrs=None):
        """Add empty graph to the hierarchy."""
        self.add_graph(graph_id, attrs=attrs)

    def valid_typing(self, source, target):
        """Check if the typing is valid."""
        with self._driver.session() as session:
            tx = session.begin_transaction()
            valid_typing = cypher.check_homomorphism(tx, source, target)
            tx.commit()
        return valid_typing

    def add_typing(self, source, target, mapping, attrs=None, check=True):
        """Add homomorphism to the hierarchy.

        Parameters
        ----------
        source
            Label of a source graph node of typing
        target
            Label of a target graph node of typing
        mapping : dict
            Dictionary representing a mapping of nodes ids
            from the source graph to target's nodes
        attrs : dict
            Dictionary containing attributes of the new
            typing edge

        Raises
        ------
        HierarchyError
            This error is raised in the following cases:

                * source or target ids are not found in the hierarchy
                * addition of an edge between source and target produces
                paths that do not commute with some already existing paths

        InvalidHomomorphism
            If a homomorphism from a graph at the source to a graph at
            the target given by `mapping` is not a valid homomorphism.
        """
        query = ""
        tmp_attrs = {'tmp': {'true'}}
        normalize_attrs(tmp_attrs)

        if len(mapping) > 0:
            with self._driver.session() as session:
                tx = session.begin_transaction()
                for u, v in mapping.items():
                    query = (
                        cypher.set_intergraph_edge(
                            source, target,
                            u, v, "typing",
                            attrs=tmp_attrs))
                    tx.run(query)
                tx.commit()

        valid_typing = True
        paths_commute = True
        if check:
            # We first check that the homorphism is valid
            try:
                with self._driver.session() as session:
                    tx = session.begin_transaction()
                    valid_typing = cypher.check_homomorphism(tx, source, target)
                    tx.commit()
            except InvalidHomomorphism as homomorphism_error:
                valid_typing = False
                del_query = (
                    "MATCH (:{})-[t:typing]-(:{})\n".format(
                        source, target) +
                    "DELETE t\n"
                )
                self.execute(del_query)
                raise homomorphism_error
            # We then check that the new typing preserv consistency
            try:
                with self._driver.session() as session:
                    tx = session.begin_transaction()
                    paths_commute = cypher.check_consistency(tx, source, target)
                    tx.commit()
            except InvalidHomomorphism as consistency_error:
                paths_commute = False
                del_query = (
                    "MATCH (:{})-[t:typing]-(:{})\n".format(
                        source, target) +
                    "DELETE t\n"
                )
                self.execute(del_query)
                raise consistency_error

        if valid_typing and paths_commute:
            skeleton_query = (
                cypher.match_nodes(
                    var_id_dict={'g_src': source, 'g_tar': target},
                    node_label=self._graph_label) +
                cypher.add_edge(
                    edge_var='new_hierarchy_edge',
                    source_var='g_src',
                    target_var='g_tar',
                    edge_label=self._typing_label,
                    attrs=attrs) +
                cypher.with_vars(["new_hierarchy_edge"]) +
                "MATCH (:{})-[t:typing]-(:{})\n".format(
                    source, target) +
                "REMOVE t.tmp\n"

            )
            self.execute(skeleton_query)
        # return result

    def add_relation(self, left, right, relation, attrs=None):
        """Add relation to the hierarchy.

        This method adds a relation between two graphs in
        the hierarchy corresponding to the nodes with ids
        `left` and `right`, the relation itself is defined
        by a dictionary `relation`, where a key is a node in
        the `left` graph and its corresponding value is a set
        of nodes from the `right` graph to which the node is
        related. Relations in the hierarchy are symmetric
        (see example below).

        Parameters
        ----------
        left
            Id of the hierarchy's node represening the `left` graph
        right
            Id of the hierarchy's node represening the `right` graph
        relation : dict
            Dictionary representing a relation of nodes from `left`
            to the nodes from `right`, a key of the dictionary is
            assumed to be a node from `left` and its value a set
            of ids of related nodes from `right`
        attrs : dict
            Dictionary containing attributes of the new relation

        Raises
        ------
        HierarchyError
            This error is raised in the following cases:

                * node with id `left`/`right` is not defined in the hierarchy;
                * node with id `left`/`right` is not a graph;
                * a relation between `left` and `right` already exists;
                * some node ids specified in `relation` are not found in the
                `left`/`right` graph.

        Examples
        --------
        >>> hierarchy = Neo4jHierarchy()
        >>> g1 = nx.DiGraph([("a", "b"), ("a", "a")])
        >>> g2 = nx.DiGraph([(1, 2), (2, 3)])
        >>> hierarchy.add_graph("G1", g1)
        >>> hierarchy.add_graph("G2", g2)
        >>> hierarchy.add_relation("G1", "G2", {"a": {1, 2}, "b": 3})
        >>> hierarchy.relation["G1"]["G2"].rel
        {'a': {1, 2}, 'b': {3}}
        >>> hierarchy.relation["G2"]["G1"].rel
        {1: {'a'}, 2: {'a'}, 3: {'b'}}
        """
        # normalize relation dict
        new_relation_dict = dict()
        for key, values in relation.items():
            if type(values) == set:
                new_relation_dict[key] = values
            elif type(values) == str:
                new_relation_dict[key] = {values}
            else:
                try:
                    new_set = set()
                    for v in values:
                        new_set.add(v)
                    new_relation_dict[key] = new_set
                except TypeError:
                    new_relation_dict[key] = {values}
        relation = new_relation_dict

        if attrs is not None:
            normalize_attrs(attrs)

        g_left = self._access_graph(left)
        g_right = self._access_graph(right)

        query = ""
        rel_creation_queries = []
        nodes_to_match_left = set()
        nodes_to_match_right = set()
        for key, values in new_relation_dict.items():
            nodes_to_match_left.add(key)
            for value in values:
                nodes_to_match_right.add(value)
                rel_creation_queries.append(
                    cypher.add_edge(
                        edge_var="rel_" + key + "_" + value,
                        source_var="n" + key + "_left",
                        target_var="n" + value + "_right",
                        edge_label="relation"))

        if len(nodes_to_match_left) > 0:
            query += cypher.match_nodes(
                {"n" + n + "_left": n for n in nodes_to_match_left},
                node_label=g_left._node_label)
            query += cypher.with_vars(
                ["n" + s + "_left" for s in nodes_to_match_left])
            query += cypher.match_nodes(
                {"n" + n + "_right": n for n in nodes_to_match_right},
                node_label=g_right._node_label)
            for q in rel_creation_queries:
                query += q
        rel_addition_result = self.execute(query)
        skeleton_query = (
            cypher.match_nodes(
                var_id_dict={'g_left': left, 'g_right': right},
                node_label=self._graph_label) +
            cypher.add_edge(
                edge_var='new_hierarchy_edge',
                source_var='g_left',
                target_var='g_right',
                edge_label=self._relation_label,
                attrs=attrs)
        )

        skeleton_addition_result = self.execute(skeleton_query)
        return (rel_addition_result, skeleton_addition_result)

    def remove_graph(self, node_id, reconnect=False):
        """Remove node from the hierarchy.

        Removes a node from the hierarchy, if the `reconnect`
        parameter is set to True, adds typing from the
        predecessors of the removed node to all its successors,
        by composing the homomorphisms (for every predecessor `p`
        and for every successor 's' composes two homomorphisms
        `p`->`node_id` and `node_id`->`s`, then removes `node_id` and
        all its incident edges, by which makes node's
        removal a procedure of 'forgetting' one level
        of 'abstraction').

        Parameters
        ----------
        node_id
            Id of a node to remove
        reconnect : bool
            Reconnect the descendants of the removed node to
            its predecessors

        Raises
        ------
        HierarchyError
            If node with `node_id` is not defined in the hierarchy
        """
        g = self._access_graph(node_id)

        if reconnect:
            query = (
                "MATCH (n:{})".format(node_id) +
                "OPTIONAL MATCH (pred)-[:typing]->(n)-[:typing]->(suc)\n" +
                "WITH pred, suc WHERE pred IS NOT NULL\n" +
                cypher.add_edge(
                    edge_var='recennect_typing',
                    source_var='pred',
                    target_var='suc',
                    edge_label="typing")
            )
            self.execute(query)
        # Clear the graph and drop the constraint on the ids
        g._drop_constraint('id')
        g._clear()

        # Remove the graph (and reconnect if True)
        if reconnect:
            query = (
                cypher.match_node(
                    var_name="graph_to_rm",
                    node_id=node_id,
                    node_label=self._graph_label) +
                "OPTIONAL MATCH (pred)-[:{}]->(n)-[:{}]->(suc)\n".format(
                    self._typing_label, self._typing_label) +
                "WITH pred, suc WHERE pred IS NOT NULL\n" +
                cypher.add_edge(
                    edge_var='recennect_typing',
                    source_var='pred',
                    target_var='suc',
                    edge_label="typing")
            )
            self.execute(query)
        query = cypher.match_node(var_name="graph_to_rm",
                                  node_id=node_id,
                                  node_label=self._graph_label)
        query += cypher.remove_nodes(["graph_to_rm"])
        self.execute(query)

    def remove_typing(self, u, v):
        """Remove a typing from the hierarchy."""
        pass

    def remove_relation(self, u, v):
        """Remove a relation from the hierarchy."""
        pass

    def adjacent_relations(self, graph_id):
        """Return a list of related graphs."""
        query = cypher.successors_query(
            var_name='g',
            node_id=graph_id,
            node_label=self._graph_label,
            edge_label=self._relation_label,
            undirected=True)
        succ = self.execute(query).value()
        if succ[0] is None:
            succ = []
        return succ

    def _access_graph(self, graph_id, edge_label=None):
        """Access a graph of the hierarchy."""
        if edge_label is None:
            edge_label = "edge"
        g = graphs.Neo4jGraph(
            self._driver,
            node_label=graph_id, edge_label=edge_label)
        return g

    def _check_typing(self, source, target):
        """Check if a typing is a valid homomorphism."""
        with self._driver.session() as session:
            tx = session.begin_transaction()
            res = cypher._check_homomorphism(tx, source, target)
            tx.commit()

    def find_matching(self, graph_id, pattern,
                      pattern_typing=None, nodes=None):
        """Find an instance of a pattern in a specified graph.

        This function takes as an input a graph and a pattern graph,
        optionally, it also takes a dictionary specifying pattern typing
        and a collection of nodes specifying the subgraph of the
        original graph, where the matching should be searched in, then it
        searches for a matching of the pattern inside of the graph (or induced
        subragh), which corresponds to solving subgraph matching problem.
        The matching is defined by a map from the nodes of the pattern
        to the nodes of the graph such that:

        * edges are preserved, i.e. if there is an edge between nodes `n1`
          and `n2` in the pattern, there is an edge between the nodes of
          the graph that correspond to the image of `n1` and `n2`, moreover,
          the attribute dictionary of the edge between `n1` and `n2` is the
          subdictiotary of the edge it corresponds to in the graph;
        * the attribute dictionary of a pattern node is a subdictionary of
          its image in the graph;
        * (if pattern typing is specified) if node `n1` of the pattern
          is typed by some node `t` in the graph `T` of the hierarchy,
          then its image is also typed by `t` from the graph `T`.

        Uses `networkx.isomorphism.(Di)GraphMatcher` class, which implements
        subgraph matching algorithm.

        Parameters
        ----------
        graph_id
            Id of the graph in the hierarchy to search for matches
        pattern : nx.(Di)Graph
            Pattern graph to search for
        pattern_typing : dict, optional
            Dictionary defining the (partial) pattern typing,
            where keys are graph nodes of the hierarchy and
            values are (partial) mappings from the nodes
            of the pattern to the nodes of its typing graph given
            by the respective key
        nodes : iterable
            Subset of nodes to search for matching

        Returns
        -------
        instances : list of dict's
            List of instances of matching found in the graph, every instance
            is represented with a dictionary where keys are nodes of the
            pattern, and values are corresponding nodes of the graph.

        Raises
        ------
        ReGraphError
            If `graph_id` is a rule node or pattern is not valid under the
            provided `pattern_typing`
        """
        graph = self._access_graph(graph_id)
        instances = graph.find_matching(
            pattern, pattern_typing=pattern_typing, nodes=nodes)

        return instances

    def rewrite(self, graph_id, rule, instance,
                rhs_typing=None, strict=False, p_typing=None):
        """Rewrite and propagate the changes up & down.

        Rewriting in the hierarchy cosists of an application of the
        SqPO-rewriting rule (given by the `rule` parameter) to a
        graph in the hierarchy. Such rewriting often triggers a set of
        changes that are applied to other graphs and homomorphisms in the
        hierarchy, which are necessary to ensure that the hierarchy stays
        consistent. If the rule is restrictive (deletes nodes/edges/attrs
        or clones nodes), in general, the respective changes to all the graphs
        (transitively) typed by the graph subject to rewriting are made.
        On the other hand, if the rule is relaxing (adds nodes/edges/attrs
        or merges nodes), in general, the respective changes to all the graphs
        that (tansitively) type the graph subject to rewriting are made.


        Parameters
        ----------
        graph_id
            Id of the graph in the hierarchy to rewrite
        rule : regraph.rule.Rule
            Rule object to apply
        instance : dict, optional
            Dictionary containing an instance of the lhs of the rule in
            the graph subject to rewriting, by default, tries to construct
            identity morphism of the nodes of the pattern
        rhs_typing : dict, optional
            Dictionary containing typing of the rhs by graphs of the hierarchy,
            keys are ids of hierarchy graphs, values are dictionaries
            containing the mapping of nodes from the lhs to the nodes of
            the typing graph given by the respective key of the value
            (note that a node from the rhs can be typed by a set of nodes of
            some graph, e.g. if we want to perform merging of some types, etc).
        strict : bool, optional
            Rewriting is strict when propagation down is not allowed

        Raises
        ------
        HierarchyError
            If the graph is not in the database
        TypingWarning
            If the rhs typing is inconsistent
        """
        if rhs_typing is None:
            rhs_typing = {}
        if p_typing is None:
            p_typing = {}

        if strict is True:
            self._check_rhs_typing(graph_id, rule, instance, rhs_typing)

        # Rewriting of the base graph
        g = self._access_graph(graph_id)
        start = time.time()
        rhs_g = g.rewrite(
            rule, instance, holistic=False,
            edge_labels=[
                self._graph_typing_label,
                self._graph_edge_label,
                self._graph_relation_label])
        # print("Rewritten base graph: ", time.time() - start)

        start = time.time()
        if rule.is_restrictive():
            if len(rule.cloned_nodes()) > 0 and p_typing:
                self._add_tmp_p_typing(
                    graph_id, rule, rhs_g, p_typing)
            self._propagate_up(graph_id, rule)
        # print("Propagated up: ", time.time() - start)

        start = time.time()
        if strict is False and rule.is_relaxing():
            if len(rule.added_nodes()) > 0 and len(rhs_typing) > 0:
                self._add_tmp_rhs_typing(graph_id, rhs_g, rhs_typing)
            self._propagate_down(graph_id, graph_id, rule)
        # print("Propagated down: ", time.time() - start)

        return self, rhs_g

    def _propagate_up(self, graph_id, rule):
        predecessors = self.predecessors(graph_id)
        for predecessor in predecessors:
            clone_query = None
            remove_node_query = None
            remove_edge_query = None

            # Propagate node clones
            if len(rule.cloned_nodes()) > 0:
                with self._driver.session() as session:
                    tx = session.begin_transaction()
                    cypher.propagate_clones(tx, graph_id, predecessor)
                    tx.commit()
                # clone_query = cypher.clone_propagation_query(
                #     graph_id, predecessor)

            # Propagate node deletes
            if len(rule.removed_nodes()) > 0 or\
               len(rule.removed_node_attrs()) > 0:
                remove_node_query = cypher.remove_node_propagation_query(
                    graph_id, predecessor)

            # Propagate edge deletes
            if len(rule.removed_edges()) > 0 or\
               len(rule.removed_edge_attrs()) > 0:
                remove_edge_query = cypher.remove_edge_propagation_query(
                    graph_id, predecessor)

            # run multiple queries in one transaction
            with self._driver.session() as session:
                tx = session.begin_transaction()
                # if clone_query:
                #     tx.run(clone_query)
                if remove_node_query:
                    tx.run(remove_node_query)
                if remove_edge_query:
                    tx.run(remove_edge_query)
                tx.commit()
        for ancestor in predecessors:
            self._propagate_up(ancestor, rule)

    def _propagate_down(self, origin_graph, graph_id, rule):
        successors = self.successors(graph_id)
        for successor in successors:
            # Propagate merges
            merge_query = None
            add_nodes_query = None
            add_edges_query = None

            # Propagate node merges
            if len(rule.merged_nodes()) > 0:
                # match nodes of T with the same pre-image in G and merge them
                merge_query = cypher.merge_propagation_query(
                    graph_id, successor)

            # Propagate node adds
            # if len(rule.added_nodes()) > 0 or\
            #    len(rule.added_node_attrs()) > 0:
            #     add_nodes_query = cypher.add_node_propagation_query(
            #         origin_graph, graph_id, successor)

            # (Propagate edge adds
            if len(rule.added_edges()) > 0 or\
               len(rule.added_edge_attrs()) > 0:
                add_edges_query = cypher.add_edge_propagation_query(
                    graph_id, successor)

            # Run multiple queries in one transaction
            with self._driver.session() as session:
                tx = session.begin_transaction()
                if merge_query:
                    tx.run(merge_query).single()
                if len(rule.added_nodes()) > 0 or\
                   len(rule.added_node_attrs()) > 0:
                    cypher.propagate_add_node(
                        tx, origin_graph, graph_id, successor)
                if add_edges_query:
                    tx.run(add_edges_query).single()
                tx.commit()

        for successor in successors:
            self._propagate_down(origin_graph, successor, rule)

    def _add_tmp_p_typing(self, graph_id, rule, rhs_g, p_typing):
        p_typing = normalize_typing_relation(p_typing)
        for graph in p_typing.keys():
            # We add attr _to_remove to an edge which will be deleted
            # all this is happening before the propagation itself
            for _, clones in rule.cloned_nodes().items():
                for k, v in p_typing[graph].items():
                    query = (
                        "OPTIONAL MATCH (h_i:{} {{id: '{}'}})-[:typing*]->(g_i:{})\n".format(
                            graph, k, graph_id) +
                        "WHERE NOT g_i.id IN [{}]\n".format(
                            ", ".join("'{}'".format(
                                rhs_g[rule.p_rhs[el]]) for el in v)) +
                        "FOREACH(dummy IN CASE WHEN h_i IS NULL THEN [] ELSE [1] END |\n" +
                        "\tMERGE (h_i)-[:_to_remove]->(g_i))\n"
                    )
                    self.execute(query)

            # Check all predecessors are r
            query = (
                "OPTIONAL MATCH (p:{})<-[:_to_remove]-(pred)".format(graph_id) +
                "-[t:typing]->(m:{})-[:_to_remove]->(o:{})\n".format(
                    graph, graph_id) +
                "WHERE p.id <> o.id\n" +
                "RETURN CASE WHEN p IS NULL OR o IS NULL \n" +
                "\tTHEN true ELSE \n" +
                "\t\tCASE WHEN t IS NULL \n" +
                "\t\t\tTHEN true ELSE false END END as res"
            )
            res = self.execute(query)
            valid = False
            for record in res:
                if record["res"] is True:
                    valid = True
            if valid is True:
                # apply p typing
                query = cypher.remove_targeted_typing(graph_id)
            else:
                # roll back to canonical
                query = cypher.remove_targetting(graph_id)
            self.execute(query)

    def _add_tmp_rhs_typing(self, graph_id, rhs_g, rhs_typing):
        rhs_tmp_typing = ""
        for graph in rhs_typing.keys():
            # Add temp typing subquery

            nodes_to_match = []
            merge_subqueres = []
            if rhs_typing[graph]:
                for node in rhs_typing[graph].keys():
                    rhs_typed_var = "n{}_{}".format(rhs_g[node], graph_id)
                    rhs_typing_var = "n{}_{}".format(
                        rhs_typing[graph][node], graph)
                    nodes_to_match.append(
                        "({}:{} {{id:'{}'}}), ".format(
                            rhs_typed_var, graph_id, rhs_g[node]) +
                        "({}:{} {{id:'{}'}})".format(
                            rhs_typing_var, graph, rhs_typing[graph][node]))
                    merge_subqueres.append(
                        "MERGE ({})-[:tmp_typing]->({})".format(
                            rhs_typed_var, rhs_typing_var)
                    )

                if len(nodes_to_match) > 0:
                    query = (
                        "// Adding temporary typing of the rhs nodes\n" +
                        "OPTIONAL MATCH "
                    )

                    query += (
                        ", ".join(nodes_to_match) + "\n" +
                        "\n".join(merge_subqueres)
                        # cypher.with_vars(["NULL"]) + "\n"
                    )
                    rhs_tmp_typing += query + "\n"
                    self.execute(query)

        # Checking if the introduces rhs typing is consistent
        with self._driver.session() as session:
            tx = session.begin_transaction()
            consistent_typing = cypher.check_tmp_consistency(
                tx, graph_id, self._graph_label, self._typing_label)
            tx.commit()

        if consistent_typing:
            self.execute(
                cypher.preserve_tmp_typing(
                    graph_id, self._graph_label, self._typing_label,
                    direction="successors"))
        else:
            self.execute(
                cypher.remove_tmp_typing(graph_id, direction="predecessors"))

    def _check_rhs_typing(self, graph_id, rule, instance, rhs_typing):
        # Check the rhs typing can be consistently inferred
        if rule.is_relaxing():
            for s in self.successors(graph_id):
                # check if there are no untyped new nodes
                for n in rule.added_nodes():
                    if s not in rhs_typing.keys() or\
                       n not in rhs_typing[s].keys():
                        raise RewritingError(
                            "Rewriting is strict (no propagation of types is "
                            "allowed), typing of the node '{}' "
                            "in rhs is required (typing by the following "
                            "graph stays unresolved: '{}')!".format(n, s))

                # check if there are no merges of different types
                merges = {}
                for rhs_node, p_nodes in rule.merged_nodes().items():
                    merged_types = set(
                        [self.node_type(
                            graph_id, instance[rule.p_lhs[n]])[s] for n in p_nodes])
                    if len(merged_types) > 1:
                        raise RewritingError(
                            "Rewriting is strict (no propagation of merges is "
                            "allowed), merging of the nodes [{}] (matched as [{}] in "
                            "P) requires merge of nodes [{}] "
                            "in the graph '{}')!".format(
                                ", ".join([instance[rule.p_lhs[n]] for n in p_nodes]),
                                ", ".join(p_nodes),
                                ", ".join(t for t in merged_types), s))
                    merges[rhs_node] = list(merged_types)[0]

                # check if there are no forbidden edges
                preserved_nodes = {}
                for n in rule.rhs.nodes():
                    if n not in rule.merged_nodes() and\
                       n not in rule.added_nodes():
                        preserved_nodes[n] = list(
                            keys_by_value(rule.p_rhs, n))[0]

                for source, target in rule.added_edges():
                    if source in rule.added_nodes():
                        source_typing = rhs_typing[s][source]
                    elif source in merges.keys():
                        source_typing = merges[source]
                    else:
                        p_source = keys_by_value(rule.p_rhs, source)[0]
                        source_typing = self.node_type(
                            graph_id, instance[rule.p_lhs[p_source]])[s]

                    if target in rule.added_nodes():
                        target_typing = rhs_typing[s][target]
                    elif target in merges.keys():
                        target_typing = merges[target]
                    else:
                        p_target = keys_by_value(rule.p_rhs, target)[0]
                        target_typing = self.node_type(
                            graph_id, instance[rule.p_lhs[p_target]])[s]

                    if not self.exists_edge(s, source_typing, target_typing):
                        raise RewritingError(
                            "Rewriting is strict, and addition of an edge "
                            "'{}'->'{}' from R is not allowed as there ".format(
                                source, target) +
                            "is no edge '{}'->'{}' in the graph '{}')!".format(
                                source_typing, target_typing, s))

                for n, attrs in rule.added_node_attrs().items():
                    if n in rule.added_nodes():
                        typing = rhs_typing[s][n]
                    elif n in merges.keys():
                        typing = merges[n]
                    else:
                        typing = preserved_nodes[n]
                    if not self.node_attributes_included(graph_id, s, n, typing):
                        raise RewritingError(
                            "Rewriting is strict, and some attributes of " +
                            "'{}' from P added by the rule are not present in ".format(n) +
                            "'{}' of the graph {}!".format(typing, s))

                for (source, target), attrs in rule.added_edge_attrs().items():
                    if source in rule.added_nodes():
                        source_typing = rhs_typing[s][source]
                    elif source in merges.keys():
                        source_typing = merges[source]
                    else:
                        source_typing = preserved_nodes[source]
                    if target in rule.added_nodes():
                        target_typing = rhs_typing[s][target]
                    elif target in merges.keys():
                        target_typing = merges[target]
                    else:
                        target_typing = preserved_nodes[target]
                    if not self.edge_attributes_included(
                        graph_id, s, (source, target),
                            (source_typing, target_typing)):
                        raise RewritingError(
                            "Rewriting is strict, and some attributes of " +
                            "'{}'->'{}' from P added by the rule are not present in ".format(
                                source, target) +
                            "'{}'->'{}' of the graph {}!".format(
                                source_typing, target_typing, s))

    def node_type(self, graph_id, node_id):
        """Get a list of the immediate types of a node.

        Returns
        -------
        types : dict
            Dictionary whose keys are ids of the graphs in the
            hierarchy that type `graph_id` and values are the
            nodes typing `node_id` from `graph_id`

        Raises
        ------
        HierarchyError
            If graph with a given id does not exist in the hierarchy or
            the node with `node_id` is not in the graph
        """
        query = (
            "MATCH (n:{} {{id: '{}'}})\n".format(graph_id, node_id) +
            "OPTIONAL MATCH (n)-[:typing]->(m)\n" +
            "RETURN labels(m)[0] as successor, m.id as typing_node"
        )
        result = self.execute(query)
        types = {}
        for record in result:
            if "successor" in record.keys() and\
               "typing_node" in record.keys():
                types[record["successor"]] = record["typing_node"]
        return types

    def get_typing(self, source, target):
        """Get typing dict of `source` by `target`."""
        query = cypher.get_typing(source, target, "typing")
        result = self.execute(query)
        typing = {}
        for record in result:
            typing[record["node"]] = record["type"]
        return typing

    def get_relation(self, left, right):
        query = cypher.get_typing(left, right, "relation")
        result = self.execute(query)
        relation = {}
        for record in result:
            if record["node"] in relation.keys():
                relation[record["node"]].add(record["type"])
            else:
                relation[record["node"]] = {record["type"]}
        return relation

    def set_node_typing(self, source_graph, target_graph, node_id, type_id):
        """Set typing to of a particular node."""
        query = cypher.set_intergraph_edge(
            source_graph, target_graph, node_id, type_id,
            "typing")
        result = self.execute(query)

    def set_node_attrs(self, node_id, attrs):
        skeleton = self._access_graph(self._graph_label)
        skeleton.set_node_attrs(node_id, attrs)

    def set_edge_attrs(self, source, target, attrs):
        skeleton = self._access_graph(self._graph_label)
        skeleton.set_edge_attrs(source, target, attrs)

    def set_node_relation(self, source_graph, target_graph, node_id, type_id):
        """Set relation to a particular node."""
        query = cypher.set_intergraph_edge(
            source_graph, target_graph, node_id, type_id,
            "relation")
        result = self.execute(query)

    def get_graph(self, graph_id):
        return self._access_graph(graph_id)

    def get_node_attrs(self, node_id):
        """Return node's attributes."""
        query = cypher.get_node_attrs(
            node_id, self._graph_label,
            "attributes")
        result = self.execute(query)
        return cypher.properties_to_attributes(
            result, "attributes")

    def get_graph_attrs(self, graph_id):
        """Return node's attributes."""
        query = cypher.get_node_attrs(
            graph_id, self._graph_label,
            "attributes")
        result = self.execute(query)
        return cypher.properties_to_attributes(
            result, "attributes")

    def get_typing_attrs(self, source_id, target_id):
        """Return attributes attached to the typing in the hierarchy."""
        query = cypher.get_edge_attrs(
            source_id, target_id, self._typing_label,
            "attributes")
        result = self.execute(query)
        return cypher.properties_to_attributes(result, "attributes")

    def get_relation_attrs(self, left_id, right_id):
        """Return attributes attached to the typing in the hierarchy."""
        query = cypher.get_edge_attrs(
            left_id, right_id, self._relation_label,
            "attributes")
        result = self.execute(query)
        return cypher.properties_to_attributes(result, "attributes")

    def set_graph_attrs(self, graph_id, attrs):
        self.set_node_attrs(graph_id, attrs)

    def set_typing_attrs(self, source, target, attrs):
        self.set_edge_attrs(source, target, attrs)

    def successors(self, graph_label):
        """Get all the ids of the successors of a graph."""
        query = cypher.successors_query(var_name='g',
                                        node_id=graph_label,
                                        node_label=self._graph_label,
                                        edge_label=self._typing_label)
        succ = self.execute(query).value()
        if succ[0] is None:
            succ = []
        return succ

    def predecessors(self, graph_label):
        """Get all the ids of the predecessors of a graph."""
        query = cypher.predecessors_query(var_name='g',
                                          node_id=graph_label,
                                          node_label=self._graph_label,
                                          edge_label=self._typing_label)
        preds = self.execute(query).value()
        if preds[0] is None:
            preds = []
        return preds

    def to_nx_graph(self):
        """Create a simple networkx graph representing the hierarchy.

        Note that the relation edges are ignored.

        Returns
        -------
        g : nx.DiGraph
            Simple NetworkX graph representing the structure of the
            hierarchy
        """
        g = nx.DiGraph()
        for node in self.graphs():
            g.add_node(node, self.node[node].attrs)
        for s, t in self.typings():
            g.add_edge(s, t, self.edge[s][t].attrs)
        return g

    # def rename_graph(self, graph_id, new_graph_id):
    #     """Rename a graph in the hierarchy."""
    #     query = (
    #         "MATCH (n:{} {{id: '{}'}})\n".format(
    #             self._graph_label, graph_id) +
    #         "SET n.id = '{}'".format(new_graph_id)
    #     )
    #     self.execute(query)

    def rename_node(self, graph_id, node_id, new_name):
        """Rename a node in a graph of the hierarchy."""
        query = (
            "MATCH (n:{} {{id: '{}'}})\n".format(
                graph_id, node_id) +
            "SET n.id = '{}'".format(new_name)
        )
        self.execute(query)

    def unique_graph_id(self, prefix):
        """Generate a new graph id starting with a prefix."""
        pass

    def exists_edge(self, graph_id, s, t):
        """Test if an edge 's'->'t' exists in 'graph_id'."""
        query = cypher.exists_edge(
            s, t,
            node_label=graph_id, edge_label="edge")
        result = self.execute(query)
        for record in result:
            if "result" in record.keys():
                return record["result"]

    def edge_attributes_included(self, g1, g2, e1, e2):
        query = (
            cypher.match_edge("s1", "t1", e1[0], e1[0], "rel1") +
            "WITH rel1\n" +
            cypher.match_edge("s2", "t2", e2[0], e2[0], "rel2") +
            "WITH rel1, rel2, \n" +
            "\t" + cypher.attributes_inclusion("rel1", "rel2", "invalid") + " \n" +
            "RETURN invalid <> 0 as result"
        )
        result = self.execute(query)
        for record in result:
            if "result" in record.keys():
                return record["result"]

    def node_attributes_included(self, g1, g2, n1, n2):
        query = (
            cypher.match_nodes({"n1": n1, "n2": n2}) +
            "WITH n1, n2, \n" +
            "\t" + cypher.attributes_inclusion("n1", "n2", "invalid") + " \n" +
            "RETURN invalid <> 0 as result"
        )
        result = self.execute(query)
        for record in result:
            if "result" in record.keys():
                return record["result"]

    @classmethod
    def copy(cls, hierarchy):
        """Copy Neo4jHierarchy object."""
        return copy.deepcopy(hierarchy)

    @classmethod
    def from_json(cls, uri=None, user=None, password=None,
                  driver=None, json_data=None, ignore=None,
                  clear=False):
        """Create hierarchy object from JSON representation.

        Parameters
        ----------

        uri : str, optional
            Uri for Neo4j database connection
        user : str, optional
            Username for Neo4j database connection
        password : str, optional
            Password for Neo4j database connection
        driver : neo4j.v1.direct.DirectDriver, optional
            DB driver object
        json_data : dict, optional
            JSON-like dict containing representation of a hierarchy
        ignore : dict, optional
            Dictionary containing components to ignore in the process
            of converting from JSON, dictionary should respect the
            following format:
            {
                "graphs": <collection of ids of graphs to ignore>,
                "rules": <collection of ids of rules to ignore>,
                "typing": <collection of tuples containing typing
                    edges to ignore>,
                "rule_typing": <collection of tuples containing rule
                    typing edges to ignore>>,
                "relations": <collection of tuples containing
                    relations to ignore>,
            }
        directed : bool, optional
            True if graphs from JSON representation should be loaded as
            directed graphs, False otherwise, default value -- True

        Returns
        -------
        hierarchy : regraph.hierarchy.Hierarchy
        """
        hierarchy = cls(
            uri=uri, user=user, password=password, driver=driver)

        if clear is True:
            hierarchy._clear()

        # add graphs
        for graph_data in json_data["graphs"]:
            if ignore is not None and\
               "graphs" in ignore.keys() and\
               graph_data["id"] in ignore["graphs"]:
                pass
            else:
                if "attrs" not in graph_data.keys():
                    attrs = dict()
                else:
                    attrs = attrs_from_json(graph_data["attrs"])
                hierarchy.add_empty_graph(graph_data["id"], attrs)
                graph = hierarchy.get_graph(graph_data["id"])
                graph.from_json(
                    uri=uri, user=user,
                    password=password, driver=driver,
                    j_data=graph_data["graph"],
                    node_label=graph_data["id"])

        # add typing
        for typing_data in json_data["typing"]:
            if ignore is not None and\
               "typing" in ignore.keys() and\
               (typing_data["from"], typing_data["to"]) in ignore["typing"]:
                pass
            else:
                if "attrs" not in typing_data.keys():
                    attrs = dict()
                else:
                    attrs = attrs_from_json(typing_data["attrs"])
                hierarchy.add_typing(
                    typing_data["from"],
                    typing_data["to"],
                    typing_data["mapping"],
                    attrs)

        # add relations
        for relation_data in json_data["relations"]:
            from_g = relation_data["from"]
            to_g = relation_data["to"]
            if ignore is not None and\
               "relations" in ignore.keys() and\
               ((from_g, to_g) in ignore["relations"] or
                    (to_g, from_g) in ignore["relations"]):
                pass
            else:
                if "attrs" not in relation_data.keys():
                    attrs = dict()
                else:
                    attrs = attrs_from_json(relation_data["attrs"])
                if (from_g, to_g) not in hierarchy.relations():
                    hierarchy.add_relation(
                        relation_data["from"],
                        relation_data["to"],
                        {a: set(b) for a, b in relation_data["rel"].items()},
                        attrs
                    )
        return hierarchy

    @classmethod
    def load(cls, filename, uri=None, user=None, password=None,
             driver=None, ignore=None, clear=True):
        """Load the hierarchy from a file.

        Parameters
        ----------
        Returns
        -------
        Raises
        ------
        """
        if os.path.isfile(filename):
            with open(filename, "r+") as f:
                json_data = json.loads(f.read())
                hierarchy = cls.from_json(
                    uri=uri, user=user, password=password, driver=driver,
                    json_data=json_data, ignore=ignore, clear=clear)
            return hierarchy
        else:
            raise ReGraphError("File '%s' does not exist!" % filename)

    def to_json(self):
        """Return json representation of the hierarchy."""
        json_data = {
            "rules": [],
            "graphs": [],
            "typing": [],
            "rule_typing": [],
            "relations": []
        }
        for graph in self.graphs():
            json_data["graphs"].append({
                "id": graph,
                "graph": self.get_graph(graph).to_json(),
                "attrs": attrs_to_json(self.get_graph_attrs(graph))
            })
        for s, t in self.typings():
            json_data["typing"].append({
                "from": s,
                "to": t,
                "mapping": self.get_typing(s, t),
                "attrs": attrs_to_json(self.get_typing_attrs(s, t))
            })
        visited = set()
        for u, v in self.relations():
            if not (u, v) in visited and not (v, u) in visited:
                visited.add((u, v))
                json_data["relations"].append({
                    "from": u,
                    "to": v,
                    "rel": {a: list(b) for a, b in self.get_relation(u, v).items()},
                    "attrs": attrs_to_json(self.get_relation_attrs(u, v))
                })
        return json_data

    def export(self, filename):
        """Export the hierarchy to a file."""
        with open(filename, 'w') as f:
            j_data = self.to_json()
            json.dump(j_data, f)