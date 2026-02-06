import { useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Bloom, EffectComposer } from '@react-three/postprocessing';
import { Grid, Line, Stars } from '@react-three/drei';
import { Vector3 } from 'three';

export type NeuralRenderPoint = {
  x: number;
  y: number;
  intensity: number;
};

type Quality = 'balanced' | 'cinematic' | 'ultra';

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

export function TrajectoryScene({
  points,
  quality,
  motionIntensity,
  reduceMotion,
  showVectorField,
  enablePostprocessing = true,
}: {
  points: NeuralRenderPoint[];
  quality: Quality;
  motionIntensity: number;
  reduceMotion: boolean;
  showVectorField: boolean;
  enablePostprocessing?: boolean;
}) {
  const groupRef = useRef<any>(null);

  const linePoints = useMemo(() => points.map((p) => new Vector3(p.x, p.y, 0)), [points]);

  const positions = useMemo(() => {
    const out = new Float32Array(points.length * 3);
    for (let i = 0; i < points.length; i += 1) {
      const p = points[i];
      out[i * 3 + 0] = p.x;
      out[i * 3 + 1] = p.y;
      out[i * 3 + 2] = 0.02 * p.intensity;
    }
    return out;
  }, [points]);

  const colors = useMemo(() => {
    const out = new Float32Array(points.length * 3);
    for (let i = 0; i < points.length; i += 1) {
      const v = points[i].intensity;
      const r = 0.12 + 0.28 * v;
      const g = 0.62 + 0.38 * v;
      const b = 0.82 + 0.16 * v;
      out[i * 3 + 0] = r;
      out[i * 3 + 1] = g;
      out[i * 3 + 2] = b;
    }
    return out;
  }, [points]);

  useFrame((state) => {
    if (reduceMotion || !groupRef.current) return;
    const t = state.clock.elapsedTime;
    const motion = clamp(motionIntensity, 0, 2);
    groupRef.current.rotation.z = Math.sin(t * 0.12) * 0.013 * motion;
  });

  const bloomIntensity = quality === 'ultra' ? 1.12 : quality === 'cinematic' ? 0.78 : 0.0;
  const pointSize = quality === 'ultra' ? 0.048 : quality === 'cinematic' ? 0.038 : 0.028;

  return (
    <>
      <color attach="background" args={['#040915']} />
      <ambientLight intensity={0.55} />
      <pointLight position={[1.4, 1.8, 2.8]} intensity={1.05} color="#46e5ff" />
      <pointLight position={[-1.8, -1.2, 2.2]} intensity={0.35} color="#3a5fff" />

      <Grid
        args={[5.2, 5.2]}
        cellSize={0.22}
        cellThickness={0.45}
        cellColor="#2b3f63"
        sectionSize={1.1}
        sectionThickness={0.8}
        sectionColor="#4ca3d0"
        position={[0, 0, -0.18]}
        fadeDistance={8}
        fadeStrength={1.0}
        infiniteGrid={false}
      />

      {showVectorField && !reduceMotion ? (
        <Stars radius={2.3} depth={1.4} count={quality === 'ultra' ? 1100 : 700} factor={0.02} fade speed={0.35} />
      ) : null}

      <group ref={groupRef}>
        {linePoints.length > 1 ? (
          <Line
            points={linePoints}
            color="#5fe9ff"
            transparent
            opacity={0.92}
            lineWidth={2.0}
          />
        ) : null}

        {points.length > 0 ? (
          <points>
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[positions, 3]} />
              <bufferAttribute attach="attributes-color" args={[colors, 3]} />
            </bufferGeometry>
            <pointsMaterial
              size={pointSize}
              sizeAttenuation
              vertexColors
              transparent
              opacity={0.95}
              depthWrite={false}
            />
          </points>
        ) : null}
      </group>

      {enablePostprocessing && !reduceMotion && bloomIntensity > 0 ? (
        <EffectComposer multisampling={0}>
          <Bloom
            intensity={bloomIntensity}
            luminanceThreshold={0.2}
            luminanceSmoothing={0.25}
            mipmapBlur
          />
        </EffectComposer>
      ) : null}
    </>
  );
}

export function NeuralVisualizerWebGL2({
  points,
  quality,
  motionIntensity,
  reduceMotion,
  showVectorField,
}: {
  points: NeuralRenderPoint[];
  quality: Quality;
  motionIntensity: number;
  reduceMotion: boolean;
  showVectorField: boolean;
}) {
  return (
    <Canvas className="neural-canvas active" camera={{ position: [0, 0, 2.5], fov: 42 }}>
      <TrajectoryScene
        points={points}
        quality={quality}
        motionIntensity={motionIntensity}
        reduceMotion={reduceMotion}
        showVectorField={showVectorField}
      />
    </Canvas>
  );
}
