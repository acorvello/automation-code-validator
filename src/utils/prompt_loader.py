from src.utils.config import get_prompt_path

class PromptLoader:
    """Load prompts from paths configured in conf/config.json."""

    @classmethod
    def get_prompt(
        cls,
        name: str,
        framework: str = "Unknown",
        language: str = "Unknown",
    ) -> str:
        path = get_prompt_path(name)
        with open(path, "r", encoding="utf-8") as f:
            prompt = f.read()
        prompt += (
            "\n\n## Detected Test Stack\n"
            f"- Framework: {framework}\n"
            f"- Language: {language}\n"
            "Use only APIs and syntax supported by this framework and language. "
            "If either value is Unknown, do not invent stack-specific code; "
            "state the uncertainty in the recommendation.\n"
        )
        return prompt
