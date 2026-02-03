import type { ChatModelInfo } from '@/types/generated';

type ModelPickerProps = {
  value: string;
  onChange: (modelOverride: string) => void;
  models: ChatModelInfo[];
};

const SOURCE_LABELS = {
  cloud_direct: 'Cloud Direct',
  openrouter: 'OpenRouter',
  local: 'Local',
} as const;

const SOURCE_ORDER = ['cloud_direct', 'openrouter', 'local'] as const;

function toOptionValue(model: ChatModelInfo): string {
  return model.source === 'local' ? `local:${model.id}` : model.id;
}

function toOptionLabel(model: ChatModelInfo): string {
  return `${model.provider} · ${model.id}`;
}

export function ModelPicker({ value, onChange, models }: ModelPickerProps) {
  const grouped = SOURCE_ORDER.map((source) => ({
    source,
    label: SOURCE_LABELS[source],
    items: models.filter((m) => m.source === source),
  })).filter((g) => g.items.length > 0);

  return (
    <select
      data-testid="model-picker"
      value={value}
      onChange={(e) => onChange(e.target.value)}
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
      {grouped.map((group) => (
        <optgroup key={group.source} label={group.label}>
          {group.items.map((model) => {
            const optionValue = toOptionValue(model);
            return (
              <option key={optionValue} value={optionValue}>
                {toOptionLabel(model)}
              </option>
            );
          })}
        </optgroup>
      ))}
    </select>
  );
}

