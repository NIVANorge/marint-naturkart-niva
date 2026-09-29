# Materials and methods — Substrate (bunntype) model

## Study area and analysis grid

The classifier covers the Norwegian coastal zone from the coastline
out to one nautical mile beyond the *grunnlinje* (territorial
baseline). All input layers are reprojected to ETRS89 / UTM zone 33N
(EPSG:25833) and rasterised onto a common 50 m grid, matching the
native resolution of the national marine DEM.

## Data sources

| Purpose                     | Dataset                                              | Provider          | Reference |
|-----------------------------|------------------------------------------------------|-------------------|-----------|
| Depth (raster)              | Dybdedata – terrengmodeller, 50 m grid (DEM50)       | Kartverket        | [Geonorge](https://kartkatalog.geonorge.no/metadata/dybdedata-terrengmodeller-50-meters-grid/67a3a191-49cc-45bc-baf0-eaaf7c513549) |
| Depth bands, intertidal flats and soundings | Sjøkart – dybdedata, layers *Dybdeareal*, *Tørrfall* and *Dybdepunkt* | Kartverket | [Geonorge](https://kartkatalog.geonorge.no/metadata/sjoekart-dybdedata/2751aacf-5472-4850-a208-3532a51c529a) |
| Seabed sediment (labels)    | Bunnsedimenter – kornstørrelse (detaljert)           | NGU               | [Geonorge](https://kartkatalog.geonorge.no/metadata/bunnsedimenter-kornstoerrelse-detaljert/79f0f17d-9f62-456d-b1a9-2a8c754c51c4) |
| Sediment class crosswalk    | *Kornstørrelse – NiN-LM* mapping table               | NGU / MAREANO     | [static.ngu.no](https://static.ngu.no/Mareano/Kornstorrelse-NiN-LM.html) |
| Marine water types (regions)| Ny typologi 2022                                     | Miljødirektoratet | [dataleveranser.miljodirektoratet.no](https://dataleveranser.miljodirektoratet.no/nedlasting/b0fa9d93-dd2d-48fd-a89f-8fa224555c4d/) |
| Wave exposure               | Bølgeeksponeringsmodell (EswmRaster)                 | NIVA              | Isæus (2004); Isæus & Rygg (2005); Bekkby et al. (2025) |

## Target classes

Substrate is aggregated into three classes following the NGU/MAREANO
SOSI ↔ LM-DK crosswalk:

| Code | Class   | LM-DK             |
|------|---------|-------------------|
| 0    | soft    | DK_AB, DK_C, DK_D |
| 1    | mixture | DK_0              |
| 2    | hard    | DK_EFGY           |

Each NGU sediment polygon is assigned to a class by joining its SOSI
grain-size code to its LM-DK group via the crosswalk and mapping LM-DK
to the three-class scheme. The three classes are treated as
independent categories throughout training and evaluation. Detailed
grain-size correspondences are given in Appendix A.

## Predictor features

Each 50 m cell carries nine features:

* **Terrain (DEM-based).** `dem_depth`, `is_dem`, `dem_slope`,
  `dem_curvature`. `dem_depth` is gap-filled from a polygon-based
  depth surface where the DEM is missing; `is_dem` flags whether the
  DEM supplied the value.
* **Depth-polygon shape.** `sea_avg_depth`, `sea_avg_slope`,
  `sea_compactness` (`4π · area / perimeter²`) and `sea_convexity`
  (`area / convex-hull area`).
* **Physical exposure.** `wave_exposure`, resampled to the 50 m grid.

The polygon-based depth surface used both as `sea_avg_depth` and to
fill the DEM combines the *Dybdeareal* depth bands, *Tørrfall*
intertidal flats (assigned depth 0–0.5 m) and measured *Dybdepunkt*
soundings. Construction details are given in Appendix B.

## Model

The production model is an XGBoost gradient-boosted tree classifier,
selected after a preliminary comparison with random forests and
histogram gradient boosting. Class imbalance is handled with balanced
per-sample weights.

To avoid optimistic scores caused by spatial autocorrelation between
neighbouring cells, hyperparameters are tuned by randomised search
under **spatial Leave-One-Region-Out (LORO) cross-validation** using
the Miljødirektoratet marine water-type regions (N, S, M, H, G, B):
each region is held out in turn as the CV test fold. Samples outside
all regions are used only in training. A held-out 20 % of samples,
class-stratified, is reserved for final validation.

Held-out validation performance is reported in the Results section.
Training set construction, hyperparameter search space and software
details are given in Appendix C.

---

## Appendix A — SOSI grain-size correspondences

Representative SOSI grain-size names for each LM-DK group used in the
labelling, taken from the
[NGU/MAREANO SOSI ↔ LM-DK crosswalk](https://static.ngu.no/Mareano/Kornstorrelse-NiN-LM.html):

| Seabed class       | LM-DK    | Representative SOSI grain-size names                                                                                        |
|--------------------|----------|-----------------------------------------------------------------------------------------------------------------------------|
| soft               | DK_AB    | Leir, Slam, Silt, Sandholdig slam, Slamholdig sand, Grusholdig slam, …                                                       |
| soft               | DK_C     | Sand, Fin sand, Grov sand, Slamholdig sand, Siltholdig sand, Leirholdig sand, Grusholdig sand, …                             |
| soft               | DK_D     | Grus, Sandholdig grus, Slamholdig grus, Grus og stein, "Grus, stein og blokk"                                                |
| mixture            | DK_0     | Sand, grus og stein; Sand og blokk; Slam/sand med stein/blokk; Stein/blokk med sand-/slamdekke; Biogent materiale (korall)   |
| hard               | DK_EFGY  | Stein og blokk; Bart fjell; Tynt/usammenhengende sedimentdekke over berggrunn; Harde sedimenter eller sedimentære bergarter  |

## Appendix B — Depth surface construction and DEM gap-filling

Depth is the dominant predictor and combines the DEM50 raster, which
is dense offshore but has extensive coastal gaps, with the sjøkart
depth-band polygons.

The *Dybdeareal* polygons carry a minimum and maximum charted depth
(`minimumsdybde`, `maksimumsdybde`). *Tørrfall* intertidal-flat
polygons are treated as an additional depth band with range 0–0.5 m
so that they contribute the shallowest edge of the bathymetry.

A continuous depth surface is derived from the polygons as follows:

1. For each polygon, a *shallow* and a *deep* reference edge are
   detected as the pixels adjacent to a neighbouring polygon whose
   maximum (respectively minimum) charted depth matches this
   polygon's minimum (maximum) charted depth. These are the shared
   iso-depth contours with the neighbouring bands.
2. Depth is interpolated linearly between the two edges using the
   Euclidean distance transform, so that a cell at fractional distance
   `t` from the shallow edge receives `min_d + (max_d − min_d) · t`.
3. Polygons without a matching neighbour on one or both sides fall
   back to their own outer boundary; if both are absent the polygon
   degrades to its midpoint depth.
4. Wide-range polygons (charted range ≥ 150 m with a minimum depth
   essentially at the shore) are refined by fitting a thin-plate-spline
   RBF interpolator to the *Dybdepunkt* soundings that fall inside the
   polygon when at least five soundings are available, clipped to the
   charted range.
5. A narrow Gaussian blend (σ ≈ 75 m) is applied in a one-pixel band
   around every polygon boundary to remove step discontinuities that
   would otherwise inflate the derived slope feature.

DEM50 and this surface are then fused: `dem_depth` uses the DEM where
present and the interpolated depth where the DEM is missing; `is_dem`
records which source supplied the value; `dem_slope` uses the DEM
slope, falling back to the slope of the interpolated raster and then
to the polygon-average slope; `dem_curvature` uses the DEM curvature
with a flat default (0) elsewhere. The final training and prediction
mask keeps only cells with a substrate label and finite values in all
nine features.

## Appendix C — Training set, hyperparameter search and software

Training samples are individual valid 50 m cells with the nine-feature
vector and the rasterised substrate class. Class weights are computed
as `n_samples / (n_classes · n_c)` (balanced) to compensate for the
under-representation of *fastbunn* and are passed as per-sample
weights.

Every sample is tagged with the Miljødirektoratet marine water-type
*Region* by a spatial join with the dissolved *Ny typologi 2022*
polygons; samples outside all regions are tagged `unknown` and are
used only for training. The dataset is split 80 / 20 into a training
set and a held-out validation set (class-stratified, fixed random
seed).

XGBoost is used with the histogram tree method, multi-class log-loss
objective and early stopping on the held-out validation set.
Hyperparameters are tuned by randomised search over the number of
trees, tree depth, learning rate, row and column subsampling, minimum
child weight, gamma and L1/L2 regularisation. When a previous best
parameter set is stored, the search is narrowed to a ±30 % window
around it; otherwise the wide default ranges are used. Cross-validation
inside the search uses spatial Leave-One-Region-Out; the routine falls
back to stratified K-fold when region information is unavailable. The
best estimator is refitted on the full training set.

Processing uses Python with `geopandas`, `rasterio`, `xdem`,
`geoutils`, `scipy`, `numpy`, `scikit-learn` and `xgboost`. Random
seeds are fixed in the train/validation split, the balanced-class
weight computation and the hyperparameter search.
