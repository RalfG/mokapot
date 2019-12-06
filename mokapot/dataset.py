"""
This module contains the classes and methods needed to import, validate and
normalize a collection of PSMs in PIN (Percolator INput) format.
"""
import logging
import gzip
from typing import List, Union, Tuple

import numpy as np
import pandas as pd

from mokapot.qvalues import tdc

# Classes ---------------------------------------------------------------------
class PsmDataset():
    """
    Store a collection of PSMs.
    """
    def __init__(self, psm_data = pd.DataFrame) -> None:
        """Initialize a PsmDataset object."""

        self.data = psm_data
        self.data = self.data.sample(frac=1).reset_index(drop=True)
        cols = self.columns

        # Verify necessary columns are present.
        required_cols = {"label", "scannr", "peptide", "proteins"}
        if not required_cols <= set(cols):
            raise ValueError("Required columns are missing from the pin file."
                             f" These are {required_cols} and are case "
                             "insensitive.")

        # Change key cols to lowercase for consistency
        df_cols = self.data.columns.tolist()
        for col_name in required_cols:
            df_cols[cols.index(col_name)] = col_name

        self.data.columns = df_cols

    @property
    def columns(self) -> List[str]:
        """Get the columns of the PIN files in lower case."""
        return [c.lower() for c in self.data.columns.tolist()]

    @property
    def dual(self) -> bool:
        """Get the best dual setting for sklearn.svm.LinearSVC()"""
        dual = False
        if self.data.shape[0] <= self.data.shape[1]:
            dual = True
            logging.warning("The number of features is greater than the number"
                            " of PSMs.")

        return dual

    @property
    def features(self) -> pd.DataFrame:
        """Get the features of the PsmDataset"""
        cols = self.columns
        feat_end = cols.index("peptide")

        # Crux adds "ExpMass" and "CalcMass" columns after "ScanNr"
        if "calcmass" in self.columns:
            feat_start = cols.index("calcmass") + 1
        else:
            feat_start = cols.index("scannr") + 1

        return self.data.iloc[:, feat_start:feat_end]

    @property
    def label(self) -> np.ndarray:
        """Get the data PSM labels."""
        return self.data.label.values

    def find_best_feature(self, fdr: float) -> None:
        """Find the best feature to separate targets from decoys."""
        qvals = self.features.apply(tdc, target=(self.label+1)/2)
        targ_qvals = qvals[self.label == 1]
        num_passing = (targ_qvals <= fdr).sum()
        best_feat = num_passing.idxmax()
        unlabeled = np.logical_and(qvals[best_feat].values > fdr, self.label == 1)

        target = self.label.copy()
        target[unlabeled] = 0

        return best_feat, num_passing[best_feat], target

    def split(self, folds): #-> Tuple[Tuple[PsmDataset]]:
        """Split into cross-validation folds"""
        num = len(self.label) // folds

        # Split the data evenly
        splits = np.array_split(self.data, folds)

        if len(splits[-1]) < num:
            splits[-2] = pd.concat(splits[-2:])
            splits = splits[:-1]

        # Assign train and test sets
        train = []
        test = []
        for idx, test_split in enumerate(splits):
            train_split = pd.concat(splits[:idx] + splits[idx+1:])
            train.append(PsmDataset(train_split))
            test.append(PsmDataset(test_split))

        return (tuple(train), tuple(test))


# Functions -------------------------------------------------------------------
def read_pin(pin_files: Union[str, Tuple[str]]) -> PsmDataset:
    """Read a Percolator pin file to a PsmDataset"""
    if isinstance(pin_files, str):
        pin_files = (pin_files,)

    psm_data = pd.concat([_read_pin(f) for f in pin_files])
    return PsmDataset(psm_data)

def read_mpin(mpin_files: Union[str, Tuple[str]]) -> PsmDataset:
    """Read a Mokapot input (mpin) file to a PsmDataset"""
    pass

# Utility Functions -----------------------------------------------------------
def _read_pin(pin_file):
    """Parse a Percolator INput formatted file."""
    if pin_file.endswith(".gz"):
        fopen = gzip.open
    else:
        fopen = open

    with fopen(pin_file, "r") as pin:
        header = pin.readline()
        header = header.replace("\n", "").split("\t")
        rows = [l.replace("\n", "").split("\t", len(header)-1) for l in pin]

    pin_df = pd.DataFrame(columns=header, data=rows)
    return pin_df.apply(pd.to_numeric, errors="ignore")
