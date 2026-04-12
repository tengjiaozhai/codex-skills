import path from "node:path";
import { normalizeQuery, queryCacheKey } from "./query.js";
import { FileCache } from "./cache.js";
import { launchBrowser, createPage } from "./browser.js";
import { createPlatformRegistry } from "./platforms/platform-registry.js";
import { savePageSnapshot } from "./snapshots.js";

export async function searchRentalPrices(input, options = {}) {
  const query = normalizeQuery(input);
  const ttlMinutes = Number(options.ttlMinutes ?? 10);
  const ttlMs = ttlMinutes * 60 * 1000;
  const rootDir = options.rootDir || process.cwd();
  const cache = new FileCache(path.join(rootDir, ".cache"));
  const snapshotRootDir = path.join(rootDir, "snapshots");
  const oneHaiStorageStatePath = path.join(rootDir, ".profiles", "onehai-storage-state.json");
  const platforms = createPlatformRegistry();
  const browser = await launchBrowser({ headless: options.headless !== false });

  try {
    const results = [];

    for (const platform of platforms) {
      const cacheKey = queryCacheKey(query);
      const cached = await cache.get(platform.name, cacheKey, ttlMs);
      if (cached) {
        results.push({
          ...cached,
          sourceType: "cached"
        });
        continue;
      }

      const { context, page, usedStorageState } = await createPage(browser, {
        storageStatePath: platform.name === "onehai" ? oneHaiStorageStatePath : null
      });
      try {
        const result = await platform.search(page, query);
        if (platform.name === "onehai") {
          result.authMode = usedStorageState ? "session" : "anonymous";
          if (!usedStorageState && !result.warnings.includes("当前未检测到一嗨登录态，将以匿名访问继续。")) {
            result.warnings = [
              "当前未检测到一嗨登录态，将以匿名访问继续。",
              ...result.warnings
            ];
          }
        }
        if (options.snapshotMode === "all" || (options.snapshotMode === "error" && result.status !== "priced")) {
          result.snapshotDir = await savePageSnapshot(page, {
            rootDir: snapshotRootDir,
            platform: platform.name,
            reason: result.status
          });
        }
        await cache.set(platform.name, cacheKey, result);
        results.push(result);
      } catch (error) {
        const fallback = platform.createFallbackResult(query, [String(error.message || error)]);
        if (platform.name === "onehai") {
          fallback.authMode = usedStorageState ? "session" : "anonymous";
        }
        fallback.snapshotDir = await savePageSnapshot(page, {
          rootDir: snapshotRootDir,
          platform: platform.name,
          reason: "error"
        });
        results.push(fallback);
      } finally {
        await context.close();
      }
    }

    return {
      query,
      ttlMinutes,
      results
    };
  } finally {
    await browser.close();
  }
}
