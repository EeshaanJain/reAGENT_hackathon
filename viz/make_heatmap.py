"""
Build the benchmark heatmap HTML.

    cd ~/h5ad-lab && uv run python viz/make_heatmap.py

Columns follow src/metrics/metric_suite.yaml from
https://github.com/elmella/task_perturbation_prediction --
5 active historical DEG metrics + 14 pseudobulk centroid metrics.

Swap `demo_frame()` for your own results; nothing else changes.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from heatmap_render import Column, Group, fmt_bytes, fmt_duration, fmt_pct, render

OUT = Path(__file__).parent / "results.html"

# --------------------------------------------------------------------------
# Columns, transcribed from metric_suite.yaml.
#
# `direction: minimize` in the yaml becomes higher_is_better=False here, which
# inverts the ramp so a bigger, more prominent mark always means better --
# no mental flipping between an RMSE column and a Pearson column.
# --------------------------------------------------------------------------

DS = "Datasets"
DEG = "DEG (historical)"
PB = "Pseudobulk centroid"
SC = "Single-cell distributional"
RES = "Resources"

# Per-dataset aggregate score, one column each. A method that has not been run on
# a dataset is left NaN and renders as "--" rather than as a zero -- absent is not
# the same as bad, and a zero here would drag its overall score down silently.
DATASETS = [
    ("ds_srivatsan",  "srivatsan_2020 (sci-Plex 3)"),
    ("ds_emeraldbay", "EmeraldBay"),
    ("ds_tahoe",      "Tahoe"),
]

COLUMNS = [
    Column("score", "Overall score", group="Overall", kind="bar", fmt=lambda v: f"{v:.3f}"),

    *[Column(cid, label, group=DS) for cid, label in DATASETS],

    # active_historical_metrics -- target: clipped_sign_log10_pval, unit: condition
    Column("mean_rowwise_rmse",     "RMSE",     group=DEG, higher_is_better=False),
    Column("mean_rowwise_mae",      "MAE",      group=DEG, higher_is_better=False),
    Column("mean_rowwise_pearson",  "Pearson",  group=DEG),
    Column("mean_rowwise_spearman", "Spearman", group=DEG),
    Column("mean_rowwise_cosine",   "Cosine",   group=DEG),

    # paper_model_metrics -- log-normalised condition centroids
    Column("mse",                             "MSE",                      group=PB, higher_is_better=False),
    Column("weighted_mse",                    "Weighted MSE",             group=PB, higher_is_better=False),
    Column("pearson_delta_control",           "Pearson Δctrl",            group=PB),
    Column("pearson_delta_control_degs",      "Pearson Δctrl · DEG",      group=PB),
    Column("pearson_delta_perturbed_mean",    "Pearson Δpert-mean",       group=PB),
    Column("pearson_delta_perturbed_mean_degs", "Pearson Δpert-mean · DEG", group=PB),
    Column("r2_delta_control",                "R² Δctrl",                 group=PB),
    Column("r2_delta_control_degs",           "R² Δctrl · DEG",           group=PB),
    Column("r2_delta_perturbed_mean",         "R² Δpert-mean",            group=PB),
    Column("r2_delta_perturbed_mean_degs",    "R² Δpert-mean · DEG",      group=PB),
    Column("weighted_r2_delta_control",       "Weighted R² Δctrl",        group=PB),
    Column("weighted_r2_delta_perturbed_mean", "Weighted R² Δpert-mean",  group=PB),
    Column("normalized_inverse_rank",         "Normalized inverse rank",  group=PB),
    Column("centroid_accuracy",               "Centroid accuracy †",      group=PB),

    # single_cell_model_metrics -- scPertEval distributional protocols, k=50.
    # All minimise toward a perfect value of 0. "top_k" scores in the top-50 genes
    # by absolute ground-truth effect size; "pca_k" in 50 evaluator-fit PCs.
    Column("unbiased_mmd_median_top_k", "MMD (top-50 genes)",     group=SC, higher_is_better=False),
    Column("unbiased_mmd_median_pca_k", "MMD (50 PCs)",           group=SC, higher_is_better=False),
    Column("energy_distance_top_k",     "Energy dist (top-50)",   group=SC, higher_is_better=False),
    Column("energy_distance_pca_k",     "Energy dist (50 PCs)",   group=SC, higher_is_better=False),
    Column("sinkhorn_w2_top_k",         "Sinkhorn W₂ (top-50)",   group=SC, higher_is_better=False),
    Column("sinkhorn_w2_pca_k",         "Sinkhorn W₂ (50 PCs)",   group=SC, higher_is_better=False),

    Column("time",   "Time",   group=RES, kind="text", higher_is_better=False, fmt=fmt_duration),
    Column("memory", "Memory", group=RES, kind="text", higher_is_better=False, fmt=fmt_bytes),
    Column("cpu",    "CPU",    group=RES, kind="text", higher_is_better=False, fmt=fmt_pct),
]

# Two sequential contexts, two hues. Both metric families read blue because they
# are the same kind of thing (a score); the header bands carry the distinction.
# Resources are a different quantity entirely, so they take the second hue.
# One hue per band, as on the OpenProblems results page. Hue says which group a
# column belongs to; lightness and circle area say how good the score is. Each band
# is still a single-hue sequential ramp -- no scale spans two hues.
GROUPS = [
    Group("Overall", ramp="blue"),
    Group(DS,        ramp="aqua"),
    Group(DEG,       ramp="violet"),
    Group(PB,        ramp="red"),
    Group(SC,        ramp="green"),
    Group(RES,       ramp="amber"),
]

CONTROLS = {
    "Ground truth", "Mean per cell type and gene", "Mean per compound and gene",
    "Mean per gene", "Zeros", "Sample",
}

# Only these two carry colour; every other row drops to the neutral ramp. Muted rows
# keep their circle sizes, so the field is still comparable -- it just stops competing.
HIGHLIGHT = {"ScAPE", "CPA (Compositional Perturbation Autoencoder)"}

MINIMIZE = {"mean_rowwise_rmse", "mean_rowwise_mae", "mse", "weighted_mse"}

# Realistic value range per metric: (worst, best) on that metric's own scale.
# These are the scales the metrics actually live on -- R² goes negative for weak
# predictions, retrieval metrics sit at 0.5 for chance, MSE is small and positive.
# Without this every column was 0-1 and every circle landed on the same ramp step.
SCALE = {
    "mean_rowwise_rmse":                 (1.15, 0.35),
    "mean_rowwise_mae":                  (0.92, 0.26),
    "mean_rowwise_pearson":              (0.02, 0.72),
    "mean_rowwise_spearman":             (0.01, 0.65),
    "mean_rowwise_cosine":               (0.05, 0.78),
    "mse":                               (0.48, 0.04),
    "weighted_mse":                      (0.62, 0.06),
    "pearson_delta_control":             (0.05, 0.88),
    "pearson_delta_control_degs":        (0.03, 0.81),
    "pearson_delta_perturbed_mean":      (-0.02, 0.54),
    "pearson_delta_perturbed_mean_degs": (-0.04, 0.47),
    "r2_delta_control":                  (-0.35, 0.74),
    "r2_delta_control_degs":             (-0.42, 0.66),
    "r2_delta_perturbed_mean":           (-0.88, 0.29),
    "r2_delta_perturbed_mean_degs":      (-1.05, 0.22),
    "weighted_r2_delta_control":         (-0.28, 0.70),
    "weighted_r2_delta_perturbed_mean":  (-0.75, 0.31),
    "normalized_inverse_rank":           (0.50, 0.94),   # 0.5 = chance
    "centroid_accuracy":                 (0.50, 0.94),
    # Distributional distances: minimise toward a perfect value of 0. The yaml's
    # finite_sample_note says the unbiased MMD and energy estimators can go negative
    # at finite sample size and raw values are never clamped -- so the best ends here
    # dip just below zero rather than stopping at it.
    "unbiased_mmd_median_top_k":         (0.42, -0.004),
    "unbiased_mmd_median_pca_k":         (0.38, -0.006),
    "energy_distance_top_k":             (1.90, -0.010),
    "energy_distance_pca_k":             (2.40, -0.015),
    "sinkhorn_w2_top_k":                 (3.10, 0.180),  # a true distance: never < 0
    "sinkhorn_w2_pca_k":                 (4.20, 0.250),
}

# Control-referenced metrics flatter a baseline that just predicts the control mean;
# perturbed-mean-referenced metrics are the ones that separate real models from it.
# Giving baselines a bonus on the first and a penalty on the second is the single
# thing that makes this table look like a benchmark rather than a gradient.
CTRL_REFERENCED = {
    "pearson_delta_control", "pearson_delta_control_degs",
    "r2_delta_control", "r2_delta_control_degs", "weighted_r2_delta_control",
}
PERT_REFERENCED = {
    "pearson_delta_perturbed_mean", "pearson_delta_perturbed_mean_degs",
    "r2_delta_perturbed_mean", "r2_delta_perturbed_mean_degs",
    "weighted_r2_delta_perturbed_mean",
}
RETRIEVAL = {"normalized_inverse_rank", "centroid_accuracy"}
DISTRIBUTIONAL = {
    "unbiased_mmd_median_top_k", "unbiased_mmd_median_pca_k",
    "energy_distance_top_k", "energy_distance_pca_k",
    "sinkhorn_w2_top_k", "sinkhorn_w2_pca_k",
}

# The single_cell input contract needs "predicted normalized cells by genes". The
# Kaggle-lineage methods regress a DE signature vector per condition and cannot emit
# a cell population at all, so they are unscorable on this family -- NaN, not zero.
# Generative models (CPA) can; so can the mean baselines, by repeating their centroid,
# which is exactly why they score badly: a point mass has no spread to match.
CAN_EMIT_CELLS = {
    "Ground truth",
    "CPA (Compositional Perturbation Autoencoder)",
    "Mean per cell type and gene", "Mean per compound and gene", "Mean per gene",
    "Zeros", "Sample",
}

# Per-method strength by metric family. No method leads everything -- a top overall
# score comes from winning some families and conceding others, which is the whole
# reason the suite carries four of them. The two headline methods get profiles that
# reflect what they are: ScAPE regresses DE signatures, so it leads the row-wise DEG
# metrics and trails on centroid retrieval; CPA models perturbation composition, so
# it leads the harder perturbed-mean-referenced and retrieval metrics and gives up
# ground on the raw DEG row metrics.
PROFILE = {
    "ScAPE":                                       {"deg": +0.20, "ctrl": +0.10, "pert": -0.24, "retr": -0.18, "dist": 0.0},
    "CPA (Compositional Perturbation Autoencoder)": {"deg": -0.14, "ctrl": -0.02, "pert": +0.26, "retr": +0.21, "dist": +0.24},
    "NN retraining with pseudolabels":              {"deg": +0.14, "ctrl": +0.05, "pert": -0.16, "retr": -0.11, "dist": 0.0},
    "Py-boost":                                     {"deg": +0.09, "ctrl": +0.12, "pert": -0.10, "retr": -0.07, "dist": 0.0},
    "LSTM-GRU-CNN Ensemble":                        {"deg": +0.12, "ctrl": -0.04, "pert": -0.06, "retr": +0.08, "dist": 0.0},
    "JN-AP-OP2":                                    {"deg": -0.06, "ctrl": +0.09, "pert": +0.04, "retr": -0.09, "dist": 0.0},
    "Transformer Ensemble":                         {"deg": -0.11, "ctrl": +0.03, "pert": +0.10, "retr": +0.05, "dist": 0.0},
}


def demo_frame() -> pd.DataFrame:
    """PLACEHOLDER data with the real column structure.

    Values are generated from a seeded RNG driven by a per-method skill parameter,
    deliberately rather than hand-written, so nobody mistakes them for measurements.
    Resource figures are transcribed from the published OpenProblems table.
    Replace this whole function with your own scores.
    """
    # Sorted by score, so ScAPE and CPA lead the field ahead of the Kaggle methods.
    methods = [
        # name,                                     skill, time_s, mem_mb, cpu
        ("Ground truth",                             1.00,      9,   3584,  207),
        ("ScAPE",                                    0.83,   8280,  45261,  737),
        ("CPA (Compositional Perturbation Autoencoder)", 0.79, 4820,  38200,  610),
        ("NN retraining with pseudolabels",          0.74,   2520,  53965, 1294),
        ("Py-boost",                                 0.68,    180,  22733,  154),
        ("LSTM-GRU-CNN Ensemble",                    0.67,   6120,  51507,  135),
        ("JN-AP-OP2",                                0.61,   3060,  16486,  100),
        ("Mean per cell type and gene",              0.60,      3,   5837,  472),
        ("Mean per compound and gene",               0.59,      6,   6042,  213),
        ("Transformer Ensemble",                     0.58,   3960,  19354,  216),
        ("Mean per gene",                            0.57,      5,   5734,  266),
        ("Zeros",                                    0.32,      6,   5939,  235),
        ("Sample",                                   0.10,      9,   3686,  217),
    ]
    metric_ids = [c.id for c in COLUMNS if c.group in (DEG, PB, SC)]
    rng = np.random.default_rng(20260815)

    # Datasets get their own difficulty offset: sci-Plex 3 is a complete design and
    # the easiest of the three; Tahoe is the largest and hardest. Methods hardcoded
    # to the NeurIPS PBMC design have not been run on Tahoe at all.
    ds_offset = {"ds_srivatsan": 0.04, "ds_emeraldbay": -0.01, "ds_tahoe": -0.07}
    no_tahoe = {"LSTM-GRU-CNN Ensemble", "Transformer Ensemble",
                "NN retraining with pseudolabels", "JN-AP-OP2"}

    baselines = {"Mean per cell type and gene", "Mean per compound and gene",
                 "Mean per gene", "Zeros", "Sample"}

    rows = {}
    for name, skill, t, mem, cpu in methods:
        rec = {"score": skill, "time": t, "memory": mem, "cpu": cpu}
        oracle = name == "Ground truth"
        is_base = name in baselines
        # A per-method affinity per metric family: real benchmarks have methods that
        # lead one family and trail another, which is what gives the grid its texture.
        # Named methods use their declared profile; the rest draw one.
        aff = PROFILE.get(
            name, {f: rng.normal(0, 0.16) for f in ("deg", "ctrl", "pert", "retr", "dist")}
        )

        for did, off in ds_offset.items():
            if did == "ds_tahoe" and name in no_tahoe:
                rec[did] = np.nan          # not run -- rendered as "--", not zero
            else:
                rec[did] = round(float(np.clip(skill + off + rng.normal(0, 0.02), 0, 1)), 4)

        for mid in metric_ids:
            if mid in DISTRIBUTIONAL and name not in CAN_EMIT_CELLS:
                rec[mid] = np.nan      # cannot satisfy the single_cell input contract
                continue
            if mid in CTRL_REFERENCED:
                fam, bonus = "ctrl", 0.26 if is_base else 0.0
            elif mid in PERT_REFERENCED:
                fam, bonus = "pert", -0.34 if is_base else 0.0
            elif mid in RETRIEVAL:
                fam, bonus = "retr", -0.30 if is_base else 0.0
            elif mid in DISTRIBUTIONAL:
                # A point-mass prediction has no spread, so every distributional
                # distance against the real cell cloud stays large.
                fam, bonus = "dist", -0.45 if is_base else 0.0
            else:
                fam, bonus = "deg", 0.0

            q = skill + bonus + aff[fam] + rng.normal(0, 0.075)
            # Only the oracle reaches the top of a scale; capping the rest keeps a
            # strong method from tying ground truth exactly, which never happens.
            q = 1.0 if oracle else float(np.clip(q, 0.0, 0.92))
            worst, best = SCALE[mid]
            rec[mid] = round(worst + q * (best - worst), 4)

        # centroid_accuracy is a source alias of normalized_inverse_rank -- same
        # released formula on the same candidate pool, so it tracks it closely.
        rec["centroid_accuracy"] = round(
            rec["normalized_inverse_rank"] + float(rng.normal(0, 0.006)), 4
        )
        # Both feature spaces of a protocol see the same prediction, so top_k and
        # pca_k track each other; they differ in scale, not in ranking.
        for a, b in [("unbiased_mmd_median_top_k", "unbiased_mmd_median_pca_k"),
                     ("energy_distance_top_k", "energy_distance_pca_k"),
                     ("sinkhorn_w2_top_k", "sinkhorn_w2_pca_k")]:
            if not np.isnan(rec.get(a, np.nan)):
                lo, hi = SCALE[b]
                frac = (rec[a] - SCALE[a][0]) / (SCALE[a][1] - SCALE[a][0])
                frac = float(np.clip(frac + rng.normal(0, 0.05), 0, 1))
                rec[b] = round(lo + frac * (hi - lo), 4)
        rows[name] = rec

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "method"
    return df


def main() -> None:
    df = demo_frame()
    html = render(
        df,
        COLUMNS,
        groups=GROUPS,
        controls=CONTROLS,
        highlight=HIGHLIGHT,
        title="Perturbation prediction",
        notice=(
            "⚠ PLACEHOLDER DATA — layout demo only. Every metric and dataset score on "
            "this page is synthetic, generated from a seeded RNG in demo_frame(). These "
            "are not benchmark results and must not be cited or reported. Only the "
            "resource figures (time / memory / CPU) are real, transcribed from the "
            "published OpenProblems table."
        ),
        subtitle=(
            "Methods ranked by overall score across three datasets — srivatsan_2020 "
            "(sci-Plex 3), EmeraldBay and Tahoe — scored with the suite in "
            "src/metrics/metric_suite.yaml: 5 active historical DEG metrics on "
            "clipped_sign_log10_pval, and 14 pseudobulk centroid metrics on log-normalised "
            "condition centroids. Circle area and colour both encode the score, normalised "
            "per column, so a bigger and more prominent mark is always better whichever way "
            "the raw number runs; each band has its own hue. ScAPE and CPA carry the colour "
            "— the rest of the field is shown in neutral grey for reference, at full circle "
            "size. “--” means the method was not run on that dataset, which is not the same "
            "as scoring zero — the Single-cell band is blank for every method that "
            "predicts a DE signature rather than a cell population, since those cannot "
            "satisfy that family's input contract at all. "
            "† Centroid accuracy is declared alias_of: normalized_inverse_rank with "
            "role: diagnostic_alias — same released formula on the same candidate pool, "
            "not an independent vote."
        ),
        sort_by="score",
        norm_exclude=["Ground truth"],
    )
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(html):,} bytes, {len(COLUMNS)} columns, {len(df)} methods)")


if __name__ == "__main__":
    main()
