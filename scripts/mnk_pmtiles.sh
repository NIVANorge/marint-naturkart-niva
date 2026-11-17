#!/usr/bin/env bash
# Build marint-naturkart PMTiles that render well when zoomed out.
#
# Low zooms (0-LOW_MAX): only nin_kode_fkid is kept and adjacent polygons of the
#   same class are coalesced (effectively a dissolve), so the 1 km grid split and
#   millions of small polygons do not get dropped and leave holes.
# High zooms (LOW_MAX+1 - 14): all attributes, full detail.
# The two tile sets are joined into one PMTiles file.
set -euo pipefail

SRC=${1:-notebooks/marint-naturkart-ungridded_norge_2026_25833.gpkg}
OUT=${2:-${SRC%.gpkg}.pmtiles}
LOW_MAX=${LOW_MAX:-10}
LAYER=nin
TMP=$(mktemp -d -p "$(dirname "$OUT")")
trap 'rm -rf "$TMP"' EXIT

to_geojsonseq() {
  ogr2ogr -f GeoJSONSeq -t_srs EPSG:4326 /vsistdout/ "$SRC" "$@"
}

echo "Low zooms 0-$LOW_MAX (nin_kode_fkid, coalesced)"
to_geojsonseq -select nin_kode_fkid | tippecanoe -o "$TMP/low.pmtiles" \
  -l "$LAYER" -Z0 -z"$LOW_MAX" \
  --coalesce --coalesce-densest-as-needed --detect-shared-borders \
  --extend-zooms-if-still-dropping --force

echo "High zooms $((LOW_MAX + 1))-14 (all attributes)"
to_geojsonseq | tippecanoe -o "$TMP/high.pmtiles" \
  -l "$LAYER" -Z$((LOW_MAX + 1)) -z14 \
  --coalesce-densest-as-needed --detect-shared-borders \
  --extend-zooms-if-still-dropping --force

tile-join -o "$OUT" --force --no-tile-size-limit "$TMP/low.pmtiles" "$TMP/high.pmtiles"
echo "Wrote $OUT"
