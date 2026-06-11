function getPageText() {
  const text = document.body ? document.body.innerText : "";
  return text.replace(/\s+/g, " ").trim().slice(0, 20000);
}

// 方案2:抓取图片相关的文字线索(alt / title / figcaption / aria-label),
// 让纯文本模型也能"知道页面上有哪些图、大致讲什么",无需 vision 模型。
function getImageText() {
  const clues = [];
  const push = (s) => {
    if (!s) return;
    const t = s.replace(/\s+/g, " ").trim();
    if (t) clues.push(t);
  };

  document.querySelectorAll("img[alt]").forEach((el) => push(el.getAttribute("alt")));
  document.querySelectorAll("img[title]").forEach((el) => push(el.getAttribute("title")));
  document.querySelectorAll("figcaption").forEach((el) => push(el.innerText));
  document
    .querySelectorAll('svg[aria-label], [role="img"][aria-label]')
    .forEach((el) => push(el.getAttribute("aria-label")));

  // 去重、限量、限长,避免把输入撑大。
  const seen = new Set();
  const unique = [];
  for (const c of clues) {
    if (seen.has(c)) continue;
    seen.add(c);
    unique.push(c);
    if (unique.length >= 40) break;
  }
  return unique.join(" · ").slice(0, 4000);
}

chrome.runtime.sendMessage({
  type: "AGENT_BRIDGE_CONTEXT",
  payload: {
    url: window.location.href,
    title: document.title,
    selectedText: window.getSelection().toString(),
    pageText: getPageText(),
    imageText: getImageText()
  }
});
