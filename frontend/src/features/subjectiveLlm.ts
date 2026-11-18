// Keyless WorkBuddy LLM client for subjective analysis.
// Output is a subjective reading for human review ONLY: not a factor, verdict,
// or investment advice. It never enters the statistical decision layer.

import { createWorkBuddyCloud } from "@tencent-ai/workbuddy-cloud-sdk";

export interface LlmConfig {
  enabled: boolean;
  endpoint: string;
  publishableKey: string;
  note: string;
}

export interface SubjectiveResult {
  text: string;
  model: string;
  finished: boolean;
  error?: string;
}

// Stable behaviour contract. The system message is always messages[0], per the
// WorkBuddy LLM API requirement. It forbids presenting model output as validated
// evidence or an actionable signal.
export const SUBJECTIVE_SYSTEM_PROMPT =
  "You are a subjective market commentator for research discussion only. " +
  "Base every statement strictly on the supplied context. Never present output " +
  "as a validated factor, a statistical verdict, a forecast guarantee, or " +
  "investment advice. Explicitly separate observations from speculation, state " +
  "uncertainty, and note when the context has missing data. Reply concisely.";

export function buildSubjectivePrompt(context: unknown): string {
  return [
    "Given the following point-in-time research context, provide a short subjective reading.",
    "Distinguish OBSERVATIONS (grounded in supplied data) from SPECULATION.",
    "Note any missing/unavailable inputs. Do not claim effectiveness or returns.",
    "",
    "CONTEXT (JSON):",
    JSON.stringify(context, null, 2).slice(0, 12000),
  ].join("\n");
}

// Extract just the visible text delta from one SSE chunk, ignoring role-init
// placeholders and null/empty content.
export function deltaText(chunk: unknown): string {
  const choices = (chunk as { choices?: Array<{ delta?: { content?: string | null } }> })?.choices;
  const content = choices?.[0]?.delta?.content;
  return typeof content === "string" ? content : "";
}

// Minimal structural view of a model directory entry. No separate "free"
// flag exists in the upstream directory: cost is exposed only as a credit
// multiplier string (e.g. "x0.08 credits", "x0.29"). Absent credits means
// "unknown", NOT free, so unknown-cost models are ranked after known ones.
export interface CostAwareModel {
  id: string;
  enabled: boolean;
  disabled?: boolean;
  credits?: string;
}

// Extract the credit multiplier from display text. Only the "x<number>" form
// is a multiplier; other forms are treated as unknown to avoid mixing an
// absolute price with a multiplier.
export function parseCreditMultiplier(credits?: string): number | null {
  if (!credits) return null;
  const match = /x\s*([0-9]+(?:\.[0-9]+)?)/i.exec(credits);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) ? value : null;
}

// Pick the enabled model with the lowest credit multiplier. Stable sort keeps
// directory order for ties. Models with unknown cost are ranked last, never
// assumed free. Returns null when nothing is selectable.
export function pickCheapestModel<T extends CostAwareModel>(models: T[]): T | null {
  const usable = models.filter((m) => m.enabled !== false && m.disabled !== true);
  if (usable.length === 0) return null;
  const priced = usable
    .map((model) => ({ model, multiplier: parseCreditMultiplier(model.credits) }))
    .filter((entry): entry is { model: T; multiplier: number } => entry.multiplier !== null);
  if (priced.length === 0) return usable[0];
  priced.sort((a, b) => a.multiplier - b.multiplier);
  return priced[0].model;
}

export interface GenerateOptions {
  config: LlmConfig;
  context: unknown;
  model?: string;
  onToken?: (text: string) => void;
}

// Perform a real keyless model call and collect the streamed answer.
export async function generateSubjective(options: GenerateOptions): Promise<SubjectiveResult> {
  const { config, context, onToken } = options;
  if (!config.enabled || !config.endpoint || !config.publishableKey) {
    return { text: "", model: "", finished: false, error: "LLM not configured" };
  }
  const cloud = createWorkBuddyCloud({
    endpoint: config.endpoint,
    publishableKey: config.publishableKey,
  });
  const models = await cloud.llm.models.list();
  const cheapest = pickCheapestModel(models);
  if (!cheapest) {
    return { text: "", model: "", finished: false, error: "no model available" };
  }
  // An explicit model id still wins, so a user can override the cost default.
  const model = options.model || cheapest.id;
  let text = "";
  let finished = false;
  for await (const chunk of cloud.llm.chat.completions.create({
    model,
    messages: [
      { role: "system", content: SUBJECTIVE_SYSTEM_PROMPT },
      { role: "user", content: buildSubjectivePrompt(context) },
    ],
    stream: true,
  })) {
    const piece = deltaText(chunk);
    if (piece) {
      text += piece;
      onToken?.(piece);
    }
    if ((chunk as { choices?: Array<{ finish_reason?: string | null }> })?.choices?.[0]?.finish_reason) {
      finished = true;
    }
  }
  return { text, model, finished };
}
