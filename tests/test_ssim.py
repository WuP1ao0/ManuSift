

def test_ssim_one_pair_tiny_sliver_returns_zero() -> None:
    """skimage raises ValueError for images < 7x7
    (default win_size); _ssim_one_pair must return 0.0
    instead of crashing (fraud_web_v1 web_frontiers_01
    sliver-panel regression)."""
    import numpy as np
    from manusift.detectors.ssim import _ssim_one_pair
    a = np.zeros((4, 40), dtype=np.uint8)
    b = np.zeros((40, 40), dtype=np.uint8)
    assert _ssim_one_pair(a, b) == 0.0
    # and normal-size still works
    c = np.zeros((40, 40), dtype=np.uint8)
    assert _ssim_one_pair(b, c) == 1.0
