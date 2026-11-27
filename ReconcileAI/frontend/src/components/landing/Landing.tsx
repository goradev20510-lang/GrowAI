"use client";

import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { Asterisk } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import { inrShort, pct } from "@/lib/format";
import { Logo } from "@/components/Logo";
import { LinkButton } from "@/components/ui";
import { Scene } from "@/components/three/Scene";
import type { Progress } from "@/components/three/LedgerScene";
import { Preloader } from "./Preloader";
import { SmoothScroll } from "./SmoothScroll";

gsap.registerPlugin(ScrollTrigger, SplitText, useGSAP);

const TERMS = [
  "Bank statements", "UTR", "Remittance advice", "Section 194C", "Section 194J", "Form 16A", "26AS",
  "Part-payments", "Bulk credits", "Overpayments", "Duplicates", "Receivables ageing",
];

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
  const root = useRef<HTMLDivElement>(null);
  const progress = useRef(0) as Progress;
  const { data: s } = useQuery({ queryKey: ["summary"], queryFn: api.summary, retry: 0 });

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        // Headline: lines rise out of a mask, once, after the preloader.
        const split = SplitText.create(".hero-title", { type: "lines,words", mask: "lines" });
        gsap.from(split.words, { yPercent: 110, duration: 1.2, ease: "expo.out", stagger: 0.06, delay: 1.45 });
        gsap.from(".hero-fade", { opacity: 0, y: 16, duration: 1, ease: "expo.out", stagger: 0.08, delay: 1.9 });

        // Scroll drives the rings: rotation + dolly through the hero, read each frame by the scene.
        ScrollTrigger.create({
          trigger: ".hero", start: "top top", end: "bottom top", scrub: true,
          onUpdate: (st) => { progress.current = st.progress; },
        });
        gsap.to(".hero-copy", { yPercent: -30, opacity: 0, ease: "none",
          scrollTrigger: { trigger: ".hero", start: "top top", end: "70% top", scrub: true } });

        // Principles: each statement sharpens from blur as it reaches the reading line.
        gsap.utils.toArray<HTMLElement>(".principle").forEach((el) => {
          gsap.fromTo(el, { opacity: 0.18, filter: "blur(6px)" }, { opacity: 1, filter: "blur(0px)", ease: "none",
            scrollTrigger: { trigger: el, start: "top 85%", end: "top 45%", scrub: true } });
        });

        // How it works: pinned, steps advance with scroll, progress rule fills.
        const steps = gsap.utils.toArray<HTMLElement>(".step");
        const tl = gsap.timeline({ scrollTrigger: { trigger: ".flow", start: "top top", end: `+=${steps.length * 70}%`,
          scrub: 0.6, pin: ".flow-pin" } });
        steps.forEach((step, i) => {
          if (i > 0) tl.fromTo(step, { opacity: 0, y: 40, filter: "blur(8px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 1 }, i);
          if (i > 0) tl.to(steps[i - 1], { opacity: 0, y: -40, filter: "blur(8px)", duration: 1 }, i);
          tl.to(".flow-index", { innerText: i + 1, snap: { innerText: 1 }, duration: 0.01 }, i);
        });
        tl.fromTo(".flow-bar", { scaleX: 0 }, { scaleX: 1, ease: "none", duration: steps.length }, 0);

        // Figures count up once.
        gsap.utils.toArray<HTMLElement>(".count").forEach((el) => {
          gsap.from(el, { opacity: 0, y: 24, duration: 1, ease: "expo.out", scrollTrigger: { trigger: el, start: "top 88%" } });
        });
      });
      return () => mm.revert();
    },
    { scope: root, dependencies: [] },
  );

  const hasData = !!s && s.total_transactions > 0;
  const stats = hasData
    ? [
        { v: String(s.total_transactions), l: "bank credits in the ledger" },
        { v: pct(s.matched / Math.max(1, s.total_transactions)), l: "settled without a person" },
        { v: String(s.review_queue), l: "waiting for a reviewer" },
        { v: inrShort(s.outstanding_value), l: "still owed by customers" },
      ]
    : null;

  return (
    <SmoothScroll>
      <Preloader />
      <div ref={root} className="relative overflow-x-clip">
        <nav className="fixed inset-x-0 top-0 z-50 border-b border-line bg-void/70 backdrop-blur-xl">
          <div className="shell flex h-16 items-center justify-between">
            <Logo />
            <div className="hidden items-center gap-8 text-[14px] text-fg-2 md:flex">
              <a href="#principles" className="transition-colors hover:text-fg">Principles</a>
              <a href="#how" className="transition-colors hover:text-fg">How it works</a>
              <a href="#ledger" className="transition-colors hover:text-fg">Ledger</a>
            </div>
            <LinkButton href="/app/overview" variant="primary" size="sm" arrow>Open workspace</LinkButton>
          </div>
        </nav>

        {/* Hero */}
        <section className="hero relative h-[100svh] min-h-[640px]">
          <Scene progress={progress} className="absolute inset-0" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-48 bg-gradient-to-b from-transparent to-void" />
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(70%_55%_at_12%_92%,rgb(0_0_0/0.82),transparent_70%)]" />
          <div className="hero-copy shell relative flex h-full flex-col justify-end pb-[clamp(40px,9vh,96px)]">
            <h1 className="hero-title max-w-[11ch] text-[clamp(3.4rem,10vw,9rem)] font-medium leading-[0.92] tracking-[-0.045em]">
              Every rupee, reconciled.
            </h1>
            <div className="mt-10 flex flex-wrap items-end justify-between gap-8">
              <p className="hero-fade max-w-[46ch] text-[16px] leading-relaxed text-fg-2">
                Bank credits matched to open invoices for Indian businesses. TDS, part-payments and bulk payments are
                worked out by code; anything uncertain goes to a named reviewer with the evidence beside it.
              </p>
              <div className="hero-fade flex flex-wrap gap-3">
                <LinkButton href="/app/overview" variant="primary" size="lg" arrow>Open workspace</LinkButton>
                <a href="#how" className="inline-flex h-13 items-center rounded-full border border-line-2 px-7 text-[15px] font-medium transition-colors hover:border-line-3 hover:bg-white/[0.04]">
                  How it works
                </a>
              </div>
            </div>
          </div>
        </section>

        {/* Marquee */}
        <div className="border-y border-line py-6" aria-label="What it handles">
          <div className="flex w-max animate-[marquee_48s_linear_infinite] gap-14 pr-14 hover:[animation-play-state:paused]">
            {[...TERMS, ...TERMS].map((t, i) => (
              <span key={i} className="flex items-center gap-14 whitespace-nowrap font-display text-[clamp(1.3rem,2.4vw,2rem)] tracking-[-0.03em] text-fg-3" aria-hidden={i >= TERMS.length}>
                {t}
                <Asterisk className="size-4 text-fg-4" />
              </span>
            ))}
          </div>
        </div>

        {/* Principles */}
        <section id="principles" className="shell py-[clamp(96px,16vh,180px)]">
          <h2 className="max-w-[18ch] text-[clamp(2.2rem,4.6vw,4rem)] text-fg">Built for the part of finance that has to be exact.</h2>
          <div className="mt-[clamp(56px,10vh,110px)] border-t border-line">
            {PRINCIPLES.map((p) => (
              <article key={p.title} className="principle grid gap-6 border-b border-line py-[clamp(36px,6vh,64px)] md:grid-cols-[1.25fr_1fr] md:gap-16">
                <h3 className="text-[clamp(1.8rem,3.6vw,3.1rem)] text-fg">{p.title}</h3>
                <p className="max-w-[52ch] self-end text-[16px] leading-relaxed text-fg-2">{p.body}</p>
              </article>
            ))}
          </div>
        </section>

        {/* How it works — pinned sequence */}
        <section id="how" className="flow relative">
          <div className="flow-pin relative flex h-[100svh] items-center overflow-hidden">
            <Scene compact effects={false} className="pointer-events-none absolute -right-[18vw] top-1/2 h-[90vh] w-[70vw] -translate-y-1/2 opacity-55 max-md:hidden" />
            <div className="shell relative">
              <div className="flex items-baseline gap-4 text-fg-3">
                <h2 className="text-[clamp(1.6rem,2.6vw,2.2rem)] text-fg">How a credit finds its invoice.</h2>
              </div>
              <div className="mt-12 grid gap-10 md:grid-cols-[auto_1fr] md:gap-20">
                <div className="num font-display text-[clamp(6rem,16vw,14rem)] leading-[0.8] tracking-[-0.06em] text-fg">
                  <span className="flow-index">1</span><span className="text-fg-4">/4</span>
                </div>
                <div className="relative min-h-[260px] max-w-[52ch]">
                  {STEPS.map((st, i) => (
                    <div key={st.title} className="step absolute inset-0 md:pt-4" style={i ? { opacity: 0 } : undefined}>
                      <h3 className="text-[clamp(2.2rem,4.4vw,3.6rem)]">{st.title}.</h3>
                      <p className="mt-6 text-[17px] leading-relaxed text-fg-2">{st.body}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="mt-16 h-px w-full bg-line">
                <div className="flow-bar h-px origin-left bg-ice" />
              </div>
            </div>
          </div>
        </section>

        {/* Live ledger figures */}
        <section id="ledger" className="shell py-[clamp(96px,16vh,180px)]">
          <h2 className="max-w-[20ch] text-[clamp(2.2rem,4.6vw,4rem)]">Figures from the ledger, not from the model.</h2>
          {stats ? (
            <dl className="mt-16 grid border-t border-line sm:grid-cols-2 lg:grid-cols-4">
              {stats.map((x) => (
                <div key={x.l} className="count border-b border-line py-10 sm:pr-8 lg:border-b-0 lg:border-r lg:pl-8 lg:first:pl-0 lg:last:border-r-0">
                  <dd className="num font-display text-[clamp(2.8rem,5vw,4.4rem)] leading-none tracking-[-0.045em]">{x.v}</dd>
                  <dt className="mt-4 text-[14px] text-fg-3">{x.l}</dt>
                </div>
              ))}
            </dl>
          ) : (
            <p className="mt-10 max-w-[52ch] text-[16px] text-fg-2">
              Live figures appear here once the workspace has data. Load the synthetic demo set from the workspace to
              see them; no real client data is used anywhere.
            </p>
          )}
          <p className="mt-6 text-[13px] text-fg-4">Synthetic demo data. Read live from the reconciliation database.</p>
        </section>

        {/* CTA band */}
        <section className="relative overflow-hidden border-t border-line">
          <div className="shell flex flex-col items-start gap-10 py-[clamp(96px,18vh,200px)] md:flex-row md:items-end md:justify-between">
            <h2 className="max-w-[13ch] text-[clamp(2.8rem,7vw,6.2rem)] leading-[0.95]">Close the month with nothing unexplained.</h2>
            <LinkButton href="/app/overview" variant="primary" size="lg" arrow>Open workspace</LinkButton>
          </div>
        </section>

        <footer className="border-t border-line">
          <div className="shell flex flex-wrap items-center justify-between gap-6 py-10 text-[13px] text-fg-3">
            <Logo />
            <p>A prototype on synthetic data. Not tax or legal advice; a qualified reviewer signs off every exception.</p>
          </div>
        </footer>
      </div>
    </SmoothScroll>
  );
}
