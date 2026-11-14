// Pure tile arithmetic for NASA Mars Trek tiles (no map library), shared by the map module and the dashboard.
// Source (verified from its WMTS capabilities file): Viking MDIM 2.1 colour mosaic, global, 232 m/px,
// geographic tiles on the Mars 2000 sphere, 256 px, top-left (-180, 90), 2^(z+1) x 2^z tiles at zoom z, zoom 0-7.
// Context imagery only: it is not an elevation model and carries no science evidence.

export const TREK_BASE =
  "https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm";
export const TREK_MAX_LEVEL = 7;
export const TREK_TILE = 256;
export const TREK_ATTRIBUTION =
  "Imagery: Viking MDIM 2.1 colour mosaic (232 m/px) via NASA Mars Trek";

/** Degrees covered by one Trek tile at a level. */
export const trekTileDeg = (level: number) => 180 / 2 ** level;
export const trekPxPerDeg = (level: number) => TREK_TILE / trekTileDeg(level);

/** Finest-needed level for a display scale (pixels per degree), capped at the service maximum. */
export function trekLevelFor(displayPxPerDeg: number): number {
  const level = Math.ceil(Math.log2(displayPxPerDeg / (TREK_TILE / 180)));
  return Math.min(TREK_MAX_LEVEL, Math.max(0, level));
}

export type TrekTile = {
  level: number;
  row: number;
  col: number;
  west: number;
  east: number;
  north: number;
  south: number;
};

export const trekUrl = (t: Pick<TrekTile, "level" | "row" | "col">) =>
  `${TREK_BASE}/${t.level}/${t.row}/${t.col}.jpg`;

/** Trek tiles that intersect a geographic box (degrees, east-positive longitude in [-180, 180]). */
export function trekTilesFor(
  level: number,
  west: number,
  south: number,
  east: number,
  north: number,
): TrekTile[] {
  const d = trekTileDeg(level);
  const cols = 2 ** (level + 1);
  const rows = 2 ** level;
  const w = Math.max(-180, west);
  const e = Math.min(180, east);
  const s = Math.max(-90, south);
  const n = Math.min(90, north);
  if (e <= w || n <= s) return [];
  const c0 = Math.floor((w + 180) / d);
  const c1 = Math.min(cols - 1, Math.ceil((e + 180) / d) - 1);
  const r0 = Math.floor((90 - n) / d);
  const r1 = Math.min(rows - 1, Math.ceil((90 - s) / d) - 1);
  const out: TrekTile[] = [];
  for (let row = Math.max(0, r0); row <= r1; row++)
    for (let col = Math.max(0, c0); col <= c1; col++)
      out.push({
        level,
        row,
        col,
        west: -180 + col * d,
        east: -180 + (col + 1) * d,
        north: 90 - row * d,
        south: 90 - (row + 1) * d,
      });
  return out;
}

