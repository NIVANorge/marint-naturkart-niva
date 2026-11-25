#!/usr/bin/env bash
set -euo pipefail

SRC=${1:?usage: parquet_to_gpkg.sh <in.geo.parquet> [out.gpkg] [layer]}
if [ "$#" -ge 2 ]; then
  OUT=$2
else
  OUT=${SRC%.parquet}
  OUT=${OUT%.geo}.gpkg
fi
LAYER=${3:-nin}

rm -f "$OUT"
ogr2ogr -f GPKG -nln "$LAYER" \
  --config OGR_SQLITE_SYNCHRONOUS OFF \
  --config OGR_SQLITE_JOURNAL MEMORY \
  -gt 65536 \
  "$OUT" "$SRC"
echo "Wrote $OUT"
