import { nowIso } from "../utils.js";
import { collectReferencePricing } from "../extract.js";

export class PlatformAdapter {
  constructor(config) {
    this.name = config.name;
    this.displayName = config.displayName;
    this.searchUrl = config.searchUrl;
  }

  createFallbackResult(query, warnings = []) {
    return {
      platform: this.name,
      displayName: this.displayName,
      status: "fallback",
      sourceType: "fallback",
      currency: "CNY",
      pickup: query.pickup,
      dropoff: query.dropoff,
      vehicleClass: query.vehicleClass,
      priceMin: null,
      priceTotalIfAvailable: null,
      availableCars: 0,
      pricingUnit: null,
      capturedAt: nowIso(),
      bookingUrl: this.buildSearchUrl(query),
      notes: [
        "未解析出参考价，已保留可打开的搜索入口。",
        "价格以平台落地页实时展示为准。"
      ],
      warnings
    };
  }

  createPricedResult(query, scrapeResult, extra = {}) {
    return {
      platform: this.name,
      displayName: this.displayName,
      status: "priced",
      sourceType: "scraped",
      currency: "CNY",
      pickup: query.pickup,
      dropoff: query.dropoff,
      vehicleClass: scrapeResult.vehicleClass || query.vehicleClass,
      priceMin: scrapeResult.priceMin,
      priceTotalIfAvailable: scrapeResult.priceTotalIfAvailable,
      availableCars: scrapeResult.availableCars,
      pricingUnit: scrapeResult.pricingUnit,
      capturedAt: nowIso(),
      bookingUrl: scrapeResult.bookingUrl || this.buildSearchUrl(query),
      notes: [
        "参考实时价，非最终成交价。",
        "请在平台落地页复核保险、异地还车费和夜间服务费。"
      ],
      warnings: extra.warnings || []
    };
  }

  async extractResult(page, query) {
    const scrapeResult = await collectReferencePricing(page, {
      priceSelectors: this.priceSelectors || []
    });

    if (!scrapeResult.priceMin) {
      return this.createFallbackResult(query, ["页面已打开，但当前未稳定解析出价格。"]);
    }

    return this.createPricedResult(query, scrapeResult);
  }

  buildSearchUrl() {
    return this.searchUrl;
  }
}
