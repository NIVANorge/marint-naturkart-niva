import json
from pathlib import Path

import numpy as np
from scipy.stats import randint, uniform
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
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
    class_weights: dict = None,
    region_labels=None,
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

    Uses spatial Leave-One-Region-Out cross-validation when ``region_labels`` are
    provided, otherwise falls back to stratified K-fold.

    Parameters
    ----------
    class_weights : dict, optional
        Per-class weights {class_label: weight}. Passed as sample_weight to XGBoost
        so that misclassifications of rare/important classes are penalized more.
    region_labels : array-like of shape (n_train_samples,), optional
        Region code per training sample (e.g. ``N``, ``S``, ``M``, ``H``, ``G``, ``B``
        from the marine vanntyper ``Region`` column).  When provided, spatial
        Leave-One-Region-Out CV is used instead of stratified K-fold, giving a more
        realistic estimate of generalisation to new geographic areas.
        Obtain with ``subkart.training.assign_region_labels``.
    cv_folds : int
        Number of folds for stratified K-fold.  Ignored when ``region_labels`` is given.
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

    # Define search space with stronger regularization
    if base_params is not None:
        param_distributions = _create_param_search_around_base(base_params, search_width)
    else:
        param_distributions = {
            "n_estimators": randint(100, 1000),
            "max_depth": randint(3, 12),  # Reduced max depth to prevent overfitting
            "learning_rate": uniform(0.01, 0.3),
            "subsample": uniform(0.6, 0.4),  # 0.6 to 1.0 (higher minimum)
            "colsample_bytree": uniform(0.6, 0.4),  # 0.6 to 1.0 (higher minimum)
            "min_child_weight": randint(1, 10),
            "gamma": uniform(0, 0.5),
            "reg_alpha": uniform(0, 2.0),  # Increased L1 regularization
            "reg_lambda": uniform(1.0, 3.0),  # Increased L2 regularization (1.0 to 4.0)
        }
        print("No existing parameters found. Using wide search space.")

    # Create base XGBoost classifier with early stopping parameters
    xgb_base = XGBClassifier(
        num_class=len(classes),
        random_state=random_state,
        n_jobs=n_jobs if n_jobs != -1 else 2,
        tree_method="hist",
        eval_metric="mlogloss",
        early_stopping_rounds=50,  # Stop if no improvement for 50 rounds
    )

    # Build per-sample weights from class_weights (if provided)
    sample_weight_train = None
    if class_weights is not None:
        sample_weight_train = np.array([class_weights[int(c)] for c in y_train])

    # Choose CV strategy: spatial LORO when region labels are available
    if region_labels is not None:
        region_labels = np.asarray(region_labels)
        # Build folds manually so "unknown" samples are included in every training
        # fold but are never used as a test fold.
        known_mask = region_labels != "unknown"
        n_unknown = (~known_mask).sum()
        known_regions = np.unique(region_labels[known_mask])
        if n_unknown > 0:
            print(f"  {n_unknown} samples with unknown region included in all training folds, excluded from test folds.")
        cv_strategy = _loro_with_unknown_splits(region_labels, known_regions)
        cv_description = f"spatial Leave-One-Region-Out ({len(known_regions)} regions: {known_regions.tolist()})"
        unique, counts = np.unique(region_labels, return_counts=True)
        print(f"Samples per region: { {r: int(c) for r, c in zip(unique, counts)} }")
    else:
        cv_strategy = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
        cv_description = f"{cv_folds}-fold stratified K-fold"

    print(f"\nStarting randomized search with {n_iter} iterations, {cv_description}...")
    random_search_cv = RandomizedSearchCV(
        xgb_base,
        param_distributions=param_distributions,
        n_iter=n_iter,
        cv=cv_strategy,
        verbose=verbose,
        random_state=random_state,
        n_jobs=n_jobs,
        scoring="accuracy",
        return_train_score=True,  # Track train scores to detect overfitting
    )

    # Fit with validation set for early stopping
    fit_kwargs = {
        "eval_set": [(X_val, y_val)],
        "verbose": False,
    }
    if sample_weight_train is not None:
        fit_kwargs["sample_weight"] = sample_weight_train

    random_search_cv.fit(X_train, y_train, **fit_kwargs)
    
    # Get best model (already fitted during CV)
    best_classifier = random_search_cv.best_estimator_

    # Evaluate on train and validation sets
    train_score = best_classifier.score(X_train, y_train)
    val_score = best_classifier.score(X_val, y_val)

    # Calculate overfitting gap
    cv_train_score = random_search_cv.cv_results_['mean_train_score'][random_search_cv.best_index_]
    overfitting_gap = train_score - val_score

    print(f"\n{'='*60}")
    print(f"Optimization complete!")
    print(f"{'='*60}")
    print(f"Best CV score: {random_search_cv.best_score_:.4f}")
    print(f"CV train score: {cv_train_score:.4f}")
    print(f"Train accuracy: {train_score:.4f}")
    print(f"Validation accuracy: {val_score:.4f}")
    print(f"Overfitting gap (train - val): {overfitting_gap:.4f}")
    if overfitting_gap > 0.1:
        print("⚠️  Warning: Large overfitting gap detected. Consider more regularization.")
    print(f"\nBest parameters:")
    for param, value in random_search_cv.best_params_.items():
        print(f"  {param}: {value}")

    # Prepare results dictionary
    search_results = {
        "best_score": float(random_search_cv.best_score_),
        "cv_train_score": float(cv_train_score),
        "train_score": float(train_score),
        "val_score": float(val_score),
        "overfitting_gap": float(overfitting_gap),
        "best_params": random_search_cv.best_params_,
        "cv_results": random_search_cv.cv_results_,
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
    # Use stronger regularization by default to prevent overfitting
    if "min_child_weight" not in base_params:
        param_distributions["min_child_weight"] = randint(1, 10)
    else:
        center = base_params["min_child_weight"]
        low = max(1, int(center * (1 - search_width)))
        high = int(center * (1 + search_width))
        param_distributions["min_child_weight"] = randint(low, high + 1)
    
    if "gamma" not in base_params:
        param_distributions["gamma"] = uniform(0, 0.5)
    else:
        center = base_params["gamma"]
        width = center * search_width if center > 0 else 0.1
        low = max(0, center - width)
        param_distributions["gamma"] = uniform(low, 2 * width)
    
    if "reg_alpha" not in base_params:
        param_distributions["reg_alpha"] = uniform(0, 2.0)  # Increased default
    else:
        center = base_params["reg_alpha"]
        width = center * search_width if center > 0 else 0.5
        low = max(0, center - width)
        param_distributions["reg_alpha"] = uniform(low, 2 * width)
    
    if "reg_lambda" not in base_params:
        param_distributions["reg_lambda"] = uniform(1.0, 3.0)  # Increased default (1.0 to 4.0)
    else:
        center = base_params["reg_lambda"]
        width = center * search_width if center > 0 else 0.5
        low = max(0, center - width)
        param_distributions["reg_lambda"] = uniform(low, 2 * width)
    
    return param_distributions


def _loro_with_unknown_splits(region_labels, known_regions):
    """
    Generate (train_idx, test_idx) pairs for Leave-One-Region-Out CV.

    Samples labelled ``"unknown"`` are included in every training fold but
    are never placed in a test fold, so the final model still trains on them.
    """
    idx = np.arange(len(region_labels))
    splits = []
    for region in known_regions:
        test_idx = idx[region_labels == region]
        # train = everything except the held-out region (unknowns stay in train)
        train_idx = idx[region_labels != region]
        splits.append((train_idx, test_idx))
    return splits


def assign_region_labels(coords_xy, crs: str = "EPSG:25833"):
    """
    Assign each sample coordinate to a marine vanntyper ``Region`` (N/S/M/H/G/B).

    Performs a spatial join between sample points and the dissolved marine vanntyper
    polygons, using the ``Region`` column directly.

    Parameters
    ----------
    coords_xy : array-like of shape (n_samples, 2)
        (x, y) coordinates of each sample in ``crs``.
    crs : str
        Coordinate reference system of ``coords_xy``.  Defaults to EPSG:25833.

    Returns
    -------
    region_labels : np.ndarray of shape (n_samples,)
        Region code (one of ``N``, ``S``, ``M``, ``H``, ``G``, ``B``) for each
        sample, or ``"unknown"`` if the point falls outside all regions.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    mv = subkart.sources.marine_vanntyper().to_crs(crs)
    mv_dissolved = mv[["Region", "geometry"]].dissolve(by="Region").reset_index()

    points = gpd.GeoDataFrame(
        geometry=[Point(x, y) for x, y in coords_xy],
        crs=crs,
    )
    joined = points.sjoin(mv_dissolved, how="left", predicate="within")
    # sjoin can produce duplicates if a point falls in overlapping polygons — keep first
    labels = joined.groupby(level=0)["Region"].first().reindex(range(len(points))).fillna("unknown").to_numpy()
    return labels
