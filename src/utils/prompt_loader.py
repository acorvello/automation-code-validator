from src.utils.config import get_prompt_path

class PromptLoader:
    """Load prompts from paths configured in conf/config.json."""

    @classmethod
    def get_prompt(cls, name: str) -> str:
        path = get_prompt_path(name)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
