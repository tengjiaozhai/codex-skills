#!/usr/bin/env node
import { fileURLToPath } from "node:url";
import { searchRentalPrices } from "./search.js";

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const part = argv[index];
    if (!part.startsWith("--")) {
      continue;
    }

    const key = part.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      args[key] = true;
      continue;
    }

    args[key] = next;
    index += 1;
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));

const input = {
  pickupCity: args.pickupCity,
  pickupLocation: args.pickupLocation,
  pickupScene: args.pickupScene,
  dropoffCity: args.dropoffCity,
  dropoffLocation: args.dropoffLocation,
  dropoffScene: args.dropoffScene,
  pickupDateTime: args.pickupDatetime,
  dropoffDateTime: args.dropoffDatetime,
  vehicleClass: args.vehicleClass
};

searchRentalPrices(input, {
  headless: !args.headed,
  ttlMinutes: args.ttlMinutes,
  snapshotMode: args.snapshot || "error",
  rootDir: fileURLToPath(new URL("..", import.meta.url))
}).then((result) => {
  console.log(JSON.stringify(result, null, 2));
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
