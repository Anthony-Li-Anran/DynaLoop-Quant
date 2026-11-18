import { Badge } from "../ui/Badge";

type Status =
  | "connected"
  | "unavailable"
  | "connecting"
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "passed"
  | "warning";

const statusTones: Record<Status, "neutral" | "cyan" | "green" | "amber" | "red"> = {
  connected: "green",
  unavailable: "red",
  connecting: "neutral",
  pending: "neutral",
  running: "cyan",
  completed: "green",
  failed: "red",
  cancelled: "neutral",
  passed: "green",
  warning: "amber",
};

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase() as Status;
  const tone = normalized in statusTones ? statusTones[normalized] : "neutral";
  return <Badge tone={tone} className="gap-2 capitalize"><span aria-hidden className="h-2 w-2 rounded-full bg-current" />{status.replaceAll("_", " ")}</Badge>;
}
