"""G2 -- exact id_map row order and gene space. Any reliance on the metric's --resolve_genes
rescue is a hard fail here, not a convenience (todo.html gap: the contract's gene_order_fixed
default and this gate previously disagreed -- this test enforces the strict reading).
"""

from gauntlet.checks import check_id_map_alignment


def test_row_order_and_gene_space_match_exactly(prediction, id_map_df, fixture_manifest):
    gene_ids = [f"g{str(i).zfill(4)}" for i in range(fixture_manifest["n_genes"])]
    result = check_id_map_alignment(prediction, id_map_df, gene_order=gene_ids)
    result.assert_ok()
