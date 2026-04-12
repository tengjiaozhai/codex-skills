import fs from "node:fs/promises";
import path from "node:path";
import { createTimestampSlug, sanitizeFilePart } from "./utils.js";

export async function savePageSnapshot(page, options = {}) {
  const rootDir = options.rootDir;
  const platform = sanitizeFilePart(options.platform || "platform");
  const reason = sanitizeFilePart(options.reason || "snapshot");
  const timestamp = createTimestampSlug();
  const dir = path.join(rootDir, `${timestamp}-${platform}-${reason}`);

  await fs.mkdir(dir, { recursive: true });

  const url = page.url();
  const html = await page.content().catch(() => "");
  const text = await page.locator("body").innerText().catch(() => "");

  await fs.writeFile(path.join(dir, "page-url.txt"), `${url}\n`);
  await fs.writeFile(path.join(dir, "page.html"), html);
  await fs.writeFile(path.join(dir, "page.txt"), text);
  await page.screenshot({
    path: path.join(dir, "page.png"),
    fullPage: true
  }).catch(() => {});

  return dir;
}
