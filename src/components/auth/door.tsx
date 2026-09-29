"use client";

import Image from "next/image";

import { cn } from "@/lib/utils";

/**
 * The door: one sheet on the desk, on its own, for the screens shown before
 * a person is in -- sign-in, the form, waiting, turned off. No rail: there
 * is nothing to go to yet. The wordmark heads it, as it heads the rail.
 */
export function Door({
  title,
  children,
  wide = false,
  labelledBy = "door-title",
}: {
  title: React.ReactNode;
  children: React.ReactNode;
  /** The form needs more room than a sentence and a button. */
  wide?: boolean;
  labelledBy?: string;
}) {
  return (
    <div className="flex min-h-screen items-start justify-center px-4 py-10 md:items-center md:py-16">
      <main
        id="main"
        aria-labelledby={labelledBy}
        className={cn(
          "w-full rounded-sheet bg-sheet px-8 py-9 max-md:px-5 max-md:py-7",
          wide ? "max-w-[36rem]" : "max-w-[26rem]",
        )}
      >
        <Image
          src="/brand/legal-soft.png"
          alt="Legal Soft"
          width={6945}
          height={1737}
          priority
          sizes="112px"
          className="h-[22px] w-auto"
        />
        <p className="type-semi-narrow mt-2 text-meta font-medium text-slate">Lead Gen Engine</p>
        <h1 id={labelledBy} className="type-narrow mt-7 text-title font-semibold tracking-[-0.01em] text-ink">
          {title}
        </h1>
        <div className="mt-4 grid gap-4 text-body text-ink">{children}</div>
      </main>
    </div>
  );
}

/** Something went wrong on the way in: a redline rule and the sentence. */
export function DoorNotice({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="border-l-2 border-redline py-1 pl-3 text-body text-ink">
      {children}
    </p>
  );
}
