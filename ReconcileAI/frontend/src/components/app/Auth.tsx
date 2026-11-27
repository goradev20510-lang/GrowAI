"use client";

import { ClerkProvider, SignIn, UserButton, useAuth, useUser } from "@clerk/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, saveSessionToken, setApiTokenProvider, type SessionUser } from "@/lib/api";
import { useReviewer } from "@/components/providers";
import { Logo } from "@/components/Logo";
import { Button, ErrorNote } from "@/components/ui";

// Public by design. With it, Clerk handles sign-in; without it, the API's email-and-password
// accounts do (and the API decides whether sign-in is required at all).
const KEY = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export function AuthGate({ children }: { children: React.ReactNode }) {
  if (!KEY) return <LocalGate>{children}</LocalGate>;
  return (
    <ClerkProvider publishableKey={KEY} afterSignOutUrl="/">
      <Gate>{children}</Gate>
    </ClerkProvider>
  );
}

const LocalUser = createContext<SessionUser | null>(null);

export function useLocalUser() {
  return useContext(LocalUser);
}

/** False only for a signed-in account the API would refuse (loading demo data is admin-only). */
export function useCanLoadDemo() {
  const user = useLocalUser();
  return !user || user.role === "admin";
}

export function AccountButton() {
  const user = useLocalUser();
  const router = useRouter();
  const qc = useQueryClient();
  if (KEY) return <UserButton />;
  if (!user) return null;
  const signOut = async () => {
    await api.signOut().catch(() => {});
    saveSessionToken(null);
    router.replace("/");
    qc.clear();
  };
  return (
    <div className="flex flex-wrap items-center justify-end gap-3">
      <span className="text-right text-[13px] text-fg-2">
        {user.username}
        <span className="block capitalize text-fg-3">{user.role}</span>
      </span>
      <Button size="sm" onClick={signOut}>Sign out</Button>
    </div>
  );
}

function LocalGate({ children }: { children: React.ReactNode }) {
  const { setReviewer } = useReviewer();
  // Always re-checked on entry, so a result cached before signing in is never trusted.
  const session = useQuery({ queryKey: ["session"], queryFn: api.session, refetchOnMount: "always" });
  const user = session.data?.user ?? null;
  const mustSignIn = !!session.data?.auth_required && !user;
  const demo = session.data?.demo;
  const qc = useQueryClient();
  const [autoError, setAutoError] = useState<Error | null>(null);

  // No sign-in page: open the workspace straight away with the demo account.
  useEffect(() => {
    if (!mustSignIn || session.isFetching) return;
    if (!demo) { setAutoError(new Error("Sign-in is required but no demo account is configured.")); return; }
    let cancelled = false;
    api.signIn(demo.username, demo.password)
      .then(({ token }) => { if (!cancelled) { saveSessionToken(token); qc.invalidateQueries({ queryKey: ["session"] }); } })
      .catch((e: Error) => { if (!cancelled) setAutoError(e); });
    return () => { cancelled = true; };
  }, [mustSignIn, session.isFetching, demo, qc]);

  const name = user?.username;
  useEffect(() => {
    // Decisions are recorded against the account, so the reviewer name follows it.
    if (name) setReviewer(name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  if (session.data && !mustSignIn) return <LocalUser.Provider value={user}>{children}</LocalUser.Provider>;
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 px-4 py-12">
      <Logo href="/" />
      {session.error || autoError
        ? <ErrorNote error={session.error ?? autoError} />
        : <p className="text-[14px] text-fg-3" role="status">Opening workspace…</p>}
    </div>
  );
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
