// Typed client for the FastAPI layer (api/main.py). Every figure on screen comes from here.

export type Summary = {
  total_transactions: number; matched: number; needs_review: number; unmatched: number; duplicates: number;
  excluded: number; invoices_total: number; invoices_open: number; invoices_partial: number;
  invoices_settled: number; invoices_overpaid: number; open_review_cases: number; amount_received: number;
  amount_matched: number; amount_in_review: number; amount_unmatched: number; amount_duplicate: number;
  invoice_value: number; outstanding_value: number; tds_pending: number; review_queue: number;
  vendor_bills: number; vendor_billed: number; vendor_paid: number; vendor_unpaid: number;
  vendor_bills_missing: number; debit_total: number; debit_unlinked: number; debit_unlinked_count: number;
};

export type StatementLine = Txn & {
  direction: "in" | "out"; debit_amount: number; unlinked: number; linked_to: string[];
};

export type VendorPayment = {
  payment_id: string; transaction_id: string; bill_id: string | null; amount: number; linked_by: string;
  notes: string | null; vendor_name: string | null; bill_number: string | null; transaction_date: string | null;
};

export type VendorBill = {
  bill_id: string; vendor_name: string; bill_number: string; bill_date: string | null; due_date: string | null;
  amount: number; paid: number; pending: number; status: string; bill_on_file: boolean; payments: VendorPayment[];
};

export type DebitDetail = {
  debit: Txn & { debit_amount: number; linked: number; unlinked: number; links: VendorPayment[] };
  suggestions: (VendorBill & { reasons: string[]; would_link: number })[];
};

export type Txn = {
  transaction_id: string; transaction_date: string | null; narration: string | null; utr: string | null;
  credit_amount: number; status: string; bank_name: string | null; account_number: string | null;
};

export type Invoice = {
  invoice_id: string; customer_name: string | null; invoice_date: string | null; due_date: string | null;
  total_amount: number; taxable_amount: number | null; outstanding_amount: number; status: string;
};

export type Allocation = {
  allocation_id: string; invoice_id: string; bank_credit: number; tds: number; tds_section: string | null;
  applied: number; score: number; status: string; decided_by: string | null; decision_reason: string | null;
};

export type Case = {
  case_id: string; transaction_id: string; invoice_id: string | null; exception_type: string;
  exception_summary: string | null; suggested_action: string | null; status: string; created_at: string | null;
  reviewed_at?: string | null; reviewer?: string | null; resolution_notes?: string | null;
  amount?: number; stale?: string[];
};

export type Remittance = {
  customer_name: string | null; invoice_references: string[]; payment_amount: number | null;
  tds_amount: number | null; tds_section: string | null; payment_date: string | null; utr: string | null;
  evidence_text: string[];
};

export type CaseDetail = {
  case: Case; transaction: Txn; invoice: Invoice | null; proposed: Allocation[]; remittance: Remittance | null;
};

export type TdsRow = {
  component_id: string; invoice_id: string; customer_name: string | null; transaction_id: string;
  amount: number; tds_section: string | null; tds_status: string | null; supporting_doc: string | null;
};

export type AuditRow = {
  log_id: string; entity_type: string; entity_id: string; action: string; actor: string;
  details: Record<string, unknown> | string; created_at: string;
};

export class ApiError extends Error {}

let reviewerName = "";
// HTTP headers only carry Latin-1.
export const setApiReviewer = (name: string) => { reviewerName = name.replace(/[^\x20-\x7e\xa0-\xff]/g, "").trim(); };

// Set by the Clerk gate; unused when the app runs without sign-in.
let tokenProvider: (() => Promise<string | null>) | null = null;
export const setApiTokenProvider = (p: typeof tokenProvider) => { tokenProvider = p; };

async function authorise(headers: Headers) {
  const token = await tokenProvider?.();
  if (token) headers.set("Authorization", `Bearer ${token}`);
}

export async function downloadReport() {
  const headers = new Headers();
  await authorise(headers);
  const res = await fetch("/api/reports/export.xlsx", { headers, cache: "no-store" });
  if (!res.ok) throw new ApiError(`Could not download the report (${res.status}).`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = res.headers.get("content-disposition")?.match(/filename="([^"]+)"/)?.[1] ?? "reconciliation.xlsx";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (reviewerName) headers.set("X-Reviewer", reviewerName);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  await authorise(headers);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError("Can't reach the ReconcileAI API. Start it with: uvicorn api.main:app --port 8000");
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {}
    if (res.status >= 500 && msg.startsWith("5")) msg = "The API is not responding. Is uvicorn running on port 8000?";
    throw new ApiError(msg);
  }
  return res.json() as Promise<T>;
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) });

export const api = {
  summary: () => request<Summary>("/summary"),
  meta: () => request<{ tds_sections: Record<string, number>; audit_actions: string[] }>("/meta"),
  transactions: () => request<Txn[]>("/transactions"),
  transaction: (id: string) => request<{ transaction: Txn; allocations: Allocation[] }>(`/transactions/${id}`),
  reconcileOne: (id: string) => post<{ outcome: string; invoice_id?: string }>(`/transactions/${id}/reconcile`),
  reverse: (id: string, notes: string) => post(`/transactions/${id}/reverse`, { notes }),
  statement: () => request<StatementLine[]>("/statement"),
  vendorBills: () => request<VendorBill[]>("/vendor-bills"),
  debit: (id: string) => request<DebitDetail>(`/debits/${id}`),
  linkDebit: (id: string, bill_id: string) => post<{ amount: number }>(`/debits/${id}/link`, { bill_id }),
  notVendor: (id: string, notes: string) => post(`/debits/${id}/not-vendor`, { notes }),
  unlinkPayment: (id: string, notes: string) => post(`/payments/${id}/unlink`, { notes }),
  billOnFile: (id: string, on_file: boolean) => post(`/vendor-bills/${id}/on-file`, { on_file }),
  invoices: () => request<Invoice[]>("/invoices"),
  openInvoices: (credit: number) => request<Invoice[]>(`/invoices/open?credit=${credit}`),
  review: () => request<Case[]>("/review"),
  resolved: () => request<Case[]>("/review/resolved"),
  case: (id: string) => request<CaseDetail>(`/review/${id}`),
  decide: (id: string, body: { action: string; notes?: string; invoice_ids?: string[]; tds_amount?: number;
    tds_section?: string | null }) => post<Record<string, unknown>>(`/review/${id}/decide`, body),
  loadDemo: () => post<{ already_loaded?: boolean; invoices?: number; transactions?: number }>("/demo/load"),
  reconcile: () => post<{ total: number; matched: number; needs_review: number; unmatched: number;
    duplicates?: number }>("/reconcile"),
  importFile: (kind: "bank" | "invoice" | "remittance" | "vendor_bill", form: FormData) =>
    post<Record<string, unknown> & { success?: boolean; reason?: string; duplicate_file?: boolean }>(`/import/${kind}`, form),
  documents: () => request<{ document_id: string; filename: string; document_type: string | null; upload_time: string }[]>("/documents"),
  aging: () => request<{ as_of: string; buckets: { bucket: string; invoices: number; outstanding: number }[];
    by_customer: Record<string, string | number | null>[]; detail: Record<string, string | number | null>[] }>("/reports/aging"),
  customers: () => request<Record<string, string | number | null>[]>("/reports/customers"),
  tds: () => request<TdsRow[]>("/reports/tds"),
  verifyTds: (id: string, form: FormData) => post(`/tds/${id}/verify`, form),
  rejectTds: (id: string, notes: string) => post<{ invoice_id?: string; new_outstanding?: number }>(`/tds/${id}/reject`, { notes }),
  draftSummary: () => post<{ text: string; used_llm: boolean }>("/reports/draft-summary"),
  audit: (q: { q?: string; entity?: string; action?: string }) => {
    const p = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]);
    return request<AuditRow[]>(`/audit?${p}`);
  },
  ask: (query: string) => post<{ answer: string; used_llm: boolean; source: string | null; rows: unknown }>("/ask", { query }),
};
