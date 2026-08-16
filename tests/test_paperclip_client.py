"""Parser tests for paperclip CLI output scraping.

Fixtures are captured from real paperclip output (2026-08); the regex-scraping
layer is the most fragile piece of the system, so any upstream format change
should fail here first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from litsearch.paperclip_client import (  # noqa: E402
    _parse_hits,
    _parse_result_set_id,
)

SEARCH_OUTPUT = """\
Found 3 papers  [s_a7190a40]

  1. The Limitations of TabPFN for High-Dimensional RNA-seq Analysis
     Summer Zhou, Vinayak Agarwal, Ashwin Gopinath, Timothy Kassis *
     bio_66425d6272fa · bioRxiv · 2025-08-15
     https://doi.org/10.1101/2025.08.15.670537
     "TabPFN was adapted for high-dimensional RNA-seq analysis."

  2. Towards generalizable single-cell perturbation modeling
     Alice Driessen, Benedek Harsanyi, Marianna Rapsomaniki, Jannis Born
     arx_2504.08328 · arXiv · 2025

  3. Learning single-cell perturbation responses using neural optimal transport
     Charlotte Bunne, Stefan G. Stark, Gabriele Gut
     PMC10630137 · PMC · 2023-09-28
     https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10630137/

[295ms, saved to s_a7190a40]
"""

EMPTY_OUTPUT = """\
No papers found.
Try broader terms, --all for full corpus, or --source pmc,biorxiv
[338ms, saved to s_02ca3c35]
"""

FILTER_SUMMARY_OUTPUT = """\
Filtered: 4 -> 3 papers (1 removed as irrelevant) in 494ms
  -> 3 papers after filtering
Results ID: s_18b32471 (updated in place)
[568ms, saved to s_18b32471]
"""


def test_parse_hits_ids_titles_ranks():
    hits = _parse_hits(SEARCH_OUTPUT)
    assert [h.doc_id for h in hits] == ["bio_66425d6272fa", "arx_2504.08328",
                                        "PMC10630137"]
    assert hits[0].rank == 1 and hits[2].rank == 3
    assert hits[1].title.startswith("Towards generalizable")


def test_parse_hits_empty():
    assert _parse_hits(EMPTY_OUTPUT) == []


def test_parse_result_set_id_takes_last():
    assert _parse_result_set_id(SEARCH_OUTPUT) == "s_a7190a40"
    assert _parse_result_set_id(EMPTY_OUTPUT) == "s_02ca3c35"
    assert _parse_result_set_id(FILTER_SUMMARY_OUTPUT) == "s_18b32471"
    assert _parse_result_set_id("no ids here") is None


def test_doc_id_not_matched_in_prose():
    # A rank line followed by prose without any doc id yields no hit.
    assert _parse_hits("  1. A title\n     some authors\n") == []
