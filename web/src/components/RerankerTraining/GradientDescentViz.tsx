import { useEffect, useMemo, useRef, useState } from 'react';
import type { RerankerTrainMetricEvent } from '@/types/generated';

type ProjectionPoint = {
  ts: string;
  step?: number;
  x: number;
  y: number;
  dx?: number;
  dy?: number;
};

function parseProjectionPoints(events: RerankerTrainMetricEvent[]): ProjectionPoint[] {
  const points: ProjectionPoint[] = [];
  for (const ev of events) {
    const m = ev.metrics as Record<string, unknown> | null | undefined;
    const x = m?.proj_x;
    const y = m?.proj_y;
    if (typeof x !== 'number' || typeof y !== 'number') continue;

    const dx = m?.proj_dx;
    const dy = m?.proj_dy;
    points.push({
      ts: String(ev.ts),
      step: ev.step == null ? undefined : Number(ev.step),
      x,
      y,
      dx: typeof dx === 'number' ? dx : undefined,
      dy: typeof dy === 'number' ? dy : undefined,
    });
  }
  return points;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

export function GradientDescentViz({ events }: { events: RerankerTrainMetricEvent[] }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const points = useMemo(() => parseProjectionPoints(events), [events]);

  const [cursor, setCursor] = useState(0);
  const [live, setLive] = useState(true);

  // Keep the cursor pinned to the end when in "live" mode.
  useEffect(() => {
    if (!live) return;
    setCursor(Math.max(0, points.length - 1));
  }, [points.length, live]);

  // Resize canvas to match layout (retina aware).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = Math.max(1, Math.floor(rect.width * dpr));
      const h = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    return () => ro.disconnect();
  }, []);

  // Draw
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    const dpr = window.devicePixelRatio || 1;

    // Cinematic dark base (Welch-labs vibe)
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#070A12';
    ctx.fillRect(0, 0, w, h);

    // Subtle grid
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    const grid = Math.max(24 * dpr, Math.floor(Math.min(w, h) / 10));
    for (let x = 0; x <= w; x += grid) {
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, h);
      ctx.stroke();
    }
    for (let y = 0; y <= h; y += grid) {
      ctx.beginPath();
      ctx.moveTo(0, y + 0.5);
      ctx.lineTo(w, y + 0.5);
      ctx.stroke();
    }

    if (!points.length) {
      ctx.fillStyle = 'rgba(255,255,255,0.55)';
      ctx.font = `${Math.floor(12 * dpr)}px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace`;
      ctx.fillText('Awaiting projection telemetry (proj_x / proj_y)…', Math.floor(14 * dpr), Math.floor(24 * dpr));
      ctx.restore();
      return;
    }

    const pad = 18 * dpr;
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    let minX = Math.min(...xs);
    let maxX = Math.max(...xs);
    let minY = Math.min(...ys);
    let maxY = Math.max(...ys);

    // Expand bounds a bit to avoid edge-clipping.
    const epsX = (maxX - minX) * 0.08 || 1;
    const epsY = (maxY - minY) * 0.08 || 1;
    minX -= epsX;
    maxX += epsX;
    minY -= epsY;
    maxY += epsY;

    const toX = (x: number) => pad + ((x - minX) / (maxX - minX || 1)) * (w - 2 * pad);
    const toY = (y: number) => pad + (1 - (y - minY) / (maxY - minY || 1)) * (h - 2 * pad);

    const idx = clamp(cursor, 0, points.length - 1);
    const upto = points.slice(0, idx + 1);

    // Trajectory trail
    const grad = ctx.createLinearGradient(0, 0, w, h);
    grad.addColorStop(0.0, 'rgba(0,240,255,0.25)');
    grad.addColorStop(1.0, 'rgba(0,240,255,0.95)');
    ctx.strokeStyle = grad;
    ctx.lineWidth = Math.max(1.5, 2.25 * dpr);
    ctx.beginPath();
    for (let i = 0; i < upto.length; i += 1) {
      const p = upto[i];
      const px = toX(p.x);
      const py = toY(p.y);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();

    // Current point glow
    const cur = points[idx];
    const cx = toX(cur.x);
    const cy = toY(cur.y);
    ctx.shadowColor = 'rgba(0,240,255,0.85)';
    ctx.shadowBlur = 12 * dpr;
    ctx.fillStyle = 'rgba(0,240,255,0.95)';
    ctx.beginPath();
    ctx.arc(cx, cy, 3.5 * dpr, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    // Update vector hint (if present)
    if (typeof cur.dx === 'number' && typeof cur.dy === 'number') {
      const vx = toX(cur.x + cur.dx) - cx;
      const vy = toY(cur.y + cur.dy) - cy;
      const mag = Math.hypot(vx, vy) || 1;
      const maxArrow = 26 * dpr;
      const scale = Math.min(1, maxArrow / mag);

      ctx.strokeStyle = 'rgba(255,255,255,0.55)';
      ctx.lineWidth = 1.2 * dpr;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + vx * scale, cy + vy * scale);
      ctx.stroke();
    }

    // Caption
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    ctx.font = `${Math.floor(11 * dpr)}px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace`;
    const cap = `points=${points.length} cursor=${idx}${cur.step != null ? ` step=${cur.step}` : ''}`;
    ctx.fillText(cap, Math.floor(14 * dpr), h - Math.floor(12 * dpr));
    ctx.restore();
  }, [points, cursor]);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline' }}>
        <div style={{ fontWeight: 600 }}>Gradient descent visualizer</div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, color: 'var(--fg-muted)' }}>
            <input
              type="checkbox"
              checked={live}
              onChange={(e) => setLive(e.target.checked)}
              disabled={points.length === 0}
            />
            live
          </label>
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
            {points.length ? (
              <span style={{ fontFamily: 'var(--font-mono)' }}>{points[Math.max(0, points.length - 1)].ts}</span>
            ) : (
              '—'
            )}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <canvas
          ref={canvasRef}
          style={{
            width: '100%',
            height: 240,
            borderRadius: 12,
            border: '1px solid var(--line)',
            background: '#070A12',
          }}
        />
      </div>

      <div style={{ marginTop: 10, display: 'flex', gap: 10, alignItems: 'center' }}>
        <input
          type="range"
          min={0}
          max={Math.max(0, points.length - 1)}
          value={clamp(cursor, 0, Math.max(0, points.length - 1))}
          onChange={(e) => {
            setLive(false);
            setCursor(parseInt(e.target.value || '0', 10));
          }}
          disabled={points.length === 0}
          style={{ width: '100%' }}
        />
        <div style={{ width: 120, textAlign: 'right', fontSize: 12, color: 'var(--fg-muted)' }}>
          <span style={{ fontFamily: 'var(--font-mono)' }}>
            {points.length ? `${clamp(cursor, 0, points.length - 1) + 1}/${points.length}` : '0/0'}
          </span>
        </div>
      </div>
    </div>
  );
}

