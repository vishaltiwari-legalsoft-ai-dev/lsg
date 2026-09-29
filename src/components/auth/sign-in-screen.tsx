"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import type { AuthStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { Door, DoorNotice } from "./door";

/**
 * Why a sign-in came back without a session (`?signin=<reason>`, from the
 * engine's callback), in plain words. An unknown reason gets the plainest.
 */
export function signInReason(reason: string, domains: string[]): string {
  const where = domainWords(domains);
  switch (reason) {
    case "domain":
      return `That Google account isn't at ${where}. If you're from an email vendor's team, choose that door instead.`;
    case "not_invited":
      return "That account isn't on the vendor list yet. Ask Vishal to add your address or your company's domain, then sign in again.";
    case "unverified":
      return "That Google account's email address isn't verified. Verify it with Google, then sign in again.";
    case "cancelled":
      return "The sign-in was cancelled before it finished. Try again when you're ready.";
    case "state":
      return "That sign-in didn't start from this screen, so it was refused. Sign in again from here.";
    case "expired":
      return "The sign-in took more than ten minutes and expired. Sign in again.";
    case "google":
      return "Google didn't confirm who you are. Try again; if it keeps happening, tell Vishal.";
    case "disabled":
      return "Your access has been turned off. Ask Vishal if that's a mistake.";
    case "off":
      return "Sign-in isn't switched on for this engine yet.";
    default:
      return "The sign-in didn't finish. Try again.";
  }
}

function domainWords(domains: string[]): string {
  if (domains.length === 0) return "Legal Soft";
  if (domains.length === 1) return domains[0];
  return `${domains.slice(0, -1).join(", ")} or ${domains.at(-1)}`;
}

/**
 * The reason lives in the URL only until it has been read: it is shown once
 * and dropped, so a reload or a shared link never repeats an old failure.
 * The read is pure and happens on mount; the gate only shows this screen
 * once the engine has answered, which is on the client, so nothing is read
 * on the server. Dropping the parameter is the effect, and only that.
 */
function useSignInReason(): string | null {
  const [reason] = useState<string | null>(() =>
    typeof window === "undefined" ? null : new URL(window.location.href).searchParams.get("signin"),
  );
  useEffect(() => {
    if (!reason) return;
    const url = new URL(window.location.href);
    if (!url.searchParams.has("signin")) return;
    url.searchParams.delete("signin");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, [reason]);
  return reason;
}

type Who = "staff" | "vendor";

/**
 * The sign-in screen asks one thing first: are you from Legal Soft, or from
 * an email vendor's team? Legal Soft people walk in with their company
 * account. A vendor's person can use any Google account, but only one the
 * admin has put on the vendor list. The button is a plain link: the browser
 * goes to the engine, the engine sends it to Google, and Google sends it
 * back to where the person was (`next`).
 */
export function SignInScreen({ status }: { status: AuthStatus }) {
  const pathname = usePathname() || "/";
  const reason = useSignInReason();
  const [who, setWho] = useState<Who>(reason === "not_invited" ? "vendor" : "staff");
  const next = `next=${encodeURIComponent(pathname)}`;
  const href =
    who === "vendor"
      ? `${status.vendor_sign_in_path}${status.vendor_sign_in_path.includes("?") ? "&" : "?"}${next}`
      : `${status.sign_in_path}?${next}`;
  const where = domainWords(status.allowed_domains);
  return (
    <Door title="Sign in to the engine">
      <p className="text-slate">
        Legal Soft&apos;s lead intelligence: the proof on each firm&apos;s own site, the people to write
        to, and the first email.
      </p>
      {reason ? <DoorNotice>{signInReason(reason, status.allowed_domains)}</DoorNotice> : null}

      <fieldset className="mt-2 grid gap-2">
        <legend className="type-semi-narrow mb-1 text-meta font-medium text-slate">
          First, who are you?
        </legend>
        <WhoOption
          checked={who === "staff"}
          onChange={() => setWho("staff")}
          label="I'm from Legal Soft"
          hint={`Sign in with your ${where} Google account.`}
        />
        <WhoOption
          checked={who === "vendor"}
          onChange={() => setWho("vendor")}
          label="I'm from an email vendor's team"
          hint="Any Google account, as long as Vishal has added you or your company's domain to the vendor list."
        />
      </fieldset>

      <div className="mt-2">
        <a href={href} className={buttonVariants({ variant: "primary", size: "lg" })}>
          {who === "vendor" ? "Sign in with Google as a vendor" : "Sign in with Google"}
        </a>
      </div>
      <p className="text-table text-slate">
        {who === "vendor"
          ? "Not on the list yet? Ask Vishal before you sign in; Google will send you back here otherwise."
          : `Only Google accounts at ${where} can use this door.`}
      </p>
    </Door>
  );
}

function WhoOption({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  hint: string;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer gap-3 rounded-control border px-3 py-2",
        checked ? "border-cobalt bg-cobalt/5" : "border-rule hover:border-slate",
      )}
    >
      <input
        type="radio"
        name="who"
        checked={checked}
        onChange={onChange}
        className="mt-1 size-4 shrink-0 accent-cobalt"
      />
      <span className="grid gap-0.5">
        <span className="text-ink">{label}</span>
        <span className="text-table text-slate">{hint}</span>
      </span>
    </label>
  );
}
