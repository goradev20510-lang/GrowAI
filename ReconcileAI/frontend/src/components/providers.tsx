"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";
import { Toaster } from "sonner";
import { setApiReviewer } from "@/lib/api";

const ReviewerCtx = createContext<{ reviewer: string; setReviewer: (v: string) => void }>({
  reviewer: "", setReviewer: () => {},
});
export const useReviewer = () => useContext(ReviewerCtx);

const KEY = "reconcile.reviewer";
const listeners = new Set<() => void>();
const readReviewer = () => localStorage.getItem(KEY) ?? "";
const subscribeReviewer = (cb: () => void) => {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => { listeners.delete(cb); window.removeEventListener("storage", cb); };
};

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } } }),
  );
  const reviewer = useSyncExternalStore(subscribeReviewer, readReviewer, () => "");
  useEffect(() => setApiReviewer(reviewer.trim()), [reviewer]);

  const setReviewer = (v: string) => {
    localStorage.setItem(KEY, v);
    setApiReviewer(v.trim());
    listeners.forEach((l) => l());
  };

  return (
    <QueryClientProvider client={client}>
      <ReviewerCtx.Provider value={{ reviewer, setReviewer }}>
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            style: {
              background: "#141415", color: "#f4f4f4", border: "1px solid rgb(255 255 255 / 0.16)",
              borderRadius: 14, fontFamily: "var(--font-inter)",
            },
          }}
        />
      </ReviewerCtx.Provider>
    </QueryClientProvider>
  );
}
