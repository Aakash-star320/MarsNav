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

/**
 * Leaflet layer for the map module's simple angular CRS (1 degree = 2^zoom pixels, latitude up).
 * Each map tile is composed from the Trek tiles that cover it. Tiles that fail to load stay empty,
 * so the map still works offline, just without imagery.
 */
export function marsTrekLayer(opacity = 1): L.GridLayer {
  const Layer = L.GridLayer.extend({
    createTile(coords: L.Coords, done: L.DoneCallback) {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = TREK_TILE;
      const span = TREK_TILE / 2 ** coords.z; // degrees per map tile at this zoom
      const lng0 = coords.x * span;
      const lat1 = -coords.y * span;
      const tiles = trekTilesFor(
        trekLevelFor(2 ** coords.z),
        lng0,
        lat1 - span,
        lng0 + span,
        lat1,
      );
      const ctx = canvas.getContext("2d");
      if (!ctx || tiles.length === 0) {
        setTimeout(() => done(undefined, canvas), 0);
        return canvas;
      }
      let pending = tiles.length;
      const finish = () => {
        if (--pending === 0) done(undefined, canvas);
      };
      tiles.forEach((t) => {
        const img = new Image();
        img.onload = () => {
          const x0 = ((t.west - lng0) / span) * TREK_TILE;
          const x1 = ((t.east - lng0) / span) * TREK_TILE;
          const y0 = ((lat1 - t.north) / span) * TREK_TILE;
          const y1 = ((lat1 - t.south) / span) * TREK_TILE;
          ctx.imageSmoothingEnabled = true;
          ctx.drawImage(img, x0, y0, x1 - x0, y1 - y0);
          finish();
        };
        img.onerror = finish;
        img.src = trekUrl(t);
      });
      return canvas;
    },
  });
  return new (Layer as unknown as new (o: L.GridLayerOptions) => L.GridLayer)({
    tileSize: TREK_TILE,
    opacity,
    attribution: TREK_ATTRIBUTION,
    noWrap: true,
    updateWhenZooming: false,
    keepBuffer: 2,
  });
}
