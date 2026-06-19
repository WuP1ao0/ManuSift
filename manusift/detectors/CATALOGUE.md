# Detector Catalogue

R-2026-06-20 (CDE-D1): generated from the live `manusift.detectors` entry-point registry.

Each detector exposes a `Finding` with a deterministic `detector_id` (the entry-point name). Findings roll up to a per-detector report section.

## Index

- [`ai_generated_figure`](#ai-generated-figure)
- [`author_emails`](#author-emails)
- [`chart_data_extract`](#chart-data-extract)
- [`citation_network`](#citation-network)
- [`compliance`](#compliance)
- [`data_availability_concern`](#data-availability-concern)
- [`figure_grim`](#figure-grim)
- [`figure_stat_text`](#figure-stat-text)
- [`figure_table_consistency`](#figure-table-consistency)
- [`image_dup`](#image-dup)
- [`image_forensics`](#image-forensics)
- [`image_noise_inconsistency`](#image-noise-inconsistency)
- [`image_sift_copymove`](#image-sift-copymove)
- [`image_ssim`](#image-ssim)
- [`image_statistics`](#image-statistics)
- [`imagehash_ahash`](#imagehash-ahash)
- [`imagehash_dhash`](#imagehash-dhash)
- [`imagehash_phash`](#imagehash-phash)
- [`imagehash_whash`](#imagehash-whash)
- [`metadata`](#metadata)
- [`page_raster_dup`](#page-raster-dup)
- [`panel_dup`](#panel-dup)
- [`panel_duplicate`](#panel-duplicate)
- [`paper_mill_authorship`](#paper-mill-authorship)
- [`paper_mill_template`](#paper-mill-template)
- [`pdf_metadata`](#pdf-metadata)
- [`ref_duplicate`](#ref-duplicate)
- [`ref_format_anomaly`](#ref-format-anomaly)
- [`stat_grim`](#stat-grim)
- [`stat_percent`](#stat-percent)
- [`stat_pvalue`](#stat-pvalue)
- [`supplementary`](#supplementary)
- [`table_benford`](#table-benford)
- [`table_duplicate_row`](#table-duplicate-row)
- [`table_outlier`](#table-outlier)
- [`table_round_bias`](#table-round-bias)
- [`text_patterns`](#text-patterns)
- [`text_tortured_phrases`](#text-tortured-phrases)

## Detectors

### `ai_generated_figure`

> Three-probe AI-figure detector. See module docstring.


### `author_emails`

> Look at the author


### `chart_data_extract`

> For every image in the


### `citation_network`

> P2-D1 detector. The ``name`` attribute


### `compliance`

> Scan the document text


### `data_availability_concern`

> Scan the data-availability section for red-flag phrases.


### `figure_grim`

> Run EasyOCR over each figure region, then GRIM-check


### `figure_stat_text`

> Run EasyOCR over each figure region and emit


### `figure_table_consistency`

> Check that the


### `image_dup`

> Detect near-duplicate images inside the PDF using a


### `image_forensics`

> Image-forensics analysis: Error Level Analysis (ELA) on every


### `image_noise_inconsistency`

> Run the noise-level


### `image_sift_copymove`

> Run the SIFT-based copy-


### `image_ssim`

> Per-pair SSIM check on


### `image_statistics`

> Per-image statistics check.


### `imagehash_ahash`

> Average hash. Fastest of the


### `imagehash_dhash`

> Difference hash. Strong on


### `imagehash_phash`

> Classic DCT-based perceptual


### `imagehash_whash`

> Wavelet hash. Slowest but


### `metadata`

> Inspect PDF metadata (producer, creator, dates) and


### `page_raster_dup`

> Detect duplicate figure regions across PDF pages by


### `panel_dup`

> Detect duplicate panels within PDF figures.


### `panel_duplicate`

> For every image in the


### `paper_mill_authorship`

> Two-probe paper-mill / peer-review detector.


### `paper_mill_template`

> Scan the document for


### `pdf_metadata`

> Run the metadata +


### `ref_duplicate`

> Emit a finding per pair


### `ref_format_anomaly`

> Emit a single finding


### `stat_grim`

> The GRIM test on every


### `stat_percent`

> For every column whose


### `stat_pvalue`

> Recompute the p-value


### `supplementary`

> Inspect the PDF for


### `table_benford`

> Apply the Benford goodness-


### `table_duplicate_row`

> Find rows that are


### `table_outlier`

> For every numeric column,


### `table_round_bias`

> Report the fraction of


### `text_patterns`

> Dispatcher that runs every enabled text-pattern check against


### `text_tortured_phrases`

> Scan the document text

