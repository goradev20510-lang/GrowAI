// Ported from app.py: Indian digit grouping, lakh/crore short form, IST timestamps.

export function inr(value: number | string | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "—";
  const amount = Number(value);
  const [whole0, frac] = Math.abs(amount).toFixed(decimals).split(".");
  let whole = whole0;
  if (whole.length > 3) {
    let head = whole.slice(0, -3);
    const groups: string[] = [];
    while (head.length > 2) {
      groups.unshift(head.slice(-2));
      head = head.slice(0, -2);
    }
    whole = [...(head ? [head] : []), ...groups, whole0.slice(-3)].join(",");
  }
  return (amount < 0 ? "-" : "") + "₹" + whole + (frac ? `.${frac}` : "");
}

export function inrShort(value: number | null | undefined): string {
  const amount = Number(value || 0);
  if (Math.abs(amount) >= 1e7) return `₹${(amount / 1e7).toFixed(2)} Cr`;
  if (Math.abs(amount) >= 1e5) return `₹${(amount / 1e5).toFixed(2)} L`;
  return inr(amount, 0);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return String(value);
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

export function fmtTs(value: string | null | undefined): string {
  if (!value) return "—";
  const iso = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : value.replace(" ", "T") + "Z";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(value);
  const p = new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const g = (t: string) => p.find((x) => x.type === t)?.value ?? "";
  return `${g("day")} ${g("month")} ${g("year")}, ${g("hour")}:${g("minute")} IST`;
}

export const pct = (n: number, digits = 0) => `${(n * 100).toFixed(digits)}%`;
