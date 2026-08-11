# PDBClean base dir

import logging
import glob
import os
import sys


# list all the files included in CIFcurator
__all__ = [os.path.basename(f)[:-3] for f in glob.glob(os.path.dirname(__file__) + "/*.py") if not f.endswith('__init__.py')]

# set up the logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

sh = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(fmt='%(asctime)s - %(message)s', datefmt="%H:%M:%S")
sh.setFormatter(formatter)

logger.addHandler(sh)
logger.propagate = False
