import { createCn } from "cn/config";

/**
 * Class joining + Tailwind conflict resolution, taught the Record's scales.
 *
 * Without the `text` theme entry, the merge tables classify an unknown
 * `text-body` as a *colour*, so `cn("text-body", "text-ink")` would silently
 * drop the size. Keep these lists in step with the tokens in globals.css.
 */
export const cn = createCn({
  extend: {
    theme: {
      text: [
        "meta",
        "table",
        "body",
        "section",
        "title",
        "quote-table",
        "quote",
        "quote-title",
        "quote-proof",
      ],
      radius: ["control", "panel", "sheet"],
      shadow: ["float"],
    },
  },
});
