import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { clampInputNumber, clampNumber } from '@/utils/numbers';

type NumberFieldProps = {
  /** Committed value, normally a config field. */
  value: number;
  /** Called only when a commit actually changes the value. */
  onCommit: (value: number) => void;
  /** Lower bound, from the field's Pydantic `ge`. */
  min?: number;
  /** Upper bound, from the field's Pydantic `le`. */
  max?: number;
  /** Increment the committed value snaps to. */
  step?: number;
  disabled?: boolean;
  id?: string;
  className?: string;
  style?: CSSProperties;
  placeholder?: string;
  title?: string;
  'data-testid'?: string;
  'aria-describedby'?: string;
  'aria-label'?: string;
};

/**
 * A numeric config input that clamps on commit rather than on keystroke.
 *
 * While the operator is typing, the field holds their raw text and writes nothing: clamping
 * each keystroke makes a lower-bounded field impossible to type into (the `1` of `128` in a
 * `ge=64` field becomes `64` before the `2` is pressed). The value is parsed, snapped and
 * clamped on blur and on Enter, and Escape restores the last committed value.
 *
 * Bounds are read back off the rendered element, so what is clamped is exactly what the
 * control advertises to the operator and to `<input type=number>` validation.
 *
 * Renders a plain `<input type="number">`: existing selectors, `fill()` and keyboard
 * stepping keep working, and `fill()` followed by a blur commits.
 */
export function NumberField({ value, onCommit, min, max, step, ...rest }: NumberFieldProps) {
  const [text, setText] = useState<string>(() => String(value));
  const inputRef = useRef<HTMLInputElement>(null);
  const editingRef = useRef(false);

  // Track the committed value while the operator is not typing, so a config load or a
  // corpus switch is reflected without ever overwriting an edit in progress.
  useEffect(() => {
    if (!editingRef.current) setText(String(value));
  }, [value]);

  const commit = () => {
    // Clearing here, not in the blur handler, is what re-arms the prop sync: after an Enter
    // commit the field is no longer holding an edit, so a config load or corpus switch that
    // lands before the next blur must be allowed to update the text.
    editingRef.current = false;
    const element = inputRef.current;
    const next = element
      ? clampInputNumber(element, value)
      : clampNumber(text, { min, max, step, fallback: value });
    setText(String(next));
    if (next !== value) onCommit(next);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      // Blur so the visual state matches the committed state; the blur handler is the single
      // commit path, so Enter never sends the value twice.
      if (inputRef.current) inputRef.current.blur();
      else commit();
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      setText(String(value));
    }
  };

  return (
    <input
      {...rest}
      ref={inputRef}
      type="number"
      min={min}
      max={max}
      step={step}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onFocus={() => {
        editingRef.current = true;
      }}
      onBlur={commit}
      onKeyDown={onKeyDown}
    />
  );
}
