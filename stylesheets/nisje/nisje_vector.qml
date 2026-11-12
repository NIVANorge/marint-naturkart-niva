<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!--
  QGIS style for the niche-model (nisjemodell) vector dataset, categorized on the
  nin_kode_fkid field (NiN hovedtype), per datamodell_silver_nin_flate_NK.xlsx (k_hovedtype).
  Colors are the official k_hovedtype.hex values. MA02 and MA04 have no hex set in the
  datamodel and use clearly-marked fallback colors. The environmental axes (lys/salinitet/
  substrat/toerfall) are separate attribute fields and are not styled here.
-->
<qgis version="3.34" styleCategories="Symbology" simplifyLocal="1" simplifyAlgorithm="0" simplifyDrawingHints="1" simplifyDrawingTol="1" simplifyMaxScale="1" readOnly="0" maxScale="0" minScale="1e+08">
  <renderer-v2 type="categorizedSymbol" forceraster="0" symbollevels="0" enableorderby="0" attr="nin_kode_fkid" referencescale="-1">
    <categories>
      <category value="NA-MA01" symbol="0" label="NA-MA01 Fast saltvanns-fjærebeltebunn" type="string" render="true"/>
      <category value="NA-MA02" symbol="1" label="NA-MA02 Eufotisk fast saltvannsbunn (fallback-farge)" type="string" render="true"/>
      <category value="NA-MA03" symbol="2" label="NA-MA03 Afotisk fast saltvannsbunn" type="string" render="true"/>
      <category value="NA-MA04" symbol="3" label="NA-MA04 Fjærebelte-sedimentbunn (fallback-farge)" type="string" render="true"/>
      <category value="NA-MA05" symbol="4" label="NA-MA05 Eufotisk saltvanns-sedimentbunn" type="string" render="true"/>
      <category value="NA-MA06" symbol="5" label="NA-MA06 Afotisk saltvanns-sedimentbunn" type="string" render="true"/>
      <category value="NA-MC01" symbol="6" label="NA-MC01 Fast brakkvanns-fjærebeltebunn" type="string" render="true"/>
      <category value="NA-MC02" symbol="7" label="NA-MC02 Fast brakkvannsbunn" type="string" render="true"/>
      <category value="NA-MC04" symbol="8" label="NA-MC04 Brakkvanns-sedimentbunn" type="string" render="true"/>
      <category value="" symbol="9" label="Annet / uten nin_kode_fkid" type="string" render="true"/>
    </categories>
    <symbols>
      <symbol name="0" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="178,178,178,255"/>
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
            <Option name="color" type="QString" value="140,140,140,255"/>
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
            <Option name="color" type="QString" value="102,102,102,255"/>
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
            <Option name="color" type="QString" value="229,245,224,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol name="4" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="172,245,213,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol name="5" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="91,168,158,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol name="6" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="140,107,177,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol name="7" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="158,154,200,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol name="8" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="199,233,192,255"/>
            <Option name="outline_color" type="QString" value="35,35,35,0"/>
            <Option name="outline_style" type="QString" value="no"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol name="9" type="fill" alpha="1" frame_rate="10" is_animated="0" clip_to_extent="1" force_rhr="0">
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
