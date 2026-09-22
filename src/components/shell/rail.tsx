import Image from "next/image";
import Link from "next/link";

import { EngineStatus } from "./engine-status";
import { NavLinks } from "./nav-links";

/**
 * The rail: the blue back of the binder. The Legal Soft wordmark (its
 * gradient lives only inside the logo), the three steps with their screens,
 * and whether the engine is there. The screen you are on is a tab joined to
 * the sheet. Below 768px it folds into a top bar -- phones aren't a target,
 * but nothing breaks.
 */
export function Rail() {
  return (
    <aside className="z-30 flex bg-desk max-md:sticky max-md:top-0 max-md:items-center max-md:gap-4 max-md:border-b max-md:border-desk-deep max-md:px-4 max-md:py-2 md:fixed md:inset-y-0 md:left-0 md:w-(--rail-width) md:flex-col md:py-[var(--sheet-inset)]">
      <div className="shrink-0 md:px-5 md:pt-5 md:pb-6">
        <Link href="/" className="inline-block rounded-[4px]" aria-label="Legal Soft, Home">
          <Image
            src="/brand/legal-soft.png"
            alt="Legal Soft"
            width={6945}
            height={1737}
            priority
            sizes="96px"
            className="h-[20px] w-auto"
          />
        </Link>
        <p className="type-semi-narrow mt-2 text-meta font-medium text-slate max-md:hidden">
          Lead Gen Engine
        </p>
      </div>
      <div className="min-w-0 flex-1 md:pl-3">
        <NavLinks />
      </div>
      <div className="px-5 pb-4 max-md:hidden">
        <EngineStatus />
      </div>
    </aside>
  );
}
