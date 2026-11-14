import { useEffect, useRef, useState } from "react";
import * as T from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { useMissionStore as store } from "../../store/missionStore";
import { trekImageFor } from "./BaseImagery";
import { gridXY, heightAt, project, unproject, validateDem } from "./geometry";
import type { LonLat, BoundingBox } from "../../types/contracts";
function dispose(root: T.Object3D) {
  root.traverse((o) => {
    const m = o as T.Mesh;
    if (m.geometry) m.geometry.dispose();
    if (m.material) {
      const mats = Array.isArray(m.material) ? m.material : [m.material];
      mats.forEach((mat) => {
        const mm = mat as T.MeshBasicMaterial;
        mm.map?.dispose();
        mat.dispose();
      });
    }
  });
}
/** Lowest valid elevation: the scene is drawn relative to it, so real (for example -2600 m) terrain sits near y = 0. */
const demBase = (d: { values: (number | null)[] }) => {
  let m = Infinity;
  for (const v of d.values) if (v !== null && v < m) m = v;
  return Number.isFinite(m) ? m : 0;
};
/** Default camera framing from the DEM's real size, so any area (not only the demo crater) is in view. */
function homeView(d: Parameters<typeof gridXY>[0], exaggeration: number) {
  const w = (d.width - 1) * Math.hypot(d.affine[1], d.affine[4]);
  const h = (d.height - 1) * Math.hypot(d.affine[2], d.affine[5]);
  const e = Math.max(w, h, 400) * 2.4;
  const [cx, cy] = gridXY(d, (d.width - 1) / 2, (d.height - 1) / 2);
  return { e, pos: [cx + 0.55 * e, 0.5 * e + 50 * exaggeration, -cy + 0.62 * e] as const, target: [cx, 50 * exaggeration, -cy] as const };
}
type SceneState = {
  scene: T.Scene;
  camera: T.PerspectiveCamera;
  controls: OrbitControls;
  terrain: T.Mesh;
  renderer: T.WebGLRenderer;
  dynamic: T.Group;
  rasters: T.Group;
};
export function Terrain3D() {
  const host = useRef<HTMLDivElement>(null),
    ref = useRef<SceneState>();
  const s = store();
  const [failure, setFailure] = useState("");
  const [missing, setMissing] = useState(0);
  useEffect(() => {
    setFailure("");
    const d = s.dem;
    if (!d || !host.current) return;
    try {
      validateDem(d);
    } catch (e) {
      setFailure((e as Error).message);
      return;
    }
    const el = host.current;
    let renderer: T.WebGLRenderer;
    try {
      renderer = new T.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setFailure(
        "WebGL is unavailable. Use 2D or enable browser hardware acceleration.",
      );
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor("#12191e");
    renderer.outputColorSpace = T.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new T.Scene();
    const home = homeView(d, s.exaggeration);
    const base = demBase(d);
    const camera = new T.PerspectiveCamera(40, 1, 1, Math.max(30000, home.e * 8));
    camera.position.set(...home.pos);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(...home.target);
    controls.enableDamping = true;
    controls.minDistance = Math.min(180, home.e / 10);
    controls.maxDistance = Math.max(10000, home.e * 4);
    controls.maxPolarAngle = Math.PI * 0.49;
    scene.add(new T.HemisphereLight("#dfe6ff", "#3b2a20", 1.1));
    const sun = new T.DirectionalLight("#fff0d9", 2.6);
    sun.position.set(-home.e * 1.3, home.e * 0.55, home.e * 0.6);   // low sun: ridges and crater rims throw shading
    scene.add(sun);
    const positions: number[] = [],
      uvs: number[] = [],
      colors: number[] = [],
      indices: number[] = [];
    for (let r = 0; r < d.height; r++)
      for (let c = 0; c < d.width; c++) {
        const [x, y] = gridXY(d, c, r);
        const h = d.values[r * d.width + c];
        positions.push(x, ((h ?? base) - base) * s.exaggeration, -y);
        uvs.push(c / (d.width - 1), 1 - r / (d.height - 1));
        const color = new T.Color().setHSL(
          0.07,
          0.28,
          0.28 + Math.max(0, (h ?? base) - base) / 700,
        );
        colors.push(color.r, color.g, color.b);
      }
    for (let r = 0; r < d.height - 1; r++)
      for (let c = 0; c < d.width - 1; c++) {
        const a = r * d.width + c,
          b = a + 1,
          cc = a + d.width,
          dd = cc + 1;
        if ([a, b, cc, dd].some((i) => d.values[i] === null)) continue;
        indices.push(a, cc, b, b, cc, dd);
      }
    const geo = new T.BufferGeometry();
    geo.setAttribute("position", new T.Float32BufferAttribute(positions, 3));
    geo.setAttribute("uv", new T.Float32BufferAttribute(uvs, 2));
    geo.setAttribute("color", new T.Float32BufferAttribute(colors, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();
    const terrain = new T.Mesh(
      geo,
      new T.MeshStandardMaterial({
        vertexColors: true,
        roughness: 1,
        side: T.DoubleSide,
      }),
    );
    scene.add(terrain);
    // Real Viking imagery draped over the surface (falls back to the plain colours when offline).
    let alive = true;
    void trekImageFor(d.bounds).then((canvas) => {
      if (!alive || !canvas) return;
      const tex = new T.CanvasTexture(canvas);
      tex.colorSpace = T.SRGBColorSpace;
      tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
      const mat = terrain.material as T.MeshStandardMaterial;
      mat.map = tex;
      mat.vertexColors = false;
      mat.color.set("#ffffff");
      mat.needsUpdate = true;
    });
    // Side walls and a base, so it reads as a solid block of Mars and not a floating sheet.
    let top = 0;
    for (let i = 1; i < positions.length; i += 3) top = Math.max(top, positions[i]);
    const depth = Math.max(top * 0.8, home.e * 0.07);
    const rim: number[] = [];
    for (let c = 0; c < d.width; c++) rim.push(c);
    for (let r = 1; r < d.height; r++) rim.push(r * d.width + d.width - 1);
    for (let c = d.width - 2; c >= 0; c--) rim.push((d.height - 1) * d.width + c);
    for (let r = d.height - 2; r > 0; r--) rim.push(r * d.width);
    const wallPos: number[] = [], wallIdx: number[] = [];
    rim.forEach((v, i) => {
      wallPos.push(positions[v * 3], positions[v * 3 + 1], positions[v * 3 + 2], positions[v * 3], -depth, positions[v * 3 + 2]);
      const a = i * 2, b = ((i + 1) % rim.length) * 2;
      wallIdx.push(a, b, a + 1, b, b + 1, a + 1);
    });
    const wallGeo = new T.BufferGeometry();
    wallGeo.setAttribute("position", new T.Float32BufferAttribute(wallPos, 3));
    wallGeo.setIndex(wallIdx);
    wallGeo.computeVertexNormals();
    scene.add(new T.Mesh(wallGeo, new T.MeshStandardMaterial({ color: "#4a3427", roughness: 1, side: T.DoubleSide })));
    const grid = new T.GridHelper(home.e * 3, 24, "#36454b", "#1f2b32");
    grid.position.y = -depth - 2;
    scene.add(grid);
    const dynamic = new T.Group(),
      rasters = new T.Group();
    scene.add(dynamic, rasters);
    ref.current = {
      scene,
      camera,
      controls,
      terrain,
      renderer,
      dynamic,
      rasters,
    };
    const ray = new T.Raycaster();
    let start = [0, 0];
    const down = (e: PointerEvent) => {
      start = [e.clientX, e.clientY];
    };
    const up = (e: PointerEvent) => {
      if (
        Math.hypot(e.clientX - start[0], e.clientY - start[1]) > 5 ||
        e.button !== 0
      )
        return;
      const rect = renderer.domElement.getBoundingClientRect();
      ray.setFromCamera(
        new T.Vector2(
          ((e.clientX - rect.left) / rect.width) * 2 - 1,
          (-(e.clientY - rect.top) / rect.height) * 2 + 1,
        ),
        camera,
      );
      const target = ray
        .intersectObjects(dynamic.children, true)
        .find((hit) => hit.object.userData.targetId);
      if (target && store.getState().mode === "inspect") {
        store.getState().setSelectedTarget(target.object.userData.targetId);
        return;
      }
      const hit = ray.intersectObject(terrain)[0];
      if (hit)
        store
          .getState()
          .pick(unproject(hit.point.x, -hit.point.z, d.projection));
    };
    renderer.domElement.addEventListener("pointerdown", down);
    renderer.domElement.addEventListener("pointerup", up);
    const lost = (e: Event) => {
      e.preventDefault();
      setFailure("3D context lost. Switch to 2D, then reopen 3D.");
    };
    renderer.domElement.addEventListener("webglcontextlost", lost);
    const resize = () => {
      const { width, height } = el.getBoundingClientRect();
      renderer.setSize(width, height);
      camera.aspect = width / Math.max(1, height);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();
    let frame = 0;
    const render = () => {
      frame = requestAnimationFrame(render);
      controls.update();
      renderer.render(scene, camera);
    };
    render();
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", down);
      renderer.domElement.removeEventListener("pointerup", up);
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      controls.dispose();
      dispose(scene);
      renderer.dispose();
      renderer.domElement.remove();
      ref.current = undefined;
    };
  }, [s.dem, s.exaggeration]);
  useEffect(() => {
    const state = ref.current,
      d = s.dem;
    if (!state || !d) return;
    let live = true;
    const { rasters, terrain } = state;
    const local: T.Mesh[] = [];
    const textures: T.Texture[] = [];
    s.layers.forEach((entry, i) => {
      const l = entry.layer,
        setting = s.layerSettings[l.id];
      if (
        !setting?.visible ||
        entry.coverage === "unavailable" ||
        l.valid_percent <= 0
      )
        return;
      if (
        entry.projection !== "MARS:CANONICAL_ANGULAR" ||
        entry.format !== "image"
      ) {
        store.setState((st) => ({
          layerStatus: {
            ...st.layerStatus,
            [l.id]: "Unsupported 3D layer projection / format",
          },
        }));
        return;
      }
      const b = l.bounds,
        db = d.bounds;
      if (
        Object.keys(db).some(
          (k) =>
            Math.abs(b[k as keyof BoundingBox] - db[k as keyof BoundingBox]) >
            1e-8,
        )
      ) {
        store.setState((st) => ({
          layerStatus: {
            ...st.layerStatus,
            [l.id]: "3D overlay unavailable: bounds do not match DEM",
          },
        }));
        return;
      }
      const texture = new T.TextureLoader().load(
        l.uri,
        () => {
          if (live)
            store.setState((st) => ({
              layerStatus: { ...st.layerStatus, [l.id]: "ready" },
            }));
        },
        undefined,
        () => {
          if (live) {
            mesh.visible = false;
            store.setState((st) => ({
              layerStatus: { ...st.layerStatus, [l.id]: "Image unavailable" },
            }));
          }
        },
      );
      texture.colorSpace = T.SRGBColorSpace;
      textures.push(texture);
      const mat = new T.MeshStandardMaterial({
        map: texture,
        transparent: true,
        opacity: setting.opacity,
        roughness: 1,
        depthWrite: false,
        polygonOffset: true,
        polygonOffsetFactor: -(i + 1),
        side: T.DoubleSide,
      });
      const mesh = new T.Mesh(terrain.geometry, mat);
      mesh.renderOrder = i + 1;
      rasters.add(mesh);
      local.push(mesh);
    });
    return () => {
      live = false;
      local.forEach((m) => {
        rasters.remove(m);
        (m.material as T.Material).dispose();
      });
      textures.forEach((t) => t.dispose());
    };
  }, [s.dem, s.exaggeration, s.layers, s.layerSettings]);
  useEffect(() => {
    const state = ref.current,
      d = s.dem;
    if (!state || !d) return;
    const g = state.dynamic;
    dispose(g);
    g.clear();
    let skipped = 0;
    const pos = (p: LonLat, lift = 8) => {
      const h = heightAt(d, p);
      if (h === null) {
        skipped++;
        return null;
      }
      const [x, y] = project(p, d.projection);
      return new T.Vector3(x, (h - demBase(d)) * s.exaggeration + lift, -y);
    };
    const marker = (p: LonLat, color: string, r = 15, id?: string) => {
      const v = pos(p, 20);
      if (!v) return;
      const sphere = new T.Mesh(
        new T.SphereGeometry(r, 16, 12),
        new T.MeshStandardMaterial({
          color,
          emissive: color,
          emissiveIntensity: 0.3,
        }),
      );
      sphere.position.copy(v);
      if (id) sphere.userData.targetId = id;
      g.add(sphere);
      const ring = new T.Mesh(
        new T.TorusGeometry(r * 1.7, 2, 6, 32),
        new T.MeshBasicMaterial({ color }),
      );
      ring.rotation.x = Math.PI / 2;
      ring.position.copy(v);
      g.add(ring);
    };
    const line = (pts: LonLat[], color: string, radius = 3) => {
      for (let i = 1; i < pts.length; i++) {
        const a = pos(pts[i - 1]),
          b = pos(pts[i]);
        if (!a || !b) continue;
        const direction = new T.Vector3().subVectors(b, a),
          length = direction.length();
        if (!length) continue;
        const mesh = new T.Mesh(
          new T.CylinderGeometry(radius, radius, length, 6),
          new T.MeshBasicMaterial({ color }),
        );
        mesh.position.copy(a).add(b).multiplyScalar(0.5);
        mesh.quaternion.setFromUnitVectors(
          new T.Vector3(0, 1, 0),
          direction.normalize(),
        );
        g.add(mesh);
      }
    };
    const rect = (b: BoundingBox, color: string) => {
      const p = [
        { latitude_deg: b.south_deg, longitude_deg_east: b.west_deg_east },
        { latitude_deg: b.north_deg, longitude_deg_east: b.west_deg_east },
        { latitude_deg: b.north_deg, longitude_deg_east: b.east_deg_east },
        { latitude_deg: b.south_deg, longitude_deg_east: b.east_deg_east },
      ];
      const dense: LonLat[] = [];
      for (let i = 0; i < 4; i++)
        for (let j = 0; j < 40; j++) {
          const a = p[i],
            b = p[(i + 1) % 4],
            t = j / 40;
          dense.push({
            latitude_deg: a.latitude_deg * (1 - t) + b.latitude_deg * t,
            longitude_deg_east:
              a.longitude_deg_east * (1 - t) + b.longitude_deg_east * t,
          });
        }
      dense.push(p[0]);
      line(dense, color, 2);
    };
    if (s.showAlternatives)
      s.alternatives
        .filter((r) => r.feasible && r.id !== s.activeRoute?.id)
        .forEach((r) => line(r.geometry, "#758596", 2));
    if (s.activeRoute?.feasible) {
      line(
        s.activeRoute.geometry,
        s.replan === "pending" ? "#e8ab55" : "#65e2c5",
        5,
      );
      s.activeRoute.waypoints.forEach((p) => marker(p, "#65e2c5", 8));
    }
    if (s.base) marker(s.base, "#c8efff", 22);
    if (s.destination) marker(s.destination, "#f6bd79", 22);
    s.targets.forEach((t) =>
      marker(
        t.location,
        t.id === s.selectedTargetId ? "#fff" : "#bda8fa",
        t.id === s.selectedTargetId ? 27 : 18,
        t.id,
      ),
    );
    if (s.selectedPoint) marker(s.selectedPoint, "#fff", 10);
    if (s.first) marker(s.first, "#ffd28a", 12);
    if (s.draft) rect(s.draft, "#ffd28a");
    s.blockedAreas.forEach((b) => rect(b.bounds, "#f47e72"));
    if (s.navigation) {
      const v = pos(s.navigation.position, 35);
      if (v) {
        const avatar = new T.Mesh(
          new T.ConeGeometry(20, 55, 8),
          new T.MeshStandardMaterial({
            color: "#fff",
            emissive: "#65e2c5",
            emissiveIntensity: 0.4,
          }),
        );
        avatar.rotation.x = -Math.PI / 2;
        const pivot = new T.Group();
        pivot.add(avatar);
        pivot.position.copy(v);
        pivot.rotation.y =
          (-s.navigation.heading_deg_clockwise_from_north * Math.PI) / 180;
        g.add(pivot);
      }
    }
    setMissing(skipped);
    return () => {
      dispose(g);
      g.clear();
    };
  }, [
    s.dem,
    s.exaggeration,
    s.activeRoute,
    s.alternatives,
    s.showAlternatives,
    s.targets,
    s.selectedTargetId,
    s.base,
    s.destination,
    s.selectedPoint,
    s.first,
    s.draft,
    s.blockedAreas,
    s.navigation,
    s.replan,
  ]);
  useEffect(() => {
    const st = ref.current;
    if (st) {
      const home = s.dem ? homeView(s.dem, s.exaggeration) : null;
      st.camera.position.set(...(home?.pos ?? [2700, 2700, 3000]));
      st.controls.target.set(...(home?.target ?? [0, 50, 0]));
    }
  }, [s.focus]);
  useEffect(() => {
    const st = ref.current,
      d = s.dem,
      t = s.targets.find((t) => t.id === s.selectedTargetId);
    if (st && d && t) {
      const h = heightAt(d, t.location);
      if (h !== null) {
        const [x, y] = project(t.location, d.projection);
        st.controls.target.set(x, (h - demBase(d)) * s.exaggeration, -y);
      }
    }
  }, [s.selectedTargetId, s.targets, s.dem, s.exaggeration]);
  return (
    <div className="terrain-wrap">
      <div className="map-surface" ref={host} data-testid="terrain-3d" />
      {(!s.dem || failure) && (
        <div className="empty-view">
          <span>△</span>
          <h2>3D terrain unavailable</h2>
          <p>
            {failure ||
              "No processed elevation grid is loaded. The 2D view remains available."}
          </p>
          <button onClick={() => s.setView("2d")}>Return to 2D</button>
        </div>
      )}
      {!!s.dem && !failure && (
        <div className="terrain-note">
          DEM-derived surface · {s.exaggeration}× height
          <br />
          Drag to orbit · Right-drag to pan · Scroll to zoom
          {missing > 0 && (
            <>
              <br />
              Some geometry omitted outside valid DEM coverage
            </>
          )}
        </div>
      )}
    </div>
  );
}
