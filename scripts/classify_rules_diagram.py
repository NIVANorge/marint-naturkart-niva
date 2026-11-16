"""Generate figures/classify_rules.md (Mermaid decision tree) from mnk.rules.

Usage: pixi run classify-rules [--render]

``--render`` also writes figures/classify_rules_samlet.svg via mermaid-cli (``npx mmdc``).
"""

from __future__ import annotations

import argparse
import itertools
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

import mnk.attributes
import mnk.rules as R

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "figures"
OUT_MD = OUT_DIR / "classify_rules.md"

# Order of the niche-model axes in the tree: (column, rule-tuple index, value map).
AXES = [
    ("nkm_salinitet", 1, R.NKM_SALINITET),
    ("nkm_substrat", 2, R.NKM_SUBSTRAT),
    ("nkm_lys", 0, R.NKM_LYS),
    ("nkm_toerfall", 3, R.NKM_TOERFALL),
]

CLASSDEFS = """
    classDef drop fill:#f8d7da,stroke:#c00,color:#600;
    classDef veg fill:#d4f4c0,stroke:#2b8a3e,color:#1b4332;
    classDef salt fill:#e7f0ff,stroke:#1864ab,color:#0b3d91;
    classDef brakk fill:#fff3bf,stroke:#b08900,color:#5c4500;
    classDef direkte fill:#f3d9fa,stroke:#862e9c,color:#4a1259;
    classDef model fill:#dbe9ff,stroke:#1864ab,color:#0b3d91;
    classDef override fill:#ffe8cc,stroke:#d9480f,color:#7a2e00;"""


def nin_class(code: str) -> str:
    if code in R.SEABEE_ANGIO.values():
        return "veg"
    if code in {r["nin_kode_fkid"] for r in R.DIRECT_RULES}:
        return "direkte"
    return "salt" if code.startswith("NA-MA") else "brakk"


class Diagram:
    def __init__(self, prefix: str = ""):
        self.prefix = prefix
        self.lines: list[str] = []
        self.ids = itertools.count()
        self.leaves: dict[str, str] = {}
        self.classes: dict[str, list[str]] = defaultdict(list)

    def node(self, label: str, shape: str = "decision") -> str:
        nid = f"{self.prefix}n{next(self.ids)}"
        wrap = {"decision": '{{"{}"}}', "box": '["{}"]', "drop": '[["{}"]]',
                "start": '(["{}"])', "io": '[/"{}"/]'}[shape]
        self.lines.append(f"    {nid}{wrap.format(label)}")
        return nid

    def leaf(self, code: str, extra: str = "") -> str:
        key = code + extra
        if key not in self.leaves:
            nid = self.node(f"{code}<br/>{R.NIN_NAMES[code]}{extra}", "box")
            self.leaves[key] = nid
            self.classes[nin_class(code)].append(nid)
        return self.leaves[key]

    def edge(self, a: str, b: str, label: str | None = None) -> None:
        self.lines.append(f"    {a} -->|{label}| {b}" if label else f"    {a} --> {b}")

    def render(self) -> str:
        cls = [f"    class {','.join(v)} {k};" for k, v in self.classes.items() if v]
        return "\n".join(["flowchart TD", *self.lines, CLASSDEFS, *cls])


def niche_tree(d: Diagram, parent: str, label: str | None, rules=None, depth=0) -> None:
    """Recursively draw NISJE_RULES, collapsing branches with a single outcome."""
    rules = rules if rules is not None else list(R.NISJE_RULES.items())
    codes = {v[0] for _, v in rules}
    if len(codes) == 1:
        d.edge(parent, d.leaf(codes.pop()), label)
        return
    col, idx, vmap = AXES[depth]
    groups: dict[str, list] = defaultdict(list)
    for k, v in rules:
        groups[k[idx]].append((k, v))
    if len(groups) == 1:  # axis does not split here -> skip it
        niche_tree(d, parent, label, rules, depth + 1)
        return
    q = d.node(f"{col}?")
    d.edge(parent, q, label)
    for val, sub in groups.items():
        niche_tree(d, q, vmap[val], sub, depth + 1)


def seabee_groups():
    """Group SeaBee classes by their effect on the model axes."""
    groups: dict[tuple, list[str]] = defaultdict(list)
    for cls in [*R.SEABEE_SUBSTRAT_OVERRIDE, *sorted(R.SEABEE_KEEP_MODEL)]:
        groups[(R.SEABEE_SUBSTRAT_OVERRIDE.get(cls), R.SEABEE_LYS_OVERRIDE.get(cls))].append(cls)
    return groups


def seabee_step(d: Diagram, start: str) -> tuple[str, list[str]]:
    """Draw the SeaBee step that replaces nkm_lys / nkm_substrat.

    Returns (node leading into the NiN tree, ANGIO leaves that bypass it).
    """
    d.lines.append('    subgraph FJ["2. Fjernmåling SeaBee (04): erstatter nkm_lys og nkm_substrat"]')
    d.lines.append("    direction TB")
    q = d.node("SeaBee-klasse?")
    d.edge(start, q)

    x = d.node("❌ ikke marint – droppes", "drop")
    d.classes["drop"].append(x)
    d.edge(q, x, " / ".join(sorted(R.SEABEE_NONMARINE)))

    s = d.node("nkm_salinitet?")
    lys = R.SEABEE_LYS_OVERRIDE.get("ANGIO")
    d.edge(q, s, "ANGIO")
    angio = []
    for sal, code in R.SEABEE_ANGIO.items():
        extra = f"<br/>nkm_substrat = {R.NKM_SUBSTRAT['løst']}" + (f"<br/>nkm_lys = {lys}" if lys else "")
        leaf = d.leaf(code, extra)
        d.edge(s, leaf, R.NKM_SALINITET[sal])
        angio.append(leaf)

    outs = []
    for (sub, lys), classes in seabee_groups().items():
        parts = []
        if sub:
            parts.append(f"nkm_substrat := {R.NKM_SUBSTRAT[sub]}")
        if lys:
            parts.append(f"nkm_lys := {lys}")
        label = "<br/>".join(parts) if parts else "behold nisjemodellens<br/>nkm_lys og nkm_substrat"
        box = d.node(label, "box")
        d.classes["override" if parts else "model"].append(box)
        d.edge(q, box, " / ".join(classes) + ("" if parts else " / ingen fjernmåling"))
        outs.append(box)
    d.lines.append("    end")

    nm_in = d.node("nkm_lys · nkm_substrat · nkm_salinitet · nkm_toerfall", "io")
    d.classes["model"].append(nm_in)
    for o in outs:
        d.edge(o, nm_in)
    return nm_in, angio


def direct_chain(d: Diagram, inputs: list[str]) -> str:
    """Draw DIRECT_RULES in order; returns the final 'behold type' node.

    Direct rules only set the NiN type; nkm_* columns are read (filter) but never changed.
    """
    incoming = [(src, None) for src in inputs]
    for rule in R.DIRECT_RULES:
        cond = f"Innenfor {rule.get('label') or Path(rule['url']).name}"
        if rule["column"]:
            cond += f"<br/>{rule['column']} ∈ {', '.join(rule['values'])}"
        if rule["nkm_lys"]:
            cond += f"<br/>og nkm_lys = {' / '.join(rule['nkm_lys'])}"
        q = d.node(cond + "?")
        for src, label in incoming:
            d.edge(src, q, label)
        code = rule["nin_kode_fkid"]
        leaf = d.leaf(code, f"<br/>prosess {mnk.attributes.NKM_PROSESS[code]} · "
                            f"{rule['metode_klassifisering']}<br/>nkm_* uendret")
        d.edge(q, leaf, "ja")
        incoming = [(leaf, None), (q, "nei")]
    keep = d.node("behold type", "box")
    d.edge(incoming[1][0], keep, "nei")
    end = d.node("ferdig klassifisert", "start")
    d.edge(incoming[0][0], end)
    d.edge(keep, end)
    return end


def diagram_combined() -> str:
    d = Diagram()
    d.lines.append('    subgraph NI["1. Nisjemodell (03)"]')
    start = d.node("Nisjemodell setter<br/>nkm_lys · nkm_substrat · nkm_salinitet · nkm_toerfall", "start")
    d.classes["model"].append(start)
    d.lines.append("    end")

    nm_in, angio = seabee_step(d, start)

    d.lines.append('    subgraph NM["3. NiN-hovedtype fra nkm_*"]')
    d.lines.append("    direction TB")
    niche_tree(d, nm_in, None)
    d.lines.append("    end")

    d.lines.append('    subgraph DI["4. Direkte datasett (05): setter kun NiN-type, nkm_* uendret"]')
    d.lines.append("    direction TB")
    i0 = len(d.lines)
    end = direct_chain(d, ["NM", *angio])
    # Edges from other subgraphs must be declared outside, else Mermaid nests them.
    body = d.lines[i0:]
    ext = [l for l in body if l.lstrip().startswith(("NM ", *[a + " " for a in angio]))]
    d.lines[i0:] = [l for l in body if l not in ext]
    d.lines.append("    end")
    d.lines.extend(ext)
    grid = d.node("5. SSB 1 km rutenett → marint-naturkart", "io")
    d.edge(end, grid)
    return d.render()


def direct_table() -> str:
    rows = ["| nin_kode_fkid | NiN_name | url | utvalg | nkm_lys | metode_klassifisering | datakilde |",
            "|---|---|---|---|---|---|---|"]
    for r in R.DIRECT_RULES:
        sel = f"`{r['column']}` ∈ {', '.join(r['values'])}" if r["column"] else "alle"
        lys = ", ".join(r["nkm_lys"]) if r["nkm_lys"] else "alle"
        rows.append(f"| {r['nin_kode_fkid']} | {R.NIN_NAMES[r['nin_kode_fkid']]} | `{r['url']}` | "
                    f"{sel} | {lys} | `{r['metode_klassifisering']}` | `{r['datakilde']}` |")
    return "\n".join(rows)


DIAGRAMS = [
    ("samlet", "Samlet beslutningstre", diagram_combined),
]


def build_markdown(blocks: dict[str, str]) -> str:
    out = [
        "# Klassifiseringsregler – Marint Naturkart (NiN 3.0)",
        "",
        "<!-- Generert av scripts/classify_rules_diagram.py fra mnk/rules.py – ikke rediger manuelt. -->",
        "",
        "Rekkefølge (senere steg trumfer tidligere):",
        "",
        "1. Nisjemodell (03)",
        "2. Fjernmåling SeaBee (04)",
        *[f"{i}. Direkte: {r['nin_kode_fkid']} {R.NIN_NAMES[r['nin_kode_fkid']]} (05)"
          for i, r in enumerate(R.DIRECT_RULES, start=3)],
        f"{len(R.DIRECT_RULES) + 3}. Oppdeling i SSB 1 km rutenett → `marint-naturkart` (05)",
        "",
        "Verdier på kantene er verdiene i datasettets `nkm_*`-kolonner.",
        "",
        "Direkte datasett setter kun `nin_kode_fkid`/`NiN_name` (+ `nkm_prosess`, "
        "`metode_klassifisering`, `datakilde`); `nkm_lys`, `nkm_substrat`, `nkm_salinitet` "
        "og `nkm_toerfall` endres ikke. `nkm_lys` brukes kun som filter der regelen angir det.",
    ]
    for key, title, _ in DIAGRAMS:
        out += ["", f"## {title}", "", "```mermaid", blocks[key], "```"]
        if key == "samlet":
            out += ["", direct_table()]
    return "\n".join(out) + "\n"


def render(blocks: dict[str, str]) -> None:
    npx = shutil.which("npx")
    if not npx:
        raise SystemExit("npx not found – install Node.js to render SVG")
    for old in OUT_DIR.glob("classify_rules_*.*"):
        old.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        # Plain SVG <text> labels instead of HTML in <foreignObject>, which many
        # SVG viewers (Inkscape, image viewers, Office) do not render.
        cfg = Path(tmp) / "config.json"
        cfg.write_text('{"htmlLabels": false, "flowchart": {"htmlLabels": false, "wrappingWidth": 400}}')
        for key, block in blocks.items():
            src = Path(tmp) / f"{key}.mmd"
            src.write_text(block)
            for ext, extra in (("svg", []),):
                out = OUT_DIR / f"classify_rules_{key}.{ext}"
                subprocess.run([npx, "-y", "-p", "@mermaid-js/mermaid-cli", "mmdc", "-q",
                                "-c", str(cfg), "-i", str(src), "-o", str(out), *extra], check=True)
                print(f"Wrote {out.relative_to(REPO)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--render", action="store_true", help="also render SVG via mermaid-cli")
    args = ap.parse_args()
    blocks = {key: fn() for key, _, fn in DIAGRAMS}
    OUT_MD.write_text(build_markdown(blocks))
    print(f"Wrote {OUT_MD.relative_to(REPO)}")
    if args.render:
        render(blocks)


if __name__ == "__main__":
    main()
