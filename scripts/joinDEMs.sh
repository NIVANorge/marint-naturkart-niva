#!/bin/bash
# -----------------------------------------------------------------------------
# Script for Merging DEM Data from Geonorge 50m Grid
#
# Digital Elevation Model (DEM) data files
# downloaded from the Geonorge Kartkatalog, specifically from the 50 meters
# grid dataset available at:
# https://kartkatalog.geonorge.no/metadata/dybdedata-terrengmodeller-50-meters-grid/67a3a191-49cc-45bc-baf0-eaaf7c513549
#
# The script automates the process of combining multiple DEM tiles into a
# single, seamless raster file.
#
# Usage:
#   - Place all downloaded DEM files in a specified directory.
#   - Run this script, specifying the input directory and desired output file.
#
# Requirements:
#   - GDAL
#
# -----------------------------------------------------------------------------
set -e

if [ $# -ne 1 ]; then
    echo "Usage: $0 <input_dir>"
    exit 1
fi

INPUT_DIR="$1"
cd "$INPUT_DIR"
mkdir unzipped
for f in *.zip; do unzip "$f" -d unzipped; done
gdalbuildvrt mosaic.dem dvrt unzipped/*.tif
gdal_translate mosaic.vrt dem50_norge.tif  -of COG  -co COMPRESS=LZW  -co BIGTIFF=YES