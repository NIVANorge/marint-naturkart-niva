<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!--
  QGIS style for the niche-model (nisjemodell) raster, paletted on the nin_int pixel value.
  Each nin_int value is colored by its NiN hovedtype (nin_kode_fkid) using the official
  k_hovedtype.hex colors from datamodell_silver_nin_flate_NK.xlsx. Several nin_int values
  share one NiN code (e.g. 1/5/6 = NA-MC04, 9/10 = NA-MC02) and therefore share its color;
  they differ only in the separate nkm_lys/nkm_salinitet/nkm_toerfall axes.

  Official hex (k_hovedtype): MA01 #B2B2B2, MA03 #666666, MA05 #ACF5D5, MA06 #5BA89E,
  MC01 #8C6BB1, MC02 #9E9AC8, MC04 #C7E9C0.
  Fallback (no official hex set in datamodel): MA02 #8C8C8C, MA04 #E5F5E0.
  255 = nodata.
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
        <paletteEntry value="1" color="#C7E9C0" alpha="255" label="NA-MC04 Brakkvanns-sedimentbunn (eufot. innenfor)"/>
        <paletteEntry value="2" color="#E5F5E0" alpha="255" label="NA-MA04 Fjærebelte-sedimentbunn"/>
        <paletteEntry value="3" color="#8C6BB1" alpha="255" label="NA-MC01 Fast brakkvanns-fjærebeltebunn"/>
        <paletteEntry value="4" color="#B2B2B2" alpha="255" label="NA-MA01 Fast saltvanns-fjærebeltebunn"/>
        <paletteEntry value="5" color="#C7E9C0" alpha="255" label="NA-MC04 Brakkvanns-sedimentbunn (eufot. utenfor)"/>
        <paletteEntry value="6" color="#C7E9C0" alpha="255" label="NA-MC04 Brakkvanns-sedimentbunn (afot. utenfor)"/>
        <paletteEntry value="7" color="#ACF5D5" alpha="255" label="NA-MA05 Eufotisk saltvanns-sedimentbunn"/>
        <paletteEntry value="8" color="#5BA89E" alpha="255" label="NA-MA06 Afotisk saltvanns-sedimentbunn"/>
        <paletteEntry value="9" color="#9E9AC8" alpha="255" label="NA-MC02 Fast brakkvannsbunn (eufot.)"/>
        <paletteEntry value="10" color="#9E9AC8" alpha="255" label="NA-MC02 Fast brakkvannsbunn (afot.)"/>
        <paletteEntry value="11" color="#8C8C8C" alpha="255" label="NA-MA02 Eufotisk fast saltvannsbunn"/>
        <paletteEntry value="12" color="#666666" alpha="255" label="NA-MA03 Afotisk fast saltvannsbunn"/>
      </colorPalette>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" colorizeStrength="100" colorizeOn="0" grayscaleMode="0" colorizeBlue="128" colorizeGreen="128" colorizeRed="255"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
