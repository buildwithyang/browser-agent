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
