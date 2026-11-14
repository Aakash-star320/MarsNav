// Published radiation figures for the Martian surface, used for a typical-exposure estimate. Nothing here is fetched:
// these are a few numbers from one scientific paper, stored with their source, so the panel can say exactly where
// they came from and what they do not cover.
//
// Source: Hassler et al., "Mars' Surface Radiation Environment Measured with the Mars Science Laboratory's Curiosity
// Rover", Science 343 (2014), measured by Curiosity's Radiation Assessment Detector (RAD) in Gale crater. The dose
// rates below are the figures the mission team reported for galactic cosmic rays (the steady background that always
// reaches the surface); sudden solar storms are NOT included.

export const MARS_SURFACE_RADIATION = {
  /** Dose equivalent (how biologically significant the exposure is) in millisieverts per day, as reported by the mission team. */
  doseEquivalentMSvPerDay: 0.67,
  /** Absorbed dose (energy deposited per kilogram) in milligrays per day, with its stated uncertainty. */
  absorbedMGyPerDay: 0.21,
  absorbedUncertaintyMGyPerDay: 0.04,
  /** For comparison: the rate measured on the way to Mars, in millisieverts per day. */
  transitMSvPerDay: 1.8,
  instrument: 'Curiosity rover, Radiation Assessment Detector (RAD)',
  site: 'Gale crater',
  siteElevationM: -4400,
  period: 'August 2012 to June 2013 (about 300 sols, near solar maximum)',
  paperUrl: 'https://ntrs.nasa.gov/citations/20180007641',
  paperDoi: 'https://doi.org/10.1126/science.1244797',
  releaseUrl: 'https://swri.org/node/9079',
} as const;

/** Estimated dose equivalent, in millisieverts, for `hours` spent outside at the typical surface rate. */
export const doseForHours = (hours: number): number => (MARS_SURFACE_RADIATION.doseEquivalentMSvPerDay * Math.max(0, hours)) / 24;

/** The same rate per hour, in millisieverts. */
export const ratePerHour = (): number => MARS_SURFACE_RADIATION.doseEquivalentMSvPerDay / 24;

/** Small doses in microsieverts (a thousandth of a millisievert) so they stay readable. */
export function fmtDose(mSv: number): string {
  if (!Number.isFinite(mSv)) return 'n/a';
  if (mSv < 0.1) return `${Math.round(mSv * 1000)} µSv`;
  return `${mSv.toFixed(mSv < 1 ? 2 : 1)} mSv`;
}
