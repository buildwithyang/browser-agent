const GATEWAY_URL = "http://127.0.0.1:17321/tasks";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "send-to-agent-bridge",
    title: "Send to Agent Bridge",
    contexts: ["page", "selection"]
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "send-to-agent-bridge" || !tab.id) {
    return;
  }

  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["content.js"]
  });
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.type !== "AGENT_BRIDGE_CONTEXT" || !sender.tab) {
    return;
  }

  const tabId = sender.tab.id;
  showResult(tabId, "Agent Bridge: analyzing…");

  fetch(GATEWAY_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message.payload)
  })
    .then((response) => response.json())
    .then((task) => showResult(tabId, task.result || "(no result)"))
    .catch((error) => {
      console.error("Agent Bridge gateway request failed", error);
      showResult(tabId, "Agent Bridge error: " + error.message);
    });
});

// Render the agent result in an overlay panel injected into the originating page.
function showResult(tabId, text) {
  chrome.scripting.executeScript({
    target: { tabId },
    func: renderPanel,
    args: [text]
  });
}

function renderPanel(text) {
  const existing = document.getElementById("agent-bridge-panel");
  if (existing) existing.remove();

  const panel = document.createElement("div");
  panel.id = "agent-bridge-panel";
  panel.style.cssText = [
    "position:fixed", "top:16px", "right:16px", "z-index:2147483647",
    "max-width:420px", "max-height:70vh", "overflow:auto",
    "background:#1e1e1e", "color:#f0f0f0", "padding:16px",
    "border-radius:8px", "box-shadow:0 4px 24px rgba(0,0,0,0.4)",
    "font:14px/1.5 system-ui,sans-serif", "white-space:pre-wrap"
  ].join(";");

  const close = document.createElement("button");
  close.textContent = "×";
  close.style.cssText =
    "float:right;background:none;border:none;color:#f0f0f0;font-size:20px;cursor:pointer";
  close.onclick = () => panel.remove();

  const body = document.createElement("div");
  body.textContent = text;

  panel.appendChild(close);
  panel.appendChild(body);
  document.body.appendChild(panel);
}
