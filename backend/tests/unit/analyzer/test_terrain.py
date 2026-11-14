import numpy as np
import pytest

from app.analyzer.preprocessing.terrain import edge_grade, roughness_std, slope_deg


def plane(rows=20, cols=20, dzdx=0.0, dzdy=0.0, px=10.0, py=10.0):
    c, r = np.meshgrid(np.arange(cols) * px, np.arange(rows) * py)
    return dzdx * c + dzdy * r


def test_known_plane_slope_uses_pixel_spacing() -> None:
    z = plane(dzdx=0.5)  # rise 0.5 per metre east -> atan(0.5)
    s, ok = slope_deg(z, np.ones(z.shape, bool), 10.0, 10.0)
    assert ok.all()
    assert np.nanmax(np.abs(s - np.degrees(np.arctan(0.5)))) < 1e-9


def test_non_square_pixels() -> None:
    z = plane(dzdy=0.2, px=5.0, py=20.0)
    s, _ = slope_deg(z, np.ones(z.shape, bool), 5.0, 20.0)
    assert np.allclose(s, np.degrees(np.arctan(0.2)))


def test_flat_surface_is_zero_slope_and_zero_roughness() -> None:
    z = np.full((10, 10), 1500.0)
    v = np.ones(z.shape, bool)
    assert np.allclose(slope_deg(z, v, 10, 10)[0], 0.0)
    assert np.allclose(roughness_std(z, v)[0][1:-1, 1:-1], 0.0)


def test_nodata_does_not_create_fake_gradients() -> None:
    z = plane(dzdx=0.1)
    z[5, 5] = -9999.0
    v = np.ones(z.shape, bool)
    v[5, 5] = False
    s, ok = slope_deg(z, v, 10, 10)
    assert not ok[5, 5] and np.isnan(s[5, 5])
    # neighbours use one-sided differences and keep the true slope; the sentinel value never leaks.
    assert s[5, 4] == pytest.approx(np.degrees(np.arctan(0.1)))
    assert s[5, 6] == pytest.approx(np.degrees(np.arctan(0.1)))
    assert np.nanmax(s) < 10


def test_isolated_valid_cell_has_undefined_slope() -> None:
    z = np.zeros((5, 5)); v = np.zeros((5, 5), bool); v[2, 2] = True
    assert not slope_deg(z, v, 10, 10)[1].any()


def test_directional_grade_is_signed_and_antisymmetric() -> None:
    z = plane(dzdx=0.1)
    v = np.ones(z.shape, bool)
    east, ok_e = edge_grade(z, v, 10, 10, 0, 1)
    west, ok_w = edge_grade(z, v, 10, 10, 0, -1)
    assert east[3, 3] == pytest.approx(0.1) and west[3, 4] == pytest.approx(-0.1)
    assert not ok_e[:, -1].any() and not ok_w[:, 0].any()
    diag, _ = edge_grade(z, v, 10, 10, 1, 1)
    assert diag[3, 3] == pytest.approx(10 * 0.1 / np.hypot(10, 10))


def test_edge_grade_masks_invalid_cells() -> None:
    z = np.zeros((4, 4)); v = np.ones((4, 4), bool); v[1, 2] = False
    g, ok = edge_grade(z, v, 10, 10, 0, 1)
    assert not ok[1, 1] and np.isnan(g[1, 1])


def test_roughness_separates_rough_from_steep() -> None:
    rng = np.random.default_rng(0)
    rough = rng.normal(0, 2.0, (30, 30))
    v = np.ones(rough.shape, bool)
    r_rough, _ = roughness_std(rough, v)
    ramp = plane(30, 30, dzdx=0.05)
    r_ramp, _ = roughness_std(ramp, v)
    assert np.nanmean(r_rough) > 1.0
    assert np.nanmean(r_rough) > np.nanmean(r_ramp)


def test_roughness_masks_windows_with_too_little_data() -> None:
    z = np.zeros((9, 9)); v = np.zeros((9, 9), bool); v[4, 4] = True
    _, ok = roughness_std(z, v)
    assert not ok.any()


def test_rejects_bad_spacing() -> None:
    with pytest.raises(ValueError):
        slope_deg(np.zeros((3, 3)), np.ones((3, 3), bool), 0, 10)
