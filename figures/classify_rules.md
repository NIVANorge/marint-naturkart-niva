# Klassifiseringsregler – Marint Naturkart (NiN 3.0)

<!-- Generert av scripts/classify_rules_diagram.py fra mnk/rules.py – ikke rediger manuelt. -->

Rekkefølge (senere steg trumfer tidligere):

1. Nisjemodell (03)
2. Fjernmåling SeaBee (04)
3. Direkte: NA-MC08 Marint bunnsystem preget av oksygenmangel (05)
4. Direkte: NA-MJ01 Taretrålingsbunn (05)
5. Oppdeling i SSB 1 km rutenett → `marint-naturkart` (05)

Verdier på kantene er kodene i datasettets `nkm_*`-kolonner (forklaring i parentes).

Direkte datasett setter kun `nin_kode_fkid`/`NiN_name` (+ `nkm_prosess`, `metode_klassifisering`); `nkm_lys`, `nkm_lm-dk`, `nkm_lm-sa` og `nkm_lm-tv` endres ikke. nkm_* brukes kun som filter der regelen angir det.

## Samlet beslutningstre

```mermaid
flowchart TD
    subgraph NI["1. Nisjemodell (03)"]
    n0(["Nisjemodell setter<br/>nkm_lys · nkm_lm-dk · nkm_lm-sa · nkm_lm-tv"])
    end
    subgraph FJ["2. Fjernmåling Field (04): erstatter nkm_lys og nkm_lm-dk, setter nkm_sa-fa"]
    direction TB
    n1{"SeaBee-klasse?"}
    n0 --> n1
    n2[["❌ ikke marint – droppes"]]
    n1 -->|"ANTHRO / BEACHCAST / TERR_VEG"| n2
    n3{"nkm_lm-sa?"}
    n1 -->|"ANGIO"| n3
    n4["NA-MB02<br/>Saltvanns-undervannseng<br/>nkm_lys = 0abcde (eufotisk)<br/>nkm_lm-sa = fgh (salt)<br/>nkm_lm-dk = 0ABCD (løst)<br/>nkm_lm-tv = fra nisjemodell"]
    n3 -->|"fgh (salt)"| n4
    n5["NA-MF01<br/>Brakkvanns-undervannseng<br/>nkm_lys = 0abcde (eufotisk)<br/>nkm_lm-sa = abcde (brakk)<br/>nkm_lm-dk = 0ABCD (løst)<br/>nkm_lm-tv = fra nisjemodell"]
    n3 -->|"abcde (brakk)"| n5
    n6["nkm_lm-dk := EFGY (fast)<br/>nkm_lys := 0abcde (eufotisk)<br/>nkm_sa-fa := ABC (alger)"]
    n1 -->|"ALGAE"| n6
    n7["nkm_lm-dk := EFGY (fast)<br/>nkm_lys := 0abcde (eufotisk)<br/>nkm_sa-fa := 0B (stein)"]
    n1 -->|"ROCK"| n7
    n8["nkm_lm-dk := 0ABCD (løst)<br/>nkm_lys := 0abcde (eufotisk)"]
    n1 -->|"SEDIMENT"| n8
    n9["behold nisjemodellens<br/>nkm_lys og nkm_lm-dk"]
    n1 -->|"DEEP / ingen fjernmåling"| n9
    end
    n10[/"nkm_lys · nkm_lm-dk · nkm_lm-sa · nkm_lm-tv"/]
    n6 --> n10
    n7 --> n10
    n8 --> n10
    n9 --> n10
    subgraph NM["3. NiN-hovedtype fra nkm_*"]
    direction TB
    n11{"nkm_lm-sa?"}
    n10 --> n11
    n12{"nkm_lm-dk?"}
    n11 -->|"fgh (salt)"| n12
    n13{"nkm_lys?"}
    n12 -->|"EFGY (fast)"| n13
    n14{"nkm_lm-tv?"}
    n13 -->|"0abcde (eufotisk)"| n14
    n15["NA-MA01<br/>Fast saltvanns-fjærebeltebunn<br/>nkm_lys = 0abcde (eufotisk)<br/>nkm_lm-sa = fgh (salt)<br/>nkm_lm-dk = EFGY (fast)<br/>nkm_lm-tv = LM-TV_abcdefgh (innenfor)"]
    n14 -->|"LM-TV_abcdefgh (innenfor)"| n15
    n16["NA-MA02<br/>Eufotisk fast saltvannsbunn<br/>nkm_lys = 0abcde (eufotisk)<br/>nkm_lm-sa = fgh (salt)<br/>nkm_lm-dk = EFGY (fast)<br/>nkm_lm-tv = LM-TV_0 (utenfor)"]
    n14 -->|"LM-TV_0 (utenfor)"| n16
    n17["NA-MA03<br/>Afotisk fast saltvannsbunn<br/>nkm_lys = y (afotisk)<br/>nkm_lm-sa = fgh (salt)<br/>nkm_lm-dk = EFGY (fast)<br/>nkm_lm-tv = LM-TV_0 (utenfor)"]
    n13 -->|"y (afotisk)"| n17
    n18{"nkm_lys?"}
    n12 -->|"0ABCD (løst)"| n18
    n19{"nkm_lm-tv?"}
    n18 -->|"0abcde (eufotisk)"| n19
    n20["NA-MA04<br/>Fjærebelte-sedimentbunn<br/>nkm_lys = 0abcde (eufotisk)<br/>nkm_lm-sa = fgh (salt)<br/>nkm_lm-dk = 0ABCD (løst)<br/>nkm_lm-tv = LM-TV_abcdefgh (innenfor)"]
    n19 -->|"LM-TV_abcdefgh (innenfor)"| n20
    n21["NA-MA05<br/>Eufotisk saltvanns-sedimentbunn<br/>nkm_lys = 0abcde (eufotisk)<br/>nkm_lm-sa = fgh (salt)<br/>nkm_lm-dk = 0ABCD (løst)<br/>nkm_lm-tv = LM-TV_0 (utenfor)"]
    n19 -->|"LM-TV_0 (utenfor)"| n21
    n22["NA-MA06<br/>Afotisk saltvanns-sedimentbunn<br/>nkm_lys = y (afotisk)<br/>nkm_lm-sa = fgh (salt)<br/>nkm_lm-dk = 0ABCD (løst)<br/>nkm_lm-tv = LM-TV_0 (utenfor)"]
    n18 -->|"y (afotisk)"| n22
    n23{"nkm_lm-dk?"}
    n11 -->|"abcde (brakk)"| n23
    n24{"nkm_lys?"}
    n23 -->|"EFGY (fast)"| n24
    n25{"nkm_lm-tv?"}
    n24 -->|"0abcde (eufotisk)"| n25
    n26["NA-MC01<br/>Fast brakkvanns-fjærebeltebunn<br/>nkm_lys = 0abcde (eufotisk)<br/>nkm_lm-sa = abcde (brakk)<br/>nkm_lm-dk = EFGY (fast)<br/>nkm_lm-tv = LM-TV_abcdefgh (innenfor)"]
    n25 -->|"LM-TV_abcdefgh (innenfor)"| n26
    n27["NA-MC02<br/>Fast brakkvannsbunn<br/>nkm_lys = 0abcde (eufotisk) / y (afotisk)<br/>nkm_lm-sa = abcde (brakk)<br/>nkm_lm-dk = EFGY (fast)<br/>nkm_lm-tv = LM-TV_0 (utenfor)"]
    n25 -->|"LM-TV_0 (utenfor)"| n27
    n24 -->|"y (afotisk)"| n27
    n28["NA-MC04<br/>Brakkvanns-sedimentbunn<br/>nkm_lys = 0abcde (eufotisk) / y (afotisk)<br/>nkm_lm-sa = abcde (brakk)<br/>nkm_lm-dk = 0ABCD (løst)<br/>nkm_lm-tv = LM-TV_abcdefgh (innenfor) / LM-TV_0 (utenfor)"]
    n23 -->|"0ABCD (løst)"| n28
    end
    subgraph DI["4. Direkte datasett (05): setter kun NiN-type, nkm_* uendret"]
    direction TB
    n29{"Innenfor Marine vanntyper oksygenfattig<br/>Type ∈ 01a, 02a, 03a<br/>og nkm_lys = y / 0abcde<br/>og nkm_lm-tv = LM-TV_0?"}
    n30["NA-MC08<br/>Marint bunnsystem preget av oksygenmangel<br/>prosess C · NKM_direkte_oksygenmangel<br/>nkm_* uendret"]
    n29 -->|"ja"| n30
    n31{"Innenfor taretraling_polygons_2020-2025_2026-11-15.gpkg?"}
    n30 --> n31
    n29 -->|"nei"| n31
    n32["NA-MJ01<br/>Taretrålingsbunn<br/>prosess J · NKM_direkte_taretralingsbunn<br/>nkm_* uendret"]
    n31 -->|"ja"| n32
    n33["behold type"]
    n31 -->|"nei"| n33
    n34(["ferdig klassifisert"])
    n32 --> n34
    n33 --> n34
    end
    NM --> n29
    n4 --> n29
    n5 --> n29
    n35[/"5. SSB 1 km rutenett → marint-naturkart"/]
    n34 --> n35

    classDef drop fill:#f8d7da,stroke:#c00,color:#600;
    classDef veg fill:#d4f4c0,stroke:#2b8a3e,color:#1b4332;
    classDef salt fill:#e7f0ff,stroke:#1864ab,color:#0b3d91;
    classDef brakk fill:#fff3bf,stroke:#b08900,color:#5c4500;
    classDef direkte fill:#f3d9fa,stroke:#862e9c,color:#4a1259;
    classDef model fill:#dbe9ff,stroke:#1864ab,color:#0b3d91;
    classDef override fill:#ffe8cc,stroke:#d9480f,color:#7a2e00;
    class n0,n9,n10 model;
    class n2 drop;
    class n4,n5 veg;
    class n6,n7,n8 override;
    class n15,n16,n17,n20,n21,n22 salt;
    class n26,n27,n28 brakk;
    class n30,n32 direkte;
```

| nin_kode_fkid | NiN_name | url | utvalg | filter nkm_* | metode_klassifisering |
|---|---|---|---|---|---|
| NA-MC08 | Marint bunnsystem preget av oksygenmangel | `gs://niva-geodata/MarintNaturKart/input/mdir/NyTypologi2022.geo.parquet` | `Type` ∈ 01a, 02a, 03a | `nkm_lys` ∈ y, 0abcde; `nkm_lm-tv` ∈ LM-TV_0 | `NKM_direkte_oksygenmangel` |
| NA-MJ01 | Taretrålingsbunn | `gs://niva-geodata/MarintNaturKart/input/niva/taretraling_polygons_2020-2025_2026-11-15.gpkg` | alle | alle | `NKM_direkte_taretralingsbunn` |
