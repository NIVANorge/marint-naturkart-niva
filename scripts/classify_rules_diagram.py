"""Generate figures/classify_rules.md (Mermaid decision tree) from mnk.rules.

Usage: pixi run classify-rules [--render]

``--render`` also writes figures/classify_rules_samlet.svg/.png, figures/classify_rules.html
and installs it as a goose app (~/.local/share/goose/apps/classify-rules.html) via mermaid-cli (``npx mmdc``).
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
    (R.COL_SALINITET, 1, R.NKM_SALINITET),
    (R.COL_SUBSTRAT, 2, R.NKM_SUBSTRAT),
    (R.COL_LYS, 0, R.NKM_LYS),
    (R.COL_TOERFALL, 3, R.NKM_TOERFALL),
]
NKM_COLS = f"{R.COL_LYS} · {R.COL_SUBSTRAT} · {R.COL_SALINITET} · {R.COL_TOERFALL}"


def fmt_code(vmap: dict[str, str], token: str) -> str:
    """Dataset code for *token*, with the token as explanation."""
    return f"{vmap[token]} ({token})"

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
        self.lines.append(f"    {a} -->|\"{label}\"| {b}" if label else f"    {a} --> {b}")

    def render(self) -> str:
        cls = [f"    class {','.join(v)} {k};" for k, v in self.classes.items() if v]
        return "\n".join(["flowchart TD", *self.lines, CLASSDEFS, *cls])


AXIS_ORDER = [(R.COL_LYS, 0, R.NKM_LYS), (R.COL_SALINITET, 1, R.NKM_SALINITET),
              (R.COL_SUBSTRAT, 2, R.NKM_SUBSTRAT), (R.COL_TOERFALL, 3, R.NKM_TOERFALL)]


def axes_label(rules) -> str:
    """Resulting nkm_* values for the rule keys leading to a leaf."""
    out = []
    for col, idx, vmap in AXIS_ORDER:
        vals = list(dict.fromkeys(fmt_code(vmap, k[idx]) for k, _ in rules))
        out.append(f"{col} = {' / '.join(vals)}")
    return "<br/>" + "<br/>".join(out)


def niche_tree(d: Diagram, parent: str, label: str | None, rules=None, depth=0) -> None:
    """Recursively draw NISJE_RULES, collapsing branches with a single outcome."""
    rules = rules if rules is not None else list(R.NISJE_RULES.items())
    codes = {v[0] for _, v in rules}
    if len(codes) == 1:
        code = codes.pop()
        all_rules = [(k, v) for k, v in R.NISJE_RULES.items() if v[0] == code]
        d.edge(parent, d.leaf(code, axes_label(all_rules)), label)
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
        niche_tree(d, q, fmt_code(vmap, val), sub, depth + 1)


def seabee_groups():
    """Group SeaBee classes by their effect on the model axes."""
    groups: dict[tuple, list[str]] = defaultdict(list)
    for cls in [*R.SEABEE_SUBSTRAT_OVERRIDE, *sorted(R.SEABEE_KEEP_MODEL)]:
        groups[(R.SEABEE_SUBSTRAT_OVERRIDE.get(cls), R.SEABEE_LYS_OVERRIDE.get(cls))].append(cls)
    return groups


def seabee_step(d: Diagram, start: str) -> tuple[str, list[str]]:
    """Draw the SeaBee step that replaces the lys / substrat columns.

    Returns (node leading into the NiN tree, ANGIO leaves that bypass it).
    """
    d.lines.append(f'    subgraph FJ["2. Fjernmåling Field (04): erstatter {R.COL_LYS} og {R.COL_SUBSTRAT}"]')
    d.lines.append("    direction TB")
    q = d.node("SeaBee-klasse?")
    d.edge(start, q)

    x = d.node("❌ ikke marint – droppes", "drop")
    d.classes["drop"].append(x)
    d.edge(q, x, " / ".join(sorted(R.SEABEE_NONMARINE)))

    s = d.node(f"{R.COL_SALINITET}?")
    lys = R.SEABEE_LYS_OVERRIDE.get("ANGIO")
    d.edge(q, s, "ANGIO")
    angio = []
    for sal, nin in R.SEABEE_ANGIO.items():
        extra = (f"<br/>{R.COL_LYS} = {fmt_code(R.NKM_LYS, lys) if lys else 'fra nisjemodell'}"
                 f"<br/>{R.COL_SALINITET} = {fmt_code(R.NKM_SALINITET, sal)}"
                 f"<br/>{R.COL_SUBSTRAT} = {fmt_code(R.NKM_SUBSTRAT, 'løst')}"
                 f"<br/>{R.COL_TOERFALL} = fra nisjemodell")
        leaf = d.leaf(nin, extra)
        d.edge(s, leaf, fmt_code(R.NKM_SALINITET, sal))
        angio.append(leaf)

    outs = []
    for (sub, lys), classes in seabee_groups().items():
        parts = []
        if sub:
            parts.append(f"{R.COL_SUBSTRAT} := {fmt_code(R.NKM_SUBSTRAT, sub)}")
        if lys:
            parts.append(f"{R.COL_LYS} := {fmt_code(R.NKM_LYS, lys)}")
        label = ("<br/>".join(parts) if parts
                 else f"behold nisjemodellens<br/>{R.COL_LYS} og {R.COL_SUBSTRAT}")
        box = d.node(label, "box")
        d.classes["override" if parts else "model"].append(box)
        d.edge(q, box, " / ".join(classes) + ("" if parts else " / ingen fjernmåling"))
        outs.append(box)
    d.lines.append("    end")

    nm_in = d.node(NKM_COLS, "io")
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
        for col, vals in (rule["where"] or {}).items():
            cond += f"<br/>og {col} = {' / '.join(vals)}"
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
    start = d.node(f"Nisjemodell setter<br/>{NKM_COLS}", "start")
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
    rows = ["| nin_kode_fkid | NiN_name | url | utvalg | filter nkm_* | metode_klassifisering |",
            "|---|---|---|---|---|---|"]
    for r in R.DIRECT_RULES:
        sel = f"`{r['column']}` ∈ {', '.join(r['values'])}" if r["column"] else "alle"
        lys = "; ".join(f"`{c}` ∈ {', '.join(v)}" for c, v in r["where"].items()) if r["where"] else "alle"
        rows.append(f"| {r['nin_kode_fkid']} | {R.NIN_NAMES[r['nin_kode_fkid']]} | `{r['url']}` | "
                    f"{sel} | {lys} | `{r['metode_klassifisering']}` |")
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
        "Verdier på kantene er kodene i datasettets `nkm_*`-kolonner (forklaring i parentes).",
        "",
        "Direkte datasett setter kun `nin_kode_fkid`/`NiN_name` (+ `nkm_prosess`, "
        f"`metode_klassifisering`); `{R.COL_LYS}`, `{R.COL_SUBSTRAT}`, `{R.COL_SALINITET}` "
        f"og `{R.COL_TOERFALL}` endres ikke. nkm_* brukes kun som filter der regelen angir det.",
    ]
    for key, title, _ in DIAGRAMS:
        out += ["", f"## {title}", "", "```mermaid", blocks[key], "```"]
        if key == "samlet":
            out += ["", direct_table()]
    return "\n".join(out) + "\n"


def render(blocks: dict[str, str]) -> None:
    npx = shutil.which("npx")
    if not npx:
        raise SystemExit("npx not found – install Node.js to render SVG/PNG")
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
            # SVG for docs; PNG (white background, 2x) for Teams/Office/chat.
            for ext, extra in (("svg", []), ("png", ["-s", "3", "-b", "white"])):
                out = OUT_DIR / f"classify_rules_{key}.{ext}"
                subprocess.run([npx, "-y", "-p", "@mermaid-js/mermaid-cli", "mmdc", "-q",
                                "-c", str(cfg), "-i", str(src), "-o", str(out), *extra], check=True)
                print(f"Wrote {out.relative_to(REPO)}")


APP_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Klassifiseringsregler</title>
  <style>
    html, body { margin: 0; height: 100%; font-family: system-ui, sans-serif; background: #fff; }
    #bar { position: fixed; top: 0; left: 0; right: 0; z-index: 2; display: flex; gap: 6px;
           align-items: center; padding: 6px 10px; background: #f1f3f5; border-bottom: 1px solid #ccc; }
    #bar input { flex: 1; max-width: 320px; padding: 4px 6px; }
    #bar button { padding: 4px 10px; cursor: pointer; }
    #info { margin-left: auto; color: #555; font-size: 12px; }
    #view { position: absolute; top: 42px; left: 0; right: 0; bottom: 0; overflow: hidden; cursor: grab; }
    #view.drag { cursor: grabbing; }
    #stage { transform-origin: 0 0; }
    #stage svg { max-width: none !important; height: auto; }
    .hit rect, .hit polygon, .hit path.basic { stroke: #e03131 !important; stroke-width: 4px !important; }
  </style>
  <script type="application/ld+json">
{
  "@context": "urn:goose.ai:schema",
  "@type": "GooseApp",
  "name": "classify-rules",
  "description": "Marint Naturkart klassifiseringsregler (generert fra mnk/rules.py)",
  "width": 1100,
  "height": 900,
  "resizable": true
}
  </script>
  <script type="application/x-goose-prd">
Viser beslutningstreet for Marint Naturkart (figures/classify_rules_samlet.svg).
Generert av scripts/classify_rules_diagram.py (pixi run classify-rules) – ikke rediger manuelt.
Zoom med musehjul, dra for å panorere, søk for å utheve noder.
  </script>
</head>
<body>
  <div id="bar">
    <button id="fit" title="Tilpass">⤢</button>
    <button id="in">+</button>
    <button id="out">−</button>
    <input id="q" placeholder="Søk, f.eks. NA-MC08, nkm_lys, SEDIMENT">
    <span id="info">__STAMP__</span>
  </div>
  <div id="view"><div id="stage">__SVG__</div></div>
  <script>
    const view = document.getElementById('view'), stage = document.getElementById('stage');
    const svg = stage.querySelector('svg');
    let s = 1, x = 0, y = 0;
    const apply = () => stage.style.transform = `translate(${x}px,${y}px) scale(${s})`;
    const size = () => { const vb = svg.viewBox.baseVal; return [vb.width || svg.clientWidth, vb.height || svg.clientHeight]; };
    function fit() {
      const [w, h] = size(); svg.setAttribute('width', w); svg.setAttribute('height', h);
      s = Math.min(view.clientWidth / w, view.clientHeight / h) * 0.98;
      x = (view.clientWidth - w * s) / 2; y = 4; apply();
    }
    function zoom(f, cx = view.clientWidth / 2, cy = view.clientHeight / 2) {
      x = cx - (cx - x) * f; y = cy - (cy - y) * f; s *= f; apply();
    }
    view.addEventListener('wheel', e => { e.preventDefault();
      const r = view.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
    let d = null;
    view.addEventListener('mousedown', e => { d = [e.clientX - x, e.clientY - y]; view.classList.add('drag'); });
    window.addEventListener('mouseup', () => { d = null; view.classList.remove('drag'); });
    window.addEventListener('mousemove', e => { if (d) { x = e.clientX - d[0]; y = e.clientY - d[1]; apply(); } });
    document.getElementById('fit').onclick = fit;
    document.getElementById('in').onclick = () => zoom(1.25);
    document.getElementById('out').onclick = () => zoom(0.8);
    const nodes = [...svg.querySelectorAll('g.node, g.edgeLabel, g.cluster')];
    document.getElementById('q').addEventListener('input', e => {
      const q = e.target.value.trim().toLowerCase(); let first = null;
      nodes.forEach(n => { const hit = q && n.textContent.toLowerCase().includes(q);
        n.classList.toggle('hit', !!hit); n.style.opacity = q && !hit ? 0.35 : 1; if (hit && !first) first = n; });
      if (first) { const b = first.getBBox(), m = first.getCTM(), sm = svg.getCTM();
        const px = (m.e - sm.e) / sm.a + b.x + b.width / 2, py = (m.f - sm.f) / sm.d + b.y + b.height / 2;
        s = Math.max(s, 0.8); x = view.clientWidth / 2 - px * s; y = view.clientHeight / 2 - py * s; apply(); }
    });
    window.addEventListener('resize', fit); fit();
  </script>
</body>
</html>
"""

APP_DIR = Path.home() / ".local/share/goose/apps"


def write_app(svg_path: Path) -> None:
    """Write a goose app embedding the rendered SVG (zoom/pan/search)."""
    import datetime
    import re

    svg = re.sub(r"<\?xml[^>]*>", "", svg_path.read_text())
    stamp = f"Generert {datetime.date.today():%Y-%m-%d} fra mnk/rules.py"
    html = APP_HTML.replace("__SVG__", svg).replace("__STAMP__", stamp)
    out = OUT_DIR / "classify_rules.html"
    out.write_text(html)
    print(f"Wrote {out.relative_to(REPO)}")
    if APP_DIR.is_dir():
        (APP_DIR / "classify-rules.html").write_text(html)
        print(f"Installed goose app -> {APP_DIR / 'classify-rules.html'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--render", action="store_true", help="also render SVG/PNG via mermaid-cli")
    args = ap.parse_args()
    blocks = {key: fn() for key, _, fn in DIAGRAMS}
    OUT_MD.write_text(build_markdown(blocks))
    print(f"Wrote {OUT_MD.relative_to(REPO)}")
    if args.render:
        render(blocks)
        write_app(OUT_DIR / "classify_rules_samlet.svg")


if __name__ == "__main__":
    main()
