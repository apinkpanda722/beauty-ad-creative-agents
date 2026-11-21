import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { expect, it } from "vitest";
import { BRAND } from "../lib/brand";

const web = process.cwd();
const names = { name: ["Gyeol", "Studio"].join(" "), nameKo: ["결", "스튜디오"].join(" ") };

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? sources(path) : /\.(?:[cm]?[jt]sx?|css)$/.test(entry.name) ? [path] : [];
  });
}

it("defines the exact product names once", () => {
  expect(BRAND).toEqual(names);
  const files = ["app", "components", "lib"].flatMap(directory => sources(join(web, directory)));
  expect(files.length).toBeGreaterThan(0);
  expect(files).toContain(join(web, "lib/brand.ts"));
  for (const file of files) {
    if (relative(web, file) === "lib/brand.ts") continue;
    const source = readFileSync(file, "utf8");
    for (const name of Object.values(names)) expect(source, relative(web, file)).not.toContain(name);
  }
});
