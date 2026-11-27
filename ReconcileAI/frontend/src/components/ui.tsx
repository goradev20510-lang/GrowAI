"use client";

import clsx from "clsx";
import Link from "next/link";
import { CircleNotch } from "@phosphor-icons/react";
import type { Tone } from "@/lib/vocab";
import { ApiError } from "@/lib/api";

/* ── Buttons ─────────────────────────────────────────────────────────────── */

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "quiet" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
};

const btnBase =
  "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-md font-semibold " +
  "transition-colors duration-150 disabled:pointer-events-none disabled:opacity-40 cursor-pointer";

const btnVariant = {
  primary: "bg-white text-hero hover:bg-fg-2",
  ghost: "border border-line-2 text-fg hover:border-line-3 hover:bg-white/[0.05]",
  quiet: "text-fg-2 hover:text-fg hover:bg-white/[0.06]",
  danger: "border border-brick/50 text-brick hover:bg-brick/10",
};
const btnSize = { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4 text-sm", lg: "h-11 px-5 text-[15px]" };

export function Button({ variant = "ghost", size = "md", loading, className, children, ...rest }: BtnProps) {
  return (
    <button className={clsx(btnBase, btnVariant[variant], btnSize[size], className)} {...rest}>
      {loading && <CircleNotch className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function LinkButton({ href, variant = "ghost", size = "md", className, children }: {
  href: string; variant?: BtnProps["variant"]; size?: BtnProps["size"]; className?: string; children: React.ReactNode;
}) {
  return (
    <Link href={href} className={clsx(btnBase, btnVariant[variant], btnSize[size], className)}>
      {children}
    </Link>
  );
}

/* ── Status ──────────────────────────────────────────────────────────────── */

const toneDot: Record<Tone, string> = {
  ice: "bg-ok", amber: "bg-amber", brick: "bg-brick", muted: "bg-fg-4", sea: "bg-sea",
};
const toneBadge: Record<Tone, string> = {
  ice: "border-ok text-ok", amber: "border-amber text-amber", brick: "border-brick text-brick",
  muted: "border-line-3 text-fg-3", sea: "border-sea text-sea",
};

export function Status({ label, tone }: { label: string; tone: Tone }) {
  return (
    <span className={clsx("inline-flex items-center whitespace-nowrap rounded border px-2 py-0.5 text-[12.5px] font-semibold", toneBadge[tone])}>
      {label}
    </span>
  );
}

/* ── Page structure ──────────────────────────────────────────────────────── */

export function PageHead({ title, lede, actions }: { title: string; lede?: string; actions?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-10 gap-y-4 pb-6">
      <div>
        <h2 className="text-[1.35rem]">{title}</h2>
        {lede && <p className="mt-1 max-w-[72ch] text-[14px] text-fg-3">{lede}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function SectionHead({ title, aside }: { title: string; aside?: React.ReactNode }) {
  return (
    <div className="mb-3 mt-12 flex items-end justify-between gap-6 first:mt-0">
      <h2 className="text-[1.15rem]">{title}</h2>
      {aside}
    </div>
  );
}

/* ── Table ───────────────────────────────────────────────────────────────── */

export type Col<T> = { key: string; head: string; cell: (r: T) => React.ReactNode; num?: boolean; className?: string };

export function Table<T>({ rows, cols, rowKey, onRow, selected, max, empty = "Nothing here yet." }: {
  rows: T[]; cols: Col<T>[]; rowKey: (r: T) => string; onRow?: (r: T) => void; selected?: string | null;
  max?: number; empty?: string;
}) {
  if (!rows.length) return <p className="border-y border-line px-3 py-10 text-center text-fg-3">{empty}</p>;
  return (
    <div className="overflow-hidden">
      <div className={clsx("overflow-auto", max && "max-h-[--max]")} style={max ? ({ maxHeight: max } as React.CSSProperties) : undefined}>
        <table className="w-full border-collapse text-left text-[14px]">
          <thead className="sticky top-0 z-10 bg-void">
            <tr>
              {cols.map((c) => (
                <th key={c.key} scope="col"
                  className={clsx("border-b border-line px-3 py-3 text-[13px] font-semibold text-fg-3", c.num && "text-right", c.className)}>
                  {c.head}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const k = rowKey(r);
              const active = selected === k;
              return (
                <tr key={k}
                  onClick={onRow ? () => onRow(r) : undefined}
                  onKeyDown={onRow ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onRow(r)) : undefined}
                  tabIndex={onRow ? 0 : undefined}
                  aria-selected={onRow ? active : undefined}
                  className={clsx("border-b border-line last:border-b-0 transition-colors duration-150",
                    onRow && "cursor-pointer hover:bg-white/[0.03] focus-visible:bg-white/[0.04] focus-visible:outline-none",
                    active && "bg-white/[0.06] hover:bg-white/[0.06]")}>
                  {cols.map((c) => (
                    <td key={c.key} className={clsx("px-3 py-4 align-middle", c.num && "num text-right", c.className)}>{c.cell(r)}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export const Mono = ({ children }: { children: React.ReactNode }) => (
  <span className="font-mono text-[12.5px] text-fg-2">{children ?? "—"}</span>
);

/* ── Key/value list ──────────────────────────────────────────────────────── */

export function KV({ rows }: { rows: [string, React.ReactNode, boolean?][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-6 text-[14px]">
      {rows.map(([k, v, mono]) => (
        <div key={k} className="contents">
          <dt className="border-t border-line py-2.5 text-fg-3">{k}</dt>
          <dd className={clsx("border-t border-line py-2.5 text-fg break-words", mono && "font-mono text-[12.5px] text-fg-2")}>
            {v === null || v === undefined || v === "" ? "—" : v}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/* ── Feedback ────────────────────────────────────────────────────────────── */

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-lg bg-white/[0.05]", className)} />;
}

export function ErrorNote({ error }: { error: unknown }) {
  const msg = error instanceof ApiError || error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="card border-brick/30 px-6 py-5 text-[14px]">
      <p className="font-medium text-brick">Couldn&apos;t load this.</p>
      <p className="mt-1 text-fg-2">{msg}</p>
    </div>
  );
}

export function Notice({ tone = "muted", children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 rounded-lg border border-line bg-white/[0.02] px-5 py-4 text-[14px] text-fg-2">
      <span className={clsx("mt-2 size-1.5 shrink-0 rounded-full", toneDot[tone])} aria-hidden />
      <div>{children}</div>
    </div>
  );
}

/* ── Inputs ──────────────────────────────────────────────────────────────── */

export const inputCls =
  "h-10 w-full rounded-md border border-line-2 bg-s1 px-3.5 text-[14px] text-fg placeholder:text-fg-4 " +
  "transition-colors duration-150 hover:border-line-3 focus:border-ice/60 focus:outline-none";

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-[13px] font-medium text-fg-2">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-[12.5px] text-fg-3">{hint}</span>}
    </label>
  );
}

export function Pills<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string; count?: number }[];
}) {
  return (
    <div role="radiogroup" className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={clsx("h-8 cursor-pointer rounded-md border px-3 text-[13px] transition-colors duration-150",
            value === o.value ? "border-white bg-white text-hero" : "border-line-2 text-fg-2 hover:border-line-3 hover:text-fg")}>
          {o.label}
          {o.count !== undefined && <span className="num ml-1.5 opacity-60">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}
