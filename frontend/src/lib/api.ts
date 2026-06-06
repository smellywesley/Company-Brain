/**
 * Company Brain API Client.
 *
 * Typed fetch-based client for the FastAPI backend.
 * Includes Bearer token auth, dev-mode logging, and error handling.
 */

// ── Response types ──────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  version: string;
}

export interface IngestionResponse {
  source: string;
  documents_ingested: number;
  duration_ms: number;
  status: string;
}

export interface WorkflowResponse {
  workflow: string;
  status: string;
  steps: { name: string; status: string }[];
  critic: {
    approved: boolean | null;
    risk_score: number | null;
    reasons: string[];
  };
  final_action: Record<string, unknown>;
  duration_ms: number;
  audit_trail: string[];
}

export interface FeedbackResponse {
  status: string;
  feedback_type: string;
  processed: boolean;
  message: string;
}

export interface SearchResult {
  query: string;
  results: Record<string, unknown>[];
  count: number;
}

export interface ConnectorsResponse {
  connectors: string[];
}

export interface SkillSummary {
  id: string;
  name: string;
  slug: string;
  version: number;
  status: string;
  risk_level: string;
  confidence_score: number;
  created_by: string;
  updated_at: string | null;
}

export interface SkillsResponse {
  skills: SkillSummary[];
}

export interface TenantSettingsResponse {
  tenant_id: string;
  name: string;
  slug: string;
  plan: string;
  billing: {
    accumulated_cost_usd: number;
    total_input_tokens: number;
    total_output_tokens: number;
    total_tokens: number;
  };
  connected_integrations: string[];
}

export interface RiskFactor {
  label: string;
  weight: number;
}

export interface RiskForecast {
  risk_score: number;
  probability: number; // 0-1 calibrated P(negative outcome)
  confidence_low: number; // 0-1
  confidence_high: number; // 0-1
  dynamic_threshold: number; // 0-1
  routed_to_human: boolean;
  autonomy_level: number; // 0-4
  factors: RiskFactor[];
}

export interface WorkflowRunSummary {
  id: string;
  workflow_name: string;
  status: string;
  critic_approved: boolean | null;
  critic_risk_score: number | null;
  critic_risk_level: string;
  critic_reasons: string[];
  final_action: Record<string, unknown>;
  trigger_data: Record<string, unknown>;
  created_at: string | null;
  forecast?: RiskForecast;
}

export interface WorkflowsResponse {
  workflows: WorkflowRunSummary[];
}

export interface VerdictSummary {
  id: string;
  title: string;
  verdict: string;
  risk_score: number;
  risk_level: string;
  reasons: string[];
  probability?: number;
  confidence_low?: number;
  confidence_high?: number;
  dynamic_threshold?: number;
  autonomy_level?: number;
}

export interface VerdictsResponse {
  verdicts: VerdictSummary[];
}

export interface StatsResponse {
  stats: {
    total_workflow_runs: number;
    pending_review: number;
    total_feedback: number;
    total_skills: number;
    active_skills: number;
    accumulated_cost_usd: number;
    total_tokens: number;
  };
}

export interface ActivityItem {
  id: string;
  type: string;
  title: string;
  description: string;
  timestamp: string | null;
}

export interface ActivityResponse {
  activity: ActivityItem[];
}

// ── Differentiator types ─────────────────────────────────────────────────────

export interface BlastNode {
  id: string;
  label: string;
  system: string;
  effect: "write" | "read" | "notify";
  severity: "low" | "medium" | "high";
  detail: string;
}

export interface BlastEdge {
  source: string;
  target: string;
  label: string;
}

export interface BlastRadius {
  origin: BlastNode;
  nodes: BlastNode[];
  edges: BlastEdge[];
  summary: {
    systems_touched: number;
    writes: number;
    reads: number;
    notifies: number;
    highest_severity: "low" | "medium" | "high";
  };
  simulated: boolean;
}

export interface BlastRadiusResponse {
  blast_radius: BlastRadius;
}

export interface AuditStep {
  stage: string;
  label: string;
  detail: string;
}

export interface AuditEntry {
  seq: number;
  run_id: string;
  workflow_name: string;
  status: string;
  risk_score: number | null;
  timestamp: string | null;
  snapshot_digest: string;
  steps: AuditStep[];
  prev_hash: string;
  entry_hash: string;
}

export interface AuditResponse {
  audit: AuditEntry[];
  verified: boolean;
  length: number;
}

export interface AuditSnapshot {
  captured_for_run: string;
  workflow: string;
  context_used: {
    retrieved_at?: string;
    sources?: { source: string; title: string; snippet: string }[];
    graph_facts?: string[];
  };
  candidate_action: Record<string, unknown>;
  critic: {
    risk_score: number | null;
    reasons: string[];
    approved: boolean | null;
  };
}

export interface AuditSnapshotResponse {
  snapshot: AuditSnapshot;
  digest: string;
}

export interface CalibrationBucket {
  bin_low: number;
  bin_high: number;
  predicted_mid: number;
  observed: number | null;
  count: number;
}

export interface CalibrationResponse {
  calibration: {
    curve: CalibrationBucket[];
    samples: number;
    mean_abs_error: number | null;
  };
}

export interface PolicyRule {
  rule: string;
  source: string;
  created_at: string;
  feedback_count: number;
}

export interface PolicyHistoryResponse {
  policy_history: PolicyRule[];
  active_rules: string[];
  count: number;
}

// ── Company Profile / Onboarding ─────────────────────────────────────────────

export interface CompanyBranding {
  display_name: string;
  accent: string;
  industry: string | null;
  logo: string;
}

export interface CompanyProfile {
  tenant_id: string;
  branding: CompanyBranding;
  risk_posture: string;
  risk_params: {
    label: string;
    blurb: string;
    threshold_base: number;
    auto_approve_ceiling_usd: number;
    max_autonomy_level: number;
  };
  connectors: Record<string, boolean>;
  catalog: {
    industries: { id: string; label: string }[];
    postures: { id: string; label: string; blurb: string }[];
  };
}

export interface OnboardingResult {
  status: string;
  branding: CompanyBranding;
  risk_posture: string;
  rules_seeded: number;
}

// ── Client ──────────────────────────────────────────────────────────────────

class CompanyBrainAPI {
  private baseUrl: string;

  constructor() {
    // Same-origin by default: the browser calls /api/* and Next rewrites it to
    // the backend. Keeps one public URL behind a single tunnel (no CORS).
    this.baseUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
  }

  private getHeaders(): HeadersInit {
    const headers: HeadersInit = { "Content-Type": "application/json" };
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("cb_auth_token");
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    }
    return headers;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;

    if (process.env.NODE_ENV === "development") {
      console.log(`[API] ${method} ${path}`, body || "");
    }

    const res = await fetch(url, {
      method,
      headers: this.getHeaders(),
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!res.ok) {
      const errorText = await res.text().catch(() => "Unknown error");
      throw new Error(`API ${method} ${path} failed (${res.status}): ${errorText}`);
    }

    const data = await res.json();

    if (process.env.NODE_ENV === "development") {
      console.log(`[API] Response:`, data);
    }

    return data as T;
  }

  // ── Public methods ────────────────────────────────────────────────────

  async getHealth(): Promise<HealthResponse> {
    return this.request<HealthResponse>("GET", "/health");
  }

  async triggerIngestion(source: string): Promise<IngestionResponse> {
    return this.request<IngestionResponse>("POST", `/ingest/${source}`);
  }

  async executeWorkflow(
    name: string,
    triggerData: Record<string, unknown> = {},
    config: Record<string, unknown> = {},
  ): Promise<WorkflowResponse> {
    return this.request<WorkflowResponse>("POST", `/workflow/${name}`, {
      trigger_data: triggerData,
      config,
    });
  }

  async submitFeedback(
    workflowRunId: string,
    feedbackType: string,
    correctedOutput?: Record<string, unknown>,
    reason?: string,
  ): Promise<FeedbackResponse> {
    return this.request<FeedbackResponse>("POST", "/feedback", {
      workflow_run_id: workflowRunId,
      feedback_type: feedbackType,
      corrected_output: correctedOutput,
      reason,
    });
  }

  async searchKnowledge(
    query: string,
    limit = 10,
  ): Promise<SearchResult> {
    return this.request<SearchResult>("POST", "/search", { query, limit });
  }

  async getConnectors(): Promise<ConnectorsResponse> {
    return this.request<ConnectorsResponse>("GET", "/connectors");
  }

  async getSkills(): Promise<SkillsResponse> {
    return this.request<SkillsResponse>("GET", "/skills");
  }

  async getTenantSettings(): Promise<TenantSettingsResponse> {
    return this.request<TenantSettingsResponse>("GET", "/tenant/settings");
  }

  async getWorkflows(status?: string, limit = 20): Promise<WorkflowsResponse> {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    params.set("limit", String(limit));
    return this.request<WorkflowsResponse>("GET", `/workflows?${params.toString()}`);
  }

  async getVerdicts(limit = 10): Promise<VerdictsResponse> {
    return this.request<VerdictsResponse>("GET", `/verdicts?limit=${limit}`);
  }

  async getStats(): Promise<StatsResponse> {
    return this.request<StatsResponse>("GET", "/stats");
  }

  async getActivity(limit = 12): Promise<ActivityResponse> {
    return this.request<ActivityResponse>("GET", `/activity?limit=${limit}`);
  }

  // ── Differentiators ───────────────────────────────────────────────────

  async getBlastRadius(runId: string): Promise<BlastRadiusResponse> {
    return this.request<BlastRadiusResponse>("GET", `/blast-radius/${runId}`);
  }

  async getAudit(limit = 50): Promise<AuditResponse> {
    return this.request<AuditResponse>("GET", `/audit?limit=${limit}`);
  }

  async getAuditSnapshot(runId: string): Promise<AuditSnapshotResponse> {
    return this.request<AuditSnapshotResponse>("GET", `/audit/${runId}/snapshot`);
  }

  async getCalibration(): Promise<CalibrationResponse> {
    return this.request<CalibrationResponse>("GET", "/critic/calibration");
  }

  async getPolicyHistory(): Promise<PolicyHistoryResponse> {
    return this.request<PolicyHistoryResponse>("GET", "/policy/history");
  }

  async getProfile(): Promise<CompanyProfile> {
    return this.request<CompanyProfile>("GET", "/tenant/profile");
  }

  async updateProfile(body: {
    display_name?: string;
    accent?: string;
    industry?: string;
    risk_posture?: string;
    connectors?: Record<string, boolean>;
  }): Promise<{ status: string; branding: CompanyBranding }> {
    return this.request("PUT", "/tenant/profile", body);
  }

  async onboard(body: {
    company_name: string;
    industry: string;
    risk_posture?: string;
  }): Promise<OnboardingResult> {
    return this.request<OnboardingResult>("POST", "/onboarding", body);
  }
}

export const api = new CompanyBrainAPI();
