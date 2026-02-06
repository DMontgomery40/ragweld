import { type MutableRefObject, useEffect, useMemo, useRef, useState } from 'react';

export type TelemetryPoint = {
  x: number;
  y: number;
  step: number;
  loss: number;
  lr: number;
  gradNorm: number;
  ts: string;
};

type Props = {
  pointsRef: MutableRefObject<TelemetryPoint[]>;
  pointCount: number;
};

type Vec2 = { x: number; y: number };

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function compileShader(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) {
    throw new Error('Failed to create shader');
  }
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const err = gl.getShaderInfoLog(shader) || 'unknown shader error';
    gl.deleteShader(shader);
    throw new Error(`Shader compile failed: ${err}`);
  }
  return shader;
}

function createProgram(gl: WebGL2RenderingContext, vsSource: string, fsSource: string): WebGLProgram {
  const vs = compileShader(gl, gl.VERTEX_SHADER, vsSource);
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, fsSource);
  const program = gl.createProgram();
  if (!program) {
    throw new Error('Failed to create program');
  }
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const err = gl.getProgramInfoLog(program) || 'unknown link error';
    gl.deleteProgram(program);
    throw new Error(`Program link failed: ${err}`);
  }
  return program;
}

function normalizePoints(points: TelemetryPoint[], zoom: number, pan: Vec2): Float32Array {
  if (!points.length) return new Float32Array();

  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  let minLoss = Number.POSITIVE_INFINITY;
  let maxLoss = Number.NEGATIVE_INFINITY;
  let minGrad = Number.POSITIVE_INFINITY;
  let maxGrad = Number.NEGATIVE_INFINITY;

  for (const p of points) {
    minX = Math.min(minX, p.x);
    maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y);
    maxY = Math.max(maxY, p.y);
    minLoss = Math.min(minLoss, p.loss);
    maxLoss = Math.max(maxLoss, p.loss);
    minGrad = Math.min(minGrad, p.gradNorm);
    maxGrad = Math.max(maxGrad, p.gradNorm);
  }

  const padX = (maxX - minX) * 0.08 || 1.0;
  const padY = (maxY - minY) * 0.08 || 1.0;
  minX -= padX;
  maxX += padX;
  minY -= padY;
  maxY += padY;

  const rangeX = Math.max(1e-9, maxX - minX);
  const rangeY = Math.max(1e-9, maxY - minY);
  const rangeLoss = Math.max(1e-9, maxLoss - minLoss);
  const rangeGrad = Math.max(1e-9, maxGrad - minGrad);

  const out = new Float32Array(points.length * 3);
  for (let i = 0; i < points.length; i += 1) {
    const p = points[i];
    const nx = ((p.x - minX) / rangeX) * 2.0 - 1.0;
    const ny = ((p.y - minY) / rangeY) * 2.0 - 1.0;

    const lossNorm = clamp((p.loss - minLoss) / rangeLoss, 0.0, 1.0);
    const gradNorm = clamp((p.gradNorm - minGrad) / rangeGrad, 0.0, 1.0);
    const intensity = clamp((1.0 - lossNorm) * 0.45 + gradNorm * 0.55, 0.0, 1.0);

    const tx = (nx + pan.x) * zoom;
    const ty = (ny + pan.y) * zoom;

    out[i * 3 + 0] = tx;
    out[i * 3 + 1] = ty;
    out[i * 3 + 2] = intensity;
  }

  return out;
}

export function NeuralVisualizer({ pointsRef, pointCount }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const fallbackRef = useRef<HTMLCanvasElement | null>(null);

  const [webglAvailable, setWebglAvailable] = useState<boolean>(true);
  const [live, setLive] = useState<boolean>(true);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [scrubIndex, setScrubIndex] = useState<number>(0);
  const [zoom, setZoom] = useState<number>(1.0);
  const [pan, setPan] = useState<Vec2>({ x: 0, y: 0 });

  const draggingRef = useRef(false);
  const dragStartRef = useRef<Vec2>({ x: 0, y: 0 });
  const panStartRef = useRef<Vec2>({ x: 0, y: 0 });

  const maxIndex = Math.max(0, pointCount - 1);
  const visibleIndex = live ? maxIndex : clamp(scrubIndex, 0, maxIndex);
  const visibleIndexRef = useRef(visibleIndex);
  const zoomRef = useRef(zoom);
  const panRef = useRef(pan);

  useEffect(() => {
    visibleIndexRef.current = visibleIndex;
  }, [visibleIndex]);

  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);

  useEffect(() => {
    panRef.current = pan;
  }, [pan]);

  useEffect(() => {
    if (!live) return;
    setScrubIndex(maxIndex);
  }, [live, maxIndex]);

  useEffect(() => {
    if (!isPlaying || live || maxIndex <= 0) return;
    let raf = 0;
    let last = performance.now();
    const perSecond = 70;

    const tick = (now: number) => {
      const dt = Math.max(0, now - last);
      last = now;
      const advance = Math.max(1, Math.floor((dt / 1000) * perSecond));
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
  }, [isPlaying, live, maxIndex]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext('webgl2', { antialias: true, alpha: true });
    if (!gl) {
      setWebglAvailable(false);
      return;
    }
    setWebglAvailable(true);
  }, []);

  // WebGL2 renderer
  useEffect(() => {
    if (!webglAvailable) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext('webgl2', { antialias: true, alpha: true });
    if (!gl) {
      setWebglAvailable(false);
      return;
    }

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = Math.max(1, Math.floor(rect.width * dpr));
      const h = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
    };

    const bgVs = `#version 300 es
      in vec2 a_pos;
      void main() {
        gl_Position = vec4(a_pos, 0.0, 1.0);
      }
    `;
    const bgFs = `#version 300 es
      precision highp float;
      out vec4 outColor;
      uniform vec2 u_resolution;
      uniform float u_time;
      void main() {
        vec2 uv = gl_FragCoord.xy / u_resolution.xy;
        uv = uv * 2.0 - 1.0;
        float vignette = 1.0 - 0.35 * length(uv);

        float g1 = abs(fract((gl_FragCoord.x + u_time * 14.0) / 42.0) - 0.5);
        float g2 = abs(fract((gl_FragCoord.y + u_time * 8.0) / 42.0) - 0.5);
        float grid = smoothstep(0.495, 0.5, max(g1, g2));

        vec3 base = vec3(0.022, 0.032, 0.060);
        vec3 glow = vec3(0.09, 0.25, 0.34);
        vec3 color = base + glow * grid * 0.35;
        color *= clamp(vignette, 0.2, 1.0);

        outColor = vec4(color, 1.0);
      }
    `;

    const lineVs = `#version 300 es
      in vec2 a_pos;
      void main() {
        gl_Position = vec4(a_pos, 0.0, 1.0);
      }
    `;
    const lineFs = `#version 300 es
      precision highp float;
      out vec4 outColor;
      void main() {
        outColor = vec4(0.24, 0.95, 1.0, 0.82);
      }
    `;

    const pointVs = `#version 300 es
      in vec2 a_pos;
      in float a_i;
      out float v_i;
      void main() {
        gl_Position = vec4(a_pos, 0.0, 1.0);
        v_i = a_i;
        gl_PointSize = 2.0 + 9.0 * a_i;
      }
    `;
    const pointFs = `#version 300 es
      precision highp float;
      in float v_i;
      out vec4 outColor;
      void main() {
        vec2 p = gl_PointCoord - vec2(0.5);
        float d = length(p);
        float core = smoothstep(0.28, 0.0, d);
        float halo = smoothstep(0.52, 0.12, d);
        float a = clamp(core + 0.45 * halo, 0.0, 1.0);
        vec3 c = mix(vec3(0.11, 0.70, 0.88), vec3(0.46, 1.0, 0.98), clamp(v_i, 0.0, 1.0));
        outColor = vec4(c, a);
      }
    `;

    let bgProgram: WebGLProgram;
    let lineProgram: WebGLProgram;
    let pointProgram: WebGLProgram;

    try {
      bgProgram = createProgram(gl, bgVs, bgFs);
      lineProgram = createProgram(gl, lineVs, lineFs);
      pointProgram = createProgram(gl, pointVs, pointFs);
    } catch (_e) {
      setWebglAvailable(false);
      return;
    }

    const quad = new Float32Array([
      -1, -1,
      3, -1,
      -1, 3,
    ]);

    const bgVbo = gl.createBuffer();
    const dataVbo = gl.createBuffer();
    if (!bgVbo || !dataVbo) {
      setWebglAvailable(false);
      return;
    }

    gl.bindBuffer(gl.ARRAY_BUFFER, bgVbo);
    gl.bufferData(gl.ARRAY_BUFFER, quad, gl.STATIC_DRAW);

    const bgPosLoc = gl.getAttribLocation(bgProgram, 'a_pos');
    const bgResLoc = gl.getUniformLocation(bgProgram, 'u_resolution');
    const bgTimeLoc = gl.getUniformLocation(bgProgram, 'u_time');

    const linePosLoc = gl.getAttribLocation(lineProgram, 'a_pos');
    const pointPosLoc = gl.getAttribLocation(pointProgram, 'a_pos');
    const pointILoc = gl.getAttribLocation(pointProgram, 'a_i');

    let raf = 0;
    const started = performance.now();

    const draw = (now: number) => {
      resize();
      gl.clearColor(0.0, 0.0, 0.0, 0.0);
      gl.clear(gl.COLOR_BUFFER_BIT);

      gl.disable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      // Background
      gl.useProgram(bgProgram);
      gl.bindBuffer(gl.ARRAY_BUFFER, bgVbo);
      gl.enableVertexAttribArray(bgPosLoc);
      gl.vertexAttribPointer(bgPosLoc, 2, gl.FLOAT, false, 8, 0);
      if (bgResLoc) gl.uniform2f(bgResLoc, canvas.width, canvas.height);
      if (bgTimeLoc) gl.uniform1f(bgTimeLoc, (now - started) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      const raw = pointsRef.current;
      const visible = visibleIndexRef.current;
      const upto = raw.slice(0, clamp(visible, 0, Math.max(0, raw.length - 1)) + 1);

      if (upto.length > 0) {
        const arr = normalizePoints(upto, zoomRef.current, panRef.current);
        gl.bindBuffer(gl.ARRAY_BUFFER, dataVbo);
        gl.bufferData(gl.ARRAY_BUFFER, arr, gl.DYNAMIC_DRAW);

        // Trajectory line
        gl.useProgram(lineProgram);
        gl.enableVertexAttribArray(linePosLoc);
        gl.vertexAttribPointer(linePosLoc, 2, gl.FLOAT, false, 12, 0);
        gl.lineWidth(1.0);
        gl.drawArrays(gl.LINE_STRIP, 0, upto.length);

        // Points
        gl.useProgram(pointProgram);
        gl.enableVertexAttribArray(pointPosLoc);
        gl.enableVertexAttribArray(pointILoc);
        gl.vertexAttribPointer(pointPosLoc, 2, gl.FLOAT, false, 12, 0);
        gl.vertexAttribPointer(pointILoc, 1, gl.FLOAT, false, 12, 8);
        gl.drawArrays(gl.POINTS, 0, upto.length);
      }

      raf = requestAnimationFrame(draw);
    };

    const ro = new ResizeObserver(() => resize());
    ro.observe(canvas);
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      gl.deleteBuffer(bgVbo);
      gl.deleteBuffer(dataVbo);
      gl.deleteProgram(bgProgram);
      gl.deleteProgram(lineProgram);
      gl.deleteProgram(pointProgram);
    };
  }, [webglAvailable, pointsRef]);

  // Canvas2D fallback renderer
  useEffect(() => {
    if (webglAvailable) return;
    const canvas = fallbackRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    };

    const draw = () => {
      const points = pointsRef.current;
      const visible = visibleIndexRef.current;
      const upto = points.slice(0, clamp(visible, 0, Math.max(0, points.length - 1)) + 1);
      resize();
      const w = canvas.width;
      const h = canvas.height;

      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#091126';
      ctx.fillRect(0, 0, w, h);

      const step = Math.max(28, Math.floor(Math.min(w, h) / 10));
      ctx.strokeStyle = 'rgba(120,180,200,0.12)';
      ctx.lineWidth = 1;
      for (let x = 0; x < w; x += step) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = 0; y < h; y += step) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }

      if (!upto.length) return;
      const arr = normalizePoints(upto, zoomRef.current, panRef.current);

      const toPx = (nx: number, ny: number) => ({
        x: (nx * 0.5 + 0.5) * w,
        y: (1.0 - (ny * 0.5 + 0.5)) * h,
      });

      ctx.strokeStyle = 'rgba(80,240,255,0.85)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < upto.length; i += 1) {
        const p = toPx(arr[i * 3], arr[i * 3 + 1]);
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();

      const last = upto.length - 1;
      const lp = toPx(arr[last * 3], arr[last * 3 + 1]);
      ctx.fillStyle = 'rgba(110,255,255,0.95)';
      ctx.beginPath();
      ctx.arc(lp.x, lp.y, 4.8, 0, Math.PI * 2);
      ctx.fill();
    };

    let raf = 0;
    const loop = () => {
      draw();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    const ro = new ResizeObserver(() => resize());
    ro.observe(canvas);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [webglAvailable, pointsRef]);

  const latest = useMemo(() => {
    const items = pointsRef.current;
    return items.length ? items[items.length - 1] : null;
  }, [pointCount, pointsRef]);

  return (
    <section className="studio-panel studio-visualizer-panel" data-testid="neural-visualizer">
      <header className="studio-panel-header">
        <div>
          <h3 className="studio-panel-title">Neural Visualizer</h3>
          <p className="studio-panel-subtitle">Real-time optimization trajectory from training telemetry.</p>
        </div>
        <div className="studio-chip-row">
          <span className="studio-chip">points={pointCount}</span>
          {latest ? <span className="studio-chip">step={latest.step}</span> : null}
          {!webglAvailable ? <span className="studio-chip studio-chip-warn">Canvas fallback</span> : null}
        </div>
      </header>

      <div
        className="neural-canvas-wrap"
        onMouseDown={(e) => {
          draggingRef.current = true;
          dragStartRef.current = { x: e.clientX, y: e.clientY };
          panStartRef.current = { ...pan };
        }}
        onMouseMove={(e) => {
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
          e.preventDefault();
          const dir = e.deltaY > 0 ? -0.08 : 0.08;
          setZoom((z) => clamp(z + dir, 0.25, 4.0));
        }}
      >
        <canvas ref={canvasRef} className={webglAvailable ? 'neural-canvas active' : 'neural-canvas'} />
        <canvas ref={fallbackRef} className={!webglAvailable ? 'neural-canvas active' : 'neural-canvas'} />

        {pointCount === 0 ? (
          <div className="neural-overlay" data-testid="neural-awaiting-telemetry">
            Awaiting telemetry...
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
          Live
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
          }}
          data-testid="neural-reset-view"
        >
          Reset View
        </button>
      </div>

      <div className="neural-scrub-row">
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
        <span className="studio-mono">
          {maxIndex <= 0 ? '0/0' : `${visibleIndex + 1}/${maxIndex + 1}`}
        </span>
      </div>
    </section>
  );
}
