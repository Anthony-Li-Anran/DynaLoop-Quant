import { useId } from "react";
export function SelectField({ label, value, onChange, options, description, disabled = false }: {
  label: string; value: string; onChange: (value: string) => void;
  options: readonly { value: string; label: string }[]; description?: string; disabled?: boolean;
}) {
  const id = useId();
  return <div><label htmlFor={id} className="text-[13px] font-medium text-ink">{label}</label>
    <select id={id} value={value} disabled={disabled} onChange={event => onChange(event.target.value)}
      aria-describedby={description ? id + "-help" : undefined}
      className="mt-1 min-h-10 w-full rounded-md border border-line bg-canvas px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
      {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>{description && <p id={id + "-help"} className="mt-1 text-xs leading-5 text-muted">{description}</p>}
  </div>;
}
