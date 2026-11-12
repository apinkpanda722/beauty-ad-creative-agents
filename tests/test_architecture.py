"""AST architecture guard and isolated examples of the boundaries in AGENTS.md."""

import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAYER_IMPORTS = {
    "domain": set(),
    "settings": set(),
    "obs": {"domain", "settings"},
    "llm": {"domain", "settings", "obs"},
    "sources": {"domain", "settings"},
    "store": {"domain", "settings"},
    "graph": {"domain", "settings"},
    "checks": {"domain"},
    "analysis": {"domain", "llm"},
    "agents": {"domain", "graph", "checks", "llm", "store", "obs"},
    "api": {
        "domain",
        "settings",
        "obs",
        "llm",
        "sources",
        "store",
        "graph",
        "checks",
        "analysis",
        "agents",
    },
    "pipeline": {
        "domain",
        "settings",
        "obs",
        "llm",
        "sources",
        "store",
        "graph",
        "checks",
        "analysis",
        "agents",
    },
    "eval": {
        "domain",
        "settings",
        "obs",
        "llm",
        "sources",
        "store",
        "graph",
        "checks",
        "analysis",
        "agents",
        "api",
        "pipeline",
    },
}
SDK_LAYERS = {
    "litellm": {"llm"},
    "neo4j": {"graph"},
    "psycopg": {"store", "api"},
    "psycopg_pool": {"store", "api"},
    "langgraph": {"agents", "api"},
    "fastapi": {"api"},
    "httpx": {"sources"},
    "langfuse": {"obs"},
}


class Violation(NamedTuple):
    file: str
    target: str
    rule: str


def python_files(package_root: Path) -> list[Path]:
    return sorted(
        path
        for path in package_root.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.relative_to(package_root).parts
    )


def _resolve_relative(name: str, package: str) -> str:
    """Keep escaping names dotted so the caller can report a LAYER violation."""
    level = len(name) - len(name.lstrip("."))
    if not level:
        return name
    parts = package.split(".")
    if level > len(parts):
        return name
    prefix = ".".join(parts[: len(parts) - level + 1])
    suffix = name[level:]
    return f"{prefix}.{suffix}" if suffix else prefix


def _from_targets(
    module: str, node: ast.ImportFrom, root_modules: set[str]
) -> list[str]:
    # Only the package root may export both layer modules and ordinary attributes.
    if module == "beautyads":
        return [
            f"beautyads.{alias.name}"
            for alias in node.names
            if alias.name in root_modules
        ]
    return [module]


def _dynamic_function(node: ast.Call, aliases: dict[str, str]) -> str | None:
    if isinstance(node.func, ast.Name):
        if node.func.id == "__import__":
            return "__import__"
        if aliases.get(node.func.id) == "importlib.import_module":
            return "importlib.import_module"
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
        and isinstance(node.func.value, ast.Name)
        and aliases.get(node.func.value.id) == "importlib"
    ):
        return "importlib.import_module"
    return None


def _call_argument(node: ast.Call, index: int, keyword: str) -> ast.expr | None:
    if len(node.args) > index:
        return node.args[index]
    return next((item.value for item in node.keywords if item.arg == keyword), None)


def _literal_string(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def find_violations(package_root: Path) -> set[Violation]:
    files = python_files(package_root)
    if not files:
        raise ValueError(f"No Python files under {package_root}")
    root_modules = set(LAYER_IMPORTS) | {
        path.relative_to(package_root).parts[0]
        if len(path.relative_to(package_root).parts) > 1
        else path.stem
        for path in files
    }
    violations = set()
    for path in files:
        relative = path.relative_to(package_root)
        file = relative.as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if file == "__init__.py":
            continue
        layer = relative.parts[0] if len(relative.parts) > 1 else relative.stem
        if layer not in LAYER_IMPORTS:
            violations.add(Violation(file, layer, "UNKNOWN_LAYER"))
            continue
        package = ".".join(("beautyads", *relative.parent.parts))
        aliases = {"importlib": "importlib"}
        nodes = list(ast.walk(tree))
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "importlib":
                        aliases[alias.asname or alias.name] = alias.name
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "importlib"
                and not node.level
            ):
                for alias in node.names:
                    if alias.name == "import_module":
                        aliases[alias.asname or alias.name] = "importlib.import_module"

        targets = []
        for node in nodes:
            if isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = _resolve_relative(
                    "." * node.level + (node.module or ""), package
                )
                targets.extend(_from_targets(module, node, root_modules))
            elif isinstance(node, ast.Call) and (
                function := _dynamic_function(node, aliases)
            ):
                name = _literal_string(_call_argument(node, 0, "name"))
                if name is None:
                    violations.add(Violation(file, function, "DYNAMIC_IMPORT"))
                    continue
                context = package
                if name.startswith(".") and function == "importlib.import_module":
                    argument = _call_argument(node, 1, "package")
                    if argument is not None:
                        context = _literal_string(argument)
                        if context is None:
                            violations.add(Violation(file, function, "DYNAMIC_IMPORT"))
                            continue
                targets.append(_resolve_relative(name, context))

        for target in targets:
            parts = target.split(".")
            top = parts[0]
            if target.startswith("."):
                violations.add(Violation(file, target, "LAYER"))
            elif top == "beautyads":
                if (
                    len(parts) > 1
                    and parts[1] != layer
                    and parts[1] not in LAYER_IMPORTS[layer]
                ):
                    violations.add(Violation(file, target, "LAYER"))
            else:
                if top in SDK_LAYERS and layer not in SDK_LAYERS[top]:
                    violations.add(Violation(file, target, "SDK"))
                if (
                    layer in {"domain", "settings"}
                    and top not in sys.stdlib_module_names
                    and top != "pydantic"
                ):
                    violations.add(Violation(file, target, "PURE_EXTERNAL"))
    return violations


def test_repository_architecture():
    package_root = ROOT / "src" / "beautyads"
    assert len(python_files(package_root)) >= 1
    assert find_violations(package_root) == set()


def test_empty_tree_is_rejected(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "notes.txt").write_text("resource", encoding="utf-8")
    with pytest.raises(ValueError, match="Python"):
        find_violations(tmp_path)


@pytest.mark.parametrize(
    ("file", "source", "expected"),
    [
        ("domain/x.py", "import beautyads.llm", {("beautyads.llm", "LAYER")}),
        (
            "domain/x.py",
            "import pathlib, sys\nfrom typing import Protocol\nfrom pydantic import BaseModel",
            set(),
        ),
        ("domain/x.py", "import yaml", {("yaml", "PURE_EXTERNAL")}),
        ("settings.py", "from yaml import safe_load", {("yaml", "PURE_EXTERNAL")}),
        ("domain/x.py", "from ..llm import x", {("beautyads.llm", "LAYER")}),
        ("domain/x.py", "from beautyads import llm", {("beautyads.llm", "LAYER")}),
        (
            "domain/x.py",
            "from beautyads import llm as m, graph as g",
            {("beautyads.llm", "LAYER"), ("beautyads.graph", "LAYER")},
        ),
        ("settings.py", "import beautyads.llm", {("beautyads.llm", "LAYER")}),
        ("domain/x.py", "import beautyads.settings", {("beautyads.settings", "LAYER")}),
        ("checks/x.py", "import beautyads.llm", {("beautyads.llm", "LAYER")}),
        ("sources/x.py", "import litellm", {("litellm", "SDK")}),
        ("llm/x.py", "import litellm", set()),
        ("agents/x.py", "import psycopg", {("psycopg", "SDK")}),
        ("api/x.py", "import psycopg", set()),
        ("agents/x.py", "import psycopg_pool", {("psycopg_pool", "SDK")}),
        ("store/x.py", "from psycopg_pool import ConnectionPool", set()),
        ("agents/x.py", "import langgraph", set()),
        ("llm/x.py", "import langgraph", {("langgraph", "SDK")}),
        ("agents/x.py", "import beautyads.eval", {("beautyads.eval", "LAYER")}),
        (
            "eval/x.py",
            "import beautyads.agents, beautyads.api, beautyads.pipeline",
            set(),
        ),
        (
            "domain/x.py",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import beautyads.llm",
            {("beautyads.llm", "LAYER")},
        ),
        ("foo/x.py", "", {("foo", "UNKNOWN_LAYER")}),
        ("foo/nested/x.py", "", {("foo", "UNKNOWN_LAYER")}),
        ("foo.py", "", {("foo", "UNKNOWN_LAYER")}),
        ("graph/tools/x.py", "import beautyads.llm", {("beautyads.llm", "LAYER")}),
        ("domain/x.py", "from beautyads import __version__", set()),
        (
            "domain/x.py",
            "import importlib\nimportlib.import_module(name)",
            {("importlib.import_module", "DYNAMIC_IMPORT")},
        ),
        (
            "domain/x.py",
            'import importlib\nimportlib.import_module("beautyads.llm")',
            {("beautyads.llm", "LAYER")},
        ),
        ("sources/x.py", "import yaml", set()),
        ("domain/x.py", "import beautyads.domain.models\nfrom . import models", set()),
        ("domain/x.py", "from ...llm import x", {("...llm", "LAYER")}),
        ("settings.py", "from .. import domain", {("..", "LAYER")}),
        ("graph/tools/x.py", "from ...llm import x", {("beautyads.llm", "LAYER")}),
        (
            "api/x.py",
            "from beautyads import pipeline",
            {("beautyads.pipeline", "LAYER")},
        ),
        ("pipeline/x.py", "import beautyads.api", {("beautyads.api", "LAYER")}),
        (
            "api/x.py",
            "from beautyads import sources, analysis\nimport langgraph",
            set(),
        ),
        (
            "domain/x.py",
            "import litellm",
            {("litellm", "SDK"), ("litellm", "PURE_EXTERNAL")},
        ),
        ("llm/x.py", "from httpx import Client", {("httpx", "SDK")}),
        ("sources/x.py", "import neo4j.time", {("neo4j.time", "SDK")}),
        ("graph/x.py", "from neo4j import GraphDatabase", set()),
        ("agents/x.py", "import fastapi", {("fastapi", "SDK")}),
        ("api/x.py", "import fastapi", set()),
        ("agents/x.py", "import langfuse", {("langfuse", "SDK")}),
        ("obs/x.py", "import langfuse", set()),
        ("domain/x.py", "__import__(name)", {("__import__", "DYNAMIC_IMPORT")}),
        ("domain/x.py", '__import__("beautyads.llm")', {("beautyads.llm", "LAYER")}),
        (
            "sources/x.py",
            'import importlib as il\nil.import_module("litellm")',
            {("litellm", "SDK")},
        ),
        (
            "domain/x.py",
            'from importlib import import_module as load\nload("beautyads.llm")',
            {("beautyads.llm", "LAYER")},
        ),
        (
            "domain/x.py",
            'import importlib\nimportlib.import_module(name="beautyads.llm")',
            {("beautyads.llm", "LAYER")},
        ),
        (
            "domain/x.py",
            'import importlib\nimportlib.import_module("..llm", "beautyads.domain")',
            {("beautyads.llm", "LAYER")},
        ),
        (
            "domain/x.py",
            '# import beautyads.llm\ntext = "import yaml"',
            set(),
        ),
        (
            "__init__.py",
            "import litellm\nimport beautyads.eval\n__import__(name)",
            set(),
        ),
    ],
)
def test_import_boundaries(tmp_path, file, source, expected):
    path = tmp_path / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    assert find_violations(tmp_path) == {
        Violation(file, target, rule) for target, rule in expected
    }


def test_resources_and_pycache_are_ignored(tmp_path):
    (tmp_path / "__init__.py").touch()
    (tmp_path / "empty").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "resource.txt").touch()
    cached = tmp_path / "foo" / "__pycache__"
    cached.mkdir(parents=True)
    (cached / "bad.py").write_text("not valid Python!", encoding="utf-8")
    assert python_files(tmp_path) == [tmp_path / "__init__.py"]
    assert find_violations(tmp_path) == set()


def test_only_cached_python_is_an_empty_tree(tmp_path):
    cached = tmp_path / "__pycache__"
    cached.mkdir()
    (cached / "x.py").touch()
    with pytest.raises(ValueError, match="Python"):
        find_violations(tmp_path)


def test_root_module_import_is_not_mistaken_for_an_attribute(tmp_path):
    (tmp_path / "foo.py").touch()
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "x.py").write_text("from beautyads import foo", encoding="utf-8")
    assert find_violations(tmp_path) == {
        Violation("foo.py", "foo", "UNKNOWN_LAYER"),
        Violation("domain/x.py", "beautyads.foo", "LAYER"),
    }


def test_rules_match_agents_tables():
    document = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    section = document.split("## 계층 경계\n", 1)[1].split("\n## ", 1)[0]
    tables = []
    rows = []
    for line in section.splitlines():
        if line.startswith("|"):
            rows.append(
                [
                    re.sub(r"\([^)]*\)", "", cell).strip()
                    for cell in line.strip("|").split("|")
                ]
            )
        elif rows:
            tables.append(rows)
            rows = []
    if rows:
        tables.append(rows)
    assert len(tables) == 2, "AGENTS.md 계층 경계의 두 표를 읽을 수 없다"
    layer_names = {
        name for row in tables[0][2:] for name in re.findall(r"`([^`]+)`", row[0])
    }
    sdk_layers = {}
    for row in tables[1][2:]:
        packages = re.findall(r"`([^`]+)`", row[0])
        if packages:
            sdk_layers[packages[0]] = set(re.findall(r"`([^`]+)`", row[1]))
    assert layer_names, "내부 계층 표가 비어 있다"
    assert sdk_layers and all(sdk_layers.values()), "외부 SDK 표가 비어 있다"
    assert layer_names == set(LAYER_IMPORTS)
    assert sdk_layers == {
        key: value for key, value in SDK_LAYERS.items() if key != "psycopg_pool"
    }
    assert SDK_LAYERS["psycopg_pool"] == SDK_LAYERS["psycopg"]
