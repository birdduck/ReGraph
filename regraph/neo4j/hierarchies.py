"""Persistent graph hierarchy related data structures.

This module contains a data structure implementing
graph hierarchy based on Neo4j graphs.

* `Neo4jHierarchy` -- class for persistent graph hierarchies.
"""
from neo4j import GraphDatabase
from neo4j.exceptions import ConstraintError

from regraph.exceptions import (HierarchyError,
                                InvalidHomomorphism,
                                RewritingError,
                                ReGraphError)
from regraph.hierarchies import Hierarchy
from regraph.neo4j.graphs import Neo4jGraph
from .cypher_utils.generic import (constraint_query,
                                   get_nodes,
                                   get_edges,
                                   clear_graph,
                                   successors_query,
                                   predecessors_query,
                                   get_edge_attrs,
                                   properties_to_attributes,
                                   get_node_attrs,
                                   set_attributes,
                                   match_nodes,
                                   with_vars,
                                   match_node,
                                   shortest_path_query,
                                   match_edge,
                                   )
from .cypher_utils.propagation import (set_intergraph_edge,
                                       check_homomorphism,
                                       check_consistency)
from .cypher_utils.rewriting import (add_edge,
                                     remove_nodes,
                                     remove_edge)
from regraph.utils import (normalize_attrs,
                           keys_by_value,
                           normalize_typing_relation,
                           attrs_from_json,
                           attrs_to_json,
                           normalize_relation)


class Neo4jHierarchy(Hierarchy):
    """
    Class for persistent hierarchies.

    Attributes
    ----------

    """

    # Implementation of abstract methods

    def graphs(self):
        """Return a list of graphs in the hierarchy."""
        query = get_nodes(node_label=self._graph_label)
        result = self.execute(query)
        return [list(d.values())[0] for d in result]

    def typings(self):
        """Return a list of graph typing edges in the hierarchy."""
        query = get_edges(
            self._graph_label,
            self._graph_label,
            self._typing_label)
        result = self.execute(query)
        return [(d["n.id"], d["m.id"]) for d in result]

    def relations(self):
        """Return a list of relations."""
        query = get_edges(
            self._graph_label,
            self._graph_label,
            self._relation_label)
        result = self.execute(query)
        return [(d["n.id"], d["m.id"]) for d in result]

    def successors(self, node_id):
        """Return the set of successors."""
        query = successors_query(var_name='g',
                                 node_id=node_id,
                                 node_label=self._graph_label,
                                 edge_label=self._typing_label)
        succ = self.execute(query).value()
        if succ[0] is None:
            succ = []
        return succ

    def predecessors(self, node_id):
        """Return the set of predecessors."""
        query = predecessors_query(var_name='g',
                                   node_id=node_id,
                                   node_label=self._graph_label,
                                   edge_label=self._typing_label)
        preds = self.execute(query).value()
        if preds[0] is None:
            preds = []
        return preds

    def get_graph(self, graph_id):
        """Get a graph object associated to the node 'graph_id'."""
        return self._access_graph(graph_id)

    def get_typing(self, source_id, target_id):
        """Get a typing dict associated to the edge 'source_id->target_id'."""
        query = get_edge_attrs(
            source_id, target_id, self._typing_label,
            "attributes")
        result = self.execute(query)
        return properties_to_attributes(result, "attributes")

    def get_relation(self, left_id, right_id):
        """Get a relation dict associated to the rel 'left_id->target_id'."""
        query = get_edge_attrs(
            left_id, right_id, self._relation_label,
            "attributes")
        result = self.execute(query)
        return properties_to_attributes(result, "attributes")

    def get_graph_attrs(self, graph_id):
        """Get attributes of a graph in the hierarchy.

        Parameters
        ----------
        graph_id : hashable
            Id of the graph
        """
        query = get_node_attrs(
            graph_id, self._graph_label,
            "attributes")
        result = self.execute(query)
        return properties_to_attributes(
            result, "attributes")

    def set_graph_attrs(self, graph_id, attrs, update=False):
        """Set attributes of a graph in the hierarchy.

        Parameters
        ----------
        graph_id : hashable
            Id of the graph
        """
        skeleton = self._access_graph(self._graph_label)
        skeleton.set_node_attrs(graph_id, attrs, update)

    def get_typing_attrs(self, source_id, target_id):
        """Get attributes of a typing in the hierarchy.

        Parameters
        ----------
        source : hashable
            Id of the source graph
        target : hashable
            Id of the target graph
        """
        query = get_edge_attrs(
            source_id, target_id, self._typing_label,
            "attributes")
        result = self.execute(query)
        return properties_to_attributes(result, "attributes")

    def set_typing_attrs(self, source, target, attrs):
        """Set attributes of a typing in the hierarchy.

        Parameters
        ----------
        source : hashable
            Id of the source graph
        target : hashable
            Id of the target graph
        """
        skeleton = self._access_graph(self._graph_label, self._typing_label)
        skeleton.set_edge_attrs(source, target, attrs)

    def get_relation_attrs(self, left_id, right_id):
        """Get attributes of a reltion in the hierarchy.

        Parameters
        ----------
        left : hashable
            Id of the left graph
        right : hashable
            Id of the right graph
        """
        query = get_edge_attrs(
            left_id, right_id, self._relation_label,
            "attributes")
        result = self.execute(query)
        return properties_to_attributes(result, "attributes")

    def set_relation_attrs(self, left, right, attrs):
        """Set attributes of a relation in the hierarchy.

        Parameters
        ----------
        left : hashable
            Id of the left graph
        right : hashable
            Id of the right graph
        """
        skeleton = self._access_graph(self._graph_label, self._relation_label)
        skeleton.set_edge_attrs(left, right, attrs)

    def set_node_relation(self, left_graph, right_graph, left_node,
                          right_node):
        """Set relation for a particular node.

        Parameters
        ----------
        """
        query = set_intergraph_edge(
            left_graph, right_graph, left_node, right_node,
            "relation")
        self.execute(query)

    def add_graph(self, graph_id, node_list=None, edge_list=None,
                  attrs=None):
        """Add a new graph to the hierarchy.

        Parameters
        ----------
        graph_id : hashable
            Id of a new node in the hierarchy
        graph : regraph.Graph
            Graph object corresponding to the new node of
            the hierarchy
        graph_attrs : dict, optional
            Dictionary containing attributes of the new node
        """
        self.add_graph_from_data(graph_id, node_list, edge_list, attrs)

    def add_graph_from_data(self, graph_id, node_list, edge_list, attrs=None):
        """Add a new graph to the hierarchy from the input node/edge lists.

        Parameters
        ----------
        graph_id : hashable
            Id of a new node in the hierarchy
        node_list : iterable
            List of nodes (with attributes)
        edge_list : iterable
            List of edges (with attributes)
        graph_attrs : dict, optional
            Dictionary containing attributes of the new node
        """
        try:
            # Create a node in the hierarchy
            query = "CREATE ({}:{} {{ id : '{}' }}) \n".format(
                'new_graph',
                self._graph_label,
                graph_id)
            if attrs is not None:
                normalize_attrs(attrs)
                query += set_attributes(
                    var_name='new_graph',
                    attrs=attrs)
            self.execute(query)
        except(ConstraintError):
            raise HierarchyError(
                "The graph '{}' is already in the database.".format(graph_id))
        g = Neo4jGraph(
            driver=self._driver,
            node_label=graph_id,
            unique_node_ids=True)
        if node_list is not None:
            g.add_nodes_from(node_list)
        if edge_list is not None:
            g.add_edges_from(edge_list)

    def add_empty_graph(self, graph_id, attrs=None):
        """"Add a new empty graph to the hierarchy.

        Parameters
        ----------
        graph_id : hashable
            Id of a new node in the hierarchy
        graph_attrs : dict, optional
            Dictionary containing attributes of the new node
        """
        self.add_graph(graph_id, attrs=attrs)

    def add_typing(self, source, target, mapping, attrs=None, check=True):
        """Add homomorphism to the hierarchy.

        Parameters
        ----------
        source : hashable
            Id of the source graph node of typing
        target : hashable
            Id of the target graph node of typing
        mapping : dict
            Dictionary representing a mapping of nodes
            from the source graph to target's nodes
        attrs : dict
            Dictionary containing attributes of the new
            typing edge

        Raises
        ------
        HierarchyError
            This error is raised in the following cases:

                * source or target ids are not found in the hierarchy
                * a typing edge between source and target already exists
                * addition of an edge between source and target creates
                a cycle or produces paths that do not commute with
                some already existing paths

        InvalidHomomorphism
            If a homomorphisms from a graph at the source to a graph at
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
                        set_intergraph_edge(
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
                    valid_typing = check_homomorphism(tx, source, target)
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
                    paths_commute = check_consistency(tx, source, target)
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
                match_nodes(
                    var_id_dict={'g_src': source, 'g_tar': target},
                    node_label=self._graph_label) +
                add_edge(
                    edge_var='new_hierarchy_edge',
                    source_var='g_src',
                    target_var='g_tar',
                    edge_label=self._typing_label,
                    attrs=attrs) +
                with_vars(["new_hierarchy_edge"]) +
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
        """
        new_rel = normalize_relation(relation)

        if attrs is not None:
            normalize_attrs(attrs)

        for key, values in new_rel.items():
            for v in values:
                query = (
                    "MATCH (u:{} {{id: '{}'}}), (v:{} {{id: '{}'}})\n".format(
                        left, key, right, v) +
                    add_edge(
                        edge_var="rel",
                        source_var="u",
                        target_var="v",
                        edge_label="relation")
                )
                self.execute(query)

        # query = ""
        # rel_creation_queries = []
        # nodes_to_match_left = set()
        # nodes_to_match_right = set()
        # for key, values in relation.items():
        #     nodes_to_match_left.add(key)
        #     for value in values:
        #         nodes_to_match_right.add(value)
        #         rel_creation_queries.append(
        #             add_edge(
        #                 edge_var="rel_" + key + "_" + value,
        #                 source_var="n" + key + "_left",
        #                 target_var="n" + value + "_right",
        #                 edge_label="relation"))

        # if len(nodes_to_match_left) > 0:
        #     query += match_nodes(
        #         {"n" + n + "_left": n for n in nodes_to_match_left},
        #         node_label=g_left._node_label)
        #     query += with_vars(
        #         ["n" + s + "_left" for s in nodes_to_match_left])
        #     query += match_nodes(
        #         {"n" + n + "_right": n for n in nodes_to_match_right},
        #         node_label=g_right._node_label)
        #     for q in rel_creation_queries:
        #         query += q
        # print(query)
        # rel_addition_result = self.execute(query)

        skeleton_query = (
            match_nodes(
                var_id_dict={'g_left': left, 'g_right': right},
                node_label=self._graph_label) +
            add_edge(
                edge_var='new_hierarchy_edge',
                source_var='g_left',
                target_var='g_right',
                edge_label=self._relation_label,
                attrs=attrs)
        )
        skeleton_addition_result = self.execute(skeleton_query)
        return (None, skeleton_addition_result)

    def remove_graph(self, graph_id, reconnect=False):
        """Remove graph from the hierarchy.

        Removes a graph from the hierarchy, if the `reconnect`
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
            Id of a graph to remove
        reconnect : bool
            Reconnect the descendants of the removed node to
            its predecessors

        Raises
        ------
        HierarchyError
            If graph with `node_id` is not defined in the hierarchy
        """
        g = self._access_graph(graph_id)

        if reconnect:
            query = (
                "MATCH (n:{})".format(graph_id) +
                "OPTIONAL MATCH (pred)-[:typing]->(n)-[:typing]->(suc)\n" +
                "WITH pred, suc WHERE pred IS NOT NULL\n" +
                add_edge(
                    edge_var='reconnect_typing',
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
                match_node(
                    var_name="graph_to_rm",
                    node_id=graph_id,
                    node_label=self._graph_label) +
                "OPTIONAL MATCH (pred)-[:{}]->(n)-[:{}]->(suc)\n".format(
                    self._typing_label, self._typing_label) +
                "WITH pred, suc WHERE pred IS NOT NULL\n" +
                add_edge(
                    edge_var='reconnect_typing',
                    source_var='pred',
                    target_var='suc',
                    edge_label="typing")
            )
            self.execute(query)
        query = match_node(var_name="graph_to_rm",
                           node_id=graph_id,
                           node_label=self._graph_label)
        query += remove_nodes(["graph_to_rm"])
        self.execute(query)

    def remove_typing(self, s, t):
        """Remove a typing from the hierarchy."""
        # Clean-up the represenation of the homomorphism
        query = (
            "MATCH (:{})-[r:{}]->(:{})\n".format(
                s, self._graph_typing_label, t) +
            "DELETE r\n"
        )
        self.execute(query)
        # Remove the corresponding edge from the skeleton
        query = match_edge(
            "source", "target", s, t, "e",
            self._graph_label, self._graph_label,
            edge_label=self._typing_label)
        query += remove_edge("e")
        self.execute(query)

    def remove_relation(self, left, right):
        """Remove a relation from the hierarchy."""
        query = (
            "MATCH (:{})-[r:{}]-(:{})\n".format(
                left, self._graph_relation_label, right) +
            "DELETE r\n"
        )
        self.execute(query)
        # Remove the corresponding edge from the skeleton
        query = match_edge(
            "left", "right", left, right, "e",
            self._graph_label, self._graph_label,
            edge_label=self._relation_label)
        query += remove_edge("e")
        self.execute(query)

    def bfs_tree(self, graph, reverse=False):
        """BFS tree from the graph to all other reachable graphs."""
        bfs_result = [graph]
        if reverse:
            current_level = self.predecessors(graph)
        else:
            current_level = self.successors(graph)
        bfs_result += current_level

        while len(current_level) > 0:
            next_level = []
            for g in current_level:
                if reverse:
                    next_level += [
                        p for p in self.predecessors(g)
                        if p not in set(bfs_result)]
                else:
                    next_level += [
                        s for s in self.successors(g)
                        if s not in set(bfs_result)
                    ]
            current_level = next_level
            bfs_result += next_level

        return bfs_result

    def shortest_path(self, source, target):
        """Shortest path from 'source' to 'target'."""
        query = shortest_path_query(
            source, target, self._graph_label, self._typing_label)
        result = self.execute(query)
        return result.single()["path"]

    def find_matching(self, graph_id, pattern, pattern_typing=None,
                      nodes=None):
        """Find an instance of a pattern in a specified graph.

        graph_id : hashable
            Id of a graph in the hierarchy to search for matches
        pattern : regraph.Graph or nx.DiGraph object
            A pattern to match
        pattern_typing : dict
            A dictionary that specifies a typing of a pattern,
            keys of the dictionary -- graph id that types a pattern, this graph
            should be among parents of the `graph_id` graph; values are
            mappings of nodes from pattern to the typing graph;
        nodes : iterable
            Subset of nodes where matching should be performed
        """
        graph = self._access_graph(graph_id)
        instances = graph.find_matching(
            pattern, pattern_typing=pattern_typing, nodes=nodes)

        return instances

    def copy_graph(self, graph_id, new_graph_id, attach_graphs=[]):
        """Create a copy of a graph in a hierarchy."""
        if new_graph_id in self.graphs():
            raise HierarchyError(
                "Graph with id '{}' already exists in the hierarchy".format(
                    new_graph_id))
        self.add_graph(new_graph_id, attrs=self.get_graph_attrs(graph_id))
        copy_nodes_q = (
            "MATCH (n:{}) CREATE (n1:{}) SET n1=n\n ".format(
                graph_id, new_graph_id)
            # "SET n1.oldId = n.id, n1.id = toString(id(n1))\n"
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

    @abstractmethod
    def relabel_graph_node(self, graph_id, node, new_name):
        """Rename a node in a graph of the hierarchy."""
        pass

    @abstractmethod
    def relabel_graph(self, graph_id, new_graph_id):
        """Relabel a graph in the hierarchy.

        Parameters
        ----------
        graph_id : hashable
            Id of the graph to relabel
        new_graph_id : hashable
            New graph id to assign to this graph
        """
        pass

    @abstractmethod
    def relabel_graphs(self, mapping):
        """Relabel graphs in the hierarchy.

        Parameters
        ----------
        mapping: dict
            A dictionary with keys being old graph ids and their values
            being new id's of the respective graphs.

        Raises
        ------
        ReGraphError
            If new id's do not define a set of distinct graph id's.
        """
        pass

    @abstractmethod
    def _restrictive_rewrite(self, graph_id, rule, instance):
        """Perform a restrictive rewrite of the specified graph.

        This method rewrites the graph and updates its typing by
        the immediate successors. Note that as the result of this
        update, some homomorphisms (from ancestors) are broken!
        """
        pass

    @abstractmethod
    def _expansive_rewrite(self, graph_id, rule, instance):
        """Perform an expansive rewrite of the specified graph.

        This method rewrites the graph and updates its typing by
        the immediate predecessors. Note that as the result of this
        update, some homomorphisms (to descendants) are broken!
        """
        pass

    @abstractmethod
    def _propagate_clone(self, origin_id, graph_id, p_origin_m,
                         origin_m_origin, p_typing,
                         g_m_g, g_m_origin_m):
        """Propagate clones from 'origin_id' to 'graph_id'.

        Perform a controlled propagation of clones to 'graph'

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        p_origin_m : dict
            Instance of rule's interface inside the updated origin
        origin_m_origin : dict
            Map from the updated origin to the initial origin
        p_typing : dict
            Controlling relation from the nodes of 'graph_id' to
            the nodes of the interfaces
        """
        pass

    @abstractmethod
    def _propagate_node_removal(self, origin_id, graph_id, rule, instance,
                                g_m_g, g_m_origin_m):
        """Propagate node removal from 'origin_id' to 'graph_id'.

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        origin_m_origin : dict
            Map from the updated origin to the initial origin

        """
        pass

    @abstractmethod
    def _propagate_node_attrs_removal(self, origin_id, graph_id, rule, instance):
        """Propagate node attrs removal from 'origin_id' to 'graph_id'.

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        rule : regraph.Rule
            Original rewriting rule
        instance : dict
            Original instance
        """
        pass

    @abstractmethod
    def _propagate_edge_removal(self, origin_id, graph_id, g_m_origin_m):
        """Propagate edge removal from 'origin_id' to 'graph_id'.

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        p_origin_m : dict
            Instance of rule's interface inside the updated origin
        origin_m_origin : dict
            Map from the updated origin to the initial origin
        """
        pass

    @abstractmethod
    def _propagate_edge_attrs_removal(self, origin_id, graph_id, rule, p_origin_m):
        """Propagate edge attrs removal from 'origin_id' to 'graph_id'.

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        rule : regraph.Rule
            Original rewriting rule
        p_origin_m : dict
            Instance of rule's interface inside the updated origin
        """
        pass

    @abstractmethod
    def _propagate_merge(self, origin_id, graph_id, rule, p_origin_m,
                         rhs_origin_prime, g_g_prime, origin_prime_g_prime):
        """Propagate merges from 'origin_id' to 'graph_id'.

        Perform a propagation of merges to 'graph'

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        rule : regraph.Rule
            Original rewriting rule
        p_origin_m : dict
            Instance of rule's interface inside the updated origin
        rhs_origin_prime : dict
            Instance of rule's rhs inside the updated origin
        g_g_prime : dict
            Map from the nodes of the graph 'graph_id' to the updated graph
        origin_prime_g_prime : dict
            Map from the updated origin to the updated graph with 'graph_id'
        """
        pass

    @abstractmethod
    def _propagate_node_addition(self, origin_id, graph_id, rule,
                                 rhs_origin_prime, rhs_typing,
                                 origin_prime_g_prime):
        """Propagate node additions from 'origin_id' to 'graph_id'.

        Perform a propagation of additions to 'graph'

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        rule : regraph.Rule
            Original rewriting rule
        rhs_origin_prime : dict
            Instance of rule's rhs inside the updated origin
        rhs_typing : dict
            Typing of the nodes from the rhs in 'graph_id'
        origin_prime_g_prime : dict
            Map from the updated origin to the updated graph with 'graph_id'
        """
        pass

    @abstractmethod
    def _propagate_node_attrs_addition(self, origin_id, graph_id, rule,
                                       rhs_origin_prime, origin_prime_g_prime):
        """Propagate node attrs additions from 'origin_id' to 'graph_id'.

        Perform a propagation of additions to 'graph'

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        rule : regraph.Rule
            Original rewriting rule
        rhs_origin_prime : dict
            Instance of rule's rhs inside the updated origin
        origin_prime_g_prime : dict
            Map from the updated origin to the updated graph with 'graph_id'
        """
        pass

    @abstractmethod
    def _propagate_edge_addition(self, origin_id, graph_id, rule,
                                 rhs_origin_prime, origin_prime_g_prime):
        """Propagate edge additions from 'origin_id' to 'graph_id'.

        Perform a propagation of additions to 'graph'

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        rule : regraph.Rule
            Original rewriting rule
        rhs_origin_prime : dict
            Instance of rule's rhs inside the updated origin
        origin_prime_g_prime : dict
            Map from the updated origin to the updated graph with 'graph_id'
        """
        pass

    @abstractmethod
    def _propagate_edge_attrs_addition(self, origin_id, graph_id, rule,
                                       rhs_origin_prime, origin_prime_g_prime):
        """Propagate edge attrs additions from 'origin_id' to 'graph_id'.

        Perform a propagation of additions to 'graph'

        Parameters
        ----------
        origin_id : hashable
            ID of the graph corresponding to the origin of rewriting
        graph_id : hashable
            ID of the graph where propagation is performed
        """
        pass

    @abstractmethod
    def _get_rule_liftings(self, graph_id, rule, instance, p_typing):
        pass

    @abstractmethod
    def _get_rule_projections(self, graph_id, rule, instance, rhs_typing):
        pass

    # Implementation of the Neo4jHierarchy-specific methods

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

        try:
            query = "CREATE " + constraint_query(
                'n', self._graph_label, 'id')
            self.execute(query)
        except:
            pass

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
        query = clear_graph()
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

    def _access_graph(self, graph_id, edge_label=None):
        """Access a graph of the hierarchy."""
        if edge_label is None:
            edge_label = "edge"
        g = Neo4jGraph(
            self._driver,
            node_label=graph_id, edge_label=edge_label)
        return g
