
import sys
from pathlib import Path

import gin
import numpy as np
import tensorflow as tf
from scipy.sparse import random

from data import DataLoader
from util import prune, save_weights, to_float32
from preprocessing import preprocess
from models.linear import LinearRecommenderFromFile
from models.tf import TFRecommender, SparseAutoEncoder


def test_wae_inits(tmp_path):
    """Test if a 1-layer WAE and a logistic regression model,
    initialized with the same weights, return the same predictions.
    """
    weights_path = str(tmp_path / "weights.npz")
    log_dir = str(tmp_path / "logs")
    np.random.seed(1988)

    w = np.random.randn(200, 200)
    np.fill_diagonal(w, 0.0)  # in-place
    b = np.random.randn(200)
    w_sp = prune(w, target_density=0.1)
    save_weights(weights_path, sparse_weights=w_sp, other={'biases': b})

    model_np = LinearRecommenderFromFile(log_dir, path=weights_path)
    model_tf = SparseAutoEncoder(n_items=200, weights_path=weights_path, loss='bce')

    x = random(300, 200, density=0.1)
    y_np, loss = model_np.predict(x)
    with tf.Session() as sess:
        init = tf.global_variables_initializer()
        sess.run(init)
        feed_dict = {model_tf.input_ph: to_float32(x, to_dense=True)}
        y_tf = sess.run(model_tf.logits, feed_dict=feed_dict)

    assert np.allclose(y_np, y_tf, rtol=1e-03)


def test_wae_experiment(tmp_path):
    """Test correspondence of evaluation metrics between a
    1-layer SparseAutoEncoder and a logistic regression model, initialized with the same weights

    TODO:
    - is this only passing because both get random performance?
    - find out why this fails when we evaluate on predict_proba instead of predict_logits
    """
    weights_path = str(tmp_path / "weights.npz")
    np.random.seed(1988)

    # weights
    w = np.eye(200, k=1)
    b = 0.5 * np.random.randn(200)
    w_sp = prune(w, target_density=0.1)
    save_weights(weights_path, sparse_weights=w_sp, other={'biases': b})

    # data
    x_train = random(300, 200, density=0.1)
    x_val = random(100, 200, density=0.1)
    y_val = x_val.copy() + random(100, 200, density=0.1)

    # config
    config_str = f"""
    preprocess.tfidf = True
    preprocess.norm = 'l2'

    TFRecommender.Model = @SparseAutoEncoder
    SparseAutoEncoder.weights_path = '{weights_path}'
    """
    gin.parse_config(config_str)

    # run
    x_train, y_train, x_val, y_val, _, _ = preprocess(x_train, x_train.copy(), x_val, y_val)
    tf_recommender = TFRecommender(log_dir=str(tmp_path / "logs_tf"), n_epochs=0)
    tf_metrics = tf_recommender.train(x_train, y_train, x_val, y_val)
    np_recommender = LinearRecommenderFromFile(log_dir=str(tmp_path / "logs_np"),
                                               path=weights_path)
    np_metrics = np_recommender.train(x_train, y_train, x_val, y_val)

    for k in ['ndcg', 'r50']:
        assert 0.0 < tf_metrics[k] < 1.0  # should be non-trivial
        assert np.allclose(tf_metrics[k], np_metrics[k])


def compare_skl_wae_real_weights(log_dir, data_path, weights_path, cap=None):
    """Test correspondence of evaluation metrics between a
    1-layer SparseAutoEncoder and a logistic regression model, initialized with the same weights
    """
    log_dir = Path(log_dir)

    # config
    config_str = f"""
    preprocess.tfidf = True
    preprocess.norm = 'l2'
    """
    gin.parse_config(config_str)

    print('Loading data...')
    loader = DataLoader(data_path)
    x_train = loader.load_data('train')
    x_val, y_val = loader.load_data('validation')

    print('Preprocessing...')
    x_train = x_train[:cap]
    x_val = x_val[:cap]
    y_val = y_val[:cap]

    print('Predicting...')
    x_train, y_train, x_val, y_val = preprocess(x_train, x_train.copy(), x_val, y_val)
    tf_recommender = TFRecommender(log_dir=str(log_dir / "logs_tf"),
                                   weights_path=weights_path, n_epochs=0)
    tf_metrics = tf_recommender.train(x_train, y_train, x_val, y_val)
    np_recommender = LinearRecommenderFromFile(log_dir=str(log_dir / "logs_skl"),
                                               path=weights_path)
    np_metrics = np_recommender.train(x_train, y_train, x_val, y_val)

    for k in ['ndcg', 'r100']:
        assert 0.0 < tf_metrics[k] < 1.0  # should be non-trivial
        assert np.allclose(tf_metrics[k], np_metrics[k])


if __name__ == '__main__':

    log_dir, data_path, weights_path = sys.argv[1:4]
    cap = int(sys.argv[4]) if len(sys.argv) > 4 else None
    compare_skl_wae_real_weights(log_dir, data_path, weights_path, cap=cap)
