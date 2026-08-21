"""Depth raster interpolation from depth-band polygons.

The main entry point is :func:`interpolate_depth_raster`.  It is split into
four focused helpers that can also be called independently:

* :func:`_rasterize_polygon_ids`     – burn polygon IDs into a raster grid
* :func:`_build_boundary_masks`      – detect shallow / deep edges per polygon
* :func:`_fill_polygon_depths`       – per-polygon distance-transform interpolation
* :func:`_smooth_polygon_boundaries` – Gaussian blend at polygon boundaries

When a :class:`~geopandas.GeoDataFrame` of measured depth points is supplied,
polygons with a wide depth range are refined using point-based interpolation
(see :func:`_fill_polygon_from_points`).
"""

import geopandas as gpd
import numpy as np
import rasterio as rio
import rasterio.features
import shapely
from scipy.ndimage import (
    binary_dilation,
    binary_erosion,
    distance_transform_edt,
    gaussian_filter,
)


def _shift_pid(pid: np.ndarray, height: int, width: int, di: int, dj: int) -> np.ndarray:
    """Return *pid* shifted by (*di*, *dj*), filling vacated edges with -1."""
    out = np.full_like(pid, -1)
    if di > 0:
        out[di:, :]          = pid[:height - di, :]
    elif di < 0:
        out[:height + di, :] = pid[-di:, :]
    elif dj > 0:
        out[:, dj:]          = pid[:, :width - dj]
    elif dj < 0:
        out[:, :width + dj]  = pid[:, -dj:]
    return out


def _rasterize_polygon_ids(
    gdf: gpd.GeoDataFrame,
    out_shape: tuple[int, int],
    transform: rio.transform.Affine,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Burn polygon indices into a raster grid.

    Returns
    -------
    pid : np.ndarray, shape out_shape, dtype int32
        Polygon index at each pixel; -1 where no polygon covers the cell.
    min_vals, max_vals : np.ndarray, shape (n_polygons,), dtype float32
        ``minimumsdybde`` and ``maksimumsdybde`` for each polygon.
    """
    min_vals = gdf["minimumsdybde"].to_numpy(dtype=np.float32)
    max_vals = gdf["maksimumsdybde"].to_numpy(dtype=np.float32)

    pid = rasterio.features.rasterize(
        ((geom, i) for i, geom in enumerate(gdf.geometry)),
        out_shape=out_shape,
        transform=transform,
        fill=-1,
        dtype=np.int32,
    )
    return pid, min_vals, max_vals


def _build_boundary_masks(
    pid: np.ndarray,
    valid: np.ndarray,
    min_vals: np.ndarray,
    max_vals: np.ndarray,
    out_shape: tuple[int, int],
    height: int,
    width: int,
    depth_atol: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Identify shallow-edge and deep-edge pixels for every polygon.

    A pixel is on the **shallow edge** of its polygon when an immediate
    4-connected neighbour belongs to a polygon whose ``maksimumsdybde``
    matches this polygon's ``minimumsdybde`` (within *depth_atol*).
    The **deep edge** is defined symmetrically.

    Returns
    -------
    shallow_bound, deep_bound : bool ndarray, shape out_shape
    outer_edge : bool ndarray
        Valid pixels on the outer boundary of the polygon mask (coast / no-data
        edge), used as a fallback reference when a matched edge is absent.
    """
    pid_safe = np.where(valid, pid, 0)
    min_r = np.where(valid, min_vals[pid_safe], np.nan).astype(np.float32)
    max_r = np.where(valid, max_vals[pid_safe], np.nan).astype(np.float32)

    shallow_bound = np.zeros(out_shape, dtype=bool)
    deep_bound    = np.zeros(out_shape, dtype=bool)

    with np.errstate(invalid="ignore"):
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nbr      = _shift_pid(pid, height, width, di, dj)
            nbr_v    = nbr >= 0
            nbr_safe = np.where(nbr_v, nbr, 0)
            diff     = valid & nbr_v & (nbr != pid)

            shallow_bound |= diff & (
                np.abs(np.where(nbr_v, max_vals[nbr_safe], np.nan) - min_r) <= depth_atol
            )
            deep_bound |= diff & (
                np.abs(np.where(nbr_v, min_vals[nbr_safe], np.nan) - max_r) <= depth_atol
            )
            del nbr, nbr_v, nbr_safe, diff

    outer_edge = valid & ~binary_erosion(valid, border_value=0)
    return shallow_bound, deep_bound, outer_edge


def _fill_polygon_depths(
    gdf: gpd.GeoDataFrame,
    pid: np.ndarray,
    shallow_bound: np.ndarray,
    deep_bound: np.ndarray,
    outer_edge: np.ndarray,
    min_vals: np.ndarray,
    max_vals: np.ndarray,
    out_shape: tuple[int, int],
    bounds: tuple[float, float, float, float],
    res: int,
    dtype,
    gdf_points: gpd.GeoDataFrame | None = None,
    min_points: int = 5,
) -> np.ndarray:
    """Fill each polygon's pixels using a distance-transform interpolation.

    For polygon *i* the interpolated depth at pixel *p* is::

        depth(p) = min_d + (max_d - min_d) * d_to_shallow / (d_to_shallow + d_to_deep)

    where distances are measured from the shallow / deep reference edges.
    Polygons whose reference edge cannot be found fall back to ``outer_edge``
    (degrades to constant midpoint when both edges are absent).

    When *gdf_points* is provided, polygons with a wide depth range (>150 m)
    and whose minimum depth is shallow (< 15 m) are
    filled using point-based RBF interpolation instead, falling back to the
    distance-transform for cells that the RBF cannot cover.

    Returns
    -------
    depth_out : float ndarray, shape out_shape
        NaN where no polygon covers the cell.
    """
    minx, _miny, _maxx, maxy = bounds
    height, width = out_shape
    depth_out = np.full(out_shape, np.nan, dtype=dtype)

    point_tree = None
    if gdf_points is not None and len(gdf_points) > 0:
        point_tree = _build_point_spatial_index(gdf_points)

    n_point_refined = 0

    for i, geom in enumerate(gdf.geometry):
        min_d = float(min_vals[i])
        max_d = float(max_vals[i])

        bx0, by0, bx1, by1 = geom.bounds
        r0 = max(int(np.floor((maxy - by1) / res)) - 1, 0)
        r1 = min(int(np.ceil( (maxy - by0) / res)) + 1, height)
        c0 = max(int(np.floor((bx0 - minx) / res)) - 1, 0)
        c1 = min(int(np.ceil( (bx1 - minx) / res)) + 1, width)

        m = pid[r0:r1, c0:c1] == i
        if not m.any():
            continue

        # Try point-based interpolation for wide-range polygons
        if (
            point_tree is not None
            and _needs_point_refinement(geom.area, min_d, max_d)
        ):
            pt_vals = _fill_polygon_from_points(
                geom, gdf_points, point_tree,
                min_d, max_d, m, r0, c0, bounds, res, dtype,
                min_points=min_points,
            )
            if pt_vals is not None:
                depth_out[r0:r1, c0:c1][m] = pt_vals
                n_point_refined += 1
                continue

        sb_b = shallow_bound[r0:r1, c0:c1] & m
        db_b = deep_bound   [r0:r1, c0:c1] & m

        if not sb_b.any() or not db_b.any():
            oe = outer_edge[r0:r1, c0:c1] & m
            if not oe.any():
                oe = m & ~binary_erosion(m, border_value=0)
            if not sb_b.any():
                sb_b = oe
            if not db_b.any():
                db_b = oe

        d_s   = distance_transform_edt(~sb_b).astype(np.float32)
        d_d   = distance_transform_edt(~db_b).astype(np.float32)
        sum_d = d_s + d_d
        with np.errstate(invalid="ignore", divide="ignore"):
            t = np.where(sum_d > 0, d_s / sum_d, np.float32(0.5))

        depth_out[r0:r1, c0:c1][m] = min_d + (max_d - min_d) * t[m]

    if n_point_refined:
        print(f"  Point-refined {n_point_refined} wide-range polygons.")

    return depth_out


def _needs_point_refinement(
    area: float,
    min_d: float,
    max_d: float,
) -> bool:
    """Return True if a polygon would benefit from point-based depth.
    
    Typical polygons going from 0.5m to 200m"""
    return (max_d - min_d) >= 150 and min_d < 1


def _build_point_spatial_index(gdf_points: gpd.GeoDataFrame) -> shapely.STRtree:
    """Build STRtree from point geometries for fast spatial queries."""
    return shapely.STRtree(gdf_points.geometry.values)


def _fill_polygon_from_points(
    geom,
    gdf_points: gpd.GeoDataFrame,
    point_tree: shapely.STRtree,
    min_d: float,
    max_d: float,
    mask: np.ndarray,
    r0: int,
    c0: int,
    bounds: tuple[float, float, float, float],
    res: int,
    dtype,
    min_points: int = 5,
) -> np.ndarray | None:
    """Interpolate depth within a polygon using measured point data.

    Uses scipy RBFInterpolator with a thin-plate-spline kernel, clipped
    to the polygon's min/max depth range.  Returns None if fewer than
    *min_points* fall inside the polygon.
    """
    from scipy.interpolate import RBFInterpolator

    hit_idx = point_tree.query(geom, predicate="intersects")
    if len(hit_idx) < min_points:
        return None

    pts = gdf_points.iloc[hit_idx]
    coords = np.column_stack([pts.geometry.x, pts.geometry.y])
    depths = pts["dybde"].to_numpy(dtype=np.float64)

    rows, cols = np.nonzero(mask)
    minx, _miny, _maxx, maxy = bounds
    px = minx + (c0 + cols + 0.5) * res
    py = maxy - (r0 + rows + 0.5) * res
    grid_coords = np.column_stack([px, py])

    rbf = RBFInterpolator(coords, depths, kernel="thin_plate_spline", smoothing=1.0)
    interp = rbf(grid_coords).astype(dtype)
    interp = np.clip(interp, min_d, max_d)
    return interp


def _smooth_polygon_boundaries(
    depth_out: np.ndarray,
    pid: np.ndarray,
    out_shape: tuple[int, int],
    sigma: float = 1.5,
) -> np.ndarray:
    """Gaussian-blend depth in a narrow band around polygon boundaries.

    Per-polygon interpolation is independent, so depth can jump discontinuously
    where adjacent polygons use different fallback references or have different
    gradient rates.  Blending a ±1-pixel band around every polygon edge removes
    those steps without altering interior pixel values.

    Parameters
    ----------
    sigma :
        Standard deviation (in pixels) of the Gaussian kernel (default 1.5,
        i.e. ~75 m at the standard 50 m resolution).
    """
    height, width = out_shape
    valid_out = np.isfinite(depth_out)

    is_boundary = np.zeros(out_shape, dtype=bool)
    for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nbr_p = _shift_pid(pid, height, width, di, dj)
        is_boundary |= valid_out & ((nbr_p < 0) | ((nbr_p >= 0) & (nbr_p != pid)))

    depth_g  = gaussian_filter(np.where(valid_out, depth_out, 0.0).astype(np.float64), sigma=sigma)
    weight_g = gaussian_filter(valid_out.astype(np.float64), sigma=sigma)
    with np.errstate(invalid="ignore", divide="ignore"):
        depth_smooth = np.where(weight_g > 0, depth_g / weight_g, np.nan).astype(depth_out.dtype)

    smooth_band = binary_dilation(is_boundary, iterations=1)
    return np.where(smooth_band & valid_out, depth_smooth, depth_out)


def interpolate_depth_raster(
    gdf: gpd.GeoDataFrame,
    bounds: tuple[float, float, float, float],
    res: int = 50,
    dtype=np.float32,
    depth_atol: float = 0.01,
    gdf_points: gpd.GeoDataFrame | None = None,
    min_points: int = 5,
) -> np.ndarray:
    """Interpolate depth between matching polygon boundaries.

    For each polygon two reference edges are identified in the raster:

    * **Shallow edge** – pixels adjacent to a neighbour whose
      ``maksimumsdybde`` equals this polygon's ``minimumsdybde``
      (the contour shared with the shallower neighbour, at depth = min).
    * **Deep edge** – pixels adjacent to a neighbour whose
      ``minimumsdybde`` equals this polygon's ``maksimumsdybde``
      (the contour shared with the deeper neighbour, at depth = max).

    Each raster cell is then assigned::

        depth = min_d + (max_d - min_d) * d_to_shallow / (d_to_shallow + d_to_deep)

    The gradient direction follows the depth ordering from land outward,
    not polygon shape.  Polygons with no matching depth-neighbour on one
    or both sides fall back to the polygon's outer boundary as the
    missing reference edge (degrading to the flat midpoint average when
    both sides are absent).

    A narrow Gaussian blend is applied at polygon boundaries to eliminate
    sharp depth-step artefacts that would otherwise inflate the slope feature.

    Parameters
    ----------
    depth_atol :
        Absolute tolerance for matching neighbour depth values (default 0.01 m).
    gdf_points :
        Optional GeoDataFrame of measured depth points (columns: ``dybde``,
        ``geometry``).  When provided, wide-range polygons are refined using
        point-based RBF interpolation.
    min_points :
        Minimum number of measured points inside a polygon required to use
        the RBF interpolator (default 5).
    """
    minx, miny, maxx, maxy = bounds
    width  = int(round((maxx - minx) / res))
    height = int(round((maxy - miny) / res))
    transform = rio.transform.from_origin(minx, maxy, res, res)
    out_shape = (height, width)

    gdf = gdf.reset_index(drop=True)

    pid, min_vals, max_vals = _rasterize_polygon_ids(gdf, out_shape, transform)

    valid = pid >= 0
    shallow_bound, deep_bound, outer_edge = _build_boundary_masks(
        pid, valid, min_vals, max_vals, out_shape, height, width, depth_atol
    )

    depth_out = _fill_polygon_depths(
        gdf, pid, shallow_bound, deep_bound, outer_edge,
        min_vals, max_vals, out_shape, bounds, res, dtype,
        gdf_points=gdf_points,
        min_points=min_points,
    )

    return _smooth_polygon_boundaries(depth_out, pid, out_shape)
