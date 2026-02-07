import { useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import * as THREE from 'three';
import type { NeuralRenderPoint } from './NeuralVisualizerWebGL2';
import { TrajectoryScene } from './NeuralVisualizerWebGL2';

type Quality = 'balanced' | 'cinematic' | 'ultra';

type WebGPUState = {
  module: any | null;
  failed: boolean;
};

export function NeuralVisualizerWebGPU({
  points,
  terrainPoints,
  quality,
  motionIntensity,
  reduceMotion,
  showVectorField,
  resetSignal = 0,
  onFallback,
}: {
  points: NeuralRenderPoint[];
  terrainPoints?: NeuralRenderPoint[];
  quality: Quality;
  motionIntensity: number;
  reduceMotion: boolean;
  showVectorField: boolean;
  resetSignal?: number;
  onFallback?: () => void;
}) {
  const [webgpuState, setWebgpuState] = useState<WebGPUState>({ module: null, failed: false });

  useEffect(() => {
    let cancelled = false;

    void import('three/webgpu')
      .then((mod) => {
        if (cancelled) return;
        setWebgpuState({ module: mod, failed: false });
      })
      .catch(() => {
        if (cancelled) return;
        setWebgpuState({ module: null, failed: true });
        onFallback?.();
      });

    return () => {
      cancelled = true;
    };
  }, [onFallback]);

  const createRenderer = useMemo(() => {
    const WebGPU = webgpuState.module;
    if (!WebGPU || webgpuState.failed) return null;

    return (props: any) => {
      try {
        const RendererCtor = (WebGPU as any).WebGPURenderer;
        if (!RendererCtor) throw new Error('WebGPURenderer missing');
        const renderer = new RendererCtor({
          canvas: props.canvas,
          antialias: true,
          alpha: true,
        });
        if (typeof renderer.setClearColor === 'function') {
          renderer.setClearColor(0x000000, 0);
        }
        return renderer;
      } catch {
        onFallback?.();
        const fallback = new THREE.WebGLRenderer({ ...(props as any), alpha: true });
        fallback.setClearColor(0x000000, 0);
        return fallback;
      }
    };
  }, [onFallback, webgpuState.failed, webgpuState.module]);

  if (!createRenderer) {
    return <div className="neural-renderer-loading">Initializing WebGPU renderer…</div>;
  }

  return (
    <Canvas className="neural-canvas active" camera={{ position: [0, 0, 2.5], fov: 42 }} gl={createRenderer as any}>
      <TrajectoryScene
        points={points}
        terrainPoints={terrainPoints}
        quality={quality}
        motionIntensity={motionIntensity}
        reduceMotion={reduceMotion}
        showVectorField={showVectorField}
        enablePostprocessing={false}
        resetSignal={resetSignal}
      />
    </Canvas>
  );
}
