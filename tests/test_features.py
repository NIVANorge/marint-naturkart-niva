import numpy as np
import geopandas as gpd
import pytest
from shapely.geometry import Polygon, Point
from rasterio.transform import from_origin

from subkart.features import (
    depth_preprocess,
    interpolate_depth_raster,
    to_raster_shapes,
    stack,
    SEA_MAP_NAMES,
)


def test_interpolate_depth_raster_range():
    """Interpolated values must fall within [min, max] depth for each polygon."""
    polygons = [Polygon([(0, 0), (500, 0), (500, 500), (0, 500)])]
    gdf = gpd.GeoDataFrame(
        {"minimumsdybde": [5.0], "maksimumsdybde": [25.0]},
        geometry=polygons,
        crs="EPSG:25833",
    )
    bounds = (0, 0, 500, 500)
    result = interpolate_depth_raster(gdf, bounds, res=50)

    valid = result[np.isfinite(result)]
    assert valid.size > 0
    assert float(valid.min()) >= 5.0 - 1e-4
    assert float(valid.max()) <= 25.0 + 1e-4


def test_interpolate_depth_raster_gradient():
    """Depth should increase from shallow neighbour boundary to deep neighbour boundary."""
    # Two side-by-side polygons matching at depth=10:
    #   left:  min=0,  max=10
    #   right: min=10, max=20
    poly_left  = Polygon([(0, 0), (250, 0), (250, 500), (0, 500)])
    poly_right = Polygon([(250, 0), (500, 0), (500, 500), (250, 500)])
    gdf = gpd.GeoDataFrame(
        {"minimumsdybde": [0.0, 10.0], "maksimumsdybde": [10.0, 20.0]},
        geometry=[poly_left, poly_right],
        crs="EPSG:25833",
    )
    bounds = (0, 0, 500, 500)
    result = interpolate_depth_raster(gdf, bounds, res=50)

    mid_row = result.shape[0] // 2

    # Left polygon: depth increases left→right (0 at outer edge → 10 at shared boundary)
    left_cols = result[mid_row, :5]   # cols 0-4 are in the left polygon
    assert float(left_cols[0]) < float(left_cols[-1])

    # Right polygon: depth increases left→right (10 at shared boundary → 20 at outer edge)
    right_cols = result[mid_row, 5:]  # cols 5-9 are in the right polygon
    assert float(right_cols[0]) < float(right_cols[-1])

    # Boundary values: left polygon right edge ≈ max_left=10, right polygon left edge ≈ min_right=10
    assert abs(float(left_cols[-1])  - 10.0) < 2.0
    assert abs(float(right_cols[0])  - 10.0) < 2.0


def test_interpolate_depth_raster_direction_from_neighbour():
    """The gradient direction must follow the shallow→deep neighbour relationship,
    not simply edge distance, even when 'deep' is on the left."""
    # Right polygon is shallower, left polygon is deeper – gradient goes right→left.
    poly_right = Polygon([(250, 0), (500, 0), (500, 500), (250, 500)])
    poly_left  = Polygon([(0, 0), (250, 0), (250, 500), (0, 500)])
    gdf = gpd.GeoDataFrame(
        {"minimumsdybde": [10.0, 0.0], "maksimumsdybde": [20.0, 10.0]},
        geometry=[poly_left, poly_right],
        crs="EPSG:25833",
    )
    bounds = (0, 0, 500, 500)
    result = interpolate_depth_raster(gdf, bounds, res=50)

    mid_row = result.shape[0] // 2

    # Left (deeper) polygon: depth should be higher overall than right (shallower)
    left_mean  = float(np.nanmean(result[mid_row, :5]))
    right_mean = float(np.nanmean(result[mid_row, 5:]))
    assert left_mean > right_mean


def test_interpolate_depth_raster_uniform():
    """When min == max the raster should be constant over the polygon."""
    polygons = [Polygon([(0, 0), (500, 0), (500, 500), (0, 500)])]
    gdf = gpd.GeoDataFrame(
        {"minimumsdybde": [10.0], "maksimumsdybde": [10.0]},
        geometry=polygons,
        crs="EPSG:25833",
    )
    result = interpolate_depth_raster(gdf, (0, 0, 500, 500), res=50)
    valid = result[np.isfinite(result)]
    np.testing.assert_allclose(valid, 10.0, atol=1e-5)


def test_depth_preprocess():
    polygons = [Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])]
    
    gdf = gpd.GeoDataFrame(
        {
            "minimumsdybde": [10],
            "maksimumsdybde": [30],
        },
        geometry=polygons,
        crs="EPSG:25833",
    )
    
    result = depth_preprocess(gdf)
    
    assert all(name in result.columns for name in SEA_MAP_NAMES)
    assert result["sea_avg_depth"][0] == 20.0
    assert result["sea_area"][0] == 10000.0
    assert 0 <= result["sea_compactness"][0] <= 1
    assert 0 <= result["sea_convexity"][0] <= 1


def test_depth_preprocess_skip_if_present():
    polygons = [Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])]
    
    gdf = gpd.GeoDataFrame(
        {
            "minimumsdybde": [10],
            "maksimumsdybde": [30],
            "sea_avg_depth": [20],
            "sea_avg_slope": [5],
            "sea_compactness": [0.8],
            "sea_convexity": [0.9],
            "sea_area": [10000],
        },
        geometry=polygons,
        crs="EPSG:25833",
    )
    
    result = depth_preprocess(gdf, is_rerun=False)
    
    # Should return same data without modification
    assert result["sea_avg_depth"][0] == 20


def test_to_raster_shapes():
    polygons = [Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])]
    
    gdf = gpd.GeoDataFrame(geometry=polygons, crs="EPSG:25833")
    
    transform, out_shape, snapped_bounds = to_raster_shapes(gdf, res=10)
    
    assert len(out_shape) == 2
    assert isinstance(out_shape[0], int)
    assert isinstance(out_shape[1], int)
    assert len(snapped_bounds) == 4
    
    # Check bounds are snapped to resolution
    assert snapped_bounds[0] % 10 == 0
    assert snapped_bounds[1] % 10 == 0
    assert snapped_bounds[2] % 10 == 0
    assert snapped_bounds[3] % 10 == 0


def test_stack_basic():
    array1 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    array2 = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)
    arrays = [array1, array2]

    features, valid_mask = stack(arrays)

    assert features.shape[0] == 4  # All valid
    assert features.shape[1] == 2  # 2 arrays
    assert features.dtype == np.float32
    assert valid_mask.shape == (2, 2)


def test_stack_with_nan():
    array1 = np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32)
    array2 = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)
    arrays = [array1, array2]

    features, valid_mask = stack(arrays)

    # Should exclude the NaN cell
    assert features.shape[0] == 3
    assert valid_mask.sum() == 3
    assert not valid_mask[0, 1]


def test_stack_with_custom_mask():
    array1 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    arrays = [array1]

    # Custom mask excludes bottom-right cell
    custom_mask = np.array([[True, True], [True, False]], dtype=bool)

    features, valid_mask = stack(arrays, valid_mask=custom_mask)

    assert features.shape[0] == 3
    assert not valid_mask[1, 1]


def test_stack_empty_result():
    array1 = np.full((2, 2), np.nan, dtype=np.float32)
    arrays = [array1]

    features, valid_mask = stack(arrays)

    assert features.shape[0] == 0
    assert valid_mask.sum() == 0
