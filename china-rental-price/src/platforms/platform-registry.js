import { OneHaiAdapter } from "./onehai.js";
import { ZuzucheAdapter } from "./zuzuche.js";
import { ZucheAdapter } from "./zuche.js";

export function createPlatformRegistry() {
  return [
    new OneHaiAdapter(),
    new ZuzucheAdapter(),
    new ZucheAdapter()
  ];
}
