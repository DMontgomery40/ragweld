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
  quality,
  motionIntensity,
  reduceMotion,
  showVectorField,
  onFallback,
}: {
  points: NeuralRenderPoint[];
  quality: Quality;
  motionIntensity: number;
  reduceMotion: boolean;
  showVectorField: boolean;
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
        return new RendererCtor({
          canvas: props.canvas,
          antialias: true,
          alpha: true,
        });
      } catch {
        onFallback?.();
        return new THREE.WebGLRenderer(props as any);
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
        quality={quality}
        motionIntensity={motionIntensity}
        reduceMotion={reduceMotion}
        showVectorField={showVectorField}
        enablePostprocessing={false}
      />
    </Canvas>
  );
}
