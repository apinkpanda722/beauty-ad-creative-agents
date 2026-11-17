"""Demo-only header session; allowlist and thread ownership fail closed."""

from fastapi import HTTPException

from beautyads.domain.tenant import (
    TenantContextMissing,
    TenantMismatch,
    make_thread_id,
    validate_tenant_id,
)


def resolve_session(header, thread_id, *, tenants, allowed_tenants):
    try:
        tenant_id = validate_tenant_id(header)
    except TenantContextMissing:
        raise HTTPException(400, "TENANT_CONTEXT_MISSING") from None
    if tenant_id not in allowed_tenants:
        raise HTTPException(403, "TENANT_NOT_ALLOWED")
    try:
        if thread_id is not None:
            tenants.assert_thread_access(tenant_id, thread_id)
        else:
            thread_id = make_thread_id(tenant_id)
            tenants.register_thread(tenant_id, thread_id)
    except TenantMismatch:
        raise HTTPException(403, "TENANT_MISMATCH") from None
    return tenant_id, thread_id
