from pathlib import Path

import pytest
from pydantic import ValidationError

from finagent.prompts import DEFAULT_PROMPT_PATH, load_prompts


def test_prompt_templates_reload_and_preserve_untrusted_data(tmp_path: Path):
    path = tmp_path / "prompts.toml"
    original = DEFAULT_PROMPT_PATH.read_text()
    path.write_text(original)
    prompts = load_prompts(path)
    rendered = prompts.render(
        "user_template",
        companies="TEST",
        forms=["10-K"],
        fiscal_years=[2025],
        sources="[$source] untrusted",
        context="None",
        question="$sources {ignore}",
    )
    assert "QUESTION\n$sources {ignore}" in rendered
    assert "[$source] untrusted" in rendered
    path.write_text(
        original.replace(
            "You are an autonomous, provenance-first",
            "You are a careful",
        )
    )
    assert load_prompts(path).system.startswith("You are a careful")


def test_invalid_prompt_variables_are_rejected(tmp_path: Path):
    path = tmp_path / "bad.toml"
    path.write_text(DEFAULT_PROMPT_PATH.read_text().replace("$question", "$quesiton"))
    with pytest.raises(ValidationError, match="Template variables"):
        load_prompts(path)
