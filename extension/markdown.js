import { marked } from "./vendor/marked.esm.js";
import createDOMPurify from "./vendor/purify.es.mjs";

/**
 * Convert Markdown to sanitized HTML for insertion into the caller's DOM.
 *
 * @param {string} markdown - Untrusted Markdown from Workspace content.
 * @param {Window} windowRef - The destination browser window used by DOMPurify.
 * @returns {string} Sanitized HTML generated with Marked's GFM support.
 * @throws {TypeError} When markdown is not a string.
 */
export function renderMarkdown(markdown, windowRef) {
  if (typeof markdown !== "string") {
    throw new TypeError("markdown must be a string");
  }

  const parsedHtml = marked.parse(markdown, { gfm: true });
  return createDOMPurify(windowRef).sanitize(parsedHtml, {
    USE_PROFILES: { html: true },
    FORBID_ATTR: ["style"],
  });
}
