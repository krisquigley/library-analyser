// The halo around the current track's node in the 3D scene (#146): a translucent shell that never takes a pick.
// It keeps only the halo it last mounted and the node mesh it follows, so a steady selection costs no scene walk.

const HALO_NAME = 'selected-node-halo';
const HALO_SCALE = 1.3;
const HALO_MATERIAL = Object.freeze({transparent: true, opacity: 0.25, depthWrite: false, depthTest: false});
const HALO_COLOR = '#f8f7ff';
const HALO_COLOR_ON_WHITE = '#ffcc66';

export function graphObjectTrackId(object) {
  const data = (object && (object.__data || object.userData)) || {};
  return data.id || data.trackId || data.track_id || (data.node && data.node.id) || null;
}

export function findSceneObject(root, predicate) {
  if (!root) return null;
  if (predicate(root)) return root;
  for (const child of sceneChildren(root)) {
    const found = findSceneObject(child, predicate);
    if (found) return found;
  }
  return null;
}

export function createSelectedNodeHalo() {
  let mounted = null;

  function dispose() {
    const halo = mounted && mounted.mesh;
    if (halo) removeHalo(halo, mounted.scene);
    mounted = null;
  }

  function cachedNodeMesh(graph, scene, trackId) {
    if (!mounted || mounted.graph !== graph || mounted.scene !== scene || mounted.trackId !== trackId) return null;
    if (detached(mounted.mesh)) return null;
    return detached(mounted.nodeMesh) ? null : mounted.nodeMesh;
  }

  function sync(graph, nodes, trackId) {
    if (typeof graph?.scene !== 'function') return none();
    const node = trackId ? nodes.find(each => each.id === trackId) : null;
    const scene = graph.scene();
    if (!node || typeof scene?.add !== 'function') return none();
    const cached = cachedNodeMesh(graph, scene, trackId);
    if (cached) {
      placeHalo(mounted.mesh, node, cached);
      return mounted.mesh;
    }
    dispose();
    const nodeMesh = findSceneObject(scene, object => object !== scene && graphObjectTrackId(object) === trackId
      && !isHalo(object) && object.geometry && object.material);
    const halo = buildHalo(scene, node, nodeMesh);
    if (!halo) return null;
    placeHalo(halo, node, nodeMesh);
    scene.add(halo);
    mounted = {graph, scene, mesh: halo, trackId, nodeMesh: nodeMesh || null};
    return halo;
  }

  function none() {
    dispose();
    return null;
  }

  return Object.freeze({sync, clear: dispose, current: () => mounted});
}

function sceneChildren(root) {
  return root && Array.isArray(root.children) ? root.children : [];
}

function isHalo(object) {
  return object.name === HALO_NAME || object.userData?.role === HALO_NAME;
}

function detached(object) {
  return !object || object.disposed || object.parent === null;
}

function removeHalo(halo, scene) {
  if (typeof halo.parent?.remove === 'function') halo.parent.remove(halo);
  else if (typeof scene?.remove === 'function') scene.remove(halo);
  halo.geometry?.dispose?.();
  halo.material?.dispose?.();
  halo.disposed = true;
}

// The vendor bundles THREE privately, so the halo reuses the constructors of the node mesh it surrounds and
// shares that exact THREE instance. A real scene without one gets no halo; a plain test scene gets a stand-in.
function buildHalo(scene, node, nodeMesh) {
  const three = nodeMesh && nodeMesh.__THREE;
  const Geometry = (three && three.SphereGeometry) || nodeMesh?.geometry?.constructor;
  const Material = (three && three.MeshBasicMaterial) || nodeMesh?.material?.constructor;
  const Mesh = (three && three.Mesh) || nodeMesh?.constructor;
  if (!(Geometry && Material && Mesh)) return scene.isScene || scene.type === 'Scene' ? null : standInHalo(node);
  const color = node.color === HALO_COLOR ? HALO_COLOR_ON_WHITE : HALO_COLOR;
  const halo = new Mesh(new Geometry(haloRadius(nodeMesh), 32, 16), new Material({color, ...HALO_MATERIAL}));
  halo.name = HALO_NAME;
  halo.userData = {...(halo.userData || {}), role: HALO_NAME, trackId: node.id};
  halo.raycast = () => {};
  return halo;
}

function standInHalo(node) {
  const disposable = properties => ({...properties, dispose() { this.disposed = true; }});
  return {name: HALO_NAME, userData: {role: HALO_NAME, trackId: node.id}, geometry: disposable({radius: HALO_SCALE}),
    material: disposable({color: HALO_COLOR, ...HALO_MATERIAL}), position: {set(x, y, z) { Object.assign(this, {x, y, z}); }},
    scale: {setScalar(value) { this.value = value; }}, raycast() {}};
}

function haloRadius(nodeMesh) {
  const geometry = nodeMesh && nodeMesh.geometry;
  const base = Number.isFinite(geometry?.radius) ? geometry.radius
    : (Number.isFinite(geometry?.parameters?.radius) ? geometry.parameters.radius : 1);
  const scale = nodeMesh && nodeMesh.scale;
  const scalar = scale && (Number.isFinite(scale.value) ? scale.value
    : (Number.isFinite(scale.x) ? Math.max(scale.x, scale.y || scale.x, scale.z || scale.x) : 1));
  return Math.max(1, (base || 1) * (scalar || 1)) * HALO_SCALE;
}

// The node mesh's live position, once mounted; until then the node's own coordinates.
function placeHalo(halo, node, nodeMesh) {
  const source = nodeMesh && nodeMesh.position;
  const [x, y, z] = ['x', 'y', 'z'].map(axis => (Number.isFinite(source?.[axis]) ? source[axis] : node[axis]));
  if (typeof halo.position?.set === 'function') halo.position.set(x, y, z);
  else halo.position = {x, y, z};
}
