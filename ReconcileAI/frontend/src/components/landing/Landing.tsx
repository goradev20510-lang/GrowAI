import { Logo } from "@/components/Logo";
import { LinkButton } from "@/components/ui";

const PRINCIPLES = [
  {
    title: "The model reads. Python counts.",
    body: "A language model only pulls fields out of PDFs and payment emails. Every amount, TDS split and allocation is computed by deterministic code you can re-run and test.",
  },
  {
    title: "Uncertain means a person decides.",
    body: "Short-pays, bulk credits, possible duplicates and weak matches go to a review queue with the remittance excerpt, the proposed allocation and the reason it stopped.",
  },
  {
    title: "Every decision leaves a trail.",
    body: "Approvals, rejections and reversals are logged against a named reviewer with their note. Month-end gets one workbook: ledger, ageing, TDS register and the audit log.",
  },
];

const STEPS = [
  { title: "Import", body: "Bank statements as CSV or Excel, invoices as PDF or spreadsheet, payment emails as .eml or pasted text. A re-uploaded file is recognised by its hash and skipped." },
  { title: "Match", body: "UTRs, quoted invoice numbers, amounts and payer names score every open invoice. A shortfall is tested against the TDS rates for 194C, 194J and the rest before anything is called a part-payment." },
  { title: "Review", body: "Clean matches post on their own. Everything else waits for a reviewer, who approves, rejects or reassigns it to other invoices, in the order they should settle." },
  { title: "Settle", body: "Approved allocations post the bank credit and the TDS as separate components. The TDS only counts once a Form 16A is checked; a rejected claim re-opens the invoice." },
];

export function Landing() {
  return (
    <div>
      <header className="bg-hero">
        <div className="shell pb-16 pt-6">
          <Logo />
          <h1 className="mt-16 text-[clamp(2.4rem,6vw,3.6rem)]">Every rupee, reconciled.</h1>
          <p className="mt-3 max-w-[58ch] text-[17px] text-fg-2">
            Bank credits matched to open invoices for Indian businesses. TDS, part-payments and bulk payments are
            worked out by code; anything uncertain goes to a named reviewer with the evidence beside it.
          </p>
          <LinkButton href="/app" variant="primary" size="lg" className="mt-7">Open workspace</LinkButton>
        </div>
      </header>

      <main className="shell py-14">
        <h2 className="text-[1.35rem]">How it works</h2>
        <ol className="mt-4 border-t border-line">
          {STEPS.map((s, i) => (
            <li key={s.title} className="grid gap-1 border-b border-line py-5 sm:grid-cols-[200px_1fr]">
              <h3 className="text-[1.05rem]">{i + 1}. {s.title}</h3>
              <p className="max-w-[68ch] text-fg-2">{s.body}</p>
            </li>
          ))}
        </ol>

        <h2 className="mt-14 text-[1.35rem]">What you can rely on</h2>
        <div className="mt-4 grid gap-8 border-t border-line pt-6 md:grid-cols-3">
          {PRINCIPLES.map((p) => (
            <div key={p.title}>
              <h3 className="text-[1.05rem]">{p.title}</h3>
              <p className="mt-2 text-[14px] text-fg-2">{p.body}</p>
            </div>
          ))}
        </div>
      </main>

      <footer className="border-t border-line">
        <p className="shell py-8 text-[13px] text-fg-3">
          A prototype on synthetic data. Not tax or legal advice; a qualified reviewer signs off every exception.
        </p>
      </footer>
    </div>
  );
}
