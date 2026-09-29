"use client";

import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth, useOnboarding, useSignOut } from "@/lib/api/hooks";
import type { AuthStatus } from "@/lib/api/types";
import { Door } from "./door";
import { OnboardingForm } from "./onboarding-form";
import { SignInScreen } from "./sign-in-screen";

/** The app as it was: the rail beside one white sheet. */
function Shell({ rail, children }: { rail: React.ReactNode; children: React.ReactNode }) {
  return (
    <>
      {rail}
      <div className="md:pl-(--rail-width)">
        <main id="main" className="sheet flex min-w-0 flex-col">
          {children}
        </main>
      </div>
    </>
  );
}

/**
 * Before the engine has said who is asking: the frame of the app with
 * nothing written on it. Not the sign-in screen, which would flash for
 * everyone who is already in.
 */
function GateLoading() {
  return (
    <div className="md:pl-(--rail-width)" aria-busy="true" aria-label="Checking who is signed in">
      <div className="sheet px-8 pt-8 max-md:px-4">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="mt-6 h-4 w-3/5" />
        <Skeleton className="mt-3 h-4 w-2/5" />
        <Skeleton className="mt-10 h-4 w-4/5" />
        <Skeleton className="mt-3 h-4 w-3/5" />
        <Skeleton className="mt-3 h-4 w-2/3" />
      </div>
    </div>
  );
}

function SignOutButton({ className }: { className?: string }) {
  const signOut = useSignOut();
  return (
    <Button variant="link" className={className} disabled={signOut.isPending} onClick={() => signOut.mutate()}>
      {signOut.isPending ? "Signing out…" : "Sign out"}
    </Button>
  );
}

function OnboardingScreen({ status }: { status: AuthStatus }) {
  const onboarding = useOnboarding();
  return (
    <Door title="Before you start, tell us who you are" wide>
      <p className="text-slate">
        You&apos;re signed in as <span className="text-ink">{status.user?.email}</span>. Vishal sets each
        person&apos;s access by hand, and these answers are what he sees.
      </p>
      <OnboardingForm
        fields={status.onboarding_fields}
        name={status.user?.name ?? null}
        onSubmit={(answers) => onboarding.mutate(answers)}
        isPending={onboarding.isPending}
        error={onboarding.error}
      />
      <p className="text-table text-slate">
        Not you? <SignOutButton className="text-table" />
      </p>
    </Door>
  );
}

function WaitingScreen({ status }: { status: AuthStatus }) {
  return (
    <Door title="You're in. Vishal has to set your access first.">
      <p className="text-slate">
        Signed in as <span className="text-ink">{status.user?.email}</span>. Your answers are on his Users
        screen; once he sets what you may do, this screen opens by itself. It checks again every half
        minute.
      </p>
      <p>
        <SignOutButton />
      </p>
    </Door>
  );
}

function DisabledScreen({ status }: { status: AuthStatus }) {
  return (
    <Door title="Your access has been turned off.">
      <p className="text-slate">
        Signed in as <span className="text-ink">{status.user?.email}</span>. Ask Vishal if that&apos;s a
        mistake.
      </p>
      <p>
        <SignOutButton />
      </p>
    </Door>
  );
}

/**
 * The door to the app (D-067). One call, GET /api/auth/me, says who is
 * asking; the standing chooses the screen. Sign-in switched off, or a
 * person with access, sees the app as before. Everyone else sees one sheet
 * that says where they stand and what happens next -- never the rail, which
 * would list screens they cannot open.
 */
export function AuthGate({ rail, children }: { rail: React.ReactNode; children: React.ReactNode }) {
  const auth = useAuth();

  if (auth.isPending) return <GateLoading />;
  if (auth.isError) {
    return (
      <Shell rail={rail}>
        <div className="px-8 py-10 max-md:px-4">
          <ErrorState error={auth.error} onRetry={() => void auth.refetch()} />
        </div>
      </Shell>
    );
  }

  const status = auth.data;
  switch (status.standing) {
    case "off":
    case "active":
      return <Shell rail={rail}>{children}</Shell>;
    case "signed_out":
      return <SignInScreen status={status} />;
    case "needs_onboarding":
      return <OnboardingScreen status={status} />;
    case "awaiting_access":
      return <WaitingScreen status={status} />;
    case "disabled":
      return <DisabledScreen status={status} />;
  }
}
