// Same vocabulary as app.py, so both UIs speak the same language.

export type Tone = "ice" | "amber" | "brick" | "muted" | "sea";

export const TXN_STATUS: Record<string, { label: string; tone: Tone }> = {
  matched: { label: "Matched", tone: "ice" },
  review: { label: "In review", tone: "amber" },
  unmatched: { label: "Unmatched", tone: "brick" },
  duplicate: { label: "Duplicate", tone: "muted" },
  excluded: { label: "Excluded", tone: "muted" },
};

export const DEBIT_STATUS: Record<string, { label: string; tone: Tone }> = {
  linked: { label: "Linked", tone: "ice" },
  part_linked: { label: "Part-linked", tone: "amber" },
  not_linked: { label: "Not linked", tone: "brick" },
  not_vendor: { label: "Not a vendor", tone: "muted" },
};

export const BILL_STATUS: Record<string, { label: string; tone: Tone }> = {
  paid: { label: "Paid", tone: "ice" },
  part_paid: { label: "Part-paid", tone: "amber" },
  unpaid: { label: "Unpaid", tone: "brick" },
};

export const INV_STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "Open", tone: "sea" },
  partially_paid: { label: "Part-paid", tone: "amber" },
  settled: { label: "Settled", tone: "ice" },
  overpaid: { label: "Overpaid", tone: "brick" },
};

export const CASE_STATUS: Record<string, string> = {
  open: "Open", approved: "Approved", rejected: "Rejected", corrected: "Reassigned",
  escalated: "Escalated", superseded: "Superseded by re-run",
};

export const EXCEPTIONS: Record<string, string> = {
  multiple_candidate_invoices: "Several invoices fit",
  possible_tds_deduction: "Short-paid, possible TDS",
  partial_payment: "Part-payment",
  overpayment: "Overpayment",
  invoice_already_settled: "Invoice already settled",
  bulk_payment: "One credit, several invoices",
  low_confidence_match: "Weak match",
  missing_invoice_reference: "No invoice reference",
  unknown_customer: "Unknown payer",
  possible_duplicate: "Possible duplicate",
  amount_discrepancy: "Amount differs",
  payer_mismatch: "Payer does not match",
  unverified_evidence: "Evidence needs checking",
  processing_error: "Processing failed",
};

export const TDS_STATUS: Record<string, string> = {
  claimed: "Claimed", evidence_pending: "Awaiting Form 16A", verified: "Verified", rejected: "Rejected",
};

export const AGEING_LABELS: Record<string, string> = {
  "Not due": "Not yet due", "1–30": "1–30 days overdue", "31–60": "31–60 days overdue",
  "61–90": "61–90 days overdue", "90+": "Over 90 days overdue",
};

const humanise = (s?: string | null) => (s ?? "—").replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
export const excLabel = (k?: string | null) => EXCEPTIONS[k ?? ""] ?? humanise(k);
export const txnStatus = (s?: string | null) => TXN_STATUS[s ?? ""] ?? { label: humanise(s), tone: "muted" as Tone };
export const invStatus = (s?: string | null) => INV_STATUS[s ?? ""] ?? { label: humanise(s), tone: "muted" as Tone };
