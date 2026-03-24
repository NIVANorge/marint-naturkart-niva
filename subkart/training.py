import json

import geopandas as gpd
import geoutils as gu
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio as rio
import xdem
from joblib import dump
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