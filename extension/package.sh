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
  content.js
  popup.html
  popup.js
  auth.js
  icons
)

# 缺文件就直接失败，避免打出残缺包。
for f in "${FILES[@]}"; do
  [[ -e "$f" ]] || { echo "package.sh: 缺少 $f" >&2; exit 1; }
done

mkdir -p "${OUT_DIR}"

if [[ "$STORE" == "1" ]]; then
  # 暂存一份白名单文件，剥掉 manifest 的 key 字段后再打包（不动源文件 manifest.json）。
  STAGE="$(mktemp -d)"
  trap 'rm -rf "$STAGE"' EXIT
  cp -R "${FILES[@]}" "$STAGE"/
  node -e 'const fs=require("fs");const p=process.argv[1];const m=JSON.parse(fs.readFileSync(p));delete m.key;fs.writeFileSync(p,JSON.stringify(m,null,2)+"\n")' "$STAGE/manifest.json"
  ZIP="${PWD}/${OUT_DIR}/agent-bridge-extension-${VERSION}-store-firstupload.zip"
  rm -f "$ZIP"
  ( cd "$STAGE" && zip -r -X "$ZIP" "${FILES[@]}" -x '*/.DS_Store' >/dev/null )
  echo "首发包（已剥离 key，仅用于 + New item 首次上传）：${OUT_DIR}/agent-bridge-extension-${VERSION}-store-firstupload.zip"
  echo "上传后记得：Package 标签 → View public key → 回填进 manifest.json 的 key 字段。"
  unzip -l "$ZIP"
  exit 0
fi

ZIP="${OUT_DIR}/agent-bridge-extension-${VERSION}.zip"
rm -f "${ZIP}"

# -r 递归 icons/；-X 不存 macOS 扩展属性；排除 .DS_Store。
zip -r -X "${ZIP}" "${FILES[@]}" -x '*/.DS_Store' >/dev/null

# 再复制一份稳定文件名，给网站固定下载链接用（/download/agent-bridge-extension.zip）。
STABLE="${OUT_DIR}/agent-bridge-extension.zip"
cp -f "${ZIP}" "${STABLE}"

echo "打包完成：${ZIP}"
echo "稳定链接副本：${STABLE}"
unzip -l "${ZIP}"
