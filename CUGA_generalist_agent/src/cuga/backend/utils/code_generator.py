import sys
from pathlib import Path
from cuga.config import settings


def indent_code(code, num_tabs=2):
    """
    Add indentation to code lines.

    Args:
        code (str): The code to indent
        num_tabs (int): Number of tabs to add (default: 2)

    Returns:
        str: Indented code
    """
    spaces_per_tab = 4
    indent = ' ' * (num_tabs * spaces_per_tab)

    return '\n'.join(indent + line if line.strip() else line for line in code.split('\n'))


def process_python_file(file_path, task_id):
    """
    Process a Python file by injecting it into the AppWorld template.

    Args:
        file_path (str): Path to the Python file to process
        task_id (str): The task identifier
    """
    file_path = Path(file_path)

    # Check if file exists
    if not file_path.exists():
        print(f"Error: File {file_path} not found")
        return

    # Read the original file
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            original_code = f.read()
    except Exception as e:
        print(f"Error: Failed to read {file_path}: {e}")
        return

    # Validate that the file contains 'with AppWorld'
    if 'with AppWorld' in original_code:
        print(f"Error: File {file_path}   contain 'with AppWorld'")
        return

    print(f"Validation passed: Found 'with AppWorld' in {file_path}")

    # Indent the original code
    indented_code = indent_code(original_code, num_tabs=2)

    # Create the new file content with the template
    file_content = f'''from appworld import AppWorld, load_task_ids
from loguru import logger
from cuga.config import settings


def main(task_id):
    with AppWorld(
        task_id=task_id,
        experiment_name="test",
        remote_environment_url=f"http://localhost:{settings.server_ports.environment_url}",
        remote_apis_url=f"http://localhost:{settings.server_ports.apis_url}",
    ) as world:
        logger.info(f"Running task: {{task_id}}")

{indented_code.replace("host.docker.internal", "localhost")}



if __name__ == '__main__':
    main("{task_id}")
'''

    # Write back to the same file
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(file_content)
        print(f"Successfully updated: {file_path}")
    except Exception as e:
        print(f"Error: Failed to write to {file_path}: {e}")


def main():
    """Main function to handle command line arguments."""
    if len(sys.argv) != 3:
        print("Usage: python script.py <path_to_python_file> <task_id>")
        sys.exit(1)

    file_path = sys.argv[1]
    task_id = sys.argv[2]
    process_python_file(file_path, task_id)


if __name__ == "__main__":
    main()
