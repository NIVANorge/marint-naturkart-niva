<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!--
  QGIS style for the niche-model (nisjemodell) vector dataset from
  notebooks/03_nisjemodell.ipynb, categorized on the sannsynlighet_beskrivelse field.
  Colors chosen to suit the attribute domain; nin_kode_fkid styling lives
  in nisje_vector.qml and is left unchanged.
-->
<qgis version="3.34" styleCategories="Symbology" simplifyLocal="1" simplifyAlgorithm="0" simplifyDrawingHints="1" simplifyDrawingTol="1" simplifyMaxScale="1" readOnly="0" maxScale="0" minScale="1e+08">
  <renderer-v2 type="categorizedSymbol" forceraster="0" symbollevels="0" enableorderby="0" attr="sannsynlighet_beskrivelse" referencescale="-1">
    <categories>
      <category value="høy" symbol="0" label="høy" type="string" render="true"/>
      <category value="medium" symbol="1" label="medium" type="string" render="true"/>
      <category value="lav" symbol="2" label="lav" type="string" render="true"/>
    </categories>
    <symbols>
      <symbol name="0" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="26,152,80,255"/>
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
            <Option name="color" type="QString" value="254,224,139,255"/>
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
            <Option name="color" type="QString" value="215,48,39,255"/>
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
