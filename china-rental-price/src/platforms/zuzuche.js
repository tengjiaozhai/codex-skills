import { PlatformAdapter } from "./base.js";
import { splitLocalDateTime } from "../utils.js";

async function setZuzucheDateTime(page, query) {
  const pickup = splitLocalDateTime(query.pickupAt);
  const dropoff = splitLocalDateTime(query.dropoffAt);

  await page.evaluate(({ pickup, dropoff }) => {
    const setInput = (selector, value) => {
      const input = document.querySelector(selector);
      if (input) {
        input.value = value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    };

    document.querySelector(".J-crcRental")?.classList.remove("fn-hide");
    setInput("#crc_from_date", pickup.date);
    setInput("#crc_from_date2", pickup.date);
    setInput("#crc_from_time", pickup.time);
    setInput("#crc_from_time2", pickup.time);
    setInput("#crc_to_date", dropoff.date);
    setInput("#crc_to_date2", dropoff.date);
    setInput("#crc_to_time", dropoff.time);
    setInput("#crc_to_time2", dropoff.time);
  }, { pickup, dropoff });
}

async function fillAndConfirm(page, selector, value) {
  const input = page.locator(selector);
  await input.click();
  await input.fill("");
  await input.type(value, { delay: 80 });
  await input.press("ArrowDown").catch(() => {});
  await input.press("Enter").catch(() => {});
}

export class ZuzucheAdapter extends PlatformAdapter {
  constructor() {
    super({
      name: "zuzuche",
      displayName: "租租车",
      searchUrl: "https://sbt-w.zuzuche.com/sbt/pctoh5"
    });
    this.priceSelectors = [".price", ".money", ".amount", ".car-price", ".total-price"];
  }

  async search(page, query) {
    await page.goto("https://www.zuzuche.com/", {
      waitUntil: "domcontentloaded",
      timeout: 30000
    });

    await page.evaluate(() => {
      document.querySelector(".J-crcRental")?.classList.remove("fn-hide");
      document.querySelector('[data-role="crc-search-form"]')?.removeAttribute("disabled");
    });
    await page.waitForSelector("#pcname", { state: "attached", timeout: 15000 });
    await setZuzucheDateTime(page, query);
    await fillAndConfirm(page, "#pcname", query.pickup.city).catch(() => {});
    await fillAndConfirm(page, "#dcname", query.dropoff.city).catch(() => {});

    if (query.pickup.location) {
      await fillAndConfirm(page, "#plname", query.pickup.location).catch(() => {});
    }
    if (query.dropoff.location) {
      await fillAndConfirm(page, "#dlname", query.dropoff.location).catch(() => {});
    }

    await Promise.all([
      page.waitForLoadState("networkidle", { timeout: 30000 }).catch(() => {}),
      page.locator("#crcSubmit").click()
    ]);

    if (page.url() === "https://www.zuzuche.com/" || page.url() === "https://www.zuzuche.com") {
      const result = this.createFallbackResult(query, ["租租车国内 PC 查询流程未稳定跳转到结果页，本次保留入口链接。"]);
      result.bookingUrl = this.buildSearchUrl(query);
      return result;
    }

    return this.extractResult(page, query);
  }
}
