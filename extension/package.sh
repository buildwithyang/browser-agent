#!/usr/bin/env bash
# 把扩展打成一个 zip。两种模式：
#   ./package.sh          普通包：含 manifest 现有 key，用于①商店「更新」上传 ②本地 load-unpacked 调试
#   ./package.sh --store  首发包：剥掉 manifest 的 key 字段，仅用于「+ New item」首次上传商店
# Chrome 规定首次用「+ New item」上传时 manifest 带 key 会被拒（"key field not allowed in manifest"）。
# 首发上传成功后，到 Dashboard 的 Package 标签复制商店分配的 public key，回填进 manifest.json 的 key 字段，
# 之后一律用普通 ./package.sh（更新上传允许带 key，本地调试也靠这个 key 让 ID 与商店一致）。
# 只打运行所需文件，排除测试 / 包管理 / 文档 / 私钥。
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

STORE=0
[[ "${1:-}" == "--store" ]] && STORE=1

VERSION="$(node -p "require('./manifest.json').version")"
OUT_DIR="dist"

# 打进 zip 的文件白名单（运行必需）。
FILES=(
  manifest.json
  background.js
  quick-insight.js
  workspace-operation.js
  workspace.js
  workspace-controller.js
  content.js
  sidepanel.html
  sidepanel.css
  sidepanel.js
  popup.html
  popup.js
  auth.js
  config.js
  icons
)

# 缺文件就直接失败，避免打出残缺包。
for f in "${FILES[@]}"; do
  [[ -e "$f" ]] || { echo "package.sh: 缺少 $f" >&2; exit 1; }
done

mkdir -p "${OUT_DIR}"

# 一律在临时目录打包，并只修改暂存副本中的构建环境。
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "${FILES[@]}" "$STAGE"/
sed -i.bak 's/export const BUILD_ENV = "development";/export const BUILD_ENV = "production";/' "$STAGE/config.js"
rm -f "$STAGE/config.js.bak"

if [[ "$STORE" == "1" ]]; then
  # 剥掉暂存 manifest 的 key 字段（不动源文件 manifest.json）。
  node -e 'const fs=require("fs");const p=process.argv[1];const m=JSON.parse(fs.readFileSync(p));delete m.key;fs.writeFileSync(p,JSON.stringify(m,null,2)+"\n")' "$STAGE/manifest.json"
  ZIP="${PWD}/${OUT_DIR}/agent-bridge-extension-${VERSION}-store-firstupload.zip"
  rm -f "$ZIP"
  ( cd "$STAGE" && zip -r -X "$ZIP" "${FILES[@]}" -x '*/.DS_Store' >/dev/null )
  unzip -p "$ZIP" config.js | grep -q 'BUILD_ENV = "production"' || {
    echo "package.sh: production gateway config missing" >&2
    exit 1
  }
  echo "首发包（已剥离 key，仅用于 + New item 首次上传）：${OUT_DIR}/agent-bridge-extension-${VERSION}-store-firstupload.zip"
  echo "上传后记得：Package 标签 → View public key → 回填进 manifest.json 的 key 字段。"
  unzip -l "$ZIP"
  exit 0
fi

ZIP="${PWD}/${OUT_DIR}/agent-bridge-extension-${VERSION}.zip"
rm -f "${ZIP}"

# -r 递归 icons/；-X 不存 macOS 扩展属性；排除 .DS_Store。
( cd "$STAGE" && zip -r -X "${ZIP}" "${FILES[@]}" -x '*/.DS_Store' >/dev/null )

unzip -p "$ZIP" config.js | grep -q 'BUILD_ENV = "production"' || {
  echo "package.sh: production gateway config missing" >&2
  exit 1
}

# 再复制一份稳定文件名，给网站固定下载链接用（/download/agent-bridge-extension.zip）。
STABLE="${PWD}/${OUT_DIR}/agent-bridge-extension.zip"
cp -f "${ZIP}" "${STABLE}"

echo "打包完成：${OUT_DIR}/agent-bridge-extension-${VERSION}.zip"
echo "稳定链接副本：${OUT_DIR}/agent-bridge-extension.zip"
unzip -l "${ZIP}"
