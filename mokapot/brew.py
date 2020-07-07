"""
Defines a function to run the Percolator algorithm.
"""
import logging
import copy
from concurrent.futures import ProcessPoolExecutor

import pandas as pd
import numpy as np

from .model import Model

LOGGER = logging.getLogger(__name__)


# Functions -------------------------------------------------------------------
def brew(psms,
         model=None,
         train_fdr=0.01,
         test_fdr=0.01,
         max_iter=10,
         direction=None,
         folds=3,
         max_workers=1):
    """
    Re-score one or more collection of PSMs.

    The provided PSMs analyzed using the semi-supervised learning
    algorithm that was introduced by
    `Percolator <http://percolator.ms>`_. Cross-validation is used to
    ensure that the learned models to not overfit to the PSMs used for
    model training. If a multiple collections of PSMs are provided, they
    are aggregated for model training, but the confidence estimates are
    calculated separately for each collection.

    Parameters
    ----------
    psms : PsmDataset object or list of PsmDataset objects
        One or more :doc:`collections of PSMs <dataset>` objects.
        PSMs are aggregated across all of the collections for model
        training, but the confidence estimates are calculated and
        returned separately.
    model : Model object, optional
        The :py:class:`mokapot.Model` object to be fit. The default is
        :code:`None`, which attempts to mimic the same support vector
        machine models used by Percolator.
    train_fdr : float, optional
        The maximum false discovery rate at which to consider a
        target PSM as a positive example during model training.
    test_fdr : float, optional
        The false-discovery rate threshold at which to evaluate
        the learned models.
    max_iter : int, optional
        The number of iterations to use for training.
    direction : str or None, optional
        The name of the feature to use as the initial direction for
        ranking PSMs. The default, :code`None`, automatically selects
        the feature that finds the most PSMs below the `train_fdr`. This
        will be ignored in the case the model is already trained.
    folds : int, optional
        The number of cross-validation folds to use. PSMs originating
        from the same mass spectrum are always in the same fold.
    max_workers : int, optional
        The number of processes to use for model training. More workers
        will require more memory, but will typically decrease the total
        run time. An integer exceeding the number of folds will have
        no additional effect.

    Returns
    -------
    Confidence object or list of Confidence objects
        An object or a list of objects containing the
        :doc:`confidence estimates <confidence>` at various levels
        (i.e. PSMs, peptides) when assessed using the learned score.
        If a list, they will be in the same order as provided in the
        `psms` parameter.
    """
    if model is None:
        model = Model()

    try:
        iter(psms)
    except TypeError:
        psms = [psms]

    LOGGER.info("Splitting PSMs into %i folds...", folds)
    test_idx = [p._split(folds) for p in psms]
    train_sets = _make_train_sets(psms, test_idx)

    # Create args for map:
    map_args = [_fit_model,
                train_sets,
                [copy.deepcopy(model) for _ in range(folds)],
                [train_fdr]*folds,
                [max_iter]*folds,
                [direction]*folds,
                range(folds)]

    # Train models in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as prc:
        if max_workers == 1:
            map_fun = map
        else:
            map_fun = prc.map

        models = map_fun(*map_args)

    scores = [_predict(p, i, models, test_fdr) for p, i in zip(psms, test_idx)]

    LOGGER.info("")
    res = [p.assign_confidence(s, desc=True) for p, s in zip(psms, scores)]
    if len(res) == 1:
        return res[0]

    return res


# Utility Functions -----------------------------------------------------------
def _make_train_sets(psms, test_idx):
    """
    Parameters
    ----------
    psms : list of PsmDataset
        The PsmDataset to get a subset of.
    test_idx : list of list of numpy.ndarray
        The indicies of the test sets

    Yields
    ------
    PsmDataset
        The training set.
    """
    train_set = copy.copy(psms[0])
    all_idx = [set(range(len(p.data))) for p in psms]
    for idx in zip(*test_idx):
        train_set._data = None
        data = []
        for i, j, dset in zip(idx, all_idx, psms):
            data.append(dset.data.iloc[list(j - set(i)), :])

        train_set._data = pd.concat(data, ignore_index=True)
        yield train_set


def _predict(dset, test_idx, models, test_fdr):
    """
    Return the new scores for the dataset

    Parameters
    ----------
    dset : PsmDataset
        The dataset to rescore
    test_idx : list of numpy.ndarray
        The indicies of the test sets
    models : list of Model
        The models for each datasset.
    test_fdr : the fdr to calibrate at.
    """
    test_set = copy.copy(dset)
    scores = []
    for fold, mod in zip(test_idx, models):
        test_set._data = dset.data.iloc[list(fold), :]
        s = test_set._calibrate_scores(mod.predict(test_set), test_fdr)
        scores.append(s)

    rev_idx = np.argsort(sum(test_idx, [])).tolist()
    return np.concatenate(scores)[rev_idx]


def _fit_model(train_set, model, train_fdr, max_iter, direction, fold):
    """
    Fit the estimator using the training data.

    Parameters
    ----------
    train_set : PsmDataset
        A PsmDataset that specifies the training data
    model : Model
        A Classifier to train.
    train_fdr : float
        The FDR threshold used to define positive examples during the
        Percolator algorithm.
    max_iter : int
        The maximum number of iterations to run the algorithm.
    """
    LOGGER.info("")
    LOGGER.info("=== Analyzing Fold %i ===", fold+1)
    model.fit(train_set, train_fdr=train_fdr, max_iter=max_iter,
              direction=direction)
    return model
