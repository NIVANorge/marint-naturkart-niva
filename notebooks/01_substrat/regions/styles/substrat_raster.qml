<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!--
  QGIS style for the substrate prediction raster (predict_unmapped / sieved prediction).
  Pixel classes: 0 = Løsbunn (soft), 1 = Blanding (mixture), 2 = Fastbunn (hard), 255 = nodata.
  Colors match nivacloud-terriamap prod niva.json (BunnType / LM_DK styling).
-->
<qgis version="3.34" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0" maxScale="0" minScale="1e+08">
  <pipe>
    <provider>
      <resampling enabled="false" maxOversampling="2" zoomedInResamplingMethod="nearestNeighbour" zoomedOutResamplingMethod="nearestNeighbour"/>
    </provider>
    <rasterrenderer type="paletted" band="1" opacity="1" alphaBand="-1" nodataColor="">
      <rasterTransparency>
        <singleValuePixelList>
          <pixelListEntry min="255" max="255" percentTransparent="100"/>
        </singleValuePixelList>
      </rasterTransparency>
      <minMaxOrigin>
        <limits>None</limits>
        <extent>WholeRaster</extent>
        <statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower>
        <cumulativeCutUpper>0.98</cumulativeCutUpper>
        <stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <colorPalette>
        <paletteEntry value="0" color="#ffb300" alpha="255" label="Løsbunn (soft)"/>
        <paletteEntry value="1" color="#803e75" alpha="255" label="Blanding (mixture)"/>
        <paletteEntry value="2" color="#3270ae" alpha="255" label="Fastbunn (hard)"/>
      </colorPalette>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" colorizeStrength="100" colorizeOn="0" grayscaleMode="0" colorizeBlue="128" colorizeGreen="128" colorizeRed="255"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
