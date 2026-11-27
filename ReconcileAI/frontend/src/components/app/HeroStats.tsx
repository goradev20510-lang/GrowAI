"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { inr } from "@/lib/format";

const money = (n: number) => inr(n, 0);

/** The three headline figures: bank money, invoices, and what still needs a person. */
export function HeroStats() {
  const { data: s } = useQuery({ queryKey: ["summary"], queryFn: api.summary });
  if (!s) return <p className="mt-8 text-[14px] text-fg-3">Figures appear once the API responds.</p>;
  const settled = Math.max(0, s.invoice_value - s.outstanding_value);

  return (
    <div className="mt-8 grid gap-x-8 gap-y-7 md:grid-cols-2">
      <Block title="Bank credits" figure={money(s.amount_matched)} of={`matched of ${money(s.amount_received)}`}>
        <Bar total={s.amount_received} solid={s.amount_matched} striped={s.amount_in_review} />
        <Legend items={[["bg-white", "Matched", money(s.amount_matched)], ["stripes", "In review", money(s.amount_in_review)]]} />
        <Legend items={[["", "Unmatched", money(s.amount_unmatched)], ["", "Duplicate", money(s.amount_duplicate)]]} />
      </Block>

      <Block title="Invoices" figure={money(settled)} of={`settled of ${money(s.invoice_value)}`}>
        <Bar total={s.invoice_value} solid={settled} />
        <Legend items={[["bg-white", "Settled", money(settled)], ["", "Outstanding", money(s.outstanding_value)]]} />
        <Legend items={[["", "TDS awaiting certificate", money(s.tds_pending)]]} />
      </Block>

      <div>
        <p className="text-[15px] font-bold text-fg-2">Needs a person</p>
        <p className="mt-1 text-[16px] font-semibold text-fg-2">
          <span className="num mr-2 font-display text-[2.25rem] font-bold text-brick">{s.review_queue}</span>
          {s.review_queue === 1 ? "case to check" : "cases to check"}
        </p>
        <p className="mt-3 text-[14px] text-fg-2">
          <b className="num text-fg">{money(s.amount_in_review + s.amount_unmatched)}</b> in review or unmatched
        </p>
      </div>
    </div>
  );
}

function Block({ title, figure, of, children }: { title: string; figure: string; of: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[15px] font-bold text-fg-2">{title}</p>
      <p className="mt-1 text-[16px] font-semibold text-fg-2">
        <span className="num mr-2 font-display text-[2.25rem] font-bold text-white">{figure}</span>
        <span className="num whitespace-nowrap">{of}</span>
      </p>
      {children}
    </div>
  );
}

function Bar({ total, solid, striped = 0 }: { total: number; solid: number; striped?: number }) {
  const width = (n: number) => `${total > 0 ? Math.min(100, (n / total) * 100) : 0}%`;
  return (
    <div className="mt-2 flex h-5 overflow-hidden rounded-sm border border-line-3" aria-hidden>
      <span className="h-full bg-white" style={{ width: width(solid) }} />
      {striped > 0 && <span className="stripes h-full" style={{ width: width(striped) }} />}
    </div>
  );
}

function Legend({ items }: { items: [string, string, string][] }) {
  return (
    <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[14px] text-fg-2">
      {items.map(([swatch, label, value]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          {swatch && <span className={`${swatch} size-2.5 rounded-[2px]`} aria-hidden />}
          {label} <b className="num text-fg">{value}</b>
        </span>
      ))}
    </p>
  );
}
