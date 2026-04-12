import { PlatformAdapter } from "./base.js";

export class ZucheAdapter extends PlatformAdapter {
  constructor() {
    super({
      name: "zuche",
      displayName: "神州租车",
      searchUrl: "https://www.zuche.com/"
    });
    this.priceSelectors = [".price", ".money", ".amount", ".vehicle-price"];
  }

  async search(page, query) {
    await page.goto("https://www.zuche.com/", {
      waitUntil: "domcontentloaded",
      timeout: 30000
    });

    try {
      await page.waitForTimeout(3000);
      const button = page.getByText("立即选车").first();
      if (await button.count()) {
        await button.click();
        await page.waitForLoadState("domcontentloaded", { timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(2000);
      }

      if (page.url().includes("app-download.do")) {
        return this.createFallbackResult(query, ["神州租车 PC 端会跳到 App 下载页，当前无公开网页报价列表。"]);
      }

      return await this.extractResult(page, query);
    } catch {
      return this.createFallbackResult(query, ["当前神州租车页面更偏动态渲染，本次未稳定抓到结构化价格。"]);
    }
  }
}
