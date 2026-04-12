#!/usr/bin/env node
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile as execFileCallback } from "node:child_process";
import { promisify } from "node:util";
import { launchPersistentContext } from "./browser.js";

const execFile = promisify(execFileCallback);
const rootDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const projectProfilesDir = path.join(rootDir, ".profiles");
const storageStatePath = path.join(projectProfilesDir, "onehai-storage-state.json");
const importedUserDataDir = path.join(projectProfilesDir, "chrome-user-data");
/**
 * 根据操作系统自动检测 Chrome 用户数据目录。
 */
function detectChromeUserDataDir() {
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library/Application Support/Google/Chrome");
  }
  if (process.platform === "win32") {
    return path.join(
      process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData/Local"),
      "Google/Chrome/User Data"
    );
  }
  // Linux
  return path.join(os.homedir(), ".config/google-chrome");
}

const chromeUserDataDir = detectChromeUserDataDir();
const localStatePath = path.join(chromeUserDataDir, "Local State");

const PROFILE_CACHE_EXCLUDES = new Set([
  "Blob Storage",
  "Cache",
  "Code Cache",
  "Crashpad",
  "DawnGraphiteCache",
  "GPUCache",
  "GraphiteDawnCache",
  "GrShaderCache",
  "Media Cache",
  "ShaderCache"
]);

async function loadProfileNames() {
  const localState = JSON.parse(await fs.readFile(localStatePath, "utf8"));
  return Object.keys(localState.profile?.info_cache || {}).sort();
}

async function countOneHaiCookies(profileName) {
  const cookiesPath = path.join(chromeUserDataDir, profileName, "Cookies");
  try {
    await fs.access(cookiesPath);
  } catch {
    return 0;
  }

  const query = [
    "select count(1)",
    "from cookies",
    "where host_key like '%.1hai.cn'",
    "or host_key = 'www.1hai.cn'",
    "or host_key = 'booking.1hai.cn'",
    "or host_key = 'ehilogin.1hai.cn';"
  ].join(" ");

  try {
    const { stdout } = await execFile("sqlite3", [cookiesPath, query], {
      encoding: "utf8"
    });
    return Number(stdout.trim() || 0);
  } catch {
    // sqlite3 不可用（Windows 常见）或 Cookie 数据库被锁定，跳过自动检测。
    // 用户仍可通过 npm run login:onehai 走 Playwright 手动登录流程。
    return 0;
  }
}

async function detectOneHaiProfile() {
  const profileNames = await loadProfileNames();
  let bestProfile = null;
  let bestCookieCount = 0;

  for (const profileName of profileNames) {
    const cookieCount = await countOneHaiCookies(profileName);
    if (cookieCount > bestCookieCount) {
      bestProfile = profileName;
      bestCookieCount = cookieCount;
    }
  }

  if (!bestProfile) {
    throw new Error("未在当前 Chrome 用户数据中找到一嗨登录 Cookie。");
  }

  return {
    profileName: bestProfile,
    cookieCount: bestCookieCount
  };
}

function shouldCopyPath(sourcePath) {
  const baseName = path.basename(sourcePath);
  if (PROFILE_CACHE_EXCLUDES.has(baseName)) {
    return false;
  }

  return !baseName.startsWith("Singleton");
}

async function copyChromeProfile(profileName) {
  await fs.rm(importedUserDataDir, { recursive: true, force: true });
  await fs.mkdir(importedUserDataDir, { recursive: true });
  await fs.copyFile(localStatePath, path.join(importedUserDataDir, "Local State"));
  await fs.cp(
    path.join(chromeUserDataDir, profileName),
    path.join(importedUserDataDir, profileName),
    {
      recursive: true,
      filter: shouldCopyPath
    }
  );
}

function countOneHaiCookiesFromStorageState(storageState) {
  return storageState.cookies.filter((cookie) => cookie.domain.includes("1hai.cn")).length;
}

async function importSession() {
  await fs.mkdir(projectProfilesDir, { recursive: true });
  const { profileName, cookieCount } = await detectOneHaiProfile();
  await copyChromeProfile(profileName);

  const context = await launchPersistentContext(importedUserDataDir, {
    headless: true,
    profileDirectory: profileName
  });

  try {
    const page = context.pages()[0] || await context.newPage();
    await page.goto("https://www.1hai.cn/index.aspx", {
      waitUntil: "domcontentloaded",
      timeout: 30000
    });
    await page.waitForTimeout(5000);
    await context.storageState({ path: storageStatePath });

    const storageState = JSON.parse(await fs.readFile(storageStatePath, "utf8"));
    const oneHaiCookieCount = countOneHaiCookiesFromStorageState(storageState);
    const importSummaryPath = path.join(projectProfilesDir, "onehai-import-summary.json");
    await fs.writeFile(importSummaryPath, JSON.stringify({
      importedAt: new Date().toISOString(),
      chromeUserDataDir,
      profileName,
      sourceCookieCount: cookieCount,
      exportedCookieCount: oneHaiCookieCount,
      currentUrl: page.url()
    }, null, 2));

    console.log(`已从 Chrome ${profileName} 导入一嗨会话。`);
    console.log(`源 profile 中检测到 ${cookieCount} 个一嗨相关 Cookie。`);
    console.log(`导出的 storage state 中检测到 ${oneHaiCookieCount} 个一嗨相关 Cookie。`);
    console.log(`会话文件: ${storageStatePath}`);
    console.log(`导入摘要: ${importSummaryPath}`);
  } finally {
    await context.close();
  }
}

await importSession();
