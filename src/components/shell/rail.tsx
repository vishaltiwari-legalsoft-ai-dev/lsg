import Image from "next/image";
import Link from "next/link";

import { EngineStatus } from "./engine-status";
import { NavLinks } from "./nav-links";

/**
 * The fixed left rail: the Legal Soft wordmark (its gradient lives only
 * inside the logo), the screens, and whether the engine is there. Below
 * 768px it folds into a top bar — phones aren't a target, but nothing breaks.
 */
export function Rail() {
  return (
    <aside className="z-30 flex border-rule bg-paper max-md:items-center max-md:gap-4 max-md:border-b max-md:px-4 max-md:py-2 md:fixed md:inset-y-0 md:left-0 md:w-(--rail-width) md:flex-col md:border-r">
      <div className="shrink-0 md:px-5 md:pt-6 md:pb-7">
        <Link href="/" className="inline-block rounded-[4px]" aria-label="Legal Soft, Today">
          <Image
            src="/brand/legal-soft.png"
            alt="Legal Soft"
            width={6945}
            height={1737}
            priority
            sizes="80px"
            className="h-[19px] w-auto"
          />
        </Link>
        <p className="mt-2 text-meta text-slate max-md:hidden">Lead Gen Engine</p>
      </div>
      <div className="min-w-0 flex-1 md:px-3">
        <NavLinks />
      </div>
      <div className="px-3 pb-5 max-md:hidden">
        <EngineStatus />
      </div>
    </aside>
  );
}
