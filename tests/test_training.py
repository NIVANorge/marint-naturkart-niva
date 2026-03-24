import json
import numpy as np
from unittest.mock import patch
from sklearn.datasets import make_classification
from sklearn.base import is_classifier

from subkart.training import random_search 

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