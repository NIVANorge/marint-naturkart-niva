import numpy as np
import geopandas as gpd
import pytest
from shapely.geometry import Polygon, Point
from rasterio.transform import from_origin

from subkart.features import (
    marine_type_map,
    one_hot_encode_marine_types,
    rasterize_marine_types,
    marine_vanntyper_preprocess,
    depth_preprocess,
    to_raster_shapes,
    stack,
    VANNTYPER_COMBINED,
    SEA_MAP_NAMES,
)


def test_marine_type_map():
    types, id_type_map, type_id_map = marine_type_map()
    
    assert len(types) == len(VANNTYPER_COMBINED)
    assert len(id_type_map) == len(type_id_map)
    
    # Check bidirectional mapping
    for type_name, type_id in type_id_map.items():
        assert id_type_map[type_id] == type_name


def test_one_hot_encode_marine_types():
    # Create simple test raster with 3 classes
    raster = np.array([[0, 1, 2], [1, 2, -1], [0, 0, 1]], dtype=np.int8)
    
    result = one_hot_encode_marine_types(raster)
    
    assert result.dtype == np.uint8
    assert result.shape == (3, 3, len(VANNTYPER_COMBINED))
    
    # Check encoding correctness
    assert result[0, 0, 0] == 1  # First class
    assert result[0, 1, 1] == 1  # Second class
    assert result[0, 2, 2] == 1  # Third class
    
    # Check nodata is excluded
    assert result[1, 2, :].sum() == 0


def test_one_hot_encode_marine_types_all_nodata():
    raster = np.full((5, 5), -1, dtype=np.int8)
    result = one_hot_encode_marine_types(raster)
    
    assert result.sum() == 0


def test_rasterize_marine_types():
    # Create simple test GeoDataFrame
    polygons = [
        Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
        Polygon([(10, 10), (20, 10), (20, 20), (10, 20)]),
    ]
    
    gdf = gpd.GeoDataFrame(
        {"type_key": ["beskyttet", "moderat_eksponert"]},
        geometry=polygons,
        crs="EPSG:25833",
    )
    
    transform = from_origin(0, 20, 1, 1)
    out_shape = (20, 20)
    
    result = rasterize_marine_types(gdf, out_shape, transform)
    
    assert result.dtype == np.int8
    assert result.shape == out_shape
    assert (result >= -1).all()


def test_marine_vanntyper_preprocess():
    gdf = gpd.GeoDataFrame(
        {"Type": ["01", "02", "04", "06"]},
        geometry=[Point(0, 0)] * 4,
        crs="EPSG:25833",
    )
    
    result = marine_vanntyper_preprocess(gdf)
    
    assert "type_key" in result.columns
    assert result["type_key"][0] == "beskyttet"
    assert result["type_key"][1] == "beskyttet"
    assert result["type_key"][2] == "moderat_eksponert"
    assert result["type_key"][3] == "bølgeeksponert"


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
    # Create simple test arrays
    array1 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    array2 = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)
    arrays = [array1, array2]
    
    # Create one-hot types
    one_hot = np.zeros((2, 2, 3), dtype=np.uint8)
    one_hot[0, 0, 0] = 1
    one_hot[0, 1, 1] = 1
    one_hot[1, 0, 2] = 1
    one_hot[1, 1, 0] = 1
    
    features, valid_mask = stack(arrays, one_hot)
    
    assert features.shape[0] == 4  # All valid
    assert features.shape[1] == 5  # 2 arrays + 3 one-hot
    assert features.dtype == np.float32
    assert valid_mask.shape == (2, 2)


def test_stack_with_nan():
    # Create arrays with NaN
    array1 = np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32)
    array2 = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)
    arrays = [array1, array2]
    
    one_hot = np.zeros((2, 2, 2), dtype=np.uint8)
    one_hot[0, 0, 0] = 1
    one_hot[0, 1, 1] = 1
    one_hot[1, 0, 0] = 1
    one_hot[1, 1, 1] = 1
    
    features, valid_mask = stack(arrays, one_hot)
    
    # Should exclude the NaN cell
    assert features.shape[0] == 3
    assert valid_mask.sum() == 3
    assert not valid_mask[0, 1]


def test_stack_with_custom_mask():
    array1 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    arrays = [array1]
    
    one_hot = np.zeros((2, 2, 2), dtype=np.uint8)
    one_hot[:, :, 0] = 1
    
    # Custom mask excludes bottom-right cell
    custom_mask = np.array([[True, True], [True, False]], dtype=bool)
    
    features, valid_mask = stack(arrays, one_hot, valid_mask=custom_mask)
    
    assert features.shape[0] == 3
    assert not valid_mask[1, 1]


def test_stack_empty_result():
    array1 = np.full((2, 2), np.nan, dtype=np.float32)
    arrays = [array1]
    
    one_hot = np.zeros((2, 2, 2), dtype=np.uint8)
    
    features, valid_mask = stack(arrays, one_hot)
    
    assert features.shape[0] == 0
    assert valid_mask.sum() == 0
