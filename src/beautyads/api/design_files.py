"""Shared local design path calculation for validated image references."""

from hashlib import sha256
from pathlib import Path

from fastapi import HTTPException

from beautyads.api.ask_view import IMAGE_MIMES


def design_file(
    design_dir: Path, image: dict, *, reject_symlinks: bool = False
) -> tuple[Path, str]:
    """Resolve the stored original/composed image without escaping the root.

    The legacy design route permits links within the root. Saved-plan image
    requests additionally reject links at either descendant component.
    """
    directory = sha256(image["request_key"].encode("utf-8")).hexdigest()[:16]
    root = design_dir.resolve()
    composed = image.get("composed")
    filename = (
        f"{image['index']:02d}_composed.png"
        if composed is not None
        else f"{image['index']:02d}.{IMAGE_MIMES[image['mime']]}"
    )
    path = root / directory / filename
    if reject_symlinks and (path.parent.is_symlink() or path.is_symlink()):
        raise HTTPException(404, "DESIGN_NOT_FOUND")
    path = path.resolve()
    if not path.is_relative_to(root):
        raise HTTPException(404, "DESIGN_NOT_FOUND")
    return path, composed["mime"] if composed is not None else image["mime"]
