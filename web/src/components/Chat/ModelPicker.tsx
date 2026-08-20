import type { ChatModelInfo } from '@/types/generated';

type ModelPickerProps = {
  value: string;
  onChange: (modelOverride: string) => void;
  models: ChatModelInfo[];
  valueMode?: 'override' | 'id';
  allowEmpty?: boolean;
};

function toOptionValue(model: ChatModelInfo, valueMode: 'override' | 'id'): string {
  return String(valueMode === 'id' ? model.id : model.override || model.id || '');
}

function toOptionLabel(model: ChatModelInfo): string {
  const name = String(model.catalog_model || model.id || '').trim();
  return `${model.provider} · ${name}`;
}

export function ModelPicker({ value, onChange, models, valueMode = 'override', allowEmpty = false }: ModelPickerProps) {
  const gatewayModels = models.filter((model) => model.source === 'litellm');
  const hasModels = gatewayModels.length > 0;
  const currentValueAvailable = !value
    ? allowEmpty
    : gatewayModels.some((model) => toOptionValue(model, valueMode) === value);

  return (
    <select
      data-testid="model-picker"
      value={hasModels ? value : ''}
      onChange={(e) => onChange(e.target.value)}
      disabled={!hasModels}
      aria-invalid={!currentValueAvailable}
      style={{
        width: '100%',
        padding: '10px 12px',
        background: 'var(--input-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        color: 'var(--fg)',
        fontSize: '13px',
      }}
    >
      {!hasModels ? <option value="">No models available</option> : null}
      {hasModels && value && !currentValueAvailable ? (
        <option value={value} disabled>Unavailable alias: {value}</option>
      ) : null}
      {hasModels && allowEmpty ? <option value="">Use default alias</option> : null}
      {hasModels ? (
        <optgroup label="LiteLLM">
          {gatewayModels.map((model) => {
            const optionValue = toOptionValue(model, valueMode);
            return (
              <option key={optionValue} value={optionValue}>
                {toOptionLabel(model)}
              </option>
            );
          })}
        </optgroup>
      ) : null}
    </select>
  );
}
