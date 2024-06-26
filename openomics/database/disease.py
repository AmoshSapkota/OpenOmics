from abc import abstractmethod

import pandas as pd
from openomics.database.base import Database, Annotatable

__all__ = ['DiseaseAssociation', 'MalaCards', 'DisGeNet', 'HMDD', 'LncRNADisease']

class DiseaseAssociation(Database):
    def __init__(self, path, file_resources=None, **kwargs):
        """
        Args:
            path:
            file_resources:
            **kwargs:
        """
        super().__init__(path, file_resources, **kwargs)

    @abstractmethod
    def get_disease_assocs(self, index="gene_name"):
        """
        Args:
            index:
        """
        return self.data.groupby(index)[Annotatable.DISEASE_ASSOCIATIONS_COL].unique()


class MalaCards(DiseaseAssociation):
    """Loads the MalaCards database from "http://zdzlab.einstein.yu.edu/1/hedd/" .

    Default path: "http://zdzlab.einstein.yu.edu/1/hedd/" .
    Default file_resources: {
        "MalaCards.csv": "download.action.php?filename=DataDownload/MalaCards.csv",
    }
    """
    COLUMNS_RENAME_DICT = {
        "geneSymbol": "gene_name",
        "maladyMainName": Annotatable.DISEASE_ASSOCIATIONS_COL
    }

    def __init__(self, path="http://zdzlab.einstein.yu.edu/1/hedd/", file_resources=None,
                 col_rename=COLUMNS_RENAME_DICT, **kwargs):
        """
        Args:
            path:
            file_resources:
            col_rename:
            **kwargs:
        """
        if file_resources is None:
            file_resources = {}
            file_resources["MalaCards.csv"] = "download.action.php?filename=DataDownload/MalaCards.csv"

        super().__init__(path, file_resources, col_rename=col_rename, **kwargs)

    def load_dataframe(self, file_resources, blocksize=None):
        # type: (dict, int) -> pd.DataFrame
        """
        Args:
            file_resources:
            blocksize:
        """
        df = pd.read_csv(file_resources["MalaCards.csv"])
        return df


class DisGeNet(DiseaseAssociation):
    """Loads the  database from  .

    Default path:  .
    Default file_resources: {
        "": "",
        "": "",
        "": "",
    }
    """
    COLUMNS_RENAME_DICT = {"geneSymbol": "gene_name",
                           "diseaseName": Annotatable.DISEASE_ASSOCIATIONS_COL}

    def __init__(self, path="https://www.disgenet.org/static/disgenet_ap1/files/downloads/",
                 file_resources=None, curated=True, col_rename=COLUMNS_RENAME_DICT,
                 **kwargs):
        """
        Args:
            path:
            file_resources:
            curated:
            col_rename:
            **kwargs:
        """
        if file_resources is None:
            file_resources = {}
            file_resources["curated_gene_disease_associations.tsv"] = "curated_gene_disease_associations.tsv.gz"
            file_resources["all_gene_disease_associations.tsv"] = "all_gene_disease_associations.tsv.gz"

        self.curated = curated
        super().__init__(path, file_resources, col_rename=col_rename, **kwargs)

    def load_dataframe(self, file_resources, blocksize=None):
        """
        Args:
            file_resources:
            blocksize:
        """
        if self.curated:
            df = pd.read_table(file_resources["curated_gene_disease_associations.tsv"],
                               usecols=["geneSymbol", "diseaseName", "score"])
        else:
            df = pd.read_table(file_resources["all_gene_disease_associations.tsv"],
                               usecols=["geneSymbol", "diseaseName", "score"])

        df["diseaseName"] = df["diseaseName"].str.lower()
        return df


class HMDD(DiseaseAssociation):
    """Loads the HMDD database from "http://www.cuilab.cn/static/hmdd3" .

    Default path: "http://www.cuilab.cn/static/hmdd3/data/" .
    Default file_resources: {
        "alldata.txt": "alldata.txt",
    }
    """
    COLUMNS_RENAME_DICT = {
        "mir": "gene_name",
        "disease": Annotatable.DISEASE_ASSOCIATIONS_COL
    }

    def __init__(self, path="http://www.cuilab.cn/static/hmdd3/data/",
                 file_resources=None, col_rename=COLUMNS_RENAME_DICT,
                 **kwargs):
        """
        Args:
            path:
            file_resources:
            col_rename:
            **kwargs:
        """
        if file_resources is None:
            file_resources = {}
            file_resources["alldata.txt"] = "alldata.txt"

        super().__init__(path, file_resources, col_rename=col_rename, **kwargs)

    def load_dataframe(self, file_resources, blocksize=None):
        """
        Args:
            file_resources:
            blocksize:
        """
        df = pd.read_csv(file_resources["alldata.txt"], sep="\t", encoding="unicode_escape")
        df["disease"] = df["disease"].str.lower()
        return df


class LncRNADisease(DiseaseAssociation):
    COLUMNS_RENAME_DICT = {
        "LncRNA name": "gene_name",
        "Disease name": Annotatable.DISEASE_ASSOCIATIONS_COL
    }

    def __init__(self, path="http://www.cuilab.cn/files/images/ldd/",
                 file_resources=None, species="Human", col_rename=COLUMNS_RENAME_DICT,
                 **kwargs):
        """
        Args:
            path:
            file_resources:
            species:
            col_rename:
            **kwargs:
        """
        if file_resources is None:
            file_resources = {}
            file_resources["data_v2017.txt"] = "data_v2017.txt"

        self.species = species
        super().__init__(path, file_resources, col_rename=col_rename, **kwargs)

    def load_dataframe(self, file_resources, blocksize=None):
        """
        Args:
            file_resources:
            blocksize:
        """
        df = pd.read_csv(self.file_resources["data_v2017.txt"], header=None, sep="\t", encoding="unicode_escape")
        df.columns = ["LncRNA name", "Disease name", "Dysfunction type", "Description", "Chr",
                      "Start", "End", "Strand", "Species", "Alias", "Sequence", "Reference"]
        df = df[df["Species"] == self.species]
        df["Disease name"] = df["Disease name"].str.lower()
        return df
