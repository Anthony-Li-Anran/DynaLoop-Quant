export type SegmentedControlOption<Value extends string> = {
  value: Value;
  label: string;
};

type SegmentedControlProps<Value extends string> = {
  label: string;
  value: Value;
  options: readonly SegmentedControlOption<Value>[];
  onChange: (value: Value) => void;
};

export function SegmentedControl<Value extends string>({
  label,
  value,
  options,
  onChange,
}: SegmentedControlProps<Value>) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex items-center gap-0.5 rounded-md border border-line bg-canvas p-0.5"
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            className={`min-h-8 whitespace-nowrap rounded px-3 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${
              selected
                ? "bg-elevated text-ink shadow-sm"
                : "text-muted hover:bg-elevated/60 hover:text-ink"
            }`}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
