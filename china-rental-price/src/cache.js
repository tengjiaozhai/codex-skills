import fs from "node:fs/promises";
import path from "node:path";
import { sha256 } from "./utils.js";

export class FileCache {
  constructor(rootDir) {
    this.rootDir = rootDir;
  }

  async get(namespace, key, ttlMs) {
    const filePath = this.#filePath(namespace, key);
    try {
      const raw = await fs.readFile(filePath, "utf8");
      const parsed = JSON.parse(raw);
      if (Date.now() - parsed.savedAt > ttlMs) {
        return null;
      }

      return parsed.value;
    } catch {
      return null;
    }
  }

  async set(namespace, key, value) {
    const filePath = this.#filePath(namespace, key);
    await fs.mkdir(path.dirname(filePath), { recursive: true });
    await fs.writeFile(
      filePath,
      JSON.stringify({
        savedAt: Date.now(),
        value
      }, null, 2)
    );
  }

  #filePath(namespace, key) {
    return path.join(this.rootDir, namespace, `${sha256(key)}.json`);
  }
}
