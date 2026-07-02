from __future__ import annotations

from string import Template


def render_template(raw_template: str, payload: dict) -> str:
    # Safe substitution keeps unresolved placeholders untouched.
    return Template(raw_template).safe_substitute(payload)
