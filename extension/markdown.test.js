import { test } from "node:test";
import assert from "node:assert/strict";

import { JSDOM } from "jsdom";

import { renderMarkdown } from "./markdown.js";

/** Render Markdown and expose the sanitized result through a detached DOM. */
function render(markdown) {
  const dom = new JSDOM("<!doctype html><body></body>");
  const html = renderMarkdown(markdown, dom.window);
  dom.window.document.body.innerHTML = html;
  return { dom, html, body: dom.window.document.body };
}

test("renders headings and inline emphasis", () => {
  const { body } = render("# Heading\n\n**bold** and *italic*");

  assert.equal(body.querySelector("h1")?.textContent, "Heading");
  assert.equal(body.querySelector("strong")?.textContent, "bold");
  assert.equal(body.querySelector("em")?.textContent, "italic");
});

test("renders ordered and unordered lists", () => {
  const { body } = render("1. First\n2. Second\n\n- Alpha\n- Beta");

  assert.deepEqual(
    [...body.querySelectorAll("ol > li")].map((item) => item.textContent),
    ["First", "Second"]
  );
  assert.deepEqual(
    [...body.querySelectorAll("ul > li")].map((item) => item.textContent),
    ["Alpha", "Beta"]
  );
});

test("renders links and inline code", () => {
  const { body } = render("Read [the docs](https://example.com/docs) and use `npm test`.");

  assert.equal(body.querySelector("a")?.href, "https://example.com/docs");
  assert.equal(body.querySelector("code")?.textContent, "npm test");
});

test("renders fenced code blocks", () => {
  const { body } = render("```js\nconst answer = 42;\n```");
  const code = body.querySelector("pre > code.language-js");

  assert.equal(code?.textContent, "const answer = 42;\n");
});

test("renders GFM tables", () => {
  const { body } = render("| Name | Score |\n| --- | ---: |\n| Ada | 10 |");

  assert.equal(body.querySelector("table th")?.textContent, "Name");
  assert.equal(body.querySelector("table td")?.textContent, "Ada");
  assert.equal(body.querySelector("table td:nth-child(2)")?.textContent, "10");
});

test("sanitizes executable raw HTML and Markdown links", () => {
  const { dom, html, body } = render([
    "<section><strong>Allowed HTML</strong></section>",
    "<script>window.__executed = true</script>",
    "<img src=\"x\" onerror=\"window.__eventRan = true\">",
    "[unsafe](javascript:alert('xss'))",
  ].join("\n\n"));

  assert.equal(body.querySelector("section strong")?.textContent, "Allowed HTML");
  assert.equal(body.querySelector("script"), null);
  assert.equal(body.querySelector("img")?.hasAttribute("onerror"), false);
  assert.equal(body.querySelector("a")?.hasAttribute("href"), false);
  assert.equal(dom.window.__executed, undefined);
  assert.equal(dom.window.__eventRan, undefined);
  assert.doesNotMatch(html, /javascript:|onerror|<script/i);
});

test("rejects non-string Markdown input", () => {
  const dom = new JSDOM("<!doctype html>");

  for (const value of [undefined, null, 42, {}, []]) {
    assert.throws(
      () => renderMarkdown(value, dom.window),
      { name: "TypeError", message: "markdown must be a string" }
    );
  }
});
