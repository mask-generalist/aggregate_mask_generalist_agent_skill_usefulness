from pydantic import BaseModel
import re
from loguru import logger


class MarkdownSections(BaseModel):
    plan: str = ""
    answer: str = ""
    personal_information: str = ""


def parse_markdown_sections(text: str) -> MarkdownSections:
    """
    Parses markdown text looking for exact "## Plan" and "## Answer" sections (case-insensitive).
    All other sections are ignored. Missing sections get empty strings.

    Args:
        text: Markdown text with sections like "## Plan" and "## Answer"

    Returns:
        MarkdownSections model with plan and answer content (empty if not found)
    """
    result_data = {"plan": "", "answer": "", "personal_information": ""}

    # Search for "## Plan" section (case-insensitive)
    plan_pattern = r'^## Plan\s*$\n(.*?)(?=^## |\Z)'
    plan_match = re.search(plan_pattern, text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if plan_match:
        result_data["plan"] = plan_match.group(1).strip()

    # Search for "## Personal Information" section (case-insensitive)
    personal_pattern = r'^## Personal Information\s*$\n(.*?)(?=^## |\Z)'
    personal_match = re.search(personal_pattern, text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if personal_match:
        result_data["personal_information"] = personal_match.group(1).strip()

    # Search for "## Answer" section (case-insensitive)
    answer_pattern = r'^## Answer\s*$\n(.*?)(?=^## |\Z)'
    answer_match = re.search(answer_pattern, text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if answer_match:
        result_data["answer"] = answer_match.group(1).strip()

    # If nothing matches, add everything to default under plan and log warning
    if not plan_match and not personal_match and not answer_match:
        result_data["plan"] = text.strip()
        logger.warning("=" * 80)
        logger.warning("WARNING: No markdown sections found in the input text for policies or instructions!")
        logger.warning("Adding entire text content to the 'plan' field by default.")
        logger.warning("This may not be the intended behavior. Please check the input format.")
        logger.warning(
            "Expected sections: ## Plan, ## Answer, ## Personal Information (for instructions or policies)."
        )
        logger.warning("=" * 80)

    # Log what instructions were loaded
    if plan_match or personal_match or answer_match:
        logger.info("~" * 60)
        logger.info("📋 Instructions loaded:")

        if plan_match:
            logger.info(f"Plan: {result_data['plan']}")
        if personal_match:
            masked_instructions = "*" * min(len(result_data['personal_information']), 50)
            logger.info(
                f"Instructions: {masked_instructions} ({len(result_data['personal_information'])} chars)"
            )
        if answer_match:
            logger.info(f"Answer: {result_data['answer']}")

        logger.info("~" * 60)
    else:
        logger.info("~" * 60)
        logger.info("📋 Entire content loaded as plan (no structured sections found)")
        logger.info("~" * 60)

    return MarkdownSections(**result_data)
