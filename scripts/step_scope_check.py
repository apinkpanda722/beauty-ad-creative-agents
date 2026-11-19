"""step 설계의 범위 충돌 의심을 경고한다. 파일 쓰기나 하네스 연결은 없다."""

import argparse
import ast
import contextlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from step_file_checks import (
    ROOT,
    SCOPE_LINE,
    backticked,
    consumer_warnings,
    is_inside,
    machine_lines,
    modify_targets,
    paths_in,
    section,
)


COORDINATE = re.compile(
    r"(?<![\w/])(?P<path>/?[\w./-]+\.[\w]+):(?P<lines>\d+(?:[-·]\d+)*)"
    r"(?![\w·-])"
)
BULLET = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+.*?"
    r"(?=^[ \t]*(?:[-*+]|\d+[.)])[ \t]+|^\s*$|^#{1,6} |\Z)",
    re.M | re.S,
)


def _identifier(token: str) -> bool:
    return bool(
        token.isascii()
        and token.isidentifier()
        and (
            token.isupper()
            or ("_" in token and token.lower() == token)
            or re.fullmatch(r"[A-Z][a-zA-Z0-9]*[a-z][a-zA-Z0-9]*", token)
        )
    )


def _local_path(root: Path, name: str) -> Path | None:
    path = (root / name.lstrip("/")).resolve()
    return path if path.is_relative_to(root.resolve()) else None


def _path_warnings(text: str, root: Path, allowed: list[str]) -> list[str]:
    work = section(text, "작업")
    body = work + "\n" + section(text, "설계 검토 기록")
    # 선언 자체와 열람 범위 설명은 작업할 새 파일 목록이 아니다.
    body = re.sub(
        rf"^{re.escape(SCOPE_LINE)}[^\n]*(?:\n(?!\n|## )[^\n]+)*",
        "",
        body,
        flags=re.M,
    )
    body = re.sub(r"^(?:열람 금지 경로:|수정 허용 경로:).*?$", "", body, flags=re.M)
    match = re.search(r"\*\*수정할 파일\*\*(.*?)(?:\n\n|\Z)", work, re.S)
    targets = modify_targets(match.group(1)) if match else []
    warnings = []
    for token in sorted(set(paths_in(body)) | set(targets)):
        # 좌표는 다음 점검에서 별도로 확인한다.
        coordinate = COORDINATE.fullmatch(token)
        if coordinate:
            continue
        if any(mark in token for mark in ("*", "::", "…", "<", ">")):
            continue
        if any(is_inside(token, entry) for entry in allowed):
            continue
        path = _local_path(root, token)
        if path is None:
            continue
        if not path.exists():
            warnings.append(f"경로 `{token}`가 존재하지 않고 수정 허용 경로에 없다")
        elif token in targets:
            warnings.append(f"수정할 파일 `{token}`가 수정 허용 경로에 없다")
    return warnings


def _coordinate_warnings(text: str, root: Path) -> list[str]:
    warnings = []
    bullets = list(BULLET.finditer(text))
    for match in COORDINATE.finditer(text):
        label = match.group()
        path = _local_path(root, match.group("path"))
        if path is None or not path.is_file():
            warnings.append(f"좌표 `{label}`의 파일이 없다")
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            warnings.append(f"좌표 `{label}`의 파일을 읽을 수 없다")
            continue
        numbers = [int(number) for number in re.split(r"[-·]", match.group("lines"))]
        if any(number < 1 or number > len(lines) for number in numbers):
            warnings.append(f"좌표 `{label}`가 파일 줄 수({len(lines)})를 벗어난다")
            continue
        bullet = next(
            (item for item in bullets if item.start() <= match.start() < item.end()),
            None,
        )
        if bullet is None:
            continue
        # 좌표가 들어 있는 백틱의 닫는 기호부터 토큰을 다시 세지 않는다.
        tail = text[match.end() : bullet.end()]
        if tail.startswith("`"):
            tail = tail[1:]
        if "-" in match.group("lines"):
            nearby = "\n".join(lines[max(0, min(numbers) - 16) : max(numbers) + 15])
        else:
            nearby = "\n".join(
                line
                for number in numbers
                for line in lines[max(0, number - 16) : number + 15]
            )
        for name in sorted(set(filter(str.isidentifier, backticked(tail)))):
            if not re.search(rf"\b{re.escape(name)}\b", nearby):
                warnings.append(
                    f"좌표 불일치 `{label}`: `{name}`가 앞뒤 15줄 안에 없다"
                )
    return warnings


def _sources(root: Path) -> dict[str, str]:
    sources = {}
    for folder in ("src", "tests", "scripts"):
        for path in sorted((root / folder).rglob("*")):
            name = path.relative_to(root).as_posix()
            if (
                "__pycache__" in path.parts
                or path.name.startswith(".env")
                or _local_path(root, name) is None
                or not path.is_file()
            ):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if "\x00" not in source:
                sources[name] = source
    return sources


def _identifier_warnings(
    text: str, names: list[str], sources: dict[str, str]
) -> list[str]:
    new = set()
    for declaration in re.findall(
        r"^새 식별자:[ \t]*(.*)$", section(text, "작업"), re.M
    ):
        new.update(backticked(declaration))
    corpus = "\n".join(sources.values())
    return [
        f"식별자 `{name}`가 src/·tests/·scripts/에 없다(새 식별자: 선언 확인)"
        for name in names
        if name not in new and not re.search(rf"\b{re.escape(name)}\b", corpus)
    ]


def _constant_warnings(
    names: list[str], sources: dict[str, str], allowed: list[str]
) -> list[str]:
    constants = set()
    for path, source in sources.items():
        if not path.startswith("src/") or not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            constants.update(
                item.id
                for target in targets
                for item in ast.walk(target)
                if isinstance(item, ast.Name) and item.id.isupper()
            )
    warnings = []
    for name in names:
        if name not in constants:
            continue
        locations = []
        outside = []
        for path, source in sources.items():
            if not path.startswith("tests/"):
                continue
            for number, line in enumerate(source.splitlines(), 1):
                if re.search(rf"\b{re.escape(name)}\b", line) and re.search(
                    r"\bassert\b|==|<=|>=|\bFraction\b", line
                ):
                    location = f"{path}:{number}"
                    locations.append(location)
                    if not any(is_inside(path, entry) for entry in allowed):
                        outside.append(location)
        if outside:
            listing = ", ".join(outside[:12])
            if len(outside) > 12:
                listing += f", … 외 {len(outside) - 12}곳"
            warnings.append(
                f"`{name}` 상수 단언 {len(locations)}곳(허용 목록 밖: {listing})"
            )
    return warnings


def check_step(text: str, root: Path = ROOT) -> list[str]:
    """경로, 좌표, 식별자, 상수 단언, 소비자 순서의 읽기 전용 경고."""
    root = Path(root)
    machine = machine_lines(text)
    allowed = machine["allowed"] if machine else []
    sources = _sources(root)
    names = sorted(set(filter(_identifier, backticked(text))))
    return (
        _path_warnings(text, root, allowed)
        + _coordinate_warnings(text, root)
        + _identifier_warnings(text, names, sources)
        + _constant_warnings(names, sources, allowed)
        + consumer_warnings(text, root)
    )


def main(argv: list[str] | None = None, *, out=sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--root", type=Path, default=ROOT)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:
            return int(exc.code)
    counts = []
    failed = False
    for filename in sorted(set(args.files)):
        try:
            text = Path(filename).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            print(f"오류 {filename}: {exc}", file=out)
            failed = True
            continue
        warnings = check_step(text, args.root)
        for warning in warnings:
            print(f"경고 {filename}: {warning}", file=out)
        counts.append((filename, len(warnings)))
    for filename, count in counts:
        print(f"{filename}: 경고 {count}건", file=out)
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
