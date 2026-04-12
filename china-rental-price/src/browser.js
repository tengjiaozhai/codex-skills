import fs from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const DEFAULT_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"];

/**
 * 根据操作系统自动检测本机 Chrome 可执行文件路径。
 * 找不到时返回 null，后续回退到 Playwright 内建 Chromium。
 */
function detectChromeBinaryPath() {
  if (process.platform === "darwin") {
    const p = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
    return existsSync(p) ? p : null;
  }

  if (process.platform === "win32") {
    const candidates = [
      path.join(process.env.PROGRAMFILES || "", "Google/Chrome/Application/chrome.exe"),
      path.join(process.env["PROGRAMFILES(X86)"] || "", "Google/Chrome/Application/chrome.exe"),
      path.join(process.env.LOCALAPPDATA || "", "Google/Chrome/Application/chrome.exe"),
    ];
    return candidates.find((p) => existsSync(p)) || null;
  }

  // Linux
  const linuxCandidates = ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"];
  return linuxCandidates.find((p) => existsSync(p)) || null;
}

/**
 * 根据操作系统返回与当前平台匹配的默认 User-Agent。
 */
function defaultUserAgent() {
  if (process.platform === "win32") {
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36";
  }
  return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36";
}

async function canUseChromeChannel() {
  return detectChromeBinaryPath() !== null;
}

export async function launchBrowser(options = {}) {
  const launchOptions = {
    headless: options.headless !== false,
    args: DEFAULT_LAUNCH_ARGS
  };

  if (options.preferChrome !== false && await canUseChromeChannel()) {
    try {
      return await chromium.launch({
        ...launchOptions,
        channel: "chrome"
      });
    } catch {
      // Fall back to the bundled Chromium when the local Chrome channel is unavailable.
    }
  }

  return chromium.launch(launchOptions);
}

export async function launchPersistentContext(userDataDir, options = {}) {
  const launchOptions = {
    headless: options.headless !== false,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    args: [
      ...DEFAULT_LAUNCH_ARGS,
      ...(options.profileDirectory ? [`--profile-directory=${options.profileDirectory}`] : [])
    ]
  };

  if (options.preferChrome !== false && await canUseChromeChannel()) {
    try {
      return await chromium.launchPersistentContext(userDataDir, {
        ...launchOptions,
        channel: "chrome"
      });
    } catch {
      // Fall back to the bundled Chromium when the local Chrome channel is unavailable.
    }
  }

  return chromium.launchPersistentContext(userDataDir, launchOptions);
}

async function readStorageStatePath(storageStatePath) {
  if (!storageStatePath) {
    return null;
  }

  try {
    await fs.access(storageStatePath);
    return storageStatePath;
  } catch {
    return null;
  }
}

export async function createPage(browser, options = {}) {
  const storageState = await readStorageStatePath(options.storageStatePath);
  const context = await browser.newContext({
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    userAgent: defaultUserAgent(),
    ...(storageState ? { storageState } : {})
  });

  const page = await context.newPage();
  page.on("dialog", async (dialog) => {
    await dialog.dismiss().catch(() => {});
  });

  return { context, page, usedStorageState: Boolean(storageState) };
}
