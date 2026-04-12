import { PlatformAdapter } from "./base.js";
import { buildOneHaiPeakRentalHint, parseOneHaiInventoryCount } from "../onehai-policy.js";

function splitOneHaiDateTime(datetime) {
  const [date = "", time = "10:00"] = String(datetime || "").split(" ");
  const [hour = "10", minute = "00"] = time.split(":");

  return {
    date,
    hour,
    minute
  };
}

async function resolveOneHaiBooking(page, query) {
  const pickupTime = splitOneHaiDateTime(query.pickupAt);
  const dropoffTime = splitOneHaiDateTime(query.dropoffAt);

  return page.evaluate(async (runtimeQuery) => {
    function post(url, data) {
      return new Promise((resolve, reject) => {
        $.ajax({
          type: "POST",
          url,
          data,
          dataType: "html",
          async: true,
          success: resolve,
          error: (_, __, errorText) => reject(new Error(errorText || "ajax failed"))
        });
      });
    }

    function findCity(cityList, cityName) {
      return cityList.find((item) => item.cityName === cityName) || null;
    }

    function pickStore(stores, locationHint) {
      if (!Array.isArray(stores) || stores.length === 0) {
        return null;
      }

      function scoreStore(store, scene, hint) {
        const text = [store.storeName, store.address, store.district].filter(Boolean).join(" ");
        let score = 0;

        if (hint && text.includes(hint)) {
          score += 10000;
        }

        if (scene === "train_station") {
          if (/高铁站/.test(text)) score += 600;
          if (/火车站/.test(text)) score += 520;
          if (/站内取还/.test(text)) score += 360;
          if (/客运/.test(text)) score -= 260;
          if (/机场/.test(text)) score -= 400;
        }

        if (scene === "airport") {
          if (/机场|航站楼|T1|T2|T3/.test(text)) score += 600;
          if (/高铁站|火车站/.test(text)) score -= 400;
        }

        if (/站内取还/.test(text)) score += 80;
        if (/店/.test(store.storeName || "")) score += 30;
        if (/自助点/.test(text)) score += 10;
        if (/停车场/.test(text)) score -= 12;
        if (/送车点/.test(text)) score -= 20;

        return score;
      }

      return [...stores].sort((left, right) => {
        return scoreStore(right, runtimeQuery.currentScene, locationHint) - scoreStore(left, runtimeQuery.currentScene, locationHint);
      })[0];
    }

    const cityListResponse = JSON.parse(await post(window.Url.CityList, ""));
    const pickupCity = findCity(cityListResponse.data || [], runtimeQuery.pickup.city);
    if (!pickupCity) {
      return {
        ok: false,
        reason: `一嗨站内城市列表未找到 ${runtimeQuery.pickup.city}。`
      };
    }

    const dropoffCity = findCity(cityListResponse.data || [], runtimeQuery.dropoff.city);
    if (!dropoffCity) {
      return {
        ok: false,
        reason: `一嗨站内城市列表未找到 ${runtimeQuery.dropoff.city}。`
      };
    }

    const pickupStoreResponse = JSON.parse(await post(window.Url.RegionalStore, {
      cityId: pickupCity.cityId
    }));
    runtimeQuery.currentScene = runtimeQuery.pickup.scene;
    const pickupStore = pickStore(pickupStoreResponse.data || [], runtimeQuery.pickup.location);
    if (!pickupStore) {
      return {
        ok: false,
        reason: `${runtimeQuery.pickup.city} 当前未返回可预订门店。`,
        pickupCity
      };
    }

    let returnStore = pickupStore;
    if (runtimeQuery.dropoff.city !== runtimeQuery.pickup.city || runtimeQuery.dropoff.location) {
      const returnStoreResponse = JSON.parse(await post(window.Url.RegionalStore, {
        cityId: dropoffCity.cityId
      }));
      runtimeQuery.currentScene = runtimeQuery.dropoff.scene;
      returnStore = pickStore(returnStoreResponse.data || [], runtimeQuery.dropoff.location);
      if (!returnStore) {
        return {
          ok: false,
          reason: `${runtimeQuery.dropoff.city} 当前未返回可预订还车门店。`,
          pickupCity,
          pickupStore
        };
      }
    }

    const redirectResponse = JSON.parse(await post(`${window.Url.RedirectFirstStep}?v=${Date.now()}`, {
      pickupDto: {
        pickUpCityId: String(pickupCity.cityId),
        getCarCity: pickupCity.cityName,
        getStoreId: String(pickupStore.id),
        getCarCityMenDian: pickupStore.storeName,
        txtGetCarAddress: "",
        getAddress: "",
        getCheck: false,
        pickUpTime: runtimeQuery.pickupDate,
        pickUpHour: runtimeQuery.pickupHour,
        pickUpMinute: runtimeQuery.pickupMinute,
        getLng: "",
        getLat: ""
      },
      returnDto: {
        returnCityId: String(dropoffCity.cityId),
        retCarCity: dropoffCity.cityName,
        retStoreId: String(returnStore.id),
        retCarCityMenDian: returnStore.storeName,
        txtDropCarAddress: "",
        retAddress: "",
        retCheck: false,
        returnTime: runtimeQuery.dropoffDate,
        retHour: runtimeQuery.dropoffHour,
        returnMinute: runtimeQuery.dropoffMinute,
        retLng: "",
        retLat: ""
      }
    }));

    if (!redirectResponse?.success || !redirectResponse?.data?.redirectUrl) {
      return {
        ok: false,
        reason: redirectResponse?.message || "一嗨未返回选车页跳转地址。",
        pickupCity,
        pickupStore,
        returnStore
      };
    }

    return {
      ok: true,
      pickupCity,
      dropoffCity,
      pickupStore,
      returnStore,
      bookingUrl: redirectResponse.data.redirectUrl
    };
  }, {
    pickup: query.pickup,
    dropoff: query.dropoff,
    pickupDate: pickupTime.date,
    pickupHour: pickupTime.hour,
    pickupMinute: pickupTime.minute,
    dropoffDate: dropoffTime.date,
    dropoffHour: dropoffTime.hour,
    dropoffMinute: dropoffTime.minute
  });
}

export class OneHaiAdapter extends PlatformAdapter {
  constructor() {
    super({
      name: "onehai",
      displayName: "一嗨租车",
      searchUrl: "https://booking.1hai.cn/order/firstStep"
    });
    this.priceSelectors = [".price", ".money", ".car-price", ".discount-price"];
  }

  async search(page, query) {
    await page.goto("https://www.1hai.cn/index.aspx", {
      waitUntil: "domcontentloaded",
      timeout: 30000
    });
    await page.waitForSelector("#getCarCity", { timeout: 15000 });

    const booking = await resolveOneHaiBooking(page, query);
    if (!booking.ok) {
      return this.createFallbackResult(query, [booking.reason]);
    }

    await page.goto(booking.bookingUrl, {
      waitUntil: "domcontentloaded",
      timeout: 30000
    });
    await page.waitForTimeout(5000);

    const pageText = await page.locator("body").innerText().catch(() => "");
    const inventoryCount = parseOneHaiInventoryCount(pageText);
    const peakRentalHint = inventoryCount === 0 ? buildOneHaiPeakRentalHint(query, pageText) : null;
    if (pageText.includes("登录账户，即可查看库存与价格")) {
      const result = this.createFallbackResult(query, [
        "一嗨选车页仍要求登录后查看库存与价格，当前会话未能穿透到价格页。"
      ]);
      result.bookingUrl = booking.bookingUrl;
      result.selectedStore = {
        pickup: booking.pickupStore?.storeName || null,
        dropoff: booking.returnStore?.storeName || null
      };
      return result;
    }

    if (inventoryCount === 0) {
      const result = this.createFallbackResult(query, [
        peakRentalHint?.warning || "当前选择的门店与时段暂无可租车型。"
      ]);
      result.bookingUrl = booking.bookingUrl;
      result.selectedStore = {
        pickup: booking.pickupStore?.storeName || null,
        dropoff: booking.returnStore?.storeName || null
      };
      if (peakRentalHint) {
        result.bookingRestriction = peakRentalHint;
      }
      return result;
    }

    const result = await this.extractResult(page, query);
    result.bookingUrl = booking.bookingUrl;
    result.selectedStore = {
      pickup: booking.pickupStore?.storeName || null,
      dropoff: booking.returnStore?.storeName || null
    };
    if (result.status !== "priced" && inventoryCount) {
      result.availableCars = inventoryCount;
      result.warnings = [
        `当前门店有 ${inventoryCount} 种车型可租，但价格使用 canvas 渲染，普通抓取未稳定解析。`,
        ...result.warnings.filter((warning) => warning !== "页面已打开，但当前未稳定解析出价格。")
      ];
    }
    return result;
  }
}
