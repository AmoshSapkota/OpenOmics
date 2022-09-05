import os
from io import TextIOWrapper, StringIO
from typing import Tuple, List, Dict, Iterable, Union, Callable

import dask.dataframe as dd
import networkx as nx
import numpy as np
import obonet
import pandas as pd
import tqdm
from Bio.UniProt.GOA import _gaf20iterator, _gaf10iterator
from pandas import DataFrame

from openomics.utils.adj import slice_adj
from .base import Database


class Ontology(Database):
    annotations: pd.DataFrame

    def __init__(self,
                 path,
                 file_resources=None,
                 col_rename=None,
                 npartitions=0,
                 verbose=False):
        """
        Manages dataset input processing from tables and construct an ontology network from .obo file. There ontology
        network is G(V,E) where there exists e_ij for child i to parent j to present "node i is_a node j".

        Args:
            path:
            file_resources:
            col_rename:
            npartitions:
            verbose:
        """
        self.network, self.node_list = self.load_network(file_resources)

        super().__init__(
            path=path,
            file_resources=file_resources,
            col_rename=col_rename,
            npartitions=npartitions,
            verbose=verbose,
        )

    def load_network(self, file_resources) -> Tuple[nx.MultiDiGraph, List[str]]:
        raise NotImplementedError()

    def filter_network(self, namespace) -> None:
        """
        Filter the subgraph node_list to only `namespace` terms.
        Args:
            namespace: one of {"biological_process", "cellular_component", "molecular_function"}
        """
        terms = self.data[self.data["namespace"] == namespace]["go_id"].unique()
        print("{} terms: {}".format(namespace,
                                    len(terms))) if self.verbose else None
        self.network = self.network.subgraph(nodes=list(terms))
        self.node_list = np.array(list(terms))

    def adj(self, node_list):
        adj_mtx = nx.adj_matrix(self.network, nodelist=node_list)

        if node_list is None or list(node_list) == list(self.node_list):
            return adj_mtx
        elif set(node_list) < set(self.node_list):
            return slice_adj(adj_mtx, list(self.node_list), node_list,
                             None)
        elif not (set(node_list) < set(self.node_list)):
            raise Exception("A node in node_list is not in self.node_list.")

        return adj_mtx

    def filter_annotation(self, annotation: pd.Series):
        go_terms = set(self.node_list)
        filtered_annotation = annotation.map(lambda x: list(set(x) & go_terms)
                                             if isinstance(x, list) else [])

        return filtered_annotation

    def get_child_nodes(self):
        adj = self.adj(self.node_list)
        leaf_terms = self.node_list[np.nonzero(adj.sum(axis=0) == 0)[1]]
        return leaf_terms

    def get_root_nodes(self):
        adj = self.adj(self.node_list)
        parent_terms = self.node_list[np.nonzero(adj.sum(axis=1) == 0)[0]]
        return parent_terms

    def get_dfs_paths(self, root_nodes: list, filter_duplicates=False):
        """
        Return all depth-first search paths from root node(s) to children node by traversing the ontology directed graph.
        Args:
            root_nodes (list): ["GO:0008150"] if biological processes, ["GO:0003674"] if molecular_function, or ["GO:0005575"] if cellular_component
            filter_duplicates (bool): whether to remove duplicated paths that end up at the same leaf nodes

        Returns: pd.DataFrame of all paths starting from the root nodes.
        """
        if not isinstance(root_nodes, list):
            root_nodes = list(root_nodes)

        paths = list(dfs_path(self.network, root_nodes))
        paths = list(flatten_list(paths))
        paths_df = pd.DataFrame(paths)

        if filter_duplicates:
            paths_df = paths_df[~paths_df.duplicated(keep="first")]
            paths_df = filter_dfs_paths(paths_df)

        return paths_df

    def remove_predecessor_terms(self, annotation: pd.Series, sep="\||;"):
        # leaf_terms = self.get_child_nodes()
        # if not annotation.map(lambda x: isinstance(x, (list, np.ndarray))).any() and sep:
        #     annotation = annotation.str.split(sep)
        #
        # parent_terms = annotation.map(lambda x: list(
        #     set(x) & set(leaf_terms)) if isinstance(x, (list, np.ndarray)) else None)
        # return parent_terms
        raise NotImplementedError

    def get_subgraph(self, edge_types: Union[str, List[str]]) -> Union[nx.MultiDiGraph, nx.DiGraph]:
        if not hasattr(self, "_subgraphs"):
            self._subgraphs = {}
        elif edge_types in self._subgraphs:
            return self._subgraphs[edge_types]

        if edge_types and isinstance(self.network, (nx.MultiGraph, nx.MultiDiGraph)):
            g = self.network.edge_subgraph([(u, v, k) for u, v, k in self.network.edges if k in edge_types])
        else:
            g = self.network

        self._subgraphs[edge_types] = g

        return g

    def add_predecessor_terms(self, anns: pd.Series, edge_type: Union[str, List[str]] = 'is_a', sep="\||;"):
        anns_w_parents = anns.map(lambda x: [] if not isinstance(x, (list, np.ndarray)) else x) + \
                         get_predecessor_terms(self.get_subgraph(edge_type), anns)

        return anns_w_parents

    @staticmethod
    def get_node_color(
        file="~/Bioinformatics_ExternalData/GeneOntology/go_colors_biological.csv",
    ):
        go_colors = pd.read_csv(file)

        def selectgo(x):
            terms = [term for term in x if isinstance(term, str)]
            if len(terms) > 0:
                return terms[-1]
            else:
                return None

        go_colors["node"] = go_colors[[
            col for col in go_colors.columns if col.isdigit()
        ]].apply(selectgo, axis=1)
        go_id_colors = go_colors[go_colors["node"].notnull()].set_index(
            "node")["HCL.color"]
        go_id_colors = go_id_colors[~go_id_colors.index.duplicated(
            keep="first")]
        print(go_id_colors.unique().shape,
              go_colors["HCL.color"].unique().shape)
        return go_id_colors



class HumanPhenotypeOntology(Ontology):
    """Loads the Human Phenotype Ontology database from https://hpo.jax.org/app/ .

        Default path: "http://geneontology.org/gene-associations/" .
        Default file_resources: {
            "hp.obo": "http://purl.obolibrary.org/obo/hp.obo",
        }
        """
    COLUMNS_RENAME_DICT = {}

    def __init__(
        self,
        path="https://hpo.jax.org/",
        file_resources=None,
        col_rename=COLUMNS_RENAME_DICT,
        npartitions=0,
        verbose=False,
    ):
        """
        Handles downloading the latest Human Phenotype Ontology obo and annotation data, preprocesses them. It provide
        functionalities to create a directed acyclic graph of Ontology terms, filter terms, and filter annotations.
        """
        if file_resources is None:
            file_resources = {
                "hp.obo": "http://purl.obolibrary.org/obo/hp.obo",
            }
        super().__init__(
            path,
            file_resources,
            col_rename=col_rename,
            npartitions=npartitions,
            verbose=verbose,
        )

    def info(self):
        print("network {}".format(nx.info(self.network)))

    def load_network(self, file_resources):
        for file in file_resources:
            if ".obo" in file:
                network = obonet.read_obo(file_resources[file])
                network = network.reverse(copy=True)
                node_list = np.array(network.nodes)
        return network, node_list


class GeneOntology(Ontology):
    """Loads the GeneOntology database from http://geneontology.org .

    Default path: "http://geneontology.org/gene-associations/" .
    Default file_resources: {
        "go-basic.obo": "http://purl.obolibrary.org/obo/go/go-basic.obo",
        "goa_human.gaf": "goa_human.gaf.gz",
        "goa_human_rna.gaf": "goa_human_rna.gaf.gz",
        "goa_human_isoform.gaf": "goa_human_isoform.gaf.gz",
    }
    """
    COLUMNS_RENAME_DICT = {
        "DB_Object_Symbol": "gene_name",
        "DB_Object_ID": "gene_id",
        "GO_ID": "go_id",
        "Taxon_ID": 'species_id',
    }

    def __init__(
        self,
        path="http://geneontology.org/gene-associations/",
        species="HUMAN",
        file_resources=None,
        col_rename=COLUMNS_RENAME_DICT,
        npartitions=0,
        verbose=False,
    ):
        """
        Loads the GeneOntology database from http://geneontology.org .

            Default path: "http://geneontology.org/gene-associations/" .
            Default file_resources: {
                "go-basic.obo": "http://purl.obolibrary.org/obo/go/go-basic.obo",
                "goa_human.gaf": "goa_human.gaf.gz",
                "goa_human_rna.gaf": "goa_human_rna.gaf.gz",
                "goa_human_isoform.gaf": "goa_human_isoform.gaf.gz",
            }

        Handles downloading the latest Gene Ontology obo and annotation data, preprocesses them. It provide
        functionalities to create a directed acyclic graph of GO terms, filter terms, and filter annotations.
        """

        self.species = species.lower()

        if file_resources is None:
            file_resources = {
                "go-basic.obo": "http://purl.obolibrary.org/obo/go/go-basic.obo",
                f"goa_{species.lower()}.gaf.gz": f"goa_{species.lower()}.gaf.gz",
                f"goa_{species.lower()}_rna.gaf.gz": f"goa_{species.lower()}_rna.gaf.gz",
                f"goa_{species.lower()}_isoform.gaf.gz": f"goa_{species.lower()}_isoform.gaf.gz",
            }

        super().__init__(path, file_resources, col_rename=col_rename, npartitions=npartitions, verbose=verbose, )

    def info(self):
        print("network {}".format(nx.info(self.network)))

    def load_dataframe(self, file_resources: Dict[str, TextIOWrapper], npartitions=None):
        # Annotations for each GO term
        go_annotations = pd.DataFrame.from_dict(dict(self.network.nodes(data=True)), orient='index')
        go_annotations["def"] = go_annotations["def"].apply(lambda x: x.split('"')[1] if isinstance(x, str) else None)
        go_annotations.index.name = "go_id"

        # Handle .gaf annotation files
        dfs = []
        dropcols = {'DB:Reference', 'With', 'Annotation_Extension', 'Gene_Product_Form_ID'}
        for file in file_resources:
            if file.endswith(".gaf"):
                records = []
                for record in tqdm.tqdm(gafiterator(file_resources[file]), desc=file):
                    records.append({k: v for k, v in record.items() if k not in dropcols})

                df = pd.DataFrame(records)
                df["Date"] = pd.to_datetime(df["Date"], )
                df['Taxon_ID'] = df['Taxon_ID'].apply(lambda li: [s.strip("taxon:") for s in li])

                dfs.append(dd.from_pandas(df, npartitions=npartitions) if npartitions else df)

        if len(dfs):
            self.annotations = dd.concat(dfs) if npartitions else pd.concat(dfs)
            self.annotations = self.annotations.rename(columns=self.COLUMNS_RENAME_DICT)
            # self.annotations["Date"] = pd.to_datetime(self.annotations["Date"], )
            # self.annotations['species_id'] = self.annotations['species_id'].apply(lambda li: [s.strip("taxon:") for s in li])

        return go_annotations

    def load_network(self, file_resources):
        for file in file_resources:
            if file.endswith(".obo"):
                network: nx.MultiDiGraph = obonet.read_obo(file_resources[file])
                network = network.reverse(copy=True)
                node_list = np.array(network.nodes)

        return network, node_list

    def split_annotations(self, src_node_col="gene_name", dst_node_col="go_id", train_date: str = "2017-06-15",
                          valid_date: str = "2017-11-15", test_date: str = "2021-12-31",
                          filter_evidence: List = ['EXP', 'IDA', 'IPI', 'IMP', 'IGI', 'IEP', 'TAS', 'IC'],
                          groupby: List[str] = ["Qualifier"],
                          filter_dst_nodes: Union[List, pd.Index] = None,
                          agg: Union[Callable, str] = "unique") -> Tuple[DataFrame, DataFrame, DataFrame]:
        assert isinstance(groupby, list)
        if src_node_col not in groupby:
            groupby = [src_node_col] + groupby
        if "Qualifier" not in groupby:
            groupby.append("Qualifier")

        if agg == "add_parent":
            if isinstance(self.annotations, dd.DataFrame):
                agg = dd.Aggregation(name='_unique_add_parent',
                                     chunk=lambda s: s.apply(lambda x: list(set(x))),
                                     agg=lambda s0: s0.obj + get_predecessor_terms(self.get_subgraph(edge_types="is_a"),
                                                                                   s0.obj))
            else:
                def _unique_add_parent(s: pd.Series) -> List:
                    if s.empty: return
                    s = s.unique()
                    return s.tolist() + get_predecessor_terms(self.get_subgraph(edge_types="is_a"), s).iloc[0]

                agg = _unique_add_parent
        else:
            assert agg in ['unique', 'add_parent']

        # Set the source column (i.e. protein_id or gene_name), to be the first in groupby
        def _remove_dup_neg_go_id(s: pd.Series) -> pd.Series:
            if s.isna().any():
                pass
            elif isinstance(s[neg_dst_col], (list, np.ndarray)) and isinstance(s[dst_node_col], (list, np.ndarray)):
                rm_dups_go_id = [go_id for go_id in s[neg_dst_col] if go_id not in s[dst_node_col]]
                if len(rm_dups_go_id) == 0:
                    rm_dups_go_id = None
                s[neg_dst_col] = rm_dups_go_id
            return s

        neg_dst_col = f"neg_{dst_node_col}"

        # Filter annotations
        annotations = self.annotations[self.annotations["Evidence"].isin(filter_evidence)]
        if filter_dst_nodes is not None:
            annotations = annotations[annotations[dst_node_col].isin(filter_dst_nodes)]

        # Split train/valid/test annotations
        train_anns = annotations[annotations["Date"] <= pd.to_datetime(train_date)]
        valid_anns = annotations[(annotations["Date"] <= pd.to_datetime(valid_date)) & \
                                 (annotations["Date"] > pd.to_datetime(train_date))]
        if test_date:
            test_anns = annotations[(annotations["Date"] <= pd.to_datetime(test_date)) & \
                                    (annotations["Date"] > pd.to_datetime(valid_date))]
        else:
            test_anns = valid_anns

        outputs = []
        for anns in [train_anns, valid_anns, test_anns]:
            is_neg_ann = anns["Qualifier"].map(lambda li: "NOT" in li)

            # Convert `Qualifiers` entries of list of strings to string
            anns['Qualifier'] = anns['Qualifier'].apply(lambda li: "".join([i for i in li if i != "NOT"]))

            # Positive gene-GO annotations
            if isinstance(anns, pd.DataFrame):
                pos_anns = anns[~is_neg_ann].groupby(groupby).agg(**{dst_node_col: (dst_node_col, agg)})
                neg_anns = anns[is_neg_ann].groupby(groupby).agg(**{neg_dst_col: (dst_node_col, agg)})

            elif isinstance(anns, dd.DataFrame):
                pos_anns = anns[~is_neg_ann].groupby(groupby).agg({dst_node_col: agg})
                neg_anns = anns[is_neg_ann].groupby(groupby).agg({neg_dst_col: agg})

            # Negative gene-GO annotations
            pos_neg_anns = pd.concat([pos_anns, neg_anns], axis=1)
            pos_neg_anns.drop(index=[""], inplace=True, errors="ignore")

            # Remove "GO:0005515" (protein binding) annotations for a gene if it's the gene's only annotation
            _exclude_single_fn = lambda li: \
                (len(li) == 1 and "GO:0005515" in li) if isinstance(li, (list, np.ndarray)) else False
            pos_neg_anns.loc[pos_neg_anns[dst_node_col].map(_exclude_single_fn), dst_node_col] = None
            # Drop rows with allna values
            pos_neg_anns.drop(index=pos_neg_anns.index[pos_neg_anns.isna().all(1)], inplace=True)
            # Ensure no negative terms duplicates positive annotations
            pos_neg_anns = pos_neg_anns.apply(_remove_dup_neg_go_id, axis=1)

            outputs.append(pos_neg_anns)

        return tuple(outputs)


class UniProtGOA(GeneOntology):
    """Loads the GeneOntology database from https://www.ebi.ac.uk/GOA/ .

    Default path: "ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/UNIPROT/" .
    Default file_resources: {
        "goa_uniprot_all.gpi": "ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/UNIPROT/goa_uniprot_all.gpi.gz",
        "goa_uniprot_all.gaf": "goa_uniprot_all.gaf.gz",
    }
    """
    COLUMNS_RENAME_DICT = {
        "DB_Object_ID": "protein_id",
        "DB_Object_Symbol": "gene_name",
        "GO_ID": "go_id",
        "Taxon_ID": 'species_id',
    }

    def __init__(
        self,
        path="ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/",
        species="HUMAN",
        file_resources=None,
        col_rename=COLUMNS_RENAME_DICT,
        npartitions=0,
        verbose=False,
    ):
        """
        Loads the GeneOntology database from http://geneontology.org .

            Default path: "ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/UNIPROT/" .
            Default file_resources: {
                "goa_uniprot_all.gpi": "ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/UNIPROT/goa_uniprot_all.gpi.gz",
                "goa_uniprot_all.gaf": "goa_uniprot_all.gaf.gz",
            }

        Handles downloading the latest Gene Ontology obo and annotation data, preprocesses them. It provide
        functionalities to create a directed acyclic graph of GO terms, filter terms, and filter annotations.
        """
        if species is None:
            self.species = species = 'UNIPROT'
            substr = 'uniprot_all'
        else:
            self.species = species.upper()
            substr = species.lower()

        if file_resources is None:
            file_resources = {
                "go.obo": "http://current.geneontology.org/ontology/go.obo",
                f"goa_{self.species.lower()}.gaf.gz": os.path.join(species, f"goa_{substr}.gaf.gz"),
                # f"goa_{self.species.lower()}_isoform.gaf": os.path.join(species, f"goa_{substr}_isoform.gaf.gz"),
                # f"goa_{self.species.lower()}_complex.gaf": os.path.join(species, f"goa_{substr}_complex.gaf.gz"),
                # f"goa_{self.species.lower()}.gpi": os.path.join(species, f"goa_{substr}.gpi.gz"),
            }
        super().__init__(path=path, species=species, file_resources=file_resources, col_rename=col_rename,
                         npartitions=npartitions, verbose=verbose)


class InterPro(Ontology):
    def __init__(self, path="https://ftp.ebi.ac.uk/pub/databases/interpro/current_release/",
                 file_resources=None, col_rename=None, verbose=False, npartitions=None):
        """
        Args:
            path:
            file_resources:
            col_rename:
            verbose:
            npartitions:
        """

        if file_resources is None:
            file_resources = {}
            file_resources["entry.list"] = os.path.join(path, "entry.list")
            file_resources["protein2ipr.dat.gz"] = os.path.join(path, "protein2ipr.dat.gz")
            file_resources["interpro2go"] = os.path.join(path, "interpro2go")
            file_resources["ParentChildTreeFile.txt"] = os.path.join(path, "ParentChildTreeFile.txt")

        super().__init__(path=path, file_resources=file_resources, col_rename=col_rename, verbose=verbose,
                         npartitions=npartitions)

    def load_dataframe(self, file_resources: Dict[str, TextIOWrapper], npartitions=None):
        ipr_entries = pd.read_table(file_resources["entry.list"], index_col="ENTRY_AC")
        ipr2go = self.parse_interpro2go(file_resources["interpro2go"])

        ipr_entries = ipr_entries.join(ipr2go.groupby('ENTRY_AC')["go_id"].unique(), on="ENTRY_AC")

        self.annotations: dd.DataFrame = dd.read_table(
            file_resources["protein2ipr.dat"],
            names=['UniProtKB-AC', 'ENTRY_AC', 'ENTRY_NAME', 'accession', 'start', 'stop'],
            usecols=['UniProtKB-AC', 'ENTRY_AC', 'start', 'stop'],
            dtype={'UniProtKB-AC': 'category', 'ENTRY_AC': 'category'})

        return ipr_entries

    def load_network(self, file_resources):
        for file in file_resources:
            if 'ParentChildTreeFile' in file and isinstance(file_resources[file], str) \
                and os.path.exists(file_resources[file]):
                network: nx.MultiDiGraph = self.parse_ipr_treefile(file_resources[file])
                node_list = np.array(network.nodes)

                return network, node_list
        return None, None

    def get_annotations_adj(self, protein_ids: pd.Index):
        g = nx.MultiDiGraph()
        g.add_nodes_from(protein_ids.tolist())

        def add_edgelist(edgelist_df: DataFrame) -> None:
            edge_mask = edgelist_df["UniProtKB-AC"].isin(protein_ids)
            if edge_mask.sum():
                edgelist = [(row[0], row[1], row[2:].to_dict()) for i, row in edgelist_df.iterrows()]
                g.add_edges_from(edgelist, weight=1)

        self.annotations.map_partitions(add_edgelist).compute()

        adj = nx.bipartite.biadjacency_matrix(g, row_order=protein_ids, column_order=self.data["ENTRY_AC"],
                                              weight='weight',
                                              format='csc')
        adj = pd.DataFrame(adj, index=protein_ids, columns=self.data["ENTRY_AC"])
        return adj

    def parse_ipr_treefile(self, lines: Union[Iterable[str], StringIO]) -> nx.MultiDiGraph:
        """Parse the InterPro Tree from the given file.
        Args:
            lines: A readable file or file-like
        """
        if isinstance(lines, str):
            lines = open(lines, 'r')

        graph = nx.MultiDiGraph()
        previous_depth, previous_name = 0, None
        stack = [previous_name]

        def count_front(s: str) -> int:
            """Count the number of leading dashes on a string."""
            for position, element in enumerate(s):
                if element != '-':
                    return position

        for line in lines:
            depth = count_front(line)
            interpro_id, name, *_ = line[depth:].split('::')

            if depth == 0:
                stack.clear()
                stack.append(interpro_id)

                graph.add_node(interpro_id, interpro_id=interpro_id, name=name)

            else:
                if depth > previous_depth:
                    stack.append(previous_name)

                elif depth < previous_depth:
                    del stack[-1]

                parent = stack[-1]

                graph.add_node(interpro_id, interpro_id=interpro_id, parent=parent, name=name)
                graph.add_edge(parent, interpro_id, key="is_a")

            previous_depth, previous_name = depth, interpro_id

        return graph

    def parse_interpro2go(self, file: StringIO) -> DataFrame:
        if isinstance(file, str):
            file = open(file, 'r')

        def _process_line(line: str) -> Tuple[str, str, str]:
            pos = line.find('> GO')
            interpro_terms, go_term = line[:pos], line[pos:]
            interpro_id, interpro_name = interpro_terms.strip().split(' ', 1)
            go_name, go_id = go_term.split(';')
            go_desc = go_name.strip('> GO:')

            return (interpro_id.strip().split(':')[1], go_id.strip(), go_desc)

        tuples = [_process_line(line.strip()) for line in file if line[0] != '!']
        return pd.DataFrame(tuples, columns=['ENTRY_AC', "go_id", "go_desc"])


def gafiterator(handle):
    inline = handle.readline()
    if inline.strip().startswith("!gaf-version: 2"):
        # sys.stderr.write("gaf 2.0\n")
        return _gaf20iterator(handle)
    elif inline.strip() == "!gaf-version: 1.0":
        # sys.stderr.write("gaf 1.0\n")
        return _gaf10iterator(handle)
    else:
        return _gaf20iterator(handle)


def get_predecessor_terms(g: nx.MultiDiGraph, anns: pd.Series) -> pd.Series:
    if isinstance(anns, np.ndarray):
        anns = pd.Series([anns.tolist()])
    elif isinstance(anns, list):
        anns = pd.Series([anns])
    elif isinstance(anns, pd.Series) and (~anns.map(type).isin({list, np.ndarray})).any():
        anns = anns.map(list)

    try:
        parent_terms = anns.map(
            lambda li: list({parent for term in li for parent in nx.ancestors(g, term)}) \
                if isinstance(li, (list, np.ndarray)) else [])

    except Exception as e:
        print(e)
        return anns

    return parent_terms


def traverse_predecessors(network, seed_node, type=["is_a", "part_of"]):
    """
    Returns all successor terms from seed_node by traversing the ontology network with edges == `type`.
    Args:
        seed_node: seed node of the traversal
        type: the ontology type to include
    Returns:
        generator of list of lists for each dfs branches.
    """
    parents = dict(network.pred[seed_node])
    for parent, v in parents.items():
        if list(v.keys())[0] in type:
            yield [parent] + list(traverse_predecessors(network, parent, type))


def flatten(lst):
    return sum(([x] if not isinstance(x, list) else flatten(x) for x in lst),
               [])


def dfs_path(graph, path):
    node = path[-1]
    successors = list(graph.successors(node))
    if len(successors) > 0:
        for child in successors:
            yield list(dfs_path(graph, path + [child]))
    else:
        yield path


def flatten_list(list_in):
    if isinstance(list_in, list):
        for l in list_in:
            if isinstance(list_in[0], list):
                for y in flatten_list(l):
                    yield y
            elif isinstance(list_in[0], str):
                yield list_in
    else:
        yield list_in


def filter_dfs_paths(paths_df: pd.DataFrame):
    idx = {}
    for col in sorted(paths_df.columns[:-1], reverse=True):
        idx[col] = ~(paths_df[col].notnull()
                     & paths_df[col].duplicated(keep="first")
                     & paths_df[col + 1].isnull())

    idx = pd.DataFrame(idx)

    paths_df = paths_df[idx.all(axis=1)]
    return paths_df


def write_taxonomy(network, root_nodes, file_path):
    """

    Args:
        network: A network with edge(i, j) where i is a node and j is a child of i.
        root_nodes (list): a list of node names
        file_path (str):
    """
    file = open(file_path, "a")
    file.write("Root\t" + "\t".join(root_nodes) + "\n")

    for root_node in root_nodes:
        for node, children in nx.traversal.bfs_successors(network, root_node):
            if len(children) > 0:
                file.write(node + "\t" + "\t".join(children) + "\n")
    file.close()
