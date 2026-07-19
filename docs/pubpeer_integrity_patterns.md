# PubPeer-derived integrity patterns → ManuSift mapping

Screening signals only — not misconduct determinations. Patterns are
distilled from public post-publication review practice (PubPeer threads,
Bik et al. image taxonomy, publisher image-integrity pilots, Source Data
Excel cases discussed on PubPeer).

## Image patterns (Bik-style taxonomy)

| Category | Description | Typical PubPeer cue | ManuSift coverage |
|----------|-------------|---------------------|-------------------|
| **I** Simple duplication | Same panel reused for different conditions | Identical blot/microscopy band | `image_dup`, `panel_dup`, `page_raster_dup`, `imagehash_*` |
| **II** Repositioned | Rotate / flip / crop / stretch reuse | Same band upside-down or mirrored | `image_dup` secondary hashes, SIFT/copy-move, forensics texture |
| **III** Altered / clone | Partial copy-move, splice, clone stamp | Shared noise island / vertical splice | `image_forensics`, `image_sift_copymove`, noise inconsistency |
| Cross-paper reuse | Same figure across publications | Plagiarism of images | Out of band (needs external DB; Imagetwin-style) |

**Discovery tips from PubPeer practice**

1. Compare *background noise*, not just band shape.
2. Flip/rotate candidate panels before dismissing similarity.
3. Loading-control lanes reused across “independent” gels.
4. Micro-duplication inside one field (cells/colonies stamped twice).

## Source Data / Excel patterns (numeric fabrication)

| Pattern | PubPeer-style observation | ManuSift check(s) |
|---------|---------------------------|-------------------|
| Group copy | Condition A numbers = condition B | `fixed_offset` (offset=0), `cross_table_repeated_values` |
| Fixed arithmetic shift | A = B + c (constant c) | `fixed_offset`, `cross_table_fixed_offset`, `partial_fixed_offset` |
| Shared decimal tails | Parallel samples share `.xx` digits | `matching_decimal_tails`, integer-shift tail reuse |
| Contiguous block paste | Same run of values reappears elsewhere | `sequence_reuse` (cross-column / cross-table) |
| Zero biological variance | Replicates n=3 identical | `identical_parallel_replicates`, `zero_variance` |
| Duplicate rows | Pasted row blocks in SI tables | `table_duplicate_row`, `table_near_duplicate_row` |
| Terminal-digit / round bias | Last digits cluster on 0/5 or one pair | `table_round_bias`, terminal digit concentration |
| Systemic Excel fingerprint | Same tricks across many figures | `excel_fabrication_span` |
| PDF vs SI mismatch | Figure numbers ≠ Source Data | `source_data_consistency`, `figure_table_consistency` |

**Discovery tips from PubPeer / lab integrity write-ups**

1. Open Source Data first; many Nature/Science cases surface in XLSX.
2. Sort or scatter-plot group pairs; perfect lines imply fixed offset.
3. Search for the same multi-value sequence in another sheet.
4. Check whether “independent” replicates have zero scatter.
5. Prefer contiguous multi-cell matches over single shared numbers.

## Statistics / text (secondary on PubPeer)

| Pattern | ManuSift |
|---------|----------|
| Impossible mean for integer data | `stat_grim` / `figure_grim` |
| p-value / percent reporting glitches | `stat_pvalue`, `stat_percent` |
| Tortured phrases / paper-mill prose | `text_tortured_phrases`, `paper_mill_*` |
| Cited retracted work | `cited_retraction` |

## Intentional non-goals

- Accusing authors or labs.
- Replacing human review of image forensics edge cases.
- Cross-corpus image plagiarism without an external index.

## References (public)

- Bik, Fang, Casadevall — inappropriate image duplication taxonomy (mBio 2016).
- Publisher image-screening pilots (e.g. ASM + Imagetwin).
- PubPeer discussions of Source Data number duplications in Excel SI files.
