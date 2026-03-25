import json
from pathlib import Path

import geopandas as gpd
import geoutils as gu
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio as rio
import xdem
from joblib import dump
from scipy.stats import randint, uniform
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, confusion_matrix
from sklearn.model_selection import RandomizedSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.utils.class_weight import compute_class_weight
from xgboost import XGBClassifier

import subkart


def random_search(X_train, y_train, X_val, y_val, classes, class_weights):
    search_spaces = [
        {
            "model": [RandomForestClassifier(n_jobs=2, class_weight=class_weights, random_state=42)],
            "model__n_estimators": [100, 300],
            "model__max_depth": [10, 20],
            "model__min_samples_leaf": [4, 10],
            "model__min_samples_split": [5, 10],
        },
        {
            "model": [HistGradientBoostingClassifier(random_state=42, class_weight=class_weights)],
            "model__learning_rate": [0.05, 0.1, 0.2],
            "model__max_depth": [None, 6, 12],
            "model__max_leaf_nodes": [31, 63, 127],
            "model__min_samples_leaf": [20, 50, 100],
            "model__l2_regularization": [0.0, 0.1, 1.0],
            "model__max_bins": [128, 255],
        },
        {
            "model": [
                XGBClassifier(
                    num_class=len(classes),
                    n_estimators=300,
                    max_depth=6,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    random_state=42,
                    n_jobs=2,
                    tree_method="hist",
                )
            ],
            "model__n_estimators": [200, 300, 500],
            "model__max_depth": [4, 6, 8],
            "model__learning_rate": [0.05, 0.1, 0.2],
            "model__subsample": [0.7, 0.8, 1.0],
            "model__colsample_bytree": [0.7, 0.8, 1.0],
        },
    ]
    pipe = Pipeline([("model", RandomForestClassifier())])
    random_search = RandomizedSearchCV(
        pipe, param_distributions=search_spaces, n_iter=80, cv=2, verbose=3, random_state=42
    )
    random_search.fit(X_train, y_train)

    # Use the best model for downstream cells
    classifier = random_search.best_estimator_.named_steps["model"]

    cv = random_search.cv_results_
    best_by_model = {}

    for i, p in enumerate(cv["params"]):
        model_name = type(p["model"]).__name__
        score = float(cv["mean_test_score"][i])
        if (model_name not in best_by_model) or (score > best_by_model[model_name]["score"]):
            readable = {}
            for k, v in p.items():
                if k == "model":
                    continue
                readable[k.split("__", 1)[1] if k.startswith("model__") else k] = v
            best_by_model[model_name] = {"score": score, "params": readable}

    # Print summary
    for name, info in best_by_model.items():
        print(f"{name}: mean_test_score={info['score']:.4f}, params={info['params']}")

    # Dump summary to JSON
    with open(subkart.utils.model_dir_path() / "cv_best_by_model.json", "w", encoding="utf-8") as f:
        json.dump(
            {name: {"score": info["score"], "params": info["params"]} for name, info in best_by_model.items()},
            f,
            indent=2,
        )

    classifier.fit(X_train, y_train)
    
    print("Train accuracy:", classifier.score(X_train, y_train))
    print("Validation accuracy:", classifier.score(X_val, y_val))

    return classifier


def optimize_xgboost_hyperparameters(
    X_train,
    y_train,
    X_val,
    y_val,
    classes,
    cv_results_path: Path = None,
    n_iter: int = 50,
    cv_folds: int = 3,
    search_width: float = 0.3,
    random_state: int = 42,
    n_jobs: int = -1,
    verbose: int = 2,
):
    """
    Find optimal hyperparameters for XGBoost classifier using randomized search.
    """
    
    # Load existing best parameters if available
    if cv_results_path is None:
        cv_results_path = subkart.utils.model_dir_path() / "cv_best_by_model.json"
    
    base_params = None
    if cv_results_path.exists():
        with open(cv_results_path, "r", encoding="utf-8") as f:
            cv_results = json.load(f)
            if "XGBClassifier" in cv_results:
                base_params = cv_results["XGBClassifier"]["params"]
                print(f"Starting search around existing parameters: {base_params}")
    
    # Define search space
    if base_params is not None:
        # Search around existing parameters
        param_distributions = _create_param_search_around_base(base_params, search_width)
    else:
        # Use default wide search space
        param_distributions = {
            "n_estimators": randint(100, 1000),
            "max_depth": randint(3, 15),
            "learning_rate": uniform(0.01, 0.3),
            "subsample": uniform(0.5, 0.5),  # 0.5 to 1.0
            "colsample_bytree": uniform(0.5, 0.5),  # 0.5 to 1.0
            "min_child_weight": randint(1, 10),
            "gamma": uniform(0, 0.5),
            "reg_alpha": uniform(0, 1.0),
            "reg_lambda": uniform(0, 2.0),
        }
        print("No existing parameters found. Using wide search space.")
    
    # Create base XGBoost classifier
    xgb_base = XGBClassifier(
        num_class=len(classes),
        random_state=random_state,
        n_jobs=n_jobs if n_jobs != -1 else 2,
        tree_method="hist",
        eval_metric="mlogloss",
    )
    
    # Perform randomized search
    print(f"\nStarting randomized search with {n_iter} iterations and {cv_folds}-fold CV...")
    random_search = RandomizedSearchCV(
        xgb_base,
        param_distributions=param_distributions,
        n_iter=n_iter,
        cv=cv_folds,
        verbose=verbose,
        random_state=random_state,
        n_jobs=n_jobs,
        scoring="accuracy",
    )
    
    random_search.fit(X_train, y_train)
    
    # Get best model
    best_classifier = random_search.best_estimator_
    
    # Train on full training set and evaluate
    best_classifier.fit(X_train, y_train)
    train_score = best_classifier.score(X_train, y_train)
    val_score = best_classifier.score(X_val, y_val)
    
    print(f"\n{'='*60}")
    print(f"Optimization complete!")
    print(f"{'='*60}")
    print(f"Best CV score: {random_search.best_score_:.4f}")
    print(f"Train accuracy: {train_score:.4f}")
    print(f"Validation accuracy: {val_score:.4f}")
    print(f"\nBest parameters:")
    for param, value in random_search.best_params_.items():
        print(f"  {param}: {value}")
    
    # Prepare results dictionary
    search_results = {
        "best_score": float(random_search.best_score_),
        "train_score": float(train_score),
        "val_score": float(val_score),
        "best_params": random_search.best_params_,
        "cv_results": random_search.cv_results_,
        "base_params": base_params,
    }
    # Dump summary to JSON (convert numpy arrays to lists)
    serializable_results = subkart.utils.to_serializable(search_results)
    with open(subkart.utils.model_dir_path() / "xgboost_results.json", "w", encoding="utf-8") as f:
        json.dump(serializable_results, f, indent=2)

    return best_classifier, search_results


def _create_param_search_around_base(base_params: dict, search_width: float = 0.3):
    """
    Create parameter distributions centered around base parameters.
    
    Parameters
    ----------
    base_params : dict
        Base parameters to search around
    search_width : float
        Fractional width of search (e.g., 0.3 for ±30%)
        
    Returns
    -------
    param_distributions : dict
        Dictionary of parameter distributions for RandomizedSearchCV
    """
    from scipy.stats import randint, uniform
    
    param_distributions = {}
    
    # Handle n_estimators
    if "n_estimators" in base_params:
        center = base_params["n_estimators"]
        low = max(50, int(center * (1 - search_width)))
        high = int(center * (1 + search_width))
        param_distributions["n_estimators"] = randint(low, high + 1)
    
    # Handle max_depth
    if "max_depth" in base_params:
        center = base_params["max_depth"]
        low = max(2, int(center * (1 - search_width)))
        high = int(center * (1 + search_width))
        param_distributions["max_depth"] = randint(low, high + 1)
    
    # Handle learning_rate
    if "learning_rate" in base_params:
        center = base_params["learning_rate"]
        width = center * search_width
        low = max(0.001, center - width)
        param_distributions["learning_rate"] = uniform(low, 2 * width)
    
    # Handle subsample
    if "subsample" in base_params:
        center = base_params["subsample"]
        width = min(center * search_width, center - 0.5, 1.0 - center)
        low = max(0.5, center - width)
        param_distributions["subsample"] = uniform(low, 2 * width)
    
    # Handle colsample_bytree
    if "colsample_bytree" in base_params:
        center = base_params["colsample_bytree"]
        width = min(center * search_width, center - 0.5, 1.0 - center)
        low = max(0.5, center - width)
        param_distributions["colsample_bytree"] = uniform(low, 2 * width)
    
    # Add additional parameters with default ranges if not in base_params
    if "min_child_weight" not in base_params:
        param_distributions["min_child_weight"] = randint(1, 10)
    
    if "gamma" not in base_params:
        param_distributions["gamma"] = uniform(0, 0.5)
    
    if "reg_alpha" not in base_params:
        param_distributions["reg_alpha"] = uniform(0, 1.0)
    
    if "reg_lambda" not in base_params:
        param_distributions["reg_lambda"] = uniform(0, 2.0)
    
    return param_distributions
