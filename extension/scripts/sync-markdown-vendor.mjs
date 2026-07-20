import { copyFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const EXTENSION_ROOT = fileURLToPath(new URL("../", import.meta.url));
const VENDOR_DIRECTORY = path.join(EXTENSION_ROOT, "vendor");
const VENDOR_ASSETS = [
  {
    source: path.join(EXTENSION_ROOT, "node_modules/marked/lib/marked.esm.js"),
    destination: path.join(VENDOR_DIRECTORY, "marked.esm.js"),
  },
  {
    source: path.join(EXTENSION_ROOT, "node_modules/dompurify/dist/purify.es.mjs"),
    destination: path.join(VENDOR_DIRECTORY, "purify.es.mjs"),
  },
  {
    source: path.join(EXTENSION_ROOT, "node_modules/marked/LICENSE"),
    destination: path.join(VENDOR_DIRECTORY, "LICENSE.marked.txt"),
  },
  {
    source: path.join(EXTENSION_ROOT, "node_modules/dompurify/LICENSE"),
    destination: path.join(VENDOR_DIRECTORY, "LICENSE.dompurify-Apache-2.0.txt"),
  },
];

/** Copy the locked Markdown runtime modules into the extension's committed vendor boundary. */
async function syncMarkdownVendor() {
  // Create the destination first so the same command works in a fresh checkout.
  await mkdir(VENDOR_DIRECTORY, { recursive: true });

  // copyFile preserves each published ESM asset byte-for-byte without transformation.
  for (const asset of VENDOR_ASSETS) {
    await copyFile(asset.source, asset.destination);
  }
}

await syncMarkdownVendor();
