#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { launchBrowser } from "./browser.js";

const rootDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const profileDir = path.join(rootDir, ".profiles");
const storageStatePath = path.join(profileDir, "onehai-storage-state.json");

await fs.mkdir(profileDir, { recursive: true });

const browser = await launchBrowser({ headless: false });
const context = await browser.newContext({
  locale: "zh-CN",
  timezoneId: "Asia/Shanghai"
});
const page = await context.newPage();

console.log("已打开一嗨页面，请在浏览器中完成登录。");
console.log("如果弹出验证码，请在页面中正常完成。");
console.log("登录完成后，回到终端按回车，我会保存会话。");

await page.goto("https://www.1hai.cn/index.aspx", {
  waitUntil: "domcontentloaded",
  timeout: 30000
});
await page.locator("#linkLogin").click().catch(() => {});

const rl = readline.createInterface({ input, output });
await rl.question("登录完成后按回车继续...");
rl.close();

await context.storageState({ path: storageStatePath });
await browser.close();

console.log(`一嗨登录态已保存到: ${storageStatePath}`);
console.log("之后直接运行查询命令即可自动复用该登录态。");
