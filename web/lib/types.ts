// Wire fields come from api/ask.py, api/ask_view.py and domain/supervisor.py.
export type ClaimChoice =
  | { mode: "selected"; claims: string[]; requested_claim: string | null }
  | { mode: "keep_requested"; claims: string[]; requested_claim: string | null }
  | { mode: "none"; claims: string[]; requested_claim: string | null };

export type ApiErrorBody = { detail: string } | { detail: unknown[] };

export type EvidenceCard = {
  evidence_id: string | null;
  source: string | null;
  url: string | null;
  brand: string | null;
  title: string | null;
  published_at: string | null;
  view_count: number | null;
  like_count: number | null;
  hook_type: string | null;
  angle: string | null;
  format: string | null;
  talent: string | null;
  cta_type: string | null;
  claims: string[] | null;
};

export type ResultCount = {
  tool: string;
  row_count: number;
  shown_count: number;
  truncated?: boolean;
  count_label: string;
};

// ask_view filters plan fields against domain/plan.py, without adding defaults.
export type Plan = {
  title: string;
  hook_type: string;
  hook_text: string;
  scenes: string[];
  copy_lines: string[];
  image_brief: string | null;
  cta_type: string;
  angle: string;
  format: string;
  category: string;
  product_url: string | null;
  claimed_efficacy: string[];
  evidence_ids: string[];
};

export type ImageReference = {
  request_key: string;
  index: number;
  mime: "image/png" | "image/jpeg" | "image/webp";
  size: number;
  sha256: string;
  composed?: {
    mime: "image/png";
    size: number;
    sha256: string;
    contrast_adjusted?: boolean;
    min_contrast?: number;
  };
};

export type UiCommand =
  | {
      kind: "show_evidence_cards";
      data: { cards: EvidenceCard[]; missing: number };
    }
  | {
      kind: "show_plan";
      data: {
        plan: Partial<Plan>;
        plan_id: string | null;
        passed: boolean;
        unknown_count: number;
        unknown_codes: Record<string, number>;
        efficacy_status: Record<string, unknown>;
        efficacy_summary: { supported: number; unknown: number };
        count_label: string;
        result_counts: ResultCount[];
        evidence_counts: Record<string, unknown>;
        status: string;
        attempts: unknown[];
        pattern_alignment: Record<string, unknown>;
        pattern_alignment_label: string;
        disclaimer: string;
        image: ImageReference | null;
        design_disclaimer: string | null;
        product_display: {
          brand: string | null;
          display_name: string | null;
          product_name: string | null;
        };
      };
    }
  | {
      kind: "show_distribution";
      data: { tool: string; rows: Record<string, unknown>[] };
    }
  | { kind: "show_graph_fragment"; data: { evidence_ids: string[] } }
  | {
      kind: "show_aggregates";
      data: {
        label: string;
        verified_counts: ResultCount[];
        model_written: { name: string; value: unknown }[];
        removed: string[];
      };
    }
  | {
      kind: "show_cost";
      data: { label: string; text_spent_usd: number; max_text_cost_usd: number };
    };

export type SseFrame =
  | { event: "step"; data: { agent: string; phase: string; status: string } }
  | { event: "tool_start"; data: { name: string; kind: string } }
  | { event: "token"; data: { text: string; display_text?: string } }
  | { event: "ui_command"; data: UiCommand }
  | { event: "error"; data: { code: string; detail?: string; error_code?: string } }
  | {
      event: "needs_clarification";
      data: {
        reason: "requested_not_confirmed" | "no_claim_requested" | "no_efficacy_confirmed";
        requested_claim: string | null;
        requested_label: string | null;
        available: { claim: string; label: string }[];
        text: string;
        options: {
          id: "keep_requested" | "select_confirmed" | "select_one" | "select_many" | "none" | "cancel";
          label: string;
        }[];
      };
    }
  | { event: "efficacy_unavailable"; data: { reason: "failed" | "no_product"; text: string } };

export type Workspace = {
  tenant_id: string;
  display_name: string | null;
  brand: string | null;
  product_name: string | null;
};
export type WorkspacesResponse = { workspaces: Workspace[]; image_enabled: boolean };
export type Clarification = Extract<SseFrame, { event: "needs_clarification" }>["data"];
export type StepEvent = Extract<SseFrame, { event: "step" }>["data"];

export type SchemaResponse = {
  labels: { label: string; layer: number; name_ko: string }[];
  relationships: { type: string; from: string; to: string; layer: number }[];
  taxonomy: Record<"hook_type" | "angle" | "format", { value: string; name: string; definition: string }[]>;
  claims: { value: string; name: string }[];
};
export type PlanView = Extract<UiCommand, { kind: "show_plan" }>["data"];
export type PatternAxis = {
  plan: string | null;
  dominant: string[];
  same: boolean | null;
  share: number | null;
};
export type PatternData = {
  axes?: Partial<Record<"hook_type" | "angle" | "format", PatternAxis>>;
  compared?: number;
  same_count?: number;
  skipped?: number;
};
export type EvaluationAttempt = {
  attempt: number;
  scores?: Record<string, number> | null;
  low_items?: string[];
  checks_passed?: boolean | null;
  final_passed?: boolean | null;
  cost_usd?: number | null;
};

// Read-only projection from graph/fragment_queries.py.
export type GraphNode = {
  id: string;
  label: string;
  name: string | null;
  props: Record<string, unknown>;
};
export type GraphFragment = {
  nodes: GraphNode[];
  edges: { source: string; target: string; type: string }[];
  missing: string[];
};

// api/plans.py projects only present plan fields and adds approval metadata.
export type SavedPlan = Partial<Pick<Plan,
  "title" | "hook_text" | "hook_type" | "angle" | "format" | "claimed_efficacy"
  | "scenes" | "copy_lines" | "evidence_ids"
>> & {
  plan_id: string;
  has_image: boolean;
  decided_at: string;
  reason: string;
};
