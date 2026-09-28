# Materials and methods — Substrate (bunntype) model

## Study area, projection and analysis grid

The substrate classifier covers the marine areas along the Norwegian
coast. All input layers are reprojected to ETRS89 / UTM zone 33N
(EPSG:25833) and rasterised onto a common 50 m grid whose cell edges are
snapped to multiples of the pixel size. The 50 m resolution matches the
native cell size of the national marine digital elevation model used as
the primary depth predictor.

## Data sources

All primary data are open datasets. They are staged as GeoParquet /
Cloud-Optimized GeoTIFF on `gs://niva-geodata/MarintNaturKart/` and
loaded through the accessors in `mnk.sources`.

| Purpose                     | Dataset                                                                 | Provider                | Reference                                                                                                                                                          |
|-----------------------------|-------------------------------------------------------------------------|-------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Depth (raster)              | Dybdedata – terrengmodeller, 50 m grid (DEM50)                          | Kartverket / Geonorge   | https://kartkatalog.geonorge.no/metadata/dybdedata-terrengmodeller-50-meters-grid/67a3a191-49cc-45bc-baf0-eaaf7c513549                                              |
| Depth bands (polygons)      | Sjøkart – dybdedata, layer *Dybdeareal*                                 | Kartverket / Geonorge   | https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a                                                                    |
| Intertidal flats (polygons) | Sjøkart – dybdedata, layer *Tørrfall*                                   | Kartverket / Geonorge   | same dataset as above                                                                                                                                              |
| Measured depth soundings    | Sjøkart – dybdedata, layer *Dybdepunkt*                                 | Kartverket / Geonorge   | same dataset as above                                                                                                                                              |
| Seabed sediment (labels)    | Bunnsedimenter – kornstørrelse (detaljert)                              | NGU                     | https://kartkatalog.geonorge.no/metadata/bunnsedimenter-kornstoerrelse-detaljert/79f0f17d-9f62-456d-b1a9-2a8c754c51c4                                               |
| Sediment class crosswalk    | *Kornstørrelse – NiN-LM* mapping table                                  | NGU / MAREANO           | https://static.ngu.no/Mareano/Kornstorrelse-NiN-LM.html                                                                                                            |
| Marine water types (regions)| Ny typologi 2022 (marine vanntyper)                                     | Miljødirektoratet       | https://dataleveranser.miljodirektoratet.no/nedlasting/b0fa9d93-dd2d-48fd-a89f-8fa224555c4d/                                                                        |
| Wave exposure               | Bølgeeksponeringsmodell (EswmRaster)                                    | NIVA                    | Isæus (2004); Isæus & Rygg (2005); as documented in Bekkby et al. (2025) and used in Miljødirektoratet's kartlegging (Miljødirektoratet 2026)                        |

The DEM, sediment polygons, marine water types and wave-exposure raster
are national in coverage. The three Kartverket sjøkart layers
(*Dybdeareal*, *Tørrfall*, *Dybdepunkt*) are distributed per fylke and
merged across all 14 coastal fylker (see `mnk.sources.FYLKER`).

## Target classes and label preparation

The classification target is a three-class simplification of seabed
substrate:

| Code | Class name (Norwegian) | English  | LM-DK groups included |
|------|------------------------|----------|-----------------------|
| 0    | løsbunn                | soft     | DK_AB, DK_C, DK_D     |
| 1    | blanding               | mixed    | DK_0                  |
| 2    | fastbunn               | hard     | DK_EFGY               |

The NGU sediment polygons carry a detailed grain-size (SOSI) code. Each
polygon is assigned to one of the three classes by joining its SOSI
code to the LM-DK dominant grain-size group via the NGU crosswalk
table, and mapping LM-DK groups as above. Polygons are dissolved by
class and rasterised onto the 50 m grid; cells not covered by any
labelled polygon are excluded from training.

Class 1 (*blanding*) is treated as a physical mixture of classes 0 and
2 rather than a distinct substrate; the ordinal structure of the class
scheme is exploited in the evaluation (see Results).

## Predictor features

Each 50 m cell is described by nine features grouped in three families.

**Terrain from the DEM50:**

1. `dem_depth` — depth from the Kartverket DEM50, gap-filled where the
   DEM is missing (see next section).
2. `is_dem` — binary indicator (1 where the DEM had a real value, 0
   where the value was reconstructed from the sea-chart depth
   polygons). This lets the tree ensemble down-weight reconstructed
   cells.
3. `dem_slope` — terrain slope of the (filled) depth surface.
4. `dem_curvature` — terrain curvature (NaN replaced with 0 = flat).

**Shape and depth of the sea-chart depth polygon covering the cell:**

5. `sea_avg_depth` — polygon-based interpolated depth (see next
   section).
6. `sea_avg_slope` — polygon-average slope, derived from the polygon's
   minimum/maximum charted depth and its hydraulic mean width
   (`area / perimeter`).
7. `sea_compactness` — `4π · area / perimeter²` of the polygon.
8. `sea_convexity` — polygon area divided by the area of its convex
   hull.

Features 5–8 are computed from polygon geometry and are therefore
constant inside a given depth polygon.

**Physical exposure:**

9. `wave_exposure` — NIVA's Bølgeeksponeringsmodell (EswmRaster)
   reprojected to the 50 m grid with bilinear resampling.

## The depth feature and missing-data handling

Depth is the dominant predictor and is derived by combining two
complementary Kartverket products:

* the **DEM50** raster, which is dense offshore but has extensive gaps
  in the shallow coastal zone; and
* the **sjøkart depth bands**, i.e. the *Dybdeareal* polygons
  (`minimumsdybde`, `maksimumsdybde` per polygon) supplemented with the
  *Tørrfall* (intertidal-flat) polygons, which are assigned a depth
  range of 0–0.5 m so that they contribute the shallowest edge of the
  bathymetry and are treated as ordinary depth bands in all downstream
  steps.

To convert the depth-band polygons into a continuous depth raster
without introducing polygon-edge step artefacts, an **interpolated
depth surface** is constructed at 50 m as follows.

1. Two reference edges are detected in the raster for each polygon:
   the *shallow edge*, where a neighbouring polygon's maximum charted
   depth matches this polygon's minimum charted depth (i.e. the shared
   iso-depth contour with the shallower neighbour), and the *deep
   edge*, defined symmetrically with the deeper neighbour.
2. Depth is interpolated linearly between these two edges using the
   Euclidean distance transform, so that a cell at fractional distance
   `t` between the shallow and deep edges receives
   `min_d + (max_d − min_d) · t`. This preserves the polygon's charted
   depth range while producing a smooth in-polygon gradient aligned
   with the true iso-depth contours.
3. Polygons with no matching neighbour on one or both sides fall back
   to the polygon's own outer boundary as the missing reference edge;
   in the degenerate case where both are absent the polygon degrades
   to its midpoint depth.
4. *Wide-range* polygons — those whose charted depth range spans at
   least 150 m and whose minimum depth is essentially at the shore — are
   refined using the measured *Dybdepunkt* soundings that fall inside
   the polygon. Where at least five soundings are available, an RBF
   (thin-plate spline) interpolator is fitted to the soundings and
   evaluated on the polygon's cells, clipped to the polygon's charted
   depth range; otherwise the distance-transform value is kept.
5. Finally, a narrow Gaussian blend (σ ≈ 75 m) is applied in a
   one-pixel band around every polygon boundary to remove step
   discontinuities that would otherwise inflate the derived slope
   feature.

The DEM50 and the interpolated surface are then fused into the final
depth stack:

* `dem_depth` uses the DEM value where present, and the interpolated
  polygon-based depth where the DEM is missing;
* `is_dem` records which of the two sources supplied the value;
* `dem_slope` uses the slope of the DEM where possible; where the DEM
  is missing, it uses the slope of the interpolated depth raster, and
  falls back further to the polygon-average slope where the
  interpolated raster is also unavailable;
* `dem_curvature` uses the DEM curvature, with a flat-terrain default
  (0) elsewhere.

The final training/prediction mask keeps only cells that (i) carry a
substrate label and (ii) have finite values in all nine features.

## Training data

Training samples are the individual valid 50 m cells; each sample
consists of the nine-feature vector and its integer substrate class.
Because *fastbunn* is under-represented nationally, class weights are
computed with a balanced scheme (inversely proportional to class
frequency) and passed as per-sample weights to the classifier.

To support spatial cross-validation, every sample is tagged with the
Miljødirektoratet marine water-type *Region* (N, S, M, H, G, B) by a
spatial join between the sample coordinates and the dissolved
*Ny typologi 2022* polygons. Samples that fall outside all regions are
labelled `unknown` and are used only for training, never for testing
(see below). The full dataset is then split into a training set and a
held-out validation set (80 % / 20 %, class-stratified, fixed random
seed) keeping features, labels, coordinates and region tags aligned.

## Classifier and hyperparameter selection

The production model is a gradient-boosted decision-tree classifier
(XGBoost) with histogram tree method, multi-class log-loss objective
and early stopping on the held-out validation set. XGBoost was
selected after a wide preliminary randomised search that also
considered random forests and histogram gradient boosting.

Hyperparameters are tuned with a randomised search over the number of
trees, tree depth, learning rate, row and column subsampling,
minimum child weight, gamma, and L1/L2 regularisation. When a previous
best-parameter file exists, the search is narrowed to a ±30 % window
around it; otherwise the wide default ranges are used.

Cross-validation uses **spatial Leave-One-Region-Out (LORO)**: each of
the marine water-type regions is held out in turn as the CV test fold
while all other samples — including those with an `unknown` region tag
— remain in the training fold. This gives a realistic estimate of
generalisation to geographic areas not seen during training and avoids
optimistic scores caused by spatial autocorrelation between nearby
cells. Where region information is unavailable the routine falls back
to stratified K-fold cross-validation.

The best estimator is refitted on the full training set and its
train, validation, cross-validation and overfitting-gap scores are
recorded together with the selected hyperparameters. Held-out
validation performance is reported in the Results section.

## Software and reproducibility

Processing uses Python with `geopandas`, `rasterio`, `xdem`,
`geoutils`, `scipy`, `numpy`, `scikit-learn` and `xgboost`. Random
seeds are fixed in the train/validation split, the balanced-class
weight computation and the hyperparameter search. The feature stack,
label raster and trained classifier are the exact inputs consumed by
the prediction step that produces the national substrate map
distributed as `nisjedata-substrat-xgbclassifier_norge_latest_25833`.
