import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import ts from "typescript";
import { expect, it } from "vitest";

const web = process.cwd();
function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true })
    .sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0)
    .flatMap(entry => entry.isDirectory() ? files(join(directory, entry.name))
      : /\.(?:tsx?|css)$/.test(entry.name) ? [join(directory, entry.name)] : []);
}
const sources = ["app", "components", "lib"].flatMap(directory => files(join(web, directory)));
const modules = sources.filter(file => /\.tsx?$/.test(file));
function parse(file: string) {
  return ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);
}
function imports(file: string): string[] {
  const targets: string[] = [];
  function add(specifier: string) {
    if (!specifier.startsWith(".")) return;
    const base = resolve(dirname(file), specifier);
    const target = [base, `${base}.ts`, `${base}.tsx`, join(base, "index.ts"), join(base, "index.tsx")]
      .find(candidate => modules.includes(candidate));
    if (target) targets.push(target);
  }
  function visit(node: ts.Node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node))
      && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) add(node.moduleSpecifier.text);
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword
      && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) add(node.arguments[0].text);
    if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument)
      && ts.isStringLiteral(node.argument.literal)) add(node.argument.literal.text);
    ts.forEachChild(node, visit);
  }
  visit(parse(file));
  return targets;
}
function classNames(): string[] {
  const names: string[] = [];
  function strings(node: ts.Node) {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)
      || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
      names.push(...node.text.split(/\s+/).filter(Boolean));
    }
    ts.forEachChild(node, strings);
  }
  function visit(node: ts.Node) {
    if (ts.isJsxAttribute(node) && node.name.getText() === "className" && node.initializer) strings(node.initializer);
    ts.forEachChild(node, visit);
  }
  for (const file of modules) visit(parse(file));
  return names;
}

it("reaches every component and library through source imports from app pages and layouts", () => {
  const targets = modules.filter(file => /^(components|lib)\//.test(relative(web, file)));
  const entries = modules.filter(file => /^app\/(?:.*\/)?(?:page|layout)\.tsx?$/.test(relative(web, file)));
  expect(targets.length).toBeGreaterThan(0);
  expect(entries.length).toBeGreaterThan(0);
  const reached = new Set<string>();
  function visit(file: string) {
    if (reached.has(file)) return;
    reached.add(file);
    for (const target of imports(file)) visit(target);
  }
  for (const entry of entries) visit(entry);
  expect(targets.filter(file => !reached.has(file)).map(file => relative(web, file))).toEqual([]);
});

it("leaves no preparation placeholder in app, component or library sources", () => {
  expect(sources.length).toBeGreaterThan(0);
  for (const file of sources) {
    const source = readFileSync(file, "utf8");
    for (const text of ["준비 중", "gs-placeholder"]) expect(source, relative(web, file)).not.toContain(text);
  }
});

it("uses every globals class selector as an exact JSX className token", () => {
  const css = readFileSync(join(web, "app/globals.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const selectors = [...css.matchAll(/(?:^|[{}])\s*([^{}]+)\{/g)].map(match => match[1]);
  const classes = selectors.flatMap(selector => [...selector.matchAll(/\.([a-zA-Z_][\w-]*)/g)].map(match => match[1]));
  const used = classNames();
  expect(selectors.length).toBeGreaterThan(0);
  expect(classes.length).toBeGreaterThan(0);
  expect(used.length).toBeGreaterThan(0);
  expect(classes.filter(name => !used.includes(name))).toEqual([]);
});
