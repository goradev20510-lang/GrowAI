"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";

/** 0→100% counter, once per session, the way the reference opens. Skipped under reduced motion. */
export function Preloader() {
  const [n, setN] = useState(0);
  const [show, setShow] = useState(true);

  useEffect(() => {
    const skip = sessionStorage.getItem("ra.loaded") || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const start = performance.now();
    if (skip) {
      const id = requestAnimationFrame(() => setShow(false));
      return () => cancelAnimationFrame(id);
    }
    const dur = 1300;
    let raf = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / dur);
      setN(Math.round((1 - Math.pow(1 - t, 3)) * 100));
      if (t < 1) raf = requestAnimationFrame(step);
      else setTimeout(() => { sessionStorage.setItem("ra.loaded", "1"); setShow(false); }, 220);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-end justify-between bg-void px-[clamp(20px,4vw,48px)] pb-10"
          exit={{ clipPath: "inset(0 0 100% 0)" }}
          initial={{ clipPath: "inset(0 0 0% 0)" }}
          transition={{ duration: 0.9, ease: [0.76, 0, 0.24, 1] }}
          aria-hidden
        >
          <span className="font-display text-sm text-fg-3">ReconcileAI</span>
          <span className="num font-display text-[clamp(5rem,16vw,13rem)] leading-none tracking-[-0.05em] text-fg">
            {n}%
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
