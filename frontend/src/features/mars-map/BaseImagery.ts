// Real Mars surface imagery under the analysis layers: NASA Mars Trek tiles.
//
// Source (verified from its WMTS capabilities file): Viking MDIM 2.1 colour mosaic, global, 232 m/px,
// geographic (plate carree) tiles on the Mars 2000 sphere (EPSG:104905), 256 px tiles, top-left corner
// (-180, 90), 2^(z+1) x 2^z tiles at zoom z, zoom 0-7 (default028mm tile matrix set).
// https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/WMTSCapabilities.xml
//
// This is context imagery only: it is not an elevation model and carries no science evidence.
import * as L from "leaflet";
import {
  TREK_TILE,
  TREK_ATTRIBUTION,
  trekLevelFor,
  trekTilesFor,
  trekUrl,
} from "../../utils/trek";

export * from "../../utils/trek";

// Decoded Trek tiles are kept for the session, so revisiting a zoom level draws instantly.
const loaded = new Map<string, HTMLImageElement>();
const inflight = new Map<string, Promise<HTMLImageElement | null>>();

function fetchTile(url: string): Promise<HTMLImageElement | null> {
  const hit = loaded.get(url);
  if (hit) return Promise.resolve(hit);
  let p = inflight.get(url);
  if (!p) {
    p = new Promise<HTMLImageElement | null>((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";   // NASA Trek allows it; needed so the tiles can also texture the 3D terrain
      img.onload = () => { loaded.set(url, img); inflight.delete(url); resolve(img); };
      img.onerror = () => { inflight.delete(url); resolve(null); };   // not cached: a later view retries
      img.src = url;
    });
    inflight.set(url, p);
  }
  return p;
}

let preloaded = false;
/** Fetches the coarse levels (the whole planet, 42 small tiles) once, so zooming out always has something to show. */
function preloadCoarseLevels(maxLevel = 2) {
  if (preloaded) return;
  preloaded = true;
  for (let level = 0; level <= maxLevel; level++) {
    trekTilesFor(level, -180, -90, 180, 90).forEach((t) => void fetchTile(trekUrl(t)));
  }
}

/**
 * Leaflet layer for the map module's simple angular CRS (1 degree = 2^zoom pixels, latitude up).
 * Each map tile is composed from the Trek tiles that cover it. A tile is handed to Leaflet at once and drawn
 * in passes: already-loaded coarser levels first (so a zoom never shows an empty tile), then the level
 * that matches the zoom as its tiles arrive. Tiles that fail to load stay empty, so the map still works
 * offline, just without imagery.
 */
export function marsTrekLayer(opacity = 1): L.GridLayer {
  preloadCoarseLevels();
  const Layer = L.GridLayer.extend({
    createTile(coords: L.Coords, done: L.DoneCallback) {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = TREK_TILE;
      const span = TREK_TILE / 2 ** coords.z; // degrees per map tile at this zoom
      const lng0 = coords.x * span;
      const lat1 = -coords.y * span;
      const ctx = canvas.getContext("2d");
      const finest = trekLevelFor(2 ** coords.z);
      const area = [lng0, lat1 - span, lng0 + span, lat1] as const;
      setTimeout(() => done(undefined, canvas), 0);
      if (!ctx) return canvas;
      ctx.imageSmoothingEnabled = true;
      const paint = (t: ReturnType<typeof trekTilesFor>[number], img: HTMLImageElement) => {
        const x0 = ((t.west - lng0) / span) * TREK_TILE;
        const x1 = ((t.east - lng0) / span) * TREK_TILE;
        const y0 = ((lat1 - t.north) / span) * TREK_TILE;
        const y1 = ((lat1 - t.south) / span) * TREK_TILE;
        ctx.drawImage(img, x0, y0, x1 - x0, y1 - y0);
      };
      // Coarse to fine: whatever is already loaded is painted straight away.
      for (let level = 0; level <= finest; level++) {
        for (const t of trekTilesFor(level, ...area)) {
          const img = loaded.get(trekUrl(t));
          if (img) paint(t, img);
          else if (level === finest) void fetchTile(trekUrl(t)).then((i) => i && paint(t, i));
        }
      }
      return canvas;
    },
  });
  return new (Layer as unknown as new (o: L.GridLayerOptions) => L.GridLayer)({
    tileSize: TREK_TILE,
    opacity,
    attribution: TREK_ATTRIBUTION,
    noWrap: true,
    updateWhenZooming: true,
    updateInterval: 60,
    keepBuffer: 3,
  });
}

/**
 * One canvas of Trek imagery covering a geographic box (used to texture the 3D terrain). Resolves with whatever
 * could be loaded; null when nothing at all could (offline), so the caller keeps its plain colours.
 */
export async function trekImageFor(
  b: { west_deg_east: number; south_deg: number; east_deg_east: number; north_deg: number },
  maxPx = 1536,
): Promise<HTMLCanvasElement | null> {
  const lon = b.east_deg_east - b.west_deg_east, lat = b.north_deg - b.south_deg;
  if (!(lon > 0) || !(lat > 0)) return null;
  const scale = maxPx / Math.max(lon, lat);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(2, Math.round(lon * scale));
  canvas.height = Math.max(2, Math.round(lat * scale));
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.imageSmoothingEnabled = true;
  const level = trekLevelFor(scale);
  const tiles = trekTilesFor(level, b.west_deg_east, b.south_deg, b.east_deg_east, b.north_deg);
  let drawn = 0;
  await Promise.all(tiles.map(async (t) => {
    const img = await fetchTile(trekUrl(t));
    if (!img) return;
    const x0 = ((t.west - b.west_deg_east) / lon) * canvas.width, x1 = ((t.east - b.west_deg_east) / lon) * canvas.width;
    const y0 = ((b.north_deg - t.north) / lat) * canvas.height, y1 = ((b.north_deg - t.south) / lat) * canvas.height;
    ctx.drawImage(img, x0, y0, x1 - x0, y1 - y0);
    drawn++;
  }));
  return drawn ? canvas : null;
}
