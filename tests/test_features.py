import numpy as np
import geopandas as gpd
import pytest
from shapely.geometry import Polygon, Point
from rasterio.transform import from_origin

from subkart.features import (
    depth_preprocess,
    to_raster_shapes,
    stack,
    SEA_MAP_NAMES,
)


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
