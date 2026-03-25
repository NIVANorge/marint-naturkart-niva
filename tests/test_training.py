import json
import numpy as np
from pathlib import Path
from unittest.mock import patch
from sklearn.datasets import make_classification
from sklearn.base import is_classifier
from xgboost import XGBClassifier

from subkart.training import random_search, optimize_xgboost_hyperparameters 

@patch("subkart.utils.model_dir_path")
def test_random_search_runs_and_saves_output(mock_model_dir, tmp_path):
    mock_model_dir.return_value = tmp_path
    
    X, y = make_classification(
        n_samples=100, 
        n_features=5, 
        n_informative=2, 
        n_redundant=1,
        n_classes=3, 
        n_clusters_per_class=1,
        random_state=42
    )
    
    X_train, X_val = X[:70], X[70:]
    y_train, y_val = y[:70], y[70:]
    
    classes = np.unique(y_train)
    class_weights = "balanced"
    

    best_classifier = random_search(X_train, y_train, X_val, y_val, classes, class_weights)
    
    assert is_classifier(best_classifier), "Returned object is not a classifier"
    assert hasattr(best_classifier, "classes_"), "The classifier is not fitted"
    
    json_path = tmp_path / "cv_best_by_model.json"
    assert json_path.exists(), "The cv_best_by_model.json file was not created"
    
    with open(json_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    
    assert len(saved_data.keys()) > 0 
    for model_name in saved_data:
        assert "score" in saved_data[model_name]
        assert "params" in saved_data[model_name]


@patch("subkart.utils.model_dir_path")
def test_optimize_xgboost_hyperparameters_without_base_params(mock_model_dir, tmp_path):
    """Test optimization function when no base parameters exist"""
    mock_model_dir.return_value = tmp_path
    
    X, y = make_classification(
        n_samples=100,
        n_features=5,
        n_informative=3,
        n_redundant=0,
        n_classes=3,
        n_clusters_per_class=1,
        random_state=42
    )
    
    X_train, X_val = X[:70], X[70:]
    y_train, y_val = y[:70], y[70:]
    classes = np.unique(y_train)
    
    # Use a non-existent path so it starts with default search space
    non_existent_path = tmp_path / "nonexistent.json"
    
    classifier, results = optimize_xgboost_hyperparameters(
        X_train, y_train, X_val, y_val,
        classes=classes,
        cv_results_path=non_existent_path,
        n_iter=3,  # Small number for fast test
        cv_folds=2,
        verbose=0,
        n_jobs=1
    )
    
    # Check classifier
    assert isinstance(classifier, XGBClassifier), "Returned classifier is not XGBClassifier"
    assert is_classifier(classifier), "Returned object is not a classifier"
    assert hasattr(classifier, "classes_"), "The classifier is not fitted"
    
    # Check results dictionary
    assert "best_score" in results
    assert "train_score" in results
    assert "val_score" in results
    assert "best_params" in results
    assert "cv_results" in results
    assert "base_params" in results
    
    # Check that base_params is None (no base parameters were used)
    assert results["base_params"] is None
    
    # Check scores are reasonable
    assert 0 <= results["best_score"] <= 1
    assert 0 <= results["train_score"] <= 1
    assert 0 <= results["val_score"] <= 1
    
    # Check best_params has expected XGBoost parameters
    assert "n_estimators" in results["best_params"]
    assert "max_depth" in results["best_params"]
    assert "learning_rate" in results["best_params"]
    
    # Check that xgboost_results.json was written to tmp location
    xgboost_results_path = tmp_path / "xgboost_results.json"
    assert xgboost_results_path.exists(), "xgboost_results.json was not written to tmp location"


@patch("subkart.utils.model_dir_path")
def test_optimize_xgboost_hyperparameters_with_base_params(mock_model_dir, tmp_path):
    """Test optimization function when base parameters exist"""
    mock_model_dir.return_value = tmp_path
    
    # Create a cv_best_by_model.json with XGBoost parameters
    cv_results = {
        "XGBClassifier": {
            "score": 0.75,
            "params": {
                "n_estimators": 100,
                "max_depth": 6,
                "learning_rate": 0.1,
                "subsample": 0.8,
                "colsample_bytree": 0.8
            }
        }
    }
    
    cv_path = tmp_path / "cv_best_by_model.json"
    with open(cv_path, "w", encoding="utf-8") as f:
        json.dump(cv_results, f)
    
    # Create test data
    X, y = make_classification(
        n_samples=100,
        n_features=5,
        n_informative=3,
        n_redundant=0,
        n_classes=3,
        n_clusters_per_class=1,
        random_state=42
    )
    
    X_train, X_val = X[:70], X[70:]
    y_train, y_val = y[:70], y[70:]
    classes = np.unique(y_train)
    
    # Run optimization (should use default path via mock)
    classifier, results = optimize_xgboost_hyperparameters(
        X_train, y_train, X_val, y_val,
        classes=classes,
        n_iter=3,  # Small number for fast test
        cv_folds=2,
        search_width=0.3,
        verbose=0,
        n_jobs=1
    )
    
    # Check classifier
    assert isinstance(classifier, XGBClassifier), "Returned classifier is not XGBClassifier"
    assert is_classifier(classifier), "Returned object is not a classifier"
    assert hasattr(classifier, "classes_"), "The classifier is not fitted"
    
    # Check results dictionary
    assert "best_score" in results
    assert "train_score" in results
    assert "val_score" in results
    assert "best_params" in results
    assert "base_params" in results
    
    # Check that base_params were loaded from the JSON file
    assert results["base_params"] is not None
    assert results["base_params"]["n_estimators"] == 100
    assert results["base_params"]["max_depth"] == 6
    assert results["base_params"]["learning_rate"] == 0.1
    
    # Check scores are reasonable
    assert 0 <= results["best_score"] <= 1
    assert 0 <= results["train_score"] <= 1
    assert 0 <= results["val_score"] <= 1
    
    # Check that xgboost_results.json was written to tmp location
    xgboost_results_path = tmp_path / "xgboost_results.json"
    assert xgboost_results_path.exists(), "xgboost_results.json was not written to tmp location"


@patch("subkart.utils.model_dir_path")
def test_optimize_xgboost_hyperparameters_custom_search_width(mock_model_dir, tmp_path):
    """Test that custom search_width parameter is respected"""
    mock_model_dir.return_value = tmp_path
    
    X, y = make_classification(
        n_samples=100,
        n_features=5,
        n_informative=3,
        n_redundant=0,
        n_classes=3,
        n_clusters_per_class=1,
        random_state=42
    )
    
    X_train, X_val = X[:70], X[70:]
    y_train, y_val = y[:70], y[70:]
    classes = np.unique(y_train)
    
    # Run with wide search width
    classifier, results = optimize_xgboost_hyperparameters(
        X_train, y_train, X_val, y_val,
        classes=classes,
        cv_results_path=tmp_path / "nonexistent.json",
        n_iter=2,
        cv_folds=2,
        search_width=0.8,  # Large search width
        verbose=0,
        n_jobs=1
    )
    
    # Just verify it runs and returns valid results
    assert isinstance(classifier, XGBClassifier)
    assert "best_params" in results
    assert len(results["best_params"]) > 0