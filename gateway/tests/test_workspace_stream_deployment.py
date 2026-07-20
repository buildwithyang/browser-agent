"""Static deployment contract tests for Workspace streaming."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIG = REPO_ROOT / "deploy" / "nginx.conf"


def _location_body(config: str, path_pattern: str) -> str:
    """Return one Nginx location body selected by an explicit pattern."""

    match = re.search(
        rf"location\s+{path_pattern}\s*\{{(?P<body>.*?)\n\s*\}}",
        config,
        re.DOTALL,
    )
    assert match is not None, f"missing Nginx location {path_pattern}"
    return match.group("body")


def test_workspace_proxy_disables_buffering_and_preserves_forwarding_headers() -> None:
    """Keep the exact Workspace stream unbuffered with the standard proxy identity."""

    config = NGINX_CONFIG.read_text(encoding="utf-8")
    workspace_location = _location_body(config, r"=\s*/api/tasks/workspace")

    for directive in (
        "proxy_pass http://gateway:17321/tasks/workspace;",
        "proxy_http_version 1.1;",
        "proxy_buffering off;",
        "proxy_cache off;",
        "proxy_set_header Host $host;",
        "proxy_set_header X-Real-IP $remote_addr;",
        "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
    ):
        assert directive in workspace_location


def test_general_api_proxy_keeps_the_existing_prefix_rewrite() -> None:
    """Protect non-Workspace API forwarding from the exact stream override."""

    config = NGINX_CONFIG.read_text(encoding="utf-8")
    api_location = _location_body(config, r"/api/")

    assert "proxy_pass http://gateway:17321/;" in api_location
    assert "proxy_set_header Host $host;" in api_location
