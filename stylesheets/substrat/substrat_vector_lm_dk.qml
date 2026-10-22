<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!--
  QGIS style for the substrate vector dataset, categorized on the LM_DK field.
  LM_DK values: "DK_AB, DK_C, DK_D" = Løsbunn (soft), "DK_0" = Blanding (mixture),
  "DK_EFGY" = Fastbunn (hard).
  Colors match nivacloud-terriamap prod niva.json.
-->
<qgis version="3.34" styleCategories="Symbology" simplifyLocal="1" simplifyAlgorithm="0" simplifyDrawingHints="1" simplifyDrawingTol="1" simplifyMaxScale="1" readOnly="0" maxScale="0" minScale="1e+08">
  <renderer-v2 type="categorizedSymbol" forceraster="0" symbollevels="0" enableorderby="0" attr="LM_DK" referencescale="-1">
    <categories>
      <category value="DK_AB, DK_C, DK_D" symbol="0" label="Løsbunn (soft)" type="string" render="true"/>
      <category value="DK_0" symbol="1" label="Blanding (mixture)" type="string" render="true"/>
      <category value="DK_EFGY" symbol="2" label="Fastbunn (hard)" type="string" render="true"/>
      <category value="" symbol="3" label="Annet / uten LM_DK" type="string" render="true"/>
    </categories>
    <symbols>
      <symbol name="0" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="255,179,0,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol name="1" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="128,62,117,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol name="2" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="50,112,174,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol name="3" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="200,200,200,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerGeometryType>2</layerGeometryType>
</qgis>
