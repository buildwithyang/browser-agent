// Language preference popup. Stored value:
//   "browser" (default) -> resolved to zh/en from the browser UI language at send time
//   "zh" / "en"         -> forced language
//   "auto"              -> follow the page's own language (model decides)
const DEFAULT_PREF = "browser";

function browserLang() {
  return (chrome.i18n.getUILanguage() || "en").toLowerCase().startsWith("zh") ? "zh" : "en";
}

function updateHint(pref) {
  const hint = document.getElementById("hint");
  if (pref === "browser") {
    const resolved = browserLang() === "zh" ? "中文" : "English";
    hint.textContent = "当前浏览器语言 → " + resolved;
  } else if (pref === "auto") {
    hint.textContent = "回复语言将与页面内容一致。";
  } else {
    hint.textContent = "";
  }
}

function markChecked() {
  document.querySelectorAll("label.opt").forEach((label) => {
    label.classList.toggle("checked", label.querySelector("input").checked);
  });
}

chrome.storage.sync.get({ langPref: DEFAULT_PREF }, ({ langPref }) => {
  const input = document.querySelector(`input[value="${langPref}"]`) ||
    document.querySelector(`input[value="${DEFAULT_PREF}"]`);
  input.checked = true;
  markChecked();
  updateHint(input.value);
});

document.getElementById("options").addEventListener("change", (event) => {
  const pref = event.target.value;
  chrome.storage.sync.set({ langPref: pref });
  markChecked();
  updateHint(pref);
});

// 网关地址（chrome.storage.local.gatewayUrl）；与 background.js 的 getGatewayConfig 对应。
const GATEWAY_KEY = "gatewayUrl";
const DEFAULT_GATEWAY = "http://127.0.0.1:17321";
const gatewayInput = document.getElementById("gateway");

chrome.storage.local.get({ [GATEWAY_KEY]: DEFAULT_GATEWAY }).then((cfg) => {
  gatewayInput.value = cfg[GATEWAY_KEY];
});

gatewayInput.addEventListener("change", () => {
  const value = gatewayInput.value.trim() || DEFAULT_GATEWAY;
  chrome.storage.local.set({ [GATEWAY_KEY]: value });
  gatewayInput.value = value;
});
