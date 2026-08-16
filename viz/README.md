# Benchmark results heatmap

Generates a self-contained HTML results table — methods on rows, metrics on columns,
one circle per cell sized *and* coloured by the normalised score. Modelled on the
[OpenProblems results page](https://openproblems.bio/benchmarks/perturbation_prediction/).

> [!WARNING]
> **The committed `results.html` contains placeholder data.** Every metric and dataset
> score is synthetic, generated from a seeded RNG in `demo_frame()`. It exists to show
> the layout. It is **not** a benchmark result — do not cite, screenshot into a deck, or
> report these numbers. Only the resource figures (time / memory / CPU) are real,
> transcribed from the published OpenProblems table. The page itself carries the same
> warning as a banner.

## Usage

```bash
uv run python make_heatmap.py   # writes results.html
```

Replace `demo_frame()` with your own results and everything else follows. The contract
is a wide DataFrame indexed by method name, one column per metric, plus a `Column` spec:

```python
Column("pearson_delta_control", "Pearson Δctrl", group=PB)
Column("mse", "MSE", group=PB, higher_is_better=False)
Column("time", "Time", group=RES, kind="text", higher_is_better=False, fmt=fmt_duration)
```

`higher_is_better=False` inverts the ramp, so a bigger and more prominent mark always
means better regardless of which way the raw number runs. Three cell kinds: `circle`
(metrics), `bar` (headline score), `text` (resources, value printed on a chip).

## Columns

Follows `src/metrics/metric_suite.yaml` (schema 0.4.0) from
[elmella/task_perturbation_prediction](https://github.com/elmella/task_perturbation_prediction):

| band | metrics | hue |
|---|---|---|
| Overall | aggregate score | blue |
| Datasets | srivatsan_2020 (sci-Plex 3), EmeraldBay, Tahoe | aqua |
| DEG (historical) | 5 row-wise metrics on `clipped_sign_log10_pval` | violet |
| Pseudobulk centroid | 14 `paper_model_metrics` on condition centroids | red |
| Single-cell distributional | 6 scPertEval protocols (MMD / energy / Sinkhorn W₂, k=50) | green |
| Resources | time, memory, CPU | amber |

## Design notes

- **Colour is sequential, one hue per band.** Hue carries group identity; lightness and
  circle area carry magnitude. No single scale spans two hues.
- **Circle area and colour both encode the value.** Size is a non-colour channel, so the
  grid still reads under colour-vision deficiency.
- **Dark mode reverses each ramp** rather than flipping the palette, so "near zero"
  always recedes toward the surface instead of glowing against it.
- **`--` means not run, never zero.** A missing run scored as 0 would silently drag a
  method's aggregate down and make it look bad rather than untested. Six methods show
  `--` across the whole single-cell band: they predict a DE signature, not a cell
  population, so they cannot satisfy that family's input contract at all.
- **`norm_exclude`** keeps an oracle row out of the colour range, so a perfect score
  does not pin the top of every column and flatten the real field.

## Files

| file | what it is |
|---|---|
| `heatmap_render.py` | the rendering engine — `render(df, columns, ...) -> str` |
| `make_heatmap.py` | column layout, demo data, entry point |
| `results.html` | generated output (placeholder data — see warning above) |

## Viewing

Open `results.html` directly. If serving it through JupyterLab, use the `/files/`
endpoint rather than `/lab/tree/` — the Lab HTML viewer sandboxes the page and disables
JavaScript, which kills the tooltips and the Chart/Table toggle.
