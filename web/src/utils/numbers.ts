// TriBridRAG - numeric input helpers shared by the config editors.

export type NumberBounds = {
  /** Lower bound, from the field's Pydantic `ge`. */
  min?: number;
  /** Upper bound, from the field's Pydantic `le`. */
  max?: number;
  /** Increment the value snaps to, measured from `min` the way HTML `step` is. */
  step?: number;
  /** Value used while the input is empty or unparseable. */
  fallback: number;
};

/** Decimal places implied by a step, so 0.01-steps do not accumulate float noise. */
function decimalsOf(step: number): number {
  const text = String(step);
  const dot = text.indexOf('.');
  return dot === -1 ? 0 : text.length - dot - 1;
}

/**
 * Parse a numeric input's value and force it inside the field's own constraints.
 *
 * Config writes go straight to the store, and the PATCH re-validates the whole section
 * against its Pydantic model: an out-of-range value comes back as a 422 with no field
 * attribution, surfaced only as a generic store error. Clamping here means the store
 * never receives a value the model would reject.
 *
 * Snapping happens before clamping, because snapping can push a value past a bound
 * (max 4, step 0.5 from min 1: 4.4 snaps to 4.5, which must still land on 4).
 */
export function clampNumber(raw: string, bounds: NumberBounds): number {
  const { min, max, step, fallback } = bounds;
  const parsed = raw === '' ? fallback : Number(raw);
  let value = Number.isFinite(parsed) ? parsed : fallback;
  if (step !== undefined && step > 0) {
    const origin = min ?? 0;
    const snapped = origin + Math.round((value - origin) / step) * step;
    value = Number(snapped.toFixed(decimalsOf(step)));
  }
  if (min !== undefined && value < min) return min;
  if (max !== undefined && value > max) return max;
  return value;
}

/**
 * `clampNumber` for a rendered `<input type="number">`, reading the bounds off the element
 * so they cannot drift from the constraints the control already advertises to the operator.
 */
export function clampInputNumber(input: HTMLInputElement, fallback: number): number {
  const bound = (text: string): number | undefined => {
    if (text === '') return undefined;
    const value = Number(text);
    return Number.isFinite(value) ? value : undefined;
  };
  return clampNumber(input.value, {
    min: bound(input.min),
    max: bound(input.max),
    step: bound(input.step),
    fallback,
  });
}
