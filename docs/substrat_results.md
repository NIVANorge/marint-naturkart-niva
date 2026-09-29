# Results — Substrate (bunntype) model

## Training data composition

After rasterising the labels and stacking the nine features, valid
training samples span all six Miljødirektoratet marine water-type
regions:

| Region       | B          | G          | H         | M          | N         | S         | unknown |
|--------------|-----------:|-----------:|----------:|-----------:|----------:|----------:|--------:|
| N samples    | 1 187 842  | 1 804 812  | 683 635   | 1 405 867  | 418 167   | 265 407   | 8 268   |

The three-class distribution is imbalanced (mixture is rarest, soft
dominates); balanced class weights are used as per-sample weights
during training:

| Class   | Weight |
|---------|-------:|
| soft    | 0.553  |
| mixture | 2.170  |
| hard    | 1.365  |

## Hyperparameter selection

The XGBoost randomised search under spatial Leave-One-Region-Out
cross-validation selected the following hyperparameters:

| Parameter        | Value    |
|------------------|---------:|
| n_estimators     | 362      |
| max_depth        | 6        |
| learning_rate    | 0.176    |
| subsample        | 0.851    |
| colsample_bytree | 1.00     |
| min_child_weight | 3        |
| gamma            | 0.276    |
| reg_alpha        | 0.163    |
| reg_lambda       | 1.016    |

Search summary scores:

| Metric                        | Value  |
|-------------------------------|-------:|
| Best CV score (LORO)          | 0.5634 |
| CV train score                | 0.7786 |
| Train accuracy                | 0.7416 |
| Validation accuracy           | 0.7395 |
| Overfitting gap (train − val) | 0.0022 |

The gap between the LORO CV score (0.56) and the held-out validation
score (0.74) reflects genuine geographic transfer: within-region
predictions are stronger than predictions in entirely unseen regions.
The near-zero train/validation gap indicates that within a random
split the model does not overfit.

## Held-out validation performance

On the 20 % held-out validation set (n = 1 154 800 cells), overall
accuracy is **0.7395** (853 923 correct predictions).

Per-class report:

| Class        | Precision | Recall | F1     | Support   |
|--------------|----------:|-------:|-------:|----------:|
| soft         | 0.928     | 0.696  | 0.796  | 695 473   |
| mixture      | 0.509     | 0.807  | 0.625  | 177 406   |
| hard         | 0.644     | 0.803  | 0.715  | 281 921   |
| macro avg    | 0.694     | 0.769  | 0.712  | 1 154 800 |
| weighted avg | 0.794     | 0.739  | 0.750  | 1 154 800 |

Confusion matrix (rows = true, columns = predicted):

|         | soft    | mixture | hard    |
|---------|--------:|--------:|--------:|
| soft    | 484 279 | 103 640 | 107 554 |
| mixture |  16 502 | 143 196 |  17 708 |
| hard    |  21 151 |  34 322 | 226 448 |

![Confusion matrix (row-normalised) on the held-out validation set.](figures/confusion_matrix.png)

The model is highly precise for soft (0.93) but under-recalls it
(0.70), redistributing some true soft cells into the mixture class
and, more rarely, into hard. Hard recall is 0.80. Mixture has the
lowest precision (0.51) because it sits between the two dominant
classes and absorbs boundary cells.

## Feature importance

Permutation importance on the held-out validation set:

| Feature         | Mean importance | Std      |
|-----------------|----------------:|---------:|
| dem_depth       | 0.1249          | 0.00039  |
| dem_slope       | 0.0875          | 0.00035  |
| wave_exposure   | 0.0685          | 0.00027  |
| sea_avg_slope   | 0.0667          | 0.00024  |
| sea_compactness | 0.0520          | 0.00023  |
| sea_convexity   | 0.0485          | 0.00017  |
| dem_curvature   | 0.0474          | 0.00022  |
| sea_avg_depth   | 0.0335          | 0.00025  |
| is_dem          | 0.0040          | 0.00003  |

![Permutation feature importance on the held-out validation set.](figures/feature_importance.png)

Depth is the dominant predictor, followed by DEM slope and wave
exposure. The polygon-based shape descriptors (`sea_avg_slope`,
`sea_compactness`, `sea_convexity`) each contribute measurable
information. The `is_dem` indicator carries almost no importance,
indicating that the DEM-versus-polygon origin of the depth value does
not meaningfully change the model's decisions.

## Regional performance

Break-down of held-out validation accuracy by marine water-type
region:

| Region  | n samples | Accuracy |
|---------|----------:|---------:|
| B       | 237 623   | 0.807    |
| G       | 360 869   | 0.715    |
| H       | 136 658   | 0.711    |
| M       | 280 829   | 0.735    |
| N       |  83 763   | 0.692    |
| S       |  53 409   | 0.778    |
| unknown |   1 649   | 0.747    |

Region B has the highest accuracy (0.81) and Region N the lowest
(0.69). The Møre area (region M) sits close to the national mean at
0.74 but its errors are the most polarised (see external validation
below).

## External validation against monitoring stations

The predicted substrate map was compared against independent NIVA
Aquamonitor monitoring stations, retrieved as WFS layers from the
Terria map viewer. Each station was intersected with the predicted
substrate polygons and aggregated through the LM-DK groupings
(`DK_AB, DK_C, DK_D` → soft, `DK_0` → mixture, `DK_EFGY` → hard).
Stations falling outside all polygons are reported separately.

Because the monitoring stations only carry a binary field label
(soft-bottom or hard-bottom), a `mixture` prediction is neither a
clean hit nor a clean miss. It is reported as a partial match and
excluded from the exact-match rate; the opposite-class column
captures the true errors.

**Soft-bottom monitoring stations** — of 1 467 stations, 1 393 fell
inside a predicted polygon:

| Predicted class | n   | % of stations inside a polygon |
|-----------------|----:|-------------------------------:|
| soft (match)    | 930 | 66.8 %                         |
| mixture (partial) | 228 | 16.4 %                       |
| hard (opposite) | 235 | 16.9 %                         |

**Hard-bottom monitoring stations** — of 280 stations, 185 fell
inside a predicted polygon:

| Predicted class | n   | % of stations inside a polygon |
|-----------------|----:|-------------------------------:|
| hard (match)    | 143 | 77.3 %                         |
| mixture (partial) |  24 | 13.0 %                       |
| soft (opposite) |  18 |  9.7 %                         |

At the reference monitoring stations the model reproduces the field
class in ≈ 67 % of the soft sites and ≈ 77 % of the hard sites inside
a predicted polygon. The opposite-class error rate is ≈ 17 % at soft
sites and ≈ 10 % at hard sites; the remainder is classified as the
intermediate `mixture` class.

## Coastal-shelf area accounting

Substrate area distribution over the shallow coastal shelf
(depth ≥ −30 m from mean sea level), by økoregion, using the DEM50
depth mask and the predicted substrate polygons rasterised at 50 m.
Where NGU BunnsedimentKornstorDetalj observations overlap the shelf
they replace the model prediction, so the accounting is a hybrid of
in-situ observations (used as ground truth in training) and the
model output elsewhere. The three classes correspond to the LM-DK
groupings `DK_AB, DK_C, DK_D` → soft, `DK_0` → mixture,
`DK_EFGY` → hard:

| Region       | Total ≥ −30 m (km²) | soft (km²) | mixture (km²) | hard (km²) | soft % | mix % | hard % |
|--------------|--------------------:|-----------:|--------------:|-----------:|-------:|------:|-------:|
| Norskehavet  | 11 882.9            | 3 024.5    | 2 353.7       | 6 495.6    | 25.5   | 19.8  | 54.7   |
| Skagerrak    |  1 292.1            |   474.6    |   194.7       |   618.8    | 36.7   | 15.1  | 47.9   |
| Nordsjøen    |  1 927.8            |   362.1    |   225.4       | 1 336.3    | 18.8   | 11.7  | 69.3   |
| Barentshavet |  1 797.2            |   526.4    |   589.3       |   680.4    | 29.3   | 32.8  | 37.9   |
| Norge (sum)  | 16 900.1            | 4 387.6    | 3 363.1       | 9 131.1    | 26.0   | 19.9  | 54.0   |

Row percentages do not sum to exactly 100 because a small fraction
of the depth mask falls outside any predicted polygon.

At national level, roughly a quarter of the shallow (≥ −30 m) shelf
is soft, a fifth mixture, and just over half hard. Composition is
strongly region-dependent: Nordsjøen is hard-dominated (≈ 69 %),
Barentshavet has the largest mixture share (≈ 33 %) and a nearly
balanced soft/hard split, and Norskehavet is close to the national
mean.

## Summary

* Overall held-out pixel accuracy is 0.74. Per-class F1 is 0.80
  (soft), 0.62 (mixture) and 0.71 (hard). Mixture has the lowest
  precision because it absorbs boundary cells between the two
  dominant classes.
* Depth is the dominant feature, followed by DEM slope and wave
  exposure. Polygon shape descriptors add measurable information; the
  DEM-vs-polygon origin flag does not.
* Regional accuracy ranges from 0.69 (region N) to 0.81 (region B).
* Independent NIVA Aquamonitor stations reproduce the predicted class
  at 67 % (soft) and 77 % (hard) of stations inside a predicted
  polygon, with an opposite-class error rate of 17 % and 10 %
  respectively; the remainder is classified as the intermediate
  `mixture` class.
* At national level, the shallow (≥ −30 m) coastal shelf is estimated
  to comprise ≈ 4 390 km² soft, ≈ 3 360 km² mixture and ≈ 9 130 km²
  hard substrate, with strong regional contrast: Nordsjøen is
  hard-dominated, Barentshavet has the largest mixture share. Where
  NGU sediment observations overlap the shelf, they are used in place
  of the model prediction.
