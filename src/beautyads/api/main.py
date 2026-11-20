"""Loopback by default; assembly remains owned by the app lifespan."""

from functools import partial

import uvicorn
from fastapi import FastAPI

from beautyads.api.app import create_app
from beautyads.api.assembly import assemble_full
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    InvalidSetting,
    get_setting,
    load_settings,
)


def _serve_options(*, environ=None, env_file=DEFAULT_ENV_FILE) -> tuple[str, str, bool]:
    config = {"environ": environ, "env_file": env_file}
    group = get_setting("BEAUTYADS_GROUP", "dev", **config)
    if group not in {"dev", "test"}:
        raise InvalidSetting("BEAUTYADS_GROUP")
    model = get_setting("BEAUTYADS_EVAL_MODEL", "claude-haiku-5-5", **config)
    if model not in {"claude-haiku-5-5", "claude-sonnet-5-5"}:
        raise InvalidSetting("BEAUTYADS_EVAL_MODEL")
    image = get_setting("BEAUTYADS_WITH_IMAGE", "0", **config)
    if image not in {"0", "1"}:
        raise InvalidSetting("BEAUTYADS_WITH_IMAGE")
    return group, model, image == "1"


def build_app(
    *, environ=None, env_file=DEFAULT_ENV_FILE, assemble=assemble_full
) -> FastAPI:
    group, model, image = _serve_options(environ=environ, env_file=env_file)
    return create_app(
        partial(
            assemble,
            settings=load_settings(environ=environ, env_file=env_file),
            group=group,
            evaluation_model=model,
            with_image_enabled=image,
            environ=environ,
            env_file=env_file,
        )
    )


def server_port(*, environ=None, env_file=DEFAULT_ENV_FILE) -> int:
    value = get_setting(
        "BEAUTYADS_API_PORT", "8000", environ=environ, env_file=env_file
    )
    try:
        port = int(value)
    except ValueError:
        raise InvalidSetting("BEAUTYADS_API_PORT") from None
    if not 1024 <= port <= 65535:
        raise InvalidSetting("BEAUTYADS_API_PORT")
    return port


def server_host(*, environ=None, env_file=DEFAULT_ENV_FILE) -> str:
    host = get_setting(
        "BEAUTYADS_API_HOST", "127.0.0.1", environ=environ, env_file=env_file
    )
    if host not in {"127.0.0.1", "0.0.0.0"}:
        raise InvalidSetting("BEAUTYADS_API_HOST")
    return host


def main() -> None:
    try:
        group, model, image = _serve_options()
        port = server_port()
        host = server_host()
        app = build_app()
    except InvalidSetting as error:
        print(f"SERVE_FAILED INVALID_SETTING:{error.name}")
        raise SystemExit(2) from None
    print(
        f"SERVE group={group} eval_model={model} image={'on' if image else 'off'} "
        f"url=http://{host}:{port}"
    )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
