"""
benchmark_heatmap — generate a self-contained HTML benchmark heatmap.

Methods on rows, metrics on columns, one circle per cell sized *and* coloured by
the normalised score. Modelled on the OpenProblems results table.

Usage
-----
    from benchmark_heatmap import Column, render

    html = render(df, columns, controls={"zeros", "sample"})
    open("results.html", "w").write(html)

`df` is wide: index = method label, one column per metric/resource id.

Design notes (why it looks like this)
-------------------------------------
* Colour encodes magnitude, so it is **sequential: one hue, light->dark**. Two
  sequential contexts are on screen at once (scores, resources), so they get two
  different hues -- blue and orange -- each as its own one-hue ramp. Never a
  rainbow, never a hue per column.
* Circle **area** is proportional to value, and colour repeats it. That redundancy
  is deliberate: size is a non-colour channel, so the chart still reads under any
  colour-vision deficiency.
* On a dark surface the ramp is reversed, so "near zero" always recedes *toward
  the surface* rather than glowing against it. Dark mode is stepped, not flipped.
"""

from __future__ import annotations

import html as _html
import json
import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import pandas as pd

# --------------------------------------------------------------------------
# Palette. Blue is the documented sequential ramp; orange is the same lightness
# steps rotated to the categorical-orange hue. Both validated for sequential use
# (monotone lightness PASS, single hue PASS -- 4 deg and 1 deg spread).
# --------------------------------------------------------------------------

RAMP_BLUE = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
    "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]
RAMP_ORANGE = [
    "#f9d7cb", "#f2c4b4", "#efb19b", "#e89d83", "#e28969", "#da7550", "#d45e2f",
    "#c54e1c", "#af4517", "#9c390c", "#883008", "#752601", "#611f02",
]

# Low-chroma neutral at the same lightness profile, for de-emphasised rows. Muted
# rows keep the full size encoding -- only the hue is withdrawn, so they stay
# readable while the highlighted rows carry the colour.
RAMP_NEUTRAL = [
    "#e4dedb", "#d4cfcc", "#c5c0bd", "#b6b1ae", "#a7a39f", "#999491", "#8a8683",
    "#7c7875", "#6e6a67", "#615c5a", "#54504d", "#474340", "#3a3734",
]

# One single-hue ramp per column group. Hue carries *group identity*; lightness and
# circle area carry magnitude within the group. That composite is not the "rainbow
# sequential" anti-pattern -- no single scale spans multiple hues. Each is the blue
# ramp's lightness profile rotated to a documented categorical slot's hue, and each
# passes the sequential checks (monotone lightness, single hue).
RAMP_AQUA = [
    "#c9e9d7", "#afddc5", "#93d2b2", "#76c6a0", "#53bb8d", "#27af7b", "#00a368",
    "#00955a", "#00844f", "#007444", "#00653a", "#00562f", "#004726",
]
RAMP_RED = [
    "#fad6d2", "#f4c2be", "#f1aea8", "#ea9a93", "#e4857e", "#dd716a", "#d75853",
    "#c74845", "#b13f3c", "#9e3432", "#892b2a", "#762221", "#621b1a",
]
RAMP_VIOLET = [
    "#dbddfb", "#cbccf6", "#babbf4", "#aaaaee", "#9a99eb", "#8c88e6", "#7d75e3",
    "#6f67d4", "#625bbd", "#564ea9", "#4a4393", "#3e377f", "#322d6a",
]
RAMP_AMBER = [
    "#f0dcc2", "#e7cca7", "#e0bb88", "#d7aa6a", "#cf9846", "#c68715", "#be7400",
    "#af6600", "#9b5a00", "#8a4d00", "#784200", "#673600", "#552c00",
]

RAMP_GREEN = [
    "#d1e7ce", "#bbdab8", "#a5cfa0", "#8ec289", "#76b771", "#5faa5a", "#429e3d",
    "#31902c", "#2a7f26", "#1f701c", "#196116", "#10520e", "#0d440b",
]

RAMPS = {
    "blue": RAMP_BLUE, "orange": RAMP_ORANGE, "aqua": RAMP_AQUA, "red": RAMP_RED,
    "violet": RAMP_VIOLET, "amber": RAMP_AMBER, "green": RAMP_GREEN,
    "neutral": RAMP_NEUTRAL,
}

# Header ink per ramp: the documented categorical slot for that hue, light/dark.
# Validated as a set -- worst adjacent CVD dE 19.2, normal-vision 22.5, all >= 3:1.
BAND_INK = {
    "blue":    ("#2a78d6", "#3987e5"),
    "orange":  ("#eb6834", "#d95926"),
    "aqua":    ("#1baf7a", "#199e70"),
    "red":     ("#e34948", "#e66767"),
    "violet":  ("#4a3aa7", "#9085e9"),
    "amber":   ("#eda100", "#c98500"),
    "green":   ("#008300", "#008300"),   # mode-invariant in the documented palette
    "neutral": ("#52514e", "#c3c2b7"),
}

# Chart chrome, from the design system's light/dark surfaces.
THEME = {
    "light": dict(
        surface="#fcfcfb", plane="#f9f9f7", ink="#0b0b0b", ink2="#52514e",
        muted="#898781", grid="#e1e0d9", rule="#c3c2b7",
        border="rgba(11,11,11,0.10)", empty="#eceae4",
    ),
    "dark": dict(
        surface="#1a1a19", plane="#0d0d0d", ink="#ffffff", ink2="#c3c2b7",
        muted="#898781", grid="#2c2c2a", rule="#383835",
        border="rgba(255,255,255,0.10)", empty="#242422",
    ),
}


@dataclass
class Column:
    """One column of the heatmap.

    id                the column name in the DataFrame
    label             header text
    group             header band this column sits under
    higher_is_better  direction for normalisation; False inverts (time, memory)
    kind              "circle" (metrics) | "bar" (headline score) | "text" (resources)
    fmt               callable turning the raw value into display text
    """

    id: str
    label: str
    group: str = "Metrics"
    higher_is_better: bool = True
    kind: str = "circle"
    fmt: Callable[[float], str] | None = None

    def render_value(self, v) -> str:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "--"
        if self.fmt:
            return self.fmt(v)
        return f"{v:.3f}" if isinstance(v, float) else str(v)


@dataclass
class Group:
    """A header band spanning several columns."""

    name: str
    ramp: str = "blue"
    note: str = ""


# --------------------------------------------------------------------------
# Formatters for the common resource columns
# --------------------------------------------------------------------------

def fmt_duration(seconds: float) -> str:
    s = float(seconds)
    if s < 90:
        return f"{s:.0f}s"
    if s < 5400:
        return f"{s / 60:.0f}m"
    return f"{s / 3600:.1f}h"


def fmt_bytes(mb: float) -> str:
    mb = float(mb)
    return f"{mb / 1024:.1f}G" if mb >= 1024 else f"{mb:.0f}M"


def fmt_pct(x: float) -> str:
    return f"{float(x):.0f}%"


# --------------------------------------------------------------------------
# Colour helpers
# --------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _relative_luminance(h: str) -> float:
    def chan(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in _hex_to_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# De-emphasised rows are squeezed into the middle of the neutral ramp. Using its
# full range would put a high-scoring muted method at the ramp's darkest step --
# which on a light surface is *more* prominent than a mid-scoring highlighted one,
# inverting the emphasis. The mid band stays quiet against either surface.
_NEUTRAL_SPAN = (0.15, 0.62)


def ramp_color(v: float, ramp: str, mode: str) -> str:
    """Map a normalised 0-1 value onto a ramp step.

    On the dark surface the ramp runs dark->light so that near-zero recedes
    toward the surface instead of glowing against it.
    """
    steps = RAMPS[ramp]
    if mode == "dark":
        steps = list(reversed(steps))
    v = min(1.0, max(0.0, float(v)))
    if ramp == "neutral":
        lo, hi = _NEUTRAL_SPAN
        v = lo + v * (hi - lo)
    return steps[round(v * (len(steps) - 1))]


def ink_on(bg: str) -> str:
    """Pick readable text ink for a filled cell (contrast, not vibes)."""
    return "#0b0b0b" if _relative_luminance(bg) > 0.42 else "#ffffff"


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

def normalise(
    series: pd.Series,
    higher_is_better: bool = True,
    exclude: Iterable[str] = (),
) -> pd.Series:
    """Min-max a column to 0-1, flipping when lower is better.

    `exclude` drops rows from the *range calculation* while still scoring them.
    This matters: a perfect-score oracle row (ground truth) otherwise pins the top
    of every column and squeezes every real method into the middle of the ramp,
    where they become visually indistinguishable. Excluded rows are still drawn --
    they just clamp to the ends of the scale.

    Constant columns collapse to 0.5 rather than dividing by zero: a flat column
    carries no ranking information and should read as uniformly mid.
    """
    s = pd.to_numeric(series, errors="coerce")
    basis = s.drop(labels=[e for e in exclude if e in s.index], errors="ignore")
    lo, hi = basis.min(), basis.max()
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        return pd.Series(0.5, index=s.index).where(s.notna())
    out = ((s - lo) / (hi - lo)).clip(0.0, 1.0)
    return out if higher_is_better else 1.0 - out


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

_CIRCLE_MIN, _CIRCLE_MAX = 5.0, 30.0


def _circle_px(v: float) -> float:
    """Area-proportional diameter: d grows with sqrt(v), so area tracks value."""
    return _CIRCLE_MIN + (_CIRCLE_MAX - _CIRCLE_MIN) * math.sqrt(max(0.0, min(1.0, v)))


def _esc(s) -> str:
    return _html.escape(str(s), quote=True)


def render(
    df: pd.DataFrame,
    columns: Sequence[Column],
    groups: Sequence[Group] | None = None,
    controls: Iterable[str] = (),
    title: str = "Benchmark results",
    subtitle: str = "",
    sort_by: str | None = None,
    norm_exclude: Iterable[str] = (),
    highlight: Iterable[str] = (),
    notice: str = "",
) -> str:
    """Build a self-contained HTML page. Returns the markup as a string.

    `norm_exclude` names rows kept out of the colour-scale range -- pass your
    oracle/ground-truth row here so it does not flatten the rest of the field.

    `highlight` names the methods the chart is *about*. When it is non-empty every
    other row drops to the neutral ramp: the emphasis pattern, not a second
    categorical scale. Muted rows keep their size encoding, so the comparison is
    still legible -- they simply stop competing for attention.
    """
    controls = set(controls)
    norm_exclude = list(norm_exclude)
    highlight = set(highlight)
    groups = list(groups) if groups else _infer_groups(columns)
    group_ramp = {g.name: g.ramp for g in groups}

    if sort_by and sort_by in df.columns:
        col = next((c for c in columns if c.id == sort_by), None)
        df = df.sort_values(sort_by, ascending=not (col.higher_is_better if col else True))

    # Normalise every column once, up front.
    norm = pd.DataFrame(index=df.index)
    for c in columns:
        if c.id in df.columns:
            norm[c.id] = normalise(df[c.id], c.higher_is_better, exclude=norm_exclude)

    payload = {
        "methods": [str(m) for m in df.index],
        "columns": [
            {"id": c.id, "label": c.label, "group": c.group, "kind": c.kind,
             "hib": c.higher_is_better}
            for c in columns
        ],
        "raw": {
            c.id: [c.render_value(df[c.id].iloc[i]) if c.id in df.columns else "--"
                   for i in range(len(df))]
            for c in columns
        },
        "norm": {
            c.id: [None if pd.isna(v) else round(float(v), 4)
                   for v in (norm[c.id] if c.id in norm.columns else [None] * len(df))]
            for c in columns
        },
    }

    body_rows = []
    for i, method in enumerate(df.index):
        is_ctrl = str(method) in controls
        muted = bool(highlight) and str(method) not in highlight
        cells = []
        for c in columns:
            v = norm[c.id].iloc[i] if c.id in norm.columns else float("nan")
            txt = c.render_value(df[c.id].iloc[i]) if c.id in df.columns else "--"
            ramp = "neutral" if muted else group_ramp.get(c.group, "blue")
            cells.append(_cell(c, v, txt, ramp, method, muted))
        cls = "fh-row"
        if is_ctrl:
            cls += " fh-ctrl"
        cls += " fh-muted" if muted else (" fh-hi" if highlight else "")
        badge = '<span class="fh-badge">ctrl</span>' if is_ctrl else ""
        body_rows.append(
            f'<tr class="{cls}"><th scope="row" class="fh-method">'
            f'<span class="fh-name">{_esc(method)}</span>{badge}</th>{"".join(cells)}</tr>'
        )

    # Header: a group band row, then the rotated per-column labels.
    band_cells, label_cells = [], []
    for g in groups:
        n = sum(1 for c in columns if c.group == g.name)
        if not n:
            continue
        band_cells.append(
            f'<th colspan="{n}" class="fh-band" data-ramp="{g.ramp}">'
            f'<span>{_esc(g.name)}</span></th>'
        )
    for c in columns:
        ramp = group_ramp.get(c.group, "blue")
        flat = " fh-flat" if c.kind == "bar" else ""
        label_cells.append(
            f'<th class="fh-collabel{flat}" data-ramp="{ramp}" scope="col">'
            f'<div class="fh-rot"><span>{_esc(c.label)}</span></div></th>'
        )

    plain_rows = []
    for i, method in enumerate(df.index):
        tds = "".join(
            f"<td>{_esc(c.render_value(df[c.id].iloc[i]) if c.id in df.columns else '--')}</td>"
            for c in columns
        )
        plain_rows.append(f"<tr><th scope='row'>{_esc(method)}</th>{tds}</tr>")
    plain_head = "".join(f"<th scope='col'>{_esc(c.label)}</th>" for c in columns)

    notice_html = (
        f'<div class="fh-notice" role="note">{_esc(notice)}</div>' if notice else ""
    )
    return _TEMPLATE.format(
        title=_esc(title),
        subtitle=_esc(subtitle),
        notice=notice_html,
        css=_css(),
        band_row="".join(band_cells),
        label_row="".join(label_cells),
        body="".join(body_rows),
        plain_head=plain_head,
        plain_body="".join(plain_rows),
        ncols=len(columns),
        payload=json.dumps(payload),
        legend=_legend(groups),
    )


def _cell(c: Column, v: float, txt: str, ramp: str, method, muted: bool = False) -> str:
    tip = f'data-m="{_esc(method)}" data-c="{_esc(c.label)}" data-v="{_esc(txt)}"'
    if pd.isna(v):
        return f'<td class="fh-cell" {tip}><span class="fh-na">--</span></td>'

    pct = round(float(v) * 100)
    if c.kind == "bar":
        fill = "fh-fill fh-fill-mute" if muted else "fh-fill"
        return (
            f'<td class="fh-cell fh-cell-bar" {tip} data-pct="{pct}">'
            f'<div class="fh-track"><div class="{fill}" style="width:{max(2.0, v * 100):.1f}%"></div></div>'
            f"</td>"
        )
    if c.kind == "text":
        lo = ramp_color(v, ramp, "light")
        dk = ramp_color(v, ramp, "dark")
        return (
            f'<td class="fh-cell fh-cell-text" {tip} data-pct="{pct}">'
            f'<span class="fh-chip" style="--bg-l:{lo};--fg-l:{ink_on(lo)};'
            f'--bg-d:{dk};--fg-d:{ink_on(dk)}">{_esc(txt)}</span></td>'
        )

    d = _circle_px(float(v))
    lo = ramp_color(v, ramp, "light")
    dk = ramp_color(v, ramp, "dark")
    return (
        f'<td class="fh-cell fh-cell-dot" {tip} data-pct="{pct}">'
        f'<span class="fh-dot" style="width:{d:.1f}px;height:{d:.1f}px;'
        f'--bg-l:{lo};--bg-d:{dk}"></span></td>'
    )


def _infer_groups(columns: Sequence[Column]) -> list[Group]:
    seen, out = [], []
    for c in columns:
        if c.group not in seen:
            seen.append(c.group)
    # First sequential context gets blue; the second gets orange; beyond that we
    # reuse rather than invent hues -- a third generated ramp would not validate.
    for i, name in enumerate(seen):
        out.append(Group(name, ramp="blue" if i % 2 == 0 else "orange"))
    return out


def _legend(groups: Sequence[Group]) -> str:
    out = []
    for g in groups:
        swatches = "".join(
            f'<i style="--bg-l:{ramp_color(k / 8, g.ramp, "light")};'
            f'--bg-d:{ramp_color(k / 8, g.ramp, "dark")}"></i>'
            for k in range(9)
        )
        out.append(
            f'<div class="fh-key"><span class="fh-key-name">{_esc(g.name)}</span>'
            f'<span class="fh-scale">{swatches}</span>'
            f'<span class="fh-key-ends"><em>worst</em><em>best</em></span></div>'
        )
    return "".join(out)


def _css() -> str:
    """Theme tokens.

    Per-cell colours are resolved *on the cell*, not on the root: custom properties
    inherit downward only, so a root-level `--dot-bg: var(--bg-l)` cannot see a
    `--bg-l` declared on a descendant. Each themed element therefore reads its own
    `--bg-l` / `--bg-d` pair directly.
    """
    L, D = THEME["light"], THEME["dark"]

    def block(t, indent="  "):
        return "\n".join(f"{indent}--{k}: {v};" for k, v in t.items())

    def swaps(prefix: str, m: str, accent: str) -> str:
        # Every rule carries the scope prefix itself -- a prefix written once
        # ahead of a block would only bind to the first selector.
        neutral = RAMP_NEUTRAL[6 if m == "l" else 5]
        idx = 0 if m == "l" else 1
        rules = [
            (".fh-dot", f"background: var(--bg-{m});"),
            (".fh-chip", f"background: var(--bg-{m}); color: var(--fg-{m});"),
            (".fh-scale i", f"background: var(--bg-{m});"),
            (".fh-fill", f"background: {accent};"),
            (".fh-fill-mute", f"background: {neutral};"),
        ]
        # Header ink, one rule per ramp, so each band names its own group.
        for ramp, pair in BAND_INK.items():
            rules.append((f'.fh-band[data-ramp="{ramp}"]', f"color: {pair[idx]};"))
            rules.append(
                (f'.fh-collabel[data-ramp="{ramp}"] .fh-rot span', f"color: {pair[idx]};")
            )
        return "\n".join(f"{prefix}{sel} {{ {decl} }}" for sel, decl in rules)

    return f"""
.fh-root {{
  color-scheme: light;
{block(L)}
}}
{swaps("", "l", "#2a78d6")}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) .fh-root {{
    color-scheme: dark;
{block(D, "    ")}
  }}
{swaps(':root:where(:not([data-theme="light"])) ', "d", "#3987e5")}
}}
:root[data-theme="dark"] .fh-root {{
  color-scheme: dark;
{block(D)}
}}
{swaps(':root[data-theme="dark"] ', "d", "#3987e5")}
"""


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; }}
{css}
.fh-root {{
  background: var(--plane);
  color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  padding: 28px clamp(14px, 4vw, 44px) 56px;
  min-height: 100vh;
}}
.fh-head {{ max-width: 74ch; margin-bottom: 22px; }}
.fh-head h1 {{ font-size: 21px; font-weight: 600; margin: 0 0 6px; letter-spacing: -0.01em; }}
.fh-head p {{ margin: 0; color: var(--ink2); font-size: 13.5px; }}
/* Provenance banner. Status colours are reserved for state, and "these numbers are
   not measurements" is exactly that -- shipped with a label, never colour alone. */
.fh-notice {{
  margin: 10px 0 12px; padding: 9px 13px; border-radius: 8px;
  border: 1px solid #fab219; border-left: 4px solid #fab219;
  background: rgba(250, 178, 25, 0.10);
  color: var(--ink); font-size: 13px; font-weight: 550; max-width: 78ch;
}}

.fh-bar {{
  display: flex; flex-wrap: wrap; gap: 16px 26px;
  align-items: center; margin-bottom: 16px;
}}
.fh-toggle {{ display: flex; gap: 2px; background: var(--grid); padding: 2px; border-radius: 8px; }}
.fh-toggle button {{
  font: inherit; font-size: 12.5px; border: 0; background: none; color: var(--ink2);
  padding: 5px 12px; border-radius: 6px; cursor: pointer;
}}
.fh-toggle button[aria-pressed="true"] {{ background: var(--surface); color: var(--ink); font-weight: 550; }}

.fh-key {{ display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: var(--muted); }}
.fh-key-name {{ font-weight: 550; color: var(--ink2); }}
.fh-scale {{ display: flex; border-radius: 3px; overflow: hidden; }}
.fh-scale i {{ width: 15px; height: 10px; }}
.fh-key-ends {{ display: flex; gap: 8px; }}
.fh-key-ends em {{ font-style: normal; }}

.fh-scroll {{
  overflow-x: auto; overflow-y: visible;
  background: var(--surface);
  border: 1px solid var(--border); border-radius: 12px;
  padding: 0 4px 4px;
}}
table.fh {{ border-collapse: separate; border-spacing: 0; }}

.fh-band {{
  font-size: 11px; font-weight: 600; letter-spacing: 0.09em; text-transform: uppercase;
  text-align: left; padding: 16px 0 7px; color: var(--ink2);
}}
/* A gap in the surface separates adjacent bands -- without it two bands sharing
   a hue read as one continuous group. */
.fh-band span {{
  display: block; padding-bottom: 6px;
  border-bottom: 2px solid currentColor; margin-right: 14px;
}}
/* Per-ramp header ink is generated in the theme block above -- nothing here may
   re-declare `color` for a band at equal-or-higher specificity. */

.fh-collabel {{ height: 206px; vertical-align: bottom; padding: 0; font-weight: 500; }}
.fh-rot {{ width: 44px; height: 202px; position: relative; }}
.fh-rot span {{
  position: absolute; bottom: 8px; left: 52%;
  transform-origin: left bottom; transform: rotate(-58deg);
  white-space: nowrap; font-size: 12px; color: var(--ink2);
}}
/* The bar column is wide; its label reads straight rather than on the diagonal. */
.fh-collabel.fh-flat .fh-rot {{ width: auto; }}
.fh-collabel.fh-flat .fh-rot span {{
  transform: none; left: 4px; bottom: 8px; transform-origin: left bottom;
}}

th.fh-method {{
  position: sticky; left: 0; z-index: 2;
  background: var(--surface);
  text-align: left; font-weight: 500; white-space: nowrap;
  padding: 0 20px 0 12px; min-width: 210px;
  border-right: 1px solid var(--grid);
}}
.fh-row:hover th.fh-method, .fh-row:hover td {{ background: var(--grid); }}
.fh-ctrl th.fh-method .fh-name {{ font-style: italic; color: var(--ink2); }}
/* Emphasis: the highlighted rows get the ink and the weight; the rest recede.
   Identity is never colour-alone -- weight and a leading rule carry it too. */
.fh-hi th.fh-method .fh-name {{ font-weight: 650; }}
.fh-hi th.fh-method {{ box-shadow: inset 3px 0 0 currentColor; color: #2a78d6; }}
.fh-hi th.fh-method .fh-name {{ color: var(--ink); }}
.fh-muted th.fh-method .fh-name {{ color: var(--ink2); }}
.fh-badge {{
  margin-left: 8px; font-size: 10px; letter-spacing: 0.05em; color: var(--muted);
  border: 1px dashed var(--rule); border-radius: 999px; padding: 1px 7px;
  vertical-align: middle;
}}

td.fh-cell {{ height: 40px; text-align: center; padding: 0 3px; }}
td.fh-cell-dot {{ min-width: 44px; }}
td.fh-cell-text {{ min-width: 58px; }}
/* Geometry only -- the themed `background` lives in the theme block above, so
   nothing here may re-declare it at equal specificity. */
.fh-dot {{
  display: inline-block; border-radius: 50%;
  box-shadow: 0 0 0 2px var(--surface);   /* surface ring, not a border */
  vertical-align: middle;
}}
.fh-na {{ color: var(--muted); font-size: 12px; }}

td.fh-cell-bar {{ min-width: 190px; padding: 0 14px 0 4px; }}
.fh-track {{ height: 9px; border-radius: 999px; background: var(--grid); overflow: hidden; }}
.fh-fill {{ height: 100%; border-radius: 0 4px 4px 0; }}   /* 4px rounded data-end */

.fh-chip {{
  display: inline-block; min-width: 46px; padding: 5px 8px; border-radius: 6px;
  font-size: 11.5px; font-variant-numeric: tabular-nums; font-weight: 550;
}}

.fh-sr {{
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip-path: inset(50%); white-space: nowrap;
}}
.fh-plain {{ display: none; margin-top: 8px; font-size: 13px; }}
.fh-plain table {{ border-collapse: collapse; width: 100%; }}
.fh-plain th, .fh-plain td {{
  border-bottom: 1px solid var(--grid); padding: 7px 12px; text-align: right;
  font-variant-numeric: tabular-nums;
}}
.fh-plain th[scope="row"] {{ text-align: left; font-weight: 500; white-space: nowrap; }}
.fh-plain thead th {{ color: var(--ink2); font-weight: 550; }}
.fh-root[data-view="table"] .fh-scroll {{ display: none; }}
.fh-root[data-view="table"] .fh-plain {{ display: block; }}

.fh-tip {{
  position: fixed; z-index: 40; pointer-events: none; opacity: 0;
  transition: opacity .1s; background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 11px; font-size: 12.5px; max-width: 280px;
  box-shadow: 0 6px 24px rgba(0,0,0,.22);
}}
.fh-tip b {{ display: block; font-weight: 600; margin-bottom: 2px; }}
.fh-tip .fh-tip-c {{ color: var(--ink2); }}
.fh-tip .fh-tip-v {{ font-variant-numeric: tabular-nums; font-weight: 600; }}

@media (prefers-reduced-motion: reduce) {{ .fh-tip {{ transition: none; }} }}
</style>
</head>
<body>

<div class="fh-root" data-view="chart">
  <div class="fh-head">
    <h1>{title}</h1>
    {notice}
    <p>{subtitle}</p>
  </div>

  <div class="fh-bar">
    <div class="fh-toggle" role="group" aria-label="View">
      <button type="button" data-view="chart" aria-pressed="true">Chart</button>
      <button type="button" data-view="table" aria-pressed="false">Table</button>
    </div>
    {legend}
  </div>

  <div class="fh-scroll">
    <table class="fh">
      <thead>
        <tr><td></td>{band_row}</tr>
        <tr><td></td>{label_row}</tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
  </div>

  <div class="fh-plain">
    <table>
      <caption class="fh-sr">Benchmark results as a data table</caption>
      <thead><tr><th scope="col">Method</th>{plain_head}</tr></thead>
      <tbody>{plain_body}</tbody>
    </table>
  </div>

  <div class="fh-tip" role="status" aria-live="polite"></div>
</div>

<script>
(function () {{
  const root = document.querySelector('.fh-root');
  const tip  = root.querySelector('.fh-tip');

  root.querySelectorAll('.fh-toggle button').forEach(function (b) {{
    b.addEventListener('click', function () {{
      root.dataset.view = b.dataset.view;
      root.querySelectorAll('.fh-toggle button').forEach(function (o) {{
        o.setAttribute('aria-pressed', String(o === b));
      }});
    }});
  }});

  // The whole cell is the hit target -- a 5px dot is far too small to hover.
  root.querySelectorAll('td.fh-cell').forEach(function (cell) {{
    cell.addEventListener('pointerenter', function () {{
      const pct = cell.dataset.pct;
      tip.innerHTML =
        '<b>' + cell.dataset.m + '</b>' +
        '<span class="fh-tip-c">' + cell.dataset.c + '</span><br>' +
        '<span class="fh-tip-v">' + cell.dataset.v + '</span>' +
        (pct === undefined ? '' :
          ' <span class="fh-tip-c">&middot; ' + pct + '% of range</span>');
      tip.style.opacity = 1;
    }});
    cell.addEventListener('pointermove', function (e) {{
      const pad = 14;
      let x = e.clientX + pad, y = e.clientY + pad;
      const r = tip.getBoundingClientRect();
      if (x + r.width  > innerWidth)  x = e.clientX - r.width  - pad;
      if (y + r.height > innerHeight) y = e.clientY - r.height - pad;
      tip.style.left = x + 'px';
      tip.style.top  = y + 'px';
    }});
    cell.addEventListener('pointerleave', function () {{ tip.style.opacity = 0; }});
  }});

  window.BENCHMARK_HEATMAP = {payload};
}})();
</script>
</body>
</html>
"""
