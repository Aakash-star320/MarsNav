"""CRISM summary-parameter browse definitions, copied from the PDS labels of the MTRDR dataset.

Source: PDS Geosciences Node, ``MRO-M-CRISM-5-RDR-MPTARGETED-V1.0`` (bundle ``mrocr_4001``). Each
browse-product label (``..._BR<code>J_MTR3.LBL`` / ``.XML``) names the three summary parameters shown in
its red, green and blue channels, the 8-bit scaling used to make the image, and a short
interpretation that cites Viviano-Beck et al. [2014]. All 18 definitions were fetched on
2026-11-14 and are recorded in ``tests/fixtures/crism/browse_definitions.json``; the scaling factors
are identical across the observations compared (HRL000040FF, FRT000047A3, FRT00005850), so they are a
fixed documented stretch, not a per-image one.

Every label says that analysis of the CRISM spectrum is required for positive mineral identification.
Nothing in this module identifies a mineral.
"""
from __future__ import annotations

from dataclasses import dataclass

PDS_DATASET_ID = "MRO-M-CRISM-5-RDR-MPTARGETED-V1.0"
PDS_BUNDLE_URL = "https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/"
LITERATURE = "Viviano-Beck et al. [2014], as cited by the PDS browse-product labels"
BROWSE_DERIVED_MAXIMUM = 254          # DERIVED_MAXIMUM of the 8-bit browse images: real value = DN x SCALING_FACTOR


@dataclass(frozen=True)
class BrowseDefinition:
    code: str                        # e.g. "BRPHY"
    bands: tuple[str, str, str]      # red, green, blue summary parameters
    scaling: tuple[float, float, float]
    description: str                 # PDS label text (shortened where it only repeats a citation)

    def stretch_max(self, band: str) -> float:
        """Parameter value that maps to full brightness (DN 254) in this browse product."""
        return BROWSE_DERIVED_MAXIMUM * self.scaling[self.bands.index(band)]


PHY = BrowseDefinition(
    code="BRPHY", bands=("D2300", "D2200", "BD1900R2"), scaling=(1.3358e-04, 6.8627e-05, 1.9584e-04),
    description=("Shows information related to hydroxylated minerals including phyllosilicate. Mg/Fe-OH bearing minerals "
                 "may appear red, or magenta when hydrated. Al/Si-OH bearing minerals may appear green, or cyan when hydrated. "
                 "Blue colors may indicate other hydrated minerals. Analysis of CRISM spectra must be used to match absorption "
                 "band positions and relative strength for positive mineral identification."),
)

HYD = BrowseDefinition(
    code="BRHYD", bands=("SINDEX2", "BD2100_2", "BD1900_2"), scaling=(9.5991e-05, 7.6784e-05, 1.8481e-04),
    description=("Shows information related to bound water in minerals. Polyhydrated sulfates have strong 1900 nm and 2400 nm "
                 "absorption bands, and may appear magenta; monohydrated sulfates have a strong 2100 nm absorption and a weak "
                 "2400 nm absorption band, and may appear yellow/green."),
)

BROWSE = {d.code: d for d in (PHY, HYD)}
