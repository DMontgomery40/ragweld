import { type MutableRefObject, useEffect, useMemo, useRef, useState } from 'react';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { NeuralVisualizerCanvas2D } from './NeuralVisualizerCanvas2D';
import { NeuralVisualizerWebGL2, type NeuralRenderPoint } from './NeuralVisualizerWebGL2';
import { NeuralVisualizerWebGPU } from './NeuralVisualizerWebGPU';

export type TelemetryPoint = {
  x: number;
  y: number;
  step: number;
  loss: number;
  lr: number;
  gradNorm: number;
  ts: string;
};

type Quality = 'balanced' | 'cinematic' | 'ultra';
type RendererPreference = 'auto' | 'webgpu' | 'webgl2' | 'canvas2d';
type IntensityMode = 'absolute' | 'delta';

type Props = {
  pointsRef: MutableRefObject<TelemetryPoint[]>;
  pointCount: number;
  rendererPreference?: RendererPreference;
  quality?: Quality;
  targetFps?: number;
  tailSeconds?: number;
  motionIntensity?: number;
  reduceMotion?: boolean;
  showVectorField?: boolean;
  intensityMode?: IntensityMode;
  bestTrainLoss?: number | null;
  bestTrainLossStep?: number | null;
  lastTrainLoss?: number | null;
  lastTrainLossStep?: number | null;
};

type Vec2 = { x: number; y: number };

function formatLossChip(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const n = Number(v);
  if (n === 0) return '0.0000';
  if (Math.abs(n) < 1) return n.toFixed(4);
  return n.toFixed(3);
}

type ProjectionMeta = {
  degenerateProjection: boolean;
  droppedPoints: number;
};

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function quantile(sorted: number[], q: number): number {
  if (!sorted.length) return Number.NaN;
  const qq = clamp(q, 0, 1);
  const pos = qq * (sorted.length - 1);
  const base = Math.floor(pos);
  const rest = pos - base;
  const a = sorted[base];
  const b = sorted[Math.min(sorted.length - 1, base + 1)];
  return a + (b - a) * rest;
}

function projectPoints(
  points: TelemetryPoint[],
  zoom: number,
  pan: Vec2,
  intensityMode: IntensityMode
): { projected: NeuralRenderPoint[]; meta: ProjectionMeta } {
  if (!points.length) {
    return {
      projected: [],
      meta: { degenerateProjection: false, droppedPoints: 0 },
    };
  }

  const finitePoints = points.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  const droppedPoints = points.length - finitePoints.length;
  if (!finitePoints.length) {
    return {
      projected: [],
      meta: { degenerateProjection: false, droppedPoints },
    };
  }

  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  let minLoss = Number.POSITIVE_INFINITY;
  let maxLoss = Number.NEGATIVE_INFINITY;
  let minGrad = Number.POSITIVE_INFINITY;
  let maxGrad = Number.NEGATIVE_INFINITY;

  const losses: number[] = [];
  const grads: number[] = [];
  for (const p of finitePoints) {
    minX = Math.min(minX, p.x);
    maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y);
    maxY = Math.max(maxY, p.y);
    minLoss = Math.min(minLoss, p.loss);
    maxLoss = Math.max(maxLoss, p.loss);
    minGrad = Math.min(minGrad, p.gradNorm);
    maxGrad = Math.max(maxGrad, p.gradNorm);
    if (Number.isFinite(p.loss)) losses.push(p.loss);
    if (Number.isFinite(p.gradNorm)) grads.push(p.gradNorm);
  }

  const coordRangeX = maxX - minX;
  const coordRangeY = maxY - minY;
  if (coordRangeX < 1e-12 && coordRangeY < 1e-12) {
    return {
      projected: [],
      meta: { degenerateProjection: true, droppedPoints },
    };
  }

  const padX = (maxX - minX) * 0.1 || 1.0;
  const padY = (maxY - minY) * 0.1 || 1.0;
  minX -= padX;
  maxX += padX;
  minY -= padY;
  maxY += padY;

  const rangeX = Math.max(1e-9, maxX - minX);
  const rangeY = Math.max(1e-9, maxY - minY);

  // Robustly center/scale loss + grad to avoid single outliers turning the whole surface into a moat.
  losses.sort((a, b) => a - b);
  grads.sort((a, b) => a - b);

  const lossP10 = Number.isFinite(losses[0]) ? quantile(losses, 0.1) : minLoss;
  const lossP50 = Number.isFinite(losses[0]) ? quantile(losses, 0.5) : (minLoss + maxLoss) * 0.5;
  const lossP90 = Number.isFinite(losses[0]) ? quantile(losses, 0.9) : maxLoss;
  const lossScale = Math.max(1e-9, (lossP90 - lossP10) / 2.0);

  const gradP10 = Number.isFinite(grads[0]) ? quantile(grads, 0.1) : minGrad;
  const gradP50 = Number.isFinite(grads[0]) ? quantile(grads, 0.5) : (minGrad + maxGrad) * 0.5;
  const gradP90 = Number.isFinite(grads[0]) ? quantile(grads, 0.9) : maxGrad;
  const gradScale = Math.max(1e-9, (gradP90 - gradP10) / 2.0);

  const projected = finitePoints.map((p) => {
    const nx = ((p.x - minX) / rangeX) * 2.0 - 1.0;
    const ny = ((p.y - minY) / rangeY) * 2.0 - 1.0;
    const lossCentered = clamp((p.loss - lossP50) / lossScale, -1.0, 1.0);
    const gradCentered = clamp((p.gradNorm - gradP50) / gradScale, -1.0, 1.0);
    void gradCentered;

    // Height should be interpretable: loss landscape (higher = worse).
    // Intensity should read as "better": lower loss => brighter.
    const z = lossCentered;

    return {
      x: (nx + pan.x) * zoom,
      y: (ny + pan.y) * zoom,
      z,
      intensity: 0,
    };
  });

  if (intensityMode === 'absolute') {
    for (let i = 0; i < projected.length; i += 1) {
      const lossNorm = (projected[i].z + 1.0) * 0.5;
      const gradCentered = clamp((finitePoints[i].gradNorm - gradP50) / gradScale, -1.0, 1.0);
      const gradNorm = (gradCentered + 1.0) * 0.5;
      projected[i].intensity = clamp((1.0 - lossNorm) * 0.85 + gradNorm * 0.15, 0.0, 1.0);
    }
  } else {
    // Delta mode: emphasize improvement/regression relative to previous step.
    // Improvement (loss decreasing) => brighter/cooler; regression => hotter.
    let prevLoss = finitePoints[0].loss;
    const deltas: number[] = new Array(finitePoints.length).fill(0);
    for (let i = 0; i < finitePoints.length; i += 1) {
      const loss = finitePoints[i].loss;
      deltas[i] = Number.isFinite(loss) && Number.isFinite(prevLoss) ? prevLoss - loss : 0;
      prevLoss = loss;
    }
    const sorted = [...deltas].sort((a, b) => a - b);
    const dP10 = quantile(sorted, 0.1);
    const dP90 = quantile(sorted, 0.9);
    const scale = Math.max(1e-9, (dP90 - dP10) / 2.0);
    const mid = (dP10 + dP90) * 0.5;
    for (let i = 0; i < projected.length; i += 1) {
      const d = clamp((deltas[i] - mid) / scale, -1.0, 1.0);
      projected[i].intensity = (d + 1.0) * 0.5;
    }
  }

  return {
    projected,
    meta: { degenerateProjection: false, droppedPoints },
  };
}

function chooseRendererMode({
  preference,
  webgpuAvailable,
  webgl2Available,
  webgpuFailed,
}: {
  preference: RendererPreference;
  webgpuAvailable: boolean;
  webgl2Available: boolean;
  webgpuFailed: boolean;
}): 'webgpu' | 'webgl2' | 'canvas2d' {
  if (preference === 'canvas2d') return 'canvas2d';

  const gpuEligible = webgpuAvailable && !webgpuFailed;

  if (preference === 'webgpu') {
    if (gpuEligible) return 'webgpu';
    if (webgl2Available) return 'webgl2';
    return 'canvas2d';
  }

  if (preference === 'webgl2') {
    if (webgl2Available) return 'webgl2';
    return 'canvas2d';
  }

  // Auto prefers WebGL2 for stability; users can explicitly opt into WebGPU.
  if (webgl2Available) return 'webgl2';
  if (gpuEligible) return 'webgpu';
  return 'canvas2d';
}

export function NeuralVisualizerCore({
  pointsRef,
  pointCount,
  rendererPreference = 'auto',
  quality = 'cinematic',
  targetFps = 60,
  tailSeconds = 8,
  motionIntensity = 1,
  reduceMotion = false,
  showVectorField = true,
  intensityMode = 'absolute',
  bestTrainLoss = null,
  bestTrainLossStep = null,
  lastTrainLoss = null,
  lastTrainLossStep = null,
}: Props) {
  const [live, setLive] = useState<boolean>(true);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [scrubIndex, setScrubIndex] = useState<number>(0);
  const [zoom, setZoom] = useState<number>(1.0);
  const [pan, setPan] = useState<Vec2>({ x: 0, y: 0 });
  const [resetSignal, setResetSignal] = useState<number>(0);

  const [webgl2Available, setWebgl2Available] = useState<boolean>(rendererPreference !== 'canvas2d');
  const [webgpuAvailable, setWebgpuAvailable] = useState<boolean>(Boolean((globalThis as any)?.navigator?.gpu));
  const [webgpuFailed, setWebgpuFailed] = useState<boolean>(false);

  const draggingRef = useRef(false);
  const dragStartRef = useRef<Vec2>({ x: 0, y: 0 });
  const panStartRef = useRef<Vec2>({ x: 0, y: 0 });

  const maxIndex = Math.max(0, pointCount - 1);
  const visibleIndex = live ? maxIndex : clamp(scrubIndex, 0, maxIndex);

  useEffect(() => {
    if (rendererPreference === 'canvas2d') {
      setWebgl2Available(false);
      return;
    }

    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2', { antialias: true, alpha: true });
    setWebgl2Available(Boolean(gl));
  }, [rendererPreference]);

  useEffect(() => {
    setWebgpuAvailable(Boolean((globalThis as any)?.navigator?.gpu));
  }, []);

  useEffect(() => {
    if (!live) return;
    setScrubIndex(maxIndex);
  }, [live, maxIndex]);

  useEffect(() => {
    if (!isPlaying || live || maxIndex <= 0) return;

    let raf = 0;
    let last = performance.now();
    const rate = clamp(Number(targetFps || 60), 30, 144);

    const tick = (now: number) => {
      const dt = Math.max(0, now - last);
      last = now;
      const advance = Math.max(1, Math.floor((dt / 1000) * rate));
      setScrubIndex((prev) => {
        const next = prev + advance;
        if (next >= maxIndex) {
          setIsPlaying(false);
          return maxIndex;
        }
        return next;
      });
      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [isPlaying, live, maxIndex, targetFps]);

  const visiblePoints = useMemo(() => {
    const raw = pointsRef.current;
    if (!raw.length) {
      return {
        projected: [],
        terrainProjected: [],
        meta: { degenerateProjection: false, droppedPoints: 0 },
      };
    }

    const maxIdx = clamp(visibleIndex, 0, raw.length - 1);
    const upto = raw.slice(0, maxIdx + 1);

    // Project once; derive both the path points (optionally tailed in live mode) and stable terrain points.
    const projectedRes = projectPoints(upto, zoom, pan, intensityMode);
    const full = projectedRes.projected;

    // Tail is only for live mode; scrubbing/playing should show full history up to the scrub index.
    if (!live || tailSeconds <= 0 || full.length < 2) {
      return { projected: full, terrainProjected: full, meta: projectedRes.meta };
    }

    const tailCount = clamp(Math.floor(tailSeconds * 14), 60, full.length);
    return {
      projected: full.slice(-tailCount),
      terrainProjected: full,
      meta: projectedRes.meta,
    };
  }, [intensityMode, live, pointsRef, visibleIndex, zoom, pan, tailSeconds]);

  const latest = useMemo(() => {
    const items = pointsRef.current;
    return items.length ? items[items.length - 1] : null;
  }, [pointCount, pointsRef]);

  const projectionMeta = visiblePoints.meta;

  const activeRenderer = useMemo(
    () =>
      chooseRendererMode({
        preference: rendererPreference,
        webgpuAvailable,
        webgl2Available,
        webgpuFailed,
      }),
    [rendererPreference, webgpuAvailable, webgl2Available, webgpuFailed]
  );

  return (
    <section className="studio-panel studio-visualizer-panel" data-testid="neural-visualizer">
      <header className="studio-panel-header">
        <div>
          <h3 className="studio-panel-title">Neural Visualizer</h3>
          <p className="studio-panel-subtitle">Cinematic optimization trajectory from live training telemetry.</p>
        </div>
        <div className="studio-chip-row">
          <span className="studio-chip">points={pointCount}</span>
          {latest ? <span className="studio-chip">step={latest.step}</span> : null}
          <span className="studio-chip">quality={quality}</span>
          <span className="studio-chip">renderer={activeRenderer}</span>
          <span className="studio-chip">
            color={intensityMode} <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_COLOR_MODE" />
          </span>
          {bestTrainLoss != null ? (
            <span className="studio-chip studio-chip-ok">
              best={formatLossChip(bestTrainLoss)}@{bestTrainLossStep ?? '—'}{' '}
              <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_BEST_SO_FAR" />
            </span>
          ) : null}
          {lastTrainLoss != null ? (
            <span className="studio-chip">
              last={formatLossChip(lastTrainLoss)}@{lastTrainLossStep ?? '—'}{' '}
              <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_LAST_STEP" />
            </span>
          ) : null}
          {projectionMeta.droppedPoints > 0 ? <span className="studio-chip studio-chip-warn">dropped={projectionMeta.droppedPoints}</span> : null}
        </div>
      </header>

      <div
        className="neural-canvas-wrap"
        onMouseDown={(e) => {
          if (activeRenderer !== 'canvas2d') return;
          draggingRef.current = true;
          dragStartRef.current = { x: e.clientX, y: e.clientY };
          panStartRef.current = { ...pan };
        }}
        onMouseMove={(e) => {
          if (activeRenderer !== 'canvas2d') return;
          if (!draggingRef.current) return;
          const dx = (e.clientX - dragStartRef.current.x) / 260;
          const dy = (e.clientY - dragStartRef.current.y) / 260;
          setPan({ x: panStartRef.current.x + dx, y: panStartRef.current.y - dy });
        }}
        onMouseUp={() => {
          draggingRef.current = false;
        }}
        onMouseLeave={() => {
          draggingRef.current = false;
        }}
        onWheel={(e) => {
          if (activeRenderer !== 'canvas2d') return;
          e.preventDefault();
          const dir = e.deltaY > 0 ? -0.08 : 0.08;
          setZoom((z) => clamp(z + dir, 0.25, 4.0));
        }}
      >
        {activeRenderer === 'webgpu' ? (
          <NeuralVisualizerWebGPU
            points={visiblePoints.projected}
            terrainPoints={visiblePoints.terrainProjected}
            quality={quality}
            motionIntensity={motionIntensity}
            reduceMotion={reduceMotion}
            showVectorField={showVectorField}
            resetSignal={resetSignal}
            onFallback={() => setWebgpuFailed(true)}
          />
        ) : null}

        {activeRenderer === 'webgl2' ? (
          <NeuralVisualizerWebGL2
            points={visiblePoints.projected}
            terrainPoints={visiblePoints.terrainProjected}
            quality={quality}
            motionIntensity={motionIntensity}
            reduceMotion={reduceMotion}
            showVectorField={showVectorField}
            resetSignal={resetSignal}
          />
        ) : null}

        {activeRenderer === 'canvas2d' ? (
          <NeuralVisualizerCanvas2D points={visiblePoints.projected} targetFps={Number(targetFps || 60)} />
        ) : null}

        {pointCount === 0 ? (
          <div className="neural-overlay" data-testid="neural-awaiting-telemetry">
            Awaiting telemetry...
          </div>
        ) : null}
        {pointCount > 0 && projectionMeta.degenerateProjection ? (
          <div className="neural-overlay" data-testid="neural-degenerate-telemetry">
            This run emitted no trajectory spread in telemetry.
          </div>
        ) : null}
      </div>

      <div className="neural-controls">
        <label className="studio-checkbox-inline">
          <input
            type="checkbox"
            checked={live}
            onChange={(e) => {
              setLive(e.target.checked);
              if (e.target.checked) setIsPlaying(false);
            }}
          />
          Live <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_LIVE_MODE" />
        </label>

        <button
          className="small-button"
          onClick={() => setIsPlaying((v) => !v)}
          disabled={live || maxIndex <= 0}
          data-testid="neural-play-pause"
        >
          {isPlaying ? 'Pause' : 'Play'}
        </button>

        <label className="neural-zoom">
          Zoom
          <input
            type="range"
            min={0.25}
            max={4}
            step={0.05}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
            data-testid="neural-zoom-slider"
          />
        </label>

        <button
          className="small-button"
          onClick={() => {
            setPan({ x: 0, y: 0 });
            setZoom(1.0);
            setResetSignal((v) => v + 1);
          }}
          data-testid="neural-reset-view"
        >
          Reset View
        </button>
      </div>

      <div className="neural-scrub-row">
        <span className="studio-help-anchor">
          History <TooltipIcon name="LEARNING_RERANKER_VISUALIZER_SCRUB_HISTORY" />
        </span>
        <input
          type="range"
          min={0}
          max={maxIndex}
          step={1}
          value={visibleIndex}
          disabled={maxIndex <= 0}
          onChange={(e) => {
            setLive(false);
            setScrubIndex(Number(e.target.value));
          }}
          data-testid="neural-scrub-slider"
        />
        <span className="studio-mono">{maxIndex <= 0 ? '0/0' : `${visibleIndex + 1}/${maxIndex + 1}`}</span>
      </div>
    </section>
  );
}
