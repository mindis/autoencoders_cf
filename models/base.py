import time
from collections import defaultdict

import gin
import numpy as np
from scipy.sparse import vstack

from metric import ndcg_binary_at_k_batch, recall_at_k_batch, count_finite, count_nonzero, mean_item_rank
from util import Logger, gen_batches, prune


class BaseRecommender(object):

    def __init__(self, log_dir, batch_size=100):
        """Generic recommender.
        
        Params:
        - log_dir (str): logging directory
        - batch_size (int): prediction batch size
        """
        self.logger = Logger(log_dir) if log_dir else None
        self.batch_size = batch_size

    def train(self, x_train, y_train, x_val, y_val):
        """Optionally train, return validation metrics"""
        return self.evaluate(x_val, y_val)

    def predict(self, x, y=None):
        """Predict scores.
        If y is not None, also return a loss.
        """
        raise NotImplementedError()

    def evaluate(self, x_val, y_val, other_metrics=None, test=False):
        """Evaluate model on observed and unobserved validation data x_val, y_val

        Use dict parameter `other_metrics` to add/replace metrics
        """
        prediction_time = 0
        batch_metrics = defaultdict(list)
        for x, y in gen_batches(x_val, y_val, batch_size=self.batch_size):
            t1 = time.perf_counter()
            y_pred, loss = self.predict(x, y)
            prediction_time += time.perf_counter() - t1
            batch_metrics['nnz'].extend(count_nonzero(y_pred))
            batch_metrics['fin'].extend(count_finite(y_pred))

            # exclude examples from training and validation (if any) and compute rank metrics
            y_pred[x.nonzero()] = np.min(y_pred)
            batch_metrics['ndcg'].extend(ndcg_binary_at_k_batch(y_pred, y, k=100))
            batch_metrics['r20'].extend(recall_at_k_batch(y_pred, y, k=50))
            batch_metrics['r50'].extend(recall_at_k_batch(y_pred, y, k=20))
            batch_metrics['mean_item_rank'].extend(mean_item_rank(y_pred, y_all=y_val, k=100))

        metrics = {k: np.mean(v) for k, v in batch_metrics.items()}
        metrics['prediction_time'] = prediction_time
        if other_metrics:
            metrics.update(other_metrics)
        if self.logger is not None:
            self.logger.log_config(gin.operative_config_str())
            self.logger.log_metrics(metrics, config=gin.operative_config_str(), test=test)

        return metrics


@gin.register
class PopularityRecommender(BaseRecommender):

    def __init__(self, log_dir, batch_size=100, nnz=100):
        """Popularity recommender.

        Params:
        - log_dir (str): logging directory
        - batch_size (int): prediction batch size
        - nnz (int): number of top items to keep
        """
        self.logger = Logger(log_dir) if log_dir else None
        self.batch_size = batch_size
        self.popularity = None
        self.nnz = nnz

    def train(self, x_train, y_train, x_val, y_val):
        """Optionally train, return validation metrics"""

        self.prior = np.array(x_train.sum(0))
        self.prior = prune(self.prior, row_nnz=self.nnz)

        return self.evaluate(x_val, y_val)

    def predict(self, x, y=None):
        """Predict scores.
        If y is not None, also return a loss.
        """
        y_pred = vstack([self.prior] * x.shape[0])

        return y_pred, None
