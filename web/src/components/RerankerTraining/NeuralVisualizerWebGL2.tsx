import { useLayoutEffect, useMemo, useRef } from 'react';
import { Canvas, extend, ReactThreeFiber, useThree } from '@react-three/fiber';
import { Bloom, ChromaticAberration, EffectComposer, Noise } from '@react-three/postprocessing';
import { Environment, Grid, OrbitControls, Stars } from '@react-three/drei';
import * as THREE from 'three';
import { Vector2 } from 'three';

class TrajectoryMaterial extends THREE.ShaderMaterial {
  constructor() {
    super({
      uniforms: {
        coolColor: { value: new THREE.Color('#22ecff') },
        hotColor: { value: new THREE.Color('#ff4b6f') },
        opacity: { value: 0.9 },
      },
      vertexShader: `
        varying vec2 vUv;
        varying float vPathIntensity;
        attribute float pathIntensity;
        void main() {
          vUv = uv;
          vPathIntensity = pathIntensity;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform vec3 coolColor;
        uniform vec3 hotColor;
        uniform float opacity;
        varying vec2 vUv;
        varying float vPathIntensity;

        void main() {
          float intensity = clamp(vPathIntensity, 0.0, 1.0);
          vec3 baseColor = mix(hotColor, coolColor, intensity);
          float edgeGlow = 1.0 - smoothstep(0.0, 0.48, abs(vUv.y - 0.5));
          vec3 finalColor = baseColor * (0.78 + intensity * 0.22) + vec3(edgeGlow * 0.09);
          gl_FragColor = vec4(finalColor, opacity);
        }
      `,
      transparent: true,
      side: THREE.DoubleSide,
      depthWrite: true,
    });
  }
}
extend({ TrajectoryMaterial });

declare global {
  namespace JSX {
    interface IntrinsicElements {
      trajectoryMaterial: ReactThreeFiber.Object3DNode<TrajectoryMaterial, typeof TrajectoryMaterial>;
    }
  }
}

export type NeuralRenderPoint = {
  x: number;
  y: number;
  z: number;
  intensity: number;
};

type Quality = 'balanced' | 'cinematic' | 'ultra';

type Domain = {
  cx: number;
  cy: number;
  span: number;
};

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function computeDomain(points: NeuralRenderPoint[]): Domain {
  if (!points.length) return { cx: 0, cy: 0, span: 2.4 };
  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const p of points) {
    minX = Math.min(minX, p.x);
    maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y);
    maxY = Math.max(maxY, p.y);
  }
  const cx = (minX + maxX) * 0.5;
  const cy = (minY + maxY) * 0.5;
  const span = Math.max(maxX - minX, maxY - minY, 1.6);
  return { cx, cy, span };
}

function decimatePoints(points: NeuralRenderPoint[], maxPoints: number): NeuralRenderPoint[] {
  if (points.length <= maxPoints) return points;
  const stride = Math.max(1, Math.ceil(points.length / maxPoints));
  const out: NeuralRenderPoint[] = [];
  for (let i = 0; i < points.length; i += stride) out.push(points[i]);
  const last = points[points.length - 1];
  if (out[out.length - 1] !== last) out.push(last);
  return out;
}

function createHeightMap(points: NeuralRenderPoint[], domain: Domain, quality: Quality): (x: number, y: number) => number {
  const terrainPoints = decimatePoints(points, quality === 'ultra' ? 96 : quality === 'cinematic' ? 72 : 56);
  if (!terrainPoints.length) return () => 0;

  let sumNearest = 0;
  for (let i = 0; i < terrainPoints.length; i += 1) {
    const a = terrainPoints[i];
    let best = Number.POSITIVE_INFINITY;
    for (let j = 0; j < terrainPoints.length; j += 1) {
      if (i === j) continue;
      const b = terrainPoints[j];
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const d2 = dx * dx + dy * dy;
      if (d2 < best) best = d2;
    }
    sumNearest += Math.sqrt(best);
  }
  const meanNearest = sumNearest / Math.max(1, terrainPoints.length);
  const sigmaMul = quality === 'ultra' ? 2.25 : quality === 'cinematic' ? 2.45 : 2.65;
  const sigma = clamp(meanNearest * sigmaMul, 0.08, domain.span * 0.26);
  const sigmaSq = Math.max(1e-6, sigma * sigma);
  const broadSigma = sigma * 3.6;
  const broadSigmaSq = Math.max(1e-6, broadSigma * broadSigma);
  let zMin = Number.POSITIVE_INFINITY;
  let zMax = Number.NEGATIVE_INFINITY;
  for (const p of terrainPoints) {
    zMin = Math.min(zMin, p.z);
    zMax = Math.max(zMax, p.z);
  }
  const zRange = Math.max(1e-6, zMax - zMin);
  const qualityAmp = quality === 'ultra' ? 1.0 : quality === 'cinematic' ? 0.94 : 0.88;
  const amp = clamp(zRange * 0.32, 0.24, 0.62) * qualityAmp;

  return (x: number, y: number): number => {
    let fineWeighted = 0;
    let fineWeight = 0;
    let broadWeighted = 0;
    let broadWeight = 0;

    for (const p of terrainPoints) {
      const dx = x - p.x;
      const dy = y - p.y;
      const distSq = dx * dx + dy * dy;

      const fineW = Math.exp(-(distSq / (2 * sigmaSq)));
      const broadW = Math.exp(-(distSq / (2 * broadSigmaSq)));
      fineWeighted += fineW * p.z;
      fineWeight += fineW;
      broadWeighted += broadW * p.z;
      broadWeight += broadW;
    }

    // Avoid hard cutoffs: far from the trajectory, weights smoothly -> 0, so height smoothly -> 0.
    const fine = fineWeighted / (fineWeight + 1e-6);
    const broad = broadWeighted / (broadWeight + 1e-6);
    const blended = broad * 0.62 + fine * 0.38;
    const compressed = Math.tanh(blended * 1.34);
    const density = broadWeight / (broadWeight + 0.65);

    return compressed * amp * density;
  };
}

function OptimizationPath({
  points,
  heightAt,
}: {
  points: NeuralRenderPoint[];
  heightAt: (x: number, y: number) => number;
}) {
  const geometry = useMemo(() => {
    if (points.length < 2) return null;

    let minX = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    for (const p of points) {
      minX = Math.min(minX, p.x);
      maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y);
      maxY = Math.max(maxY, p.y);
    }
    const localSpan = Math.max(maxX - minX, maxY - minY, 1.0);
    const radius = clamp(localSpan * 0.0032, 0.0032, 0.0054);
    const lift = clamp(radius * 0.3, 0.0012, 0.0024);
    const xyVectors = points.map((p) => new THREE.Vector3(p.x, p.y, 0));
    const xyCurve = new THREE.CatmullRomCurve3(xyVectors, false, 'centripetal', 0.5);

    const tubularSegments = Math.max(64, points.length * 10);
    const radialSegments = 12;
    const ringVertexCount = radialSegments + 1;
    const tube = new THREE.TubeGeometry(xyCurve, tubularSegments, radius, radialSegments, false);
    const intensities = new Float32Array((tubularSegments + 1) * ringVertexCount);
    const lastIdx = Math.max(1, points.length - 1);
    for (let ring = 0; ring <= tubularSegments; ring += 1) {
      const t = ring / Math.max(1, tubularSegments);
      const srcIdx = t * lastIdx;
      const idx0 = Math.floor(srcIdx);
      const idx1 = Math.min(lastIdx, idx0 + 1);
      const frac = srcIdx - idx0;
      const p0 = points[idx0];
      const p1 = points[idx1];
      const pathIntensity = clamp(p0.intensity + (p1.intensity - p0.intensity) * frac, 0, 1);
      for (let v = 0; v < ringVertexCount; v += 1) {
        intensities[ring * ringVertexCount + v] = pathIntensity;
      }
    }
    tube.setAttribute('pathIntensity', new THREE.Float32BufferAttribute(intensities, 1));

    // Lift the whole tube onto the terrain while preserving the tube's local radial offsets.
    const pos = tube.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < pos.count; i += 1) {
      const x = pos.getX(i);
      const y = pos.getY(i);
      const z = pos.getZ(i);
      pos.setZ(i, z + heightAt(x, y) + lift);
    }
    pos.needsUpdate = true;
    tube.computeVertexNormals();

    return tube;
  }, [heightAt, points]);

  if (!geometry) return null;

  return (
    <mesh geometry={geometry}>
      <trajectoryMaterial />
    </mesh>
  );
}

function GlassTerrain({
  domain,
  heightAt,
  quality,
}: {
  domain: Domain;
  heightAt: (x: number, y: number) => number;
  quality: Quality;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const resolution = quality === 'ultra' ? 200 : quality === 'cinematic' ? 140 : 96;
  const size = domain.span * 3.2;

  useLayoutEffect(() => {
    if (!meshRef.current) return;
    const geo = meshRef.current.geometry as THREE.BufferGeometry;
    const pos = geo.attributes.position as THREE.BufferAttribute;

    for (let i = 0; i < pos.count; i += 1) {
      const lx = pos.getX(i);
      const ly = pos.getY(i);
      const x = lx + domain.cx;
      const y = ly + domain.cy;
      pos.setZ(i, heightAt(x, y));
    }

    pos.needsUpdate = true;
    geo.computeVertexNormals();
  }, [domain.cx, domain.cy, heightAt, resolution]);

  return (
    <mesh ref={meshRef} position={[domain.cx, domain.cy, 0]}>
      <planeGeometry args={[size, size, resolution, resolution]} />
      <meshPhysicalMaterial
        color="#86caff"
        transmission={0.2}
        opacity={1}
        metalness={0.03}
        roughness={0.4}
        ior={1.45}
        thickness={0.68}
        specularIntensity={1}
        envMapIntensity={0.8}
        clearcoat={0.22}
        clearcoatRoughness={0.52}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

export function TrajectoryScene({
  points,
  terrainPoints,
  quality,
  motionIntensity,
  reduceMotion,
  showVectorField,
  enablePostprocessing = true,
  resetSignal = 0,
}: {
  points: NeuralRenderPoint[];
  terrainPoints?: NeuralRenderPoint[];
  quality: Quality;
  motionIntensity: number;
  reduceMotion: boolean;
  showVectorField: boolean;
  enablePostprocessing?: boolean;
  resetSignal?: number;
}) {
  const { camera } = useThree();
  const controlsRef = useRef<any>(null);
  const userInteractedRef = useRef(false);

  const terrainSrc = terrainPoints && terrainPoints.length ? terrainPoints : points;
  const domain = useMemo(() => computeDomain(terrainSrc), [terrainSrc]);
  const heightAt = useMemo(() => createHeightMap(terrainSrc, domain, quality), [domain, terrainSrc, quality]);
  const target = useMemo(() => new THREE.Vector3(domain.cx, 0, -domain.cy), [domain.cx, domain.cy]);

  const motionScale = reduceMotion ? 1.0 : clamp(motionIntensity, 0.0, 2.0);
  const bloomBase = quality === 'ultra' ? 1.05 : quality === 'cinematic' ? 0.85 : 0.6;
  const bloomIntensity = bloomBase * (0.85 + motionScale * 0.15);
  const aberrationBase = quality === 'ultra' ? 0.0022 : quality === 'cinematic' ? 0.0018 : 0.0012;
  const aberration = aberrationBase * (0.75 + motionScale * 0.25);

  const applyAutoFrame = useMemo(() => {
    return () => {
      const controls = controlsRef.current;
      if (!controls) return;

      const spanSafe = Math.max(1.0, domain.span);
      const distance = clamp(2.05 + spanSafe * 0.82, 2.2, 6.2);
      const height = clamp(1.05 + spanSafe * 0.35, 1.1, 3.8);

      controls.target.set(target.x, 0, target.z);
      camera.position.set(target.x, height, target.z + distance);
      camera.lookAt(controls.target);
      controls.update?.();
      controls.saveState?.();
    };
  }, [camera, domain.span, target.x, target.z]);

  useLayoutEffect(() => {
    if (userInteractedRef.current) return;
    applyAutoFrame();
  }, [applyAutoFrame, domain.cx, domain.cy, domain.span]);

  useLayoutEffect(() => {
    userInteractedRef.current = false;
    applyAutoFrame();
  }, [applyAutoFrame, resetSignal]);

  return (
    <>
      <Environment preset="city" blur={0.8} background={false} />

      <ambientLight intensity={0.18} />
      <pointLight position={[2.2, 2.0, 2.1]} intensity={1.15} color="#00d5ff" />
      <pointLight position={[-2.0, 1.0, -1.6]} intensity={0.55} color="#ff0066" />

      {showVectorField && !reduceMotion ? (
        <Stars
          radius={7}
          depth={2}
          count={quality === 'ultra' ? 1200 : 800}
          factor={0.02}
          fade
          speed={0.08 + motionScale * 0.06}
        />
      ) : null}

      <Grid
        position={[target.x, -0.42, target.z]}
        args={[10, 10]}
        cellSize={0.12}
        cellThickness={0.9}
        cellColor="#1f3a52"
        sectionSize={1.2}
        sectionThickness={1.4}
        sectionColor="#3e7aa1"
        fadeDistance={5}
        fadeStrength={1.6}
        infiniteGrid
      />

      <group rotation={[-Math.PI / 2, 0, 0]}>
        <GlassTerrain domain={domain} heightAt={heightAt} quality={quality} />
        <OptimizationPath
          points={points}
          heightAt={heightAt}
        />
      </group>

      <OrbitControls
        ref={controlsRef}
        makeDefault
        enableDamping
        dampingFactor={0.08}
        rotateSpeed={0.85}
        zoomSpeed={0.9}
        panSpeed={0.85}
        screenSpacePanning={false}
        maxPolarAngle={1.32}
        minPolarAngle={0.42}
        minDistance={0.9}
        maxDistance={10}
        onStart={() => {
          userInteractedRef.current = true;
        }}
      />

      {enablePostprocessing && !reduceMotion ? (
        <EffectComposer enableNormalPass={false}>
          <Bloom luminanceThreshold={0.75} mipmapBlur intensity={bloomIntensity} radius={0.6} />
          <ChromaticAberration
            offset={new Vector2(aberration, aberration)}
            radialModulation={false}
            modulationOffset={0}
          />
          <Noise opacity={0.02} />
        </EffectComposer>
      ) : null}
    </>
  );
}

export function NeuralVisualizerWebGL2({
  points,
  terrainPoints,
  quality,
  motionIntensity,
  reduceMotion,
  showVectorField,
  resetSignal = 0,
}: {
  points: NeuralRenderPoint[];
  terrainPoints?: NeuralRenderPoint[];
  quality: Quality;
  motionIntensity: number;
  reduceMotion: boolean;
  showVectorField: boolean;
  resetSignal?: number;
}) {
  return (
    <Canvas
      className="neural-canvas active"
      camera={{ position: [0.0, 1.55, 2.65], fov: 45, near: 0.01, far: 60 }}
      gl={{
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance',
      }}
      dpr={[1, 2]}
      onCreated={({ gl }) => {
        gl.toneMapping = THREE.ReinhardToneMapping;
        gl.toneMappingExposure = 1.35;
        gl.setClearColor(0x050712, 1);
      }}
    >
      <TrajectoryScene
        points={points}
        terrainPoints={terrainPoints}
        quality={quality}
        motionIntensity={motionIntensity}
        reduceMotion={reduceMotion}
        showVectorField={showVectorField}
        resetSignal={resetSignal}
      />
    </Canvas>
  );
}
