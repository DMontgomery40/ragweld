import { useEffect, useRef } from 'react';
import type { NeuralRenderPoint } from './NeuralVisualizerWebGL2';

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function drawCanvas2D({
  canvas,
  points,
}: {
  canvas: HTMLCanvasElement;
  points: NeuralRenderPoint[];
}) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));

  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);

  const bg = ctx.createLinearGradient(0, 0, w, h);
  bg.addColorStop(0, '#050912');
  bg.addColorStop(1, '#081a2f');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  const gridStep = Math.max(24, Math.floor(Math.min(w, h) / 15));
  ctx.strokeStyle = 'rgba(89,130,166,0.2)';
  ctx.lineWidth = 1;

  for (let x = 0; x < w; x += gridStep) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }

  for (let y = 0; y < h; y += gridStep) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  if (!points.length) return;

  const toPx = (nx: number, ny: number) => ({
    x: (nx * 0.5 + 0.5) * w,
    y: (1.0 - (ny * 0.5 + 0.5)) * h,
  });

  ctx.strokeStyle = 'rgba(106,238,255,0.95)';
  ctx.lineWidth = 2;
  ctx.beginPath();

  for (let i = 0; i < points.length; i += 1) {
    const p = toPx(points[i].x, points[i].y);
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }

  ctx.stroke();

  for (let i = 0; i < points.length; i += 1) {
    const p = points[i];
    const px = toPx(p.x, p.y);
    const radius = 2 + p.intensity * 4;
    const alpha = clamp(0.4 + 0.55 * p.intensity, 0.0, 1.0);
    ctx.fillStyle = `rgba(128, 243, 255, ${alpha})`;
    ctx.beginPath();
    ctx.arc(px.x, px.y, radius, 0, Math.PI * 2);
    ctx.fill();
  }
}

export function NeuralVisualizerCanvas2D({
  points,
  targetFps,
}: {
  points: NeuralRenderPoint[];
  targetFps: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let raf = 0;
    let last = 0;
    const minFrameMs = 1000 / clamp(Number(targetFps || 60), 30, 144);

    const draw = (now: number) => {
      const elapsed = now - last;
      if (elapsed >= minFrameMs) {
        last = now;
        drawCanvas2D({ canvas, points });
      }
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [points, targetFps]);

  return <canvas ref={canvasRef} className="neural-canvas active" />;
}
