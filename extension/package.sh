#!/usr/bin/env bash
# 把扩展打成一个 zip，用于：① 上传 Chrome Web Store；② 自部署者下载→解压→「加载已解压」。
# 只打运行所需文件，排除测试 / 包管理 / 文档 / 私钥。
#   用法：cd extension && ./package.sh   （或 npm run package）
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

VERSION="$(node -p "require('./manifest.json').version")"
OUT_DIR="dist"
ZIP="${OUT_DIR}/agent-bridge-extension-${VERSION}.zip"

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
rm -f "${ZIP}"

# -r 递归 icons/；-X 不存 macOS 扩展属性；排除 .DS_Store。
zip -r -X "${ZIP}" "${FILES[@]}" -x '*/.DS_Store' >/dev/null

# 再复制一份稳定文件名，给网站固定下载链接用（/download/agent-bridge-extension.zip）。
STABLE="${OUT_DIR}/agent-bridge-extension.zip"
cp -f "${ZIP}" "${STABLE}"

echo "打包完成：${ZIP}"
echo "稳定链接副本：${STABLE}"
unzip -l "${ZIP}"
