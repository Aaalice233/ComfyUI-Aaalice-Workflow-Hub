import DOMPurify from "dompurify";
import { marked } from "marked";

export function renderMarkdown(value: string): string {
  if (!value.trim()) return "";
  const html = marked.parse(value, { async: false, breaks: true, gfm: true });
  if (typeof html !== "string") return "";
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|(?:\/(?!\/)|#|\?|(?!(?:\/\/))[^:]*$))/i,
  });
}
