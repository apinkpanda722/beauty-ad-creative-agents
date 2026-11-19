"""Load workspace profiles without selecting development or evaluation tenants."""

from pathlib import Path
from typing import Literal

import yaml

from beautyads.domain.tenant import (
    TenantContextMissing,
    WorkspaceProfile,
    validate_tenant_id,
)


class Workspace(WorkspaceProfile):
    group: Literal["dev", "test", "isolation"]
    forbidden_terms: list[str] = []  # noqa: RUF012 -- Pydantic copies model field defaults


def load_workspaces(path: Path) -> list[Workspace]:
    """Report only record positions, never configuration values or YAML text."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ValueError("WORKSPACES_INVALID") from None
    if not isinstance(document, list):
        raise ValueError("WORKSPACES_INVALID")  # noqa: TRY004 -- one safe schema error
    workspaces, seen = [], set()
    for index, item in enumerate(document):
        try:
            workspace = Workspace.model_validate(item)
            tenant_id = validate_tenant_id(workspace.tenant_id)
            if tenant_id in seen:
                raise ValueError
        except (ValueError, TypeError, TenantContextMissing):
            raise ValueError(f"WORKSPACES_INVALID at [{index}]") from None
        seen.add(tenant_id)
        workspaces.append(workspace)
    return workspaces
