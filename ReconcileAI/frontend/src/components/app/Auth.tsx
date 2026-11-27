"use client";

import { ClerkProvider, SignIn, UserButton, useAuth, useUser } from "@clerk/react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { setApiTokenProvider } from "@/lib/api";
import { useReviewer } from "@/components/providers";
import { Logo } from "@/components/Logo";

// Public by design. Without it (local development) the workspace has no sign-in screen.
const KEY = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export function AuthGate({ children }: { children: React.ReactNode }) {
  if (!KEY) return children;
  return (
    <ClerkProvider publishableKey={KEY} afterSignOutUrl="/">
      <Gate>{children}</Gate>
    </ClerkProvider>
  );
}

export function AccountButton() {
  return KEY ? <UserButton /> : null;
}

function Gate({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { user } = useUser();
  const { reviewer, setReviewer } = useReviewer();
  const qc = useQueryClient();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!isSignedIn) return;
    setApiTokenProvider(() => getToken());
    // eslint-disable-next-line react-hooks/set-state-in-effect -- children must not fetch before the token is wired up
    setReady(true);
    return () => { setApiTokenProvider(null); setReady(false); qc.clear(); };
  }, [isSignedIn, getToken, qc]);

  const name = user?.fullName ?? user?.primaryEmailAddress?.emailAddress;
  useEffect(() => {
    if (name && !reviewer) setReviewer(name);
    // Prefill once the profile arrives; the field stays editable afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  if (isSignedIn && ready) return children;
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-8 px-4 py-12">
      <Logo href="/" />
      {isLoaded && !isSignedIn
        ? <SignIn routing="hash" withSignUp />
        : <p className="text-[14px] text-fg-3" role="status">Loading sign-in…</p>}
    </div>
  );
}
