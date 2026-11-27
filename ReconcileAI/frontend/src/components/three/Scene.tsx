"use client";

import dynamic from "next/dynamic";
import { useSyncExternalStore } from "react";
import type { Progress } from "./LedgerScene";

const LedgerScene = dynamic(() => import("./LedgerScene"), { ssr: false });

const RM = "(prefers-reduced-motion: reduce)";
const subscribeRM = (cb: () => void) => {
  const mq = window.matchMedia(RM);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};

export function useReducedMotion() {
  return useSyncExternalStore(subscribeRM, () => window.matchMedia(RM).matches, () => false);
}

let webgl: boolean | undefined;
function hasWebGL() {
  if (webgl === undefined) {
    try {
      const c = document.createElement("canvas");
      webgl = !!(c.getContext("webgl2") || c.getContext("webgl"));
    } catch {
      webgl = false;
    }
  }
  return webgl;
}
const noop = () => () => {};

/** Lazy, client-only 3D. Falls back to a soft glow when WebGL is unavailable. */
export function Scene(props: { progress?: Progress; compact?: boolean; effects?: boolean; className?: string }) {
  const reduced = useReducedMotion();
  const ok = useSyncExternalStore(noop, hasWebGL, () => null);
  return (
    <div className={props.className}>
      {ok === false && <div className="size-full bg-[radial-gradient(closest-side,rgb(191_213_221/0.14),transparent)]" />}
      {ok && <LedgerScene progress={props.progress} compact={props.compact} effects={props.effects} still={reduced} />}
    </div>
  );
}
