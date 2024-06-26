from __future__ import print_function, division, absolute_import

import json
import logging
import os
import sys
from os.path import join

import astropy
import dask.dataframe as dd
import pandas as pd

"""Top-level package for openomics."""

__author__ = """Nhat (Jonny) Tran"""
__email__ = 'nhat.tran@mavs.uta.edu'
__version__ = '0.8.9'


# Initialize configurations
this = sys.modules[__name__]
this.config = {}

# Set pandas backend
this.config["backend"] = pd

# Set cache download directory
this.config["cache_dir"] = astropy.config.get_cache_dir(this.__name__)
logging.info("Cache directory is", this.config["cache_dir"])

home_dir = os.path.expanduser('~')
user_conf_path = join(home_dir, ".openomics/conf.json")

# Initialize user configuration file at ~/.openomics/conf.json
if not os.path.exists(user_conf_path):
    if not os.path.exists(join(home_dir, ".openomics")):
        os.makedirs(join(home_dir, ".openomics"))

    if not os.path.isfile(user_conf_path):
        base_conf = {}
        base_conf['cache_dir'] = astropy.config.get_cache_dir(this.__name__)

        with open(user_conf_path, 'w', encoding='utf-8') as file:
            json.dump(base_conf, fp=file, indent=4)

# Read configuration from ~/.openomics/conf.json
if os.path.isfile(user_conf_path):
    try:
        with open(user_conf_path, 'r', encoding='utf-8') as file:
            user_conf = json.load(fp=file)

        if user_conf:
            for p in user_conf.get('database', []):
                this.config.update(p)

    except Exception as e:
        logging.info("Could not import configurations from", user_conf_path)

# Import submodules

from .transcriptomics import *
from .genomics import *
from .proteomics import *
from .clinical import *
from .multiomics import *


def set_backend(new: str = "pandas"):
    """Set the dataframe processing backend to either Pandas or Dask.

    Args:
        new (str): Either "dask" or "pandas". Default "pandas.
    """
    assert new in ["dask", "pandas", "modin"]

    if new == "dask":
        this.config["backend"] = dd
    else:
        this.config["backend"] = pd


def set_cache_dir(path: str, delete_temp: bool = False):
    """Set the path where external databases downloaded from URL are saved.

    Args:
        path (str):
        delete_temp (bool):
    """
    if not os.path.exists(path):
        raise NotADirectoryError(path)

    this.config["cache_dir"] = path
    astropy.config.set_temp_cache(path=path, delete=delete_temp)
    logging.info("Cache directory is", this.config["cache_dir"])
