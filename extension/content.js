function getPageText() {
  const text = document.body ? document.body.innerText : "";
  return text.replace(/\s+/g, " ").trim().slice(0, 20000);
}

chrome.runtime.sendMessage({
  type: "AGENT_BRIDGE_CONTEXT",
  payload: {
    url: window.location.href,
    title: document.title,
    selectedText: window.getSelection().toString(),
    pageText: getPageText()
  }
});
