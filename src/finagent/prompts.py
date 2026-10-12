import tomllib
from pathlib import Path
from string import Template

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_PROMPT_PATH = Path(__file__).with_name("prompts.toml")
TEMPLATE_VARIABLES = {
    "user_template": {"companies", "forms", "fiscal_years", "sources", "context", "question"},
    "source_template": {"citation_id", "ticker", "form", "locator", "text"},
    "history_template": {"history"},
    "missing_template": {"missing"},
}


class Prompts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system: str = Field(min_length=1)
    user_template: str = Field(min_length=1)
    source_template: str = Field(min_length=1)
    coverage: str = Field(min_length=1)
    history_template: str = Field(min_length=1)
    missing_template: str = Field(min_length=1)
    language_en: str = "Use English exclusively for all user-facing output, plans and deliverables."
    language_zh: str = "所有面向用户的回答、计划、研报与文件标题使用中文，保留原文与标识符。"

    def system_for(self, language: str) -> str:
        return self.system + "\n\nLANGUAGE MODE (overrides matching the question language):\n" + (
            self.language_en if language == "en" else self.language_zh
        )

    @field_validator("user_template", "source_template", "history_template", "missing_template")
    @classmethod
    def validate_template(cls, value, info):
        template = Template(value)
        if not template.is_valid():
            raise ValueError("Invalid template syntax; use $variable and $$ for a literal dollar")
        expected = TEMPLATE_VARIABLES[info.field_name]
        actual = set(template.get_identifiers())
        if actual != expected:
            raise ValueError(
                f"Template variables must be {sorted(expected)}; found {sorted(actual)}"
            )
        return value

    def render(self, name: str, **variables: object) -> str:
        if name not in TEMPLATE_VARIABLES:
            raise ValueError(f"Unknown prompt template: {name}")
        return Template(getattr(self, name)).substitute(variables)


def load_prompts(path: Path | None = None) -> Prompts:
    path = path or DEFAULT_PROMPT_PATH
    with path.open("rb") as file:
        document = tomllib.load(file)
    if set(document) != {"version", "prompts"} or document["version"] != 1:
        raise ValueError("Prompt configuration requires version=1 and a [prompts] section")
    return Prompts.model_validate(document["prompts"])
