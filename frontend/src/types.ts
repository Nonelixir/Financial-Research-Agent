export type Company = { cik: string; ticker: string; name: string; aliases?: string[] };
export type Scope = { language?: 'zh' | 'en'; companies: Company[]; fiscal_years: number[]; forms: string[]; restatement_policy: string; strict?: boolean };
export type Claim = { text: string; citation_ids: string[] };
export type Answer = { claims: Claim[]; message?: string; caveats: string[]; status: string; status_reason?: string | null };
export type EventRecord = { event: string; data: Record<string, any> };
export type Message = { id: string; role: 'user' | 'assistant'; content: string; answer?: Answer; events: EventRecord[]; status: string };
export type TableRow = { company: Company; metric: string; period: string; cell: {
  value: string | null; display_value: string; unit?: string; source_citation_ids: string[];
  verification: {status: string};
} };
export type FinancialTable = { rows: TableRow[]; title: string; verified: boolean; warnings: string[] };
export type TextDocument = { text: string; verification: string; legacy?: boolean };
export type ArtifactData = { id: string; kind: 'document' | 'report' | 'table'; title: string; data: Answer | FinancialTable | TextDocument; scope: Scope; message_id?: string;
  file?: { relative_path: string; size_bytes: number; sha256: string; origin_message_id?: string } };
export type Thread = { id: string; title: string; scope: Scope | null; messages: Message[]; artifacts: ArtifactData[]; research_sample?: {members: {company: Company; reason: string; citation_ids: string[]}[]} | null };
export type ThreadSummary = { id: string; title: string; updated_at: string };
