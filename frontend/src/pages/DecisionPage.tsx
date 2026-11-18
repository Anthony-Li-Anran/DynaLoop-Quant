import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type DecisionRecord } from "../features/api";
import { PageHeader } from "../components/shared/PageHeader";
import { Panel } from "../components/shared/Panel";
import { useTranslation } from "react-i18next";

function shown(value: unknown): string {
  if (value === null || value === undefined) return "N/A";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "N/A";
  return String(value);
}

const CHOICES: DecisionRecord["choice"][] = ["subjective", "quantitative", "both", "neither", "defer"];

export function DecisionPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const rounds = useQuery({ queryKey: ["evidence-rounds"], queryFn: api.evidenceRounds });
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: api.decisions });
  const [subjectiveNote, setSubjectiveNote] = useState("");
  const [subjectiveFp, setSubjectiveFp] = useState("");
  const [quantFp, setQuantFp] = useState("");
  const [choice, setChoice] = useState<DecisionRecord["choice"]>("defer");
  const [rationale, setRationale] = useState("");
  const [saved, setSaved] = useState<DecisionRecord | null>(null);

  const record = useMutation({
    mutationFn: () => api.recordDecision({
      choice,
      rationale,
      subjective_fingerprint: subjectiveFp || null,
      quantitative_fingerprint: quantFp || null,
    }),
    onSuccess: (data) => {
      setSaved(data);
      setRationale("");
      queryClient.invalidateQueries({ queryKey: ["decisions"] });
    },
  });

  const effectiveRounds = (rounds.data ?? []).filter((r) => (r.effective_count ?? 0) > 0);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={t("Decision / Comparison")}
        title={t("Strategy Comparison")}
        description={t("Side-by-side subjective reading and quantitative evidence. The final call is recorded by a human, never made by this system.")}
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title={t("Quantitative evidence")} description={t("Certified factors from frozen out-of-sample rounds. Read-only.")}>
          {rounds.isPending && <p role="status">{t("Loading evidence...")}</p>}
          {rounds.data?.length === 0 && <p className="text-sm text-muted">{t("No certified rounds available.")}</p>}
          <div className="space-y-2">
            {effectiveRounds.map((r) => <div key={r.round_id} className="rounded border border-line bg-elevated p-3">
              <p className="text-sm font-medium">{r.round_id}</p>
              <p className="mt-1 text-[11px] text-muted">
                {shown(r.channel_label)} · periods {shown(r.periods)} · family p {shown(r.family_p_value)}
              </p>
              <p className="mt-1 text-[11px] text-muted">effective {shown(r.effective_count)} · fp {shown(r.freeze_fingerprint)?.slice(0, 12)}</p>
            </div>)}
          </div>
          <label className="mt-4 block text-sm">
            <span className="block text-muted">{t("Quantitative fingerprint to record")}</span>
            <input className="mt-1 w-full rounded border border-line bg-elevated p-2"
              value={quantFp} onChange={(e) => setQuantFp(e.target.value)}
              placeholder={effectiveRounds[0]?.freeze_fingerprint ?? ""} />
          </label>
        </Panel>

        <Panel title={t("Subjective reading")} description={t("Paste a subjective analysis and its fingerprint from the Subjective page.")}>
          <textarea className="h-32 w-full rounded border border-line bg-elevated p-2 text-sm"
            value={subjectiveNote} onChange={(e) => setSubjectiveNote(e.target.value)}
            placeholder={t("Subjective observations and speculation...")} />
          <label className="mt-3 block text-sm">
            <span className="block text-muted">{t("Subjective fingerprint to record")}</span>
            <input className="mt-1 w-full rounded border border-line bg-elevated p-2"
              value={subjectiveFp} onChange={(e) => setSubjectiveFp(e.target.value)} />
          </label>
          {subjectiveNote && <p role="note" className="mt-2 text-[11px] text-muted">
            {subjectiveNote.length} characters · subjective only, not validated evidence.
          </p>}
        </Panel>
      </div>

      <Panel title={t("Human decision")} description={t("Record only. No automatic choice, no correctness or return claim.")}>
        <div className="flex flex-wrap gap-2">
          {CHOICES.map((c) => <button key={c}
            className={`rounded border px-3 py-1.5 text-sm ${choice === c ? "border-accent bg-elevated" : "border-line"}`}
            onClick={() => setChoice(c)}>{c}</button>)}
        </div>
        <label className="mt-4 block text-sm">
          <span className="block text-muted">Rationale (required)</span>
          <textarea className="mt-1 h-20 w-full rounded border border-line bg-elevated p-2"
            value={rationale} onChange={(e) => setRationale(e.target.value)} />
        </label>
        <div className="mt-3">
          <button className="rounded bg-accent px-4 py-2 text-sm"
            disabled={!rationale.trim() || record.isPending}
            onClick={() => record.mutate()}>
            {record.isPending ? "Saving..." : "Record decision"}
          </button>
        </div>
        {record.isError && <p role="alert" className="mt-3 text-sm text-danger">{t("Failed to record decision.")}</p>}
        {saved && <p role="status" className="mt-3 text-[11px] text-muted">
          Saved {saved.record_id.slice(0, 8)} · fingerprint {saved.fingerprint.slice(0, 12)}
        </p>}
      </Panel>

      <Panel title={t("Decision history")} description={t("Append-only audit trail of human decisions.")}>
        {decisions.data?.length === 0 && <p className="text-sm text-muted">{t("No decisions recorded.")}</p>}
        <div className="space-y-2">
          {(decisions.data ?? []).slice().reverse().map((d) => <div key={d.record_id} className="rounded border border-line bg-elevated p-3">
            <p className="text-sm font-medium">{d.choice} · {d.decision_time}</p>
            <p className="mt-1 text-xs">{d.rationale}</p>
            <p className="mt-1 break-all text-[11px] text-muted">fp {d.fingerprint.slice(0, 16)}</p>
          </div>)}
        </div>
      </Panel>
    </div>
  );
}
