import json

from langchain_core.messages import AIMessage

from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.llm.models import LLMManager
import os
import glob
from loguru import logger

llm_manager = LLMManager()
tracker = ActivityTracker()


def get_python_content_from_trajectory():
    files = {}
    indx = 1
    for step in tracker.steps:
        if step.name == "CodeAgent":
            content = json.loads(step.data)
            code = content['code']
            files[f"f{indx}.py"] = code
            indx += 1
    return files


def read_python_files(file_pattern="f*.py"):
    """Read all Python files matching the pattern (f1.py, f2.py, etc.)"""
    files_content = {}

    # Get all files matching the pattern
    file_paths = sorted(glob.glob(file_pattern))

    for file_path in file_paths:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                files_content[file_path] = file.read()
                logger.debug(f"Read {file_path}: {len(files_content[file_path])} characters")
        else:
            logger.warning(f"{file_path} not found")

    return files_content


async def consolidate_flow(chain, user_intent, file_pattern="f*.py", dynamic=True) -> AIMessage:
    """Main function to consolidate the Python flow files"""

    # Read all Python files
    logger.debug("Reading Python files from trajectory...")
    if dynamic:
        files_content = get_python_content_from_trajectory()
    else:
        files_content = read_python_files(file_pattern)

    if not files_content:
        logger.warning("No Python files found in flow trajectory (no CodeAgent steps)")
        return None

    # Create system prompt
    logger.debug(f"Creating system prompt with {len(files_content)} file(s)...")
    files_section = ""
    for file_path, content in files_content.items():
        files_section += f"\n## {file_path}\n```python\n{content}\n```\n"

    logger.debug("Generating consolidated function...")

    try:
        response = await chain.ainvoke(input={"files_section": files_section, "user_intent": user_intent})
        logger.debug(f"Generated response length: {len(response.content) if response else 0} chars")
        return response
    except Exception as e:
        logger.error(f"Error generating consolidation response: {e}")
        return None
