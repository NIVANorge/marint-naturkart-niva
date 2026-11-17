# Klassifiseringsregler – Marint Naturkart (NiN 3.0)

<!-- Generert av scripts/classify_rules_diagram.py fra mnk/rules.py – ikke rediger manuelt. -->

Rekkefølge (senere steg trumfer tidligere):

1. Nisjemodell (03)
2. Fjernmåling SeaBee (04)
3. Direkte: NA-MC08 Marint bunnsystem preget av oksygenmangel (05)
4. Direkte: NA-MJ01 Taretrålingsbunn (05)
5. Oppdeling i SSB 1 km rutenett → `marint-naturkart` (05)

Verdier på kantene er verdiene i datasettets `nkm_*`-kolonner.

Direkte datasett setter kun `nin_kode_fkid`/`NiN_name` (+ `nkm_prosess`, `metode_klassifisering`, `datakilde`); `nkm_lys`, `nkm_substrat`, `nkm_salinitet` og `nkm_toerfall` endres ikke. `nkm_lys` brukes kun som filter der regelen angir det.

## Samlet beslutningstre

```mermaid
flowchart TD
    subgraph NI["1. Nisjemodell (03)"]
    n0(["Nisjemodell setter<br/>nkm_lys · nkm_substrat · nkm_salinitet · nkm_toerfall"])
    end
    subgraph FJ["2. Fjernmåling SeaBee (04): erstatter nkm_lys og nkm_substrat"]
    direction TB
    n1{"SeaBee-klasse?"}
    n0 --> n1
    n2[["❌ ikke marint – droppes"]]
    n1 -->|ANTHRO / BEACHCAST / TERR_VEG| n2
    n3{"nkm_salinitet?"}
    n1 -->|ANGIO| n3
    n4["NA-MB02<br/>Saltvanns-undervannseng<br/>nkm_lys = eufotisk<br/>nkm_salinitet = saltvann<br/>nkm_substrat = loesbunn<br/>nkm_toerfall = fra nisjemodell"]
    n3 -->|saltvann| n4
    n5["NA-MF01<br/>Brakkvanns-undervannseng<br/>nkm_lys = eufotisk<br/>nkm_salinitet = brakkvann<br/>nkm_substrat = loesbunn<br/>nkm_toerfall = fra nisjemodell"]
    n3 -->|brakkvann| n5
    n6["nkm_substrat := fastbunn<br/>nkm_lys := eufotisk"]
    n1 -->|ALGAE / ROCK| n6
    n7["nkm_substrat := loesbunn<br/>nkm_lys := eufotisk"]
    n1 -->|SEDIMENT| n7
    n8["behold nisjemodellens<br/>nkm_lys og nkm_substrat"]
    n1 -->|DEEP / ingen fjernmåling| n8
    end
    n9[/"nkm_lys · nkm_substrat · nkm_salinitet · nkm_toerfall"/]
    n6 --> n9
    n7 --> n9
    n8 --> n9
    subgraph NM["3. NiN-hovedtype fra nkm_*"]
    direction TB
    n10{"nkm_salinitet?"}
    n9 --> n10
    n11{"nkm_substrat?"}
    n10 -->|saltvann| n11
    n12{"nkm_lys?"}
    n11 -->|fastbunn| n12
    n13{"nkm_toerfall?"}
    n12 -->|eufotisk| n13
    n14["NA-MA01<br/>Fast saltvanns-fjærebeltebunn<br/>nkm_lys = eufotisk<br/>nkm_salinitet = saltvann<br/>nkm_substrat = fastbunn<br/>nkm_toerfall = toerfall"]
    n13 -->|toerfall| n14
    n15["NA-MA02<br/>Eufotisk fast saltvannsbunn<br/>nkm_lys = eufotisk<br/>nkm_salinitet = saltvann<br/>nkm_substrat = fastbunn<br/>nkm_toerfall = permanent_vanndekket"]
    n13 -->|permanent_vanndekket| n15
    n16["NA-MA03<br/>Afotisk fast saltvannsbunn<br/>nkm_lys = afotisk<br/>nkm_salinitet = saltvann<br/>nkm_substrat = fastbunn<br/>nkm_toerfall = permanent_vanndekket"]
    n12 -->|afotisk| n16
    n17{"nkm_lys?"}
    n11 -->|loesbunn| n17
    n18{"nkm_toerfall?"}
    n17 -->|eufotisk| n18
    n19["NA-MA04<br/>Fjærebelte-sedimentbunn<br/>nkm_lys = eufotisk<br/>nkm_salinitet = saltvann<br/>nkm_substrat = loesbunn<br/>nkm_toerfall = toerfall"]
    n18 -->|toerfall| n19
    n20["NA-MA05<br/>Eufotisk saltvanns-sedimentbunn<br/>nkm_lys = eufotisk<br/>nkm_salinitet = saltvann<br/>nkm_substrat = loesbunn<br/>nkm_toerfall = permanent_vanndekket"]
    n18 -->|permanent_vanndekket| n20
    n21["NA-MA06<br/>Afotisk saltvanns-sedimentbunn<br/>nkm_lys = afotisk<br/>nkm_salinitet = saltvann<br/>nkm_substrat = loesbunn<br/>nkm_toerfall = permanent_vanndekket"]
    n17 -->|afotisk| n21
    n22{"nkm_substrat?"}
    n10 -->|brakkvann| n22
    n23{"nkm_lys?"}
    n22 -->|fastbunn| n23
    n24{"nkm_toerfall?"}
    n23 -->|eufotisk| n24
    n25["NA-MC01<br/>Fast brakkvanns-fjærebeltebunn<br/>nkm_lys = eufotisk<br/>nkm_salinitet = brakkvann<br/>nkm_substrat = fastbunn<br/>nkm_toerfall = toerfall"]
    n24 -->|toerfall| n25
    n26["NA-MC02<br/>Fast brakkvannsbunn<br/>nkm_lys = eufotisk / afotisk<br/>nkm_salinitet = brakkvann<br/>nkm_substrat = fastbunn<br/>nkm_toerfall = permanent_vanndekket"]
    n24 -->|permanent_vanndekket| n26
    n23 -->|afotisk| n26
    n27["NA-MC04<br/>Brakkvanns-sedimentbunn<br/>nkm_lys = eufotisk / afotisk<br/>nkm_salinitet = brakkvann<br/>nkm_substrat = loesbunn<br/>nkm_toerfall = toerfall / permanent_vanndekket"]
    n22 -->|loesbunn| n27
    end
    subgraph DI["4. Direkte datasett (05): setter kun NiN-type, nkm_* uendret"]
    direction TB
    n28{"Innenfor Marine vanntyper oksygenfattig<br/>Type ∈ 01a, 02a, 03a<br/>og nkm_lys = afotisk?"}
    n29["NA-MC08<br/>Marint bunnsystem preget av oksygenmangel<br/>prosess C · NKM_direkte_oksygenmangel<br/>nkm_* uendret"]
    n28 -->|ja| n29
    n30{"Innenfor taretraling_polygons_2020-2025_2026-11-15.gpkg?"}
    n29 --> n30
    n28 -->|nei| n30
    n31["NA-MJ01<br/>Taretrålingsbunn<br/>prosess J · NKM_direkte_taretralingsbunn<br/>nkm_* uendret"]
    n30 -->|ja| n31
    n32["behold type"]
    n30 -->|nei| n32
    n33(["ferdig klassifisert"])
    n31 --> n33
    n32 --> n33
    end
    NM --> n28
    n4 --> n28
    n5 --> n28
    n34[/"5. SSB 1 km rutenett → marint-naturkart"/]
    n33 --> n34

    classDef drop fill:#f8d7da,stroke:#c00,color:#600;
    classDef veg fill:#d4f4c0,stroke:#2b8a3e,color:#1b4332;
    classDef salt fill:#e7f0ff,stroke:#1864ab,color:#0b3d91;
    classDef brakk fill:#fff3bf,stroke:#b08900,color:#5c4500;
    classDef direkte fill:#f3d9fa,stroke:#862e9c,color:#4a1259;
    classDef model fill:#dbe9ff,stroke:#1864ab,color:#0b3d91;
    classDef override fill:#ffe8cc,stroke:#d9480f,color:#7a2e00;
    class n0,n8,n9 model;
    class n2 drop;
    class n4,n5 veg;
    class n6,n7 override;
    class n14,n15,n16,n19,n20,n21 salt;
    class n25,n26,n27 brakk;
    class n29,n31 direkte;
```

| nin_kode_fkid | NiN_name | url | utvalg | nkm_lys | metode_klassifisering | datakilde |
|---|---|---|---|---|---|---|
| NA-MC08 | Marint bunnsystem preget av oksygenmangel | `gs://niva-geodata/MarintNaturKart/input/mdir/NyTypologi2022.geo.parquet` | `Type` ∈ 01a, 02a, 03a | afotisk | `NKM_direkte_oksygenmangel` | `oksygen_vanntype_mdir_2022` |
| NA-MJ01 | Taretrålingsbunn | `gs://niva-geodata/MarintNaturKart/input/niva/taretraling_polygons_2020-2025_2026-11-15.gpkg` | alle | alle | `NKM_direkte_taretralingsbunn` | `taretraling_niva_2020-2025` |
