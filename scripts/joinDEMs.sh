#!/bin/bash
set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 <input_dir>"
    exit 1
fi

INPUT_DIR="$1"
cd "$INPUT_DIR"
mkdir unzipped
for f in *.zip; do unzip "$f" -d unzipped; done
gdalbuildvrt mosaic.vrt unzipped/*.tif
gdal_translate mosaic.vrt dem50_norge.tif  -of COG  -co COMPRESS=LZW  -co BIGTIFF=YES