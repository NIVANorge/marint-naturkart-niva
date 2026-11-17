"""Convert QGIS styles (.qml) to ArcGIS Pro layer files (.lyrx).

Usage: pixi run lyrx [path.qml ...]   (default: stylesheets/mnk_vector.qml)

Supported QML renderer types:
- paletteEntry          -> CIMRasterUniqueValueColorizer (paletted raster)
- singlebandpseudocolor -> CIMRasterClassifyColorizer    (classified raster)
- categorizedSymbol     -> CIMUniqueValueRenderer         (vector polygons)

For vector styles, a QML category with an empty value becomes the ArcGIS
default symbol ("all other values").
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT = [REPO / "stylesheets" / "mnk_vector.qml"]
GREY = [130, 130, 130]


def hex_to_rgb(hex_color: str) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)]


def qgis_to_rgba(value: str) -> list[int]:
    """QGIS 'R,G,B,A' (0-255) -> ArcGIS [R, G, B, alpha %]."""
    r, g, b, *a = (int(p) for p in value.split(",")[:4])
    return [r, g, b, round((a[0] if a else 255) / 255 * 100)]


def cim_color(rgba: list[int]) -> dict:
    return {"type": "CIMRGBColor", "values": rgba}


def detect_qml_type(root: ET.Element) -> str:
    if root.find(".//paletteEntry") is not None:
        return "paletted_raster"
    renderer = root.find(".//renderer-v2")
    if renderer is not None and renderer.attrib.get("type") == "categorizedSymbol":
        return "vector"
    if root.find(".//colorrampshader") is not None:
        return "continuous_raster"
    raise ValueError("Unrecognised QML renderer type")


def layer_document(name: str, layer: dict) -> dict:
    return {
        "type": "CIMLayerDocument",
        "version": "3.2.0",
        "build": 36057,
        "layers": [layer["uRI"]],
        "layerDefinitions": [layer],
    }


# ---------------------------------------------------------------------------
# Rasters
# ---------------------------------------------------------------------------


def lyrx_paletted_raster(name: str, root: ET.Element) -> dict:
    classes = [
        {
            "type": "CIMRasterUniqueValueClass",
            "values": [e.attrib["value"]],
            "label": e.attrib.get("label", e.attrib["value"]),
            "color": cim_color([*hex_to_rgb(e.attrib["color"]), 100]),
            "visible": True,
        }
        for e in root.iter("paletteEntry")
    ]
    return layer_document(name, {
        "type": "CIMRasterLayer",
        "name": name,
        "uRI": f"CIMPATH=raster/{name}.json",
        "visibility": True,
        "showPopups": True,
        "colorizer": {
            "type": "CIMRasterUniqueValueColorizer",
            "defaultColor": cim_color([*GREY, 100]),
            "defaultLabel": "<all other values>",
            "fieldName": "Value",
            "groups": [{"type": "CIMRasterUniqueValueGroup", "classes": classes, "heading": "Value"}],
            "useDefaultColor": False,
        },
    })


def lyrx_continuous_raster(name: str, root: ET.Element) -> dict:
    shader = root.find(".//colorrampshader")
    breaks = [
        {
            "type": "CIMRasterClassBreak",
            "upperBound": float(i.attrib["value"]),
            "label": i.attrib.get("label", i.attrib["value"]),
            "color": cim_color([*hex_to_rgb(i.attrib["color"]), 100]),
        }
        for i in shader.findall("item")
    ]
    return layer_document(name, {
        "type": "CIMRasterLayer",
        "name": name,
        "uRI": f"CIMPATH=raster/{name}.json",
        "visibility": True,
        "showPopups": True,
        "colorizer": {
            "type": "CIMRasterClassifyColorizer",
            "classBreaks": breaks,
            "minimumBreak": float(shader.attrib.get("minimumValue", 0)),
            "field": "Value",
            "showInAscendingOrder": True,
        },
    })


# ---------------------------------------------------------------------------
# Vector (categorized polygons)
# ---------------------------------------------------------------------------


def fill_symbol(fill: list[int], outline: list[int] | None = None, width: float = 0) -> dict:
    return {
        "type": "CIMSymbolReference",
        "symbol": {
            "type": "CIMPolygonSymbol",
            "symbolLayers": [
                {
                    "type": "CIMSolidStroke",
                    "enable": outline is not None and width > 0,
                    "width": width,
                    "color": cim_color(outline or [0, 0, 0, 0]),
                },
                {"type": "CIMSolidFill", "enable": True, "color": cim_color(fill)},
            ],
        },
    }


def parse_symbols(renderer: ET.Element) -> dict[str, dict]:
    """Symbol name -> fill_symbol, from the first SimpleFill layer."""
    out = {}
    for sym in renderer.findall("./symbols/symbol"):
        opts = {o.attrib["name"]: o.attrib.get("value") for o in sym.findall(".//layer/Option/Option")}
        fill = qgis_to_rgba(opts.get("color", "130,130,130,255"))
        if opts.get("style") == "no":
            fill[3] = 0
        outline = None
        width = 0.0
        if opts.get("outline_style", "solid") != "no":
            outline = qgis_to_rgba(opts.get("outline_color", "35,35,35,255"))
            # QGIS mm -> ArcGIS points.
            width = float(opts.get("outline_width", 0.26)) * 72 / 25.4
        out[sym.attrib["name"]] = fill_symbol(fill, outline, round(width, 2))
    return out


def lyrx_vector(name: str, root: ET.Element) -> dict:
    renderer = root.find(".//renderer-v2")
    field = renderer.attrib.get("attr", "Value")
    symbols = parse_symbols(renderer)

    classes = []
    default_symbol, default_label = fill_symbol([*GREY, 100]), "<all other values>"
    for cat in renderer.findall("./categories/category"):
        value, label = cat.attrib["value"], cat.attrib.get("label", cat.attrib["value"])
        sym = symbols.get(cat.attrib["symbol"], fill_symbol([*GREY, 100]))
        if value == "":
            default_symbol, default_label = sym, label
            continue
        classes.append({
            "type": "CIMUniqueValueClass",
            "values": [{"type": "CIMUniqueValue", "fieldValues": [value]}],
            "label": label,
            "symbol": sym,
            "visible": cat.attrib.get("render", "true") == "true",
        })

    return layer_document(name, {
        "type": "CIMFeatureLayer",
        "name": name,
        "uRI": f"CIMPATH=map/{name}.json",
        "visibility": True,
        "showPopups": True,
        "renderer": {
            "type": "CIMUniqueValueRenderer",
            "defaultSymbol": default_symbol,
            "defaultLabel": default_label,
            "useDefaultSymbol": True,
            "fields": [field],
            "groups": [{"type": "CIMUniqueValueGroup", "classes": classes, "heading": field}],
        },
    })


# ---------------------------------------------------------------------------


BUILDERS = {
    "paletted_raster": lyrx_paletted_raster,
    "continuous_raster": lyrx_continuous_raster,
    "vector": lyrx_vector,
}


def convert(qml_path: Path) -> Path:
    root = ET.parse(qml_path).getroot()
    doc = BUILDERS[detect_qml_type(root)](qml_path.stem, root)
    out = qml_path.with_suffix(".lyrx")
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main(paths: list[str]) -> None:
    for p in [Path(a).resolve() for a in paths] or DEFAULT:
        out = convert(p)
        print(f"{p.relative_to(REPO)} -> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main(sys.argv[1:])
