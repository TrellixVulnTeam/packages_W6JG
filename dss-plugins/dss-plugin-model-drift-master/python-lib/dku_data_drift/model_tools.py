# -*- coding: utf-8 -*-
import logging
import numpy as np
import math
import pandas as pd
from sklearn.neighbors import KernelDensity
from sklearn.metrics import roc_auc_score
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from dku_data_drift.preprocessing import Preprocessor
from dku_data_drift.model_drift_constants import ModelDriftConstants

logger = logging.getLogger(__name__)


def mroc_auc_score(y_true, y_predictions, sample_weight=None):
    """ Returns a auc score. Handles multi-class
    For multi-class, the AUC score is in fact the MAUC
    score described in
    David J. Hand and Robert J. Till. 2001.
    A Simple Generalisation of the Area Under the ROC Curve
    for Multiple Class Classification Problems.
    Mach. Learn. 45, 2 (October 2001), 171-186.
    DOI=10.1023/A:1010920819831
    http://dx.doi.org/10.1023/A:1010920819831
    """
    (nb_rows, max_nb_classes) = y_predictions.shape
    # Today, it may happen that if a class appears only once in a dataset
    # it can appear in the train and not in the validation set.
    # In this case it will not be in y_true and
    # y_predictions.nb_cols is not exactly the number of class
    # to consider when computing the mroc_auc_score.
    classes = np.unique(y_true)
    nb_classes = len(classes)
    if nb_classes > max_nb_classes:
        raise ValueError("Your test set contained more classes than the test set. Check your dataset or try a different split.")

    if nb_classes < 2:
        raise ValueError("Ended up with less than two-classes in the validation set.")

    if nb_classes == 2:
        classes = classes.tolist()
        y_true = y_true.map(lambda c: classes.index(c)) # ensure classes are [0 1]
        return roc_auc_score(y_true, y_predictions[:, 1], sample_weight=sample_weight)

    def A(i, j):
        """
        Returns a asymmetric proximity metric, written A(i | j)
        in the paper.
        The sum of all (i, j) with  i != j
        will give us the symmetry.
        """
        mask = np.in1d(y_true, np.array([i, j]))
        y_true_i = y_true[mask] == i
        y_pred_i = y_predictions[mask][:, i]
        if sample_weight is not None:
            sample_weight_i = sample_weight[mask]
        else:
            sample_weight_i = None
        return roc_auc_score(y_true_i, y_pred_i, sample_weight=sample_weight_i)

    C = 1.0 / (nb_classes * (nb_classes - 1))
    # TODO: double check
    return C * sum(
        A(i, j)
        for i in classes
        for j in classes
        if i != j)

def format_proba_density(data, sample_weight=None, min_support=0, max_support=100):
    """
    Estimate the density distribution of the target 1-dimensional data array.
    The support arguments (inf and sup) should be:
     - 0 and 1 for classification
     - min(data) and max(data) for regression

    Output format of the density
    >>> list(zip([1, 2, 3], [0.3, 0.3, 0.4]))

    :param data: Target data of the model
    :param sample_weight:
    :param min_support: Inferior boundary of the support for density estimation
    :param max_support: Superior boundary of the support for density estimation
    :return:
    """
    data = np.array(data)
    if len(data) == 0:
        return []
    # Heuristic for the bandwidth determination
    h = 1.06 * np.std(data) * math.pow(len(data), -.2)
    if h <= 0:
        h = 0.06
    if len(np.unique(data)) == 1:
        sample_weight = None
    # Definition of the support of the estimate
    X_plot = np.linspace(min_support, max_support, 500, dtype=float)[:, np.newaxis]
    kde = KernelDensity(kernel='gaussian', bandwidth=h).fit(data.reshape(-1, 1), sample_weight=sample_weight)
    Y_plot = [v if not np.isnan(v) else 0 for v in np.exp(kde.score_samples(X_plot))]
    return list(zip(X_plot.ravel(), Y_plot))

class SurrogateModel(object):
    """
    In case the chosen saved model uses a non-tree based algorithm (and thus does not have feature importance), we fit this surrogate model
    on top of the prediction of the former one to be able to retrieve the feature importance information.

    """

    def __init__(self, prediction_type):
        self.check(prediction_type)
        self.feature_names = None
        self.target = None
        self.prediction_type = prediction_type
        #TODO should we define some params of RF to avoid long computation ?
        if prediction_type == ModelDriftConstants.CLASSIFICATION_TYPE:
            self.clf = RandomForestClassifier(random_state=1407)
        else:
            self.clf = RandomForestRegressor(random_state=1407)

    def check(self, prediction_type):
        if prediction_type not in [ModelDriftConstants.CLASSIFICATION_TYPE, ModelDriftConstants.REGRRSSION_TYPE]:
            raise ValueError('Prediction type must either be CLASSIFICATION or REGRESSION.')

    def get_features(self):
        return self.feature_names

    def fit(self, df, target):
        preprocessor = Preprocessor(df, target)
        train, test = preprocessor.get_processed_train_test()
        train_X = train.drop(target, axis=1)
        train_Y = train[target]
        self.clf.fit(train_X, train_Y)
        self.feature_names = train_X.columns