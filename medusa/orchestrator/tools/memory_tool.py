from medusa.orchestrator.tools.memory_schema import Memory
from medusa.orchestrator.registry.views import ToolResult
from medusa.tool import Tool
from typing import Literal, Optional
from pathlib import Path

memory_path = Path.cwd() / '.memories'


@Tool('Memory', args_schema=Memory)
def memory(mode: Literal['view', 'read', 'write', 'delete', 'update'], path: Optional[str] = None,
           content: Optional[str] = None, operation: Optional[Literal['replace', 'insert']] = 'replace',
           old_str: Optional[str] = None, new_str: Optional[str] = None, line_number: Optional[int] = None,
           read_range: Optional[tuple[int, int]] = None, **kwargs) -> str:
    '''
    Persistent file-based storage system for managing information across different task stages.

    Use this tool to:
        - Store important findings and data as md files in the .memories directory
        - Maintain context across complex multi-step operations
        - Track progress of plans and accumulate knowledge during task execution
        - Cache information that may be referenced in future steps

    Modes:
        - write: Create a new memory file (returns assigned path)
        - view: List all directories and memory files in the .memories directory
        - read: Retrieve contents of a specific memory file by path
            * read_range: Optional (start, end) tuple to read specific line range (0-indexed, end exclusive)
        - update: Modify contents of an existing memory file by path
            Operations:
            * replace: Replace old_str with new_str (requires old_str and new_str)
            * insert: Insert content at line_number (requires line_number and content)
        - delete: Remove a memory file by path

    All data is persisted as files in the .memories directory, ensuring information
    survives across sessions and can be shared between different task stages.

    Essential for tasks requiring information persistence and cross-stage data sharing.
    '''
    match mode:
        case 'view':
            files = (Path(path) if path else memory_path).rglob('*.md')
            result = '\n'.join([f'{i+1}. {file.relative_to(memory_path.parent).as_posix()}'
                               for i, file in enumerate(files)])
            return result if result else "No memory files found."

        case 'write':
            file_path = memory_path / path if not Path(path).is_absolute() else Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding='utf-8')
            return f'{file_path.name} created in {file_path.parent.relative_to(memory_path.parent).as_posix()}.'

        case 'read':
            file_path = memory_path / path if not Path(path).is_absolute() else Path(path)
            if not file_path.exists():
                return ToolResult(is_success=False, error=f'{file_path.name} not found.')

            file_content = file_path.read_text(encoding='utf-8')

            if read_range:
                start, end = read_range
                lines = file_content.splitlines()

                if start < 0 or start >= len(lines):
                    return ToolResult(is_success=False, error=f'start line {start} out of range (0-{len(lines)-1}).')
                if end < start or end > len(lines):
                    return ToolResult(is_success=False, error=f'end line {end} out of range ({start}-{len(lines)}).')

                selected_lines = lines[start:end]
                return f"File: {file_path.relative_to(memory_path.parent).as_posix()}\nLines {start}-{end-1}:\n" + '\n'.join(selected_lines)

            return f"File: {file_path.relative_to(memory_path.parent).as_posix()}\nContent:\n{file_content}"

        case 'update':
            file_path = memory_path / path if not Path(path).is_absolute() else Path(path)
            if not file_path.exists():
                return ToolResult(is_success=False, error=f'{file_path.name} not found. Use "write" mode to create a new file.')

            current_content = file_path.read_text(encoding='utf-8')

            match operation:
                case 'replace':
                    if not old_str or not new_str:
                        return ToolResult(is_success=False, error='both old_str and new_str are required for replace operation.')
                    if old_str not in current_content:
                        return ToolResult(is_success=False, error=f'"{old_str}" not found in file.')

                    new_content = current_content.replace(old_str, new_str)
                    file_path.write_text(new_content, encoding='utf-8')
                    return f'{file_path.name} updated: replaced "{old_str[:50]}..." with "{new_str[:50]}...".'

                case 'insert':
                    if line_number is None:
                        return ToolResult(is_success=False, error='line_number is required for insert operation.')
                    if not content:
                        return ToolResult(is_success=False, error='content is required for insert operation.')

                    lines = current_content.splitlines(keepends=True)
                    if line_number < 0 or line_number > len(lines):
                        return ToolResult(is_success=False, error=f'line_number {line_number} out of range (0-{len(lines)}).')

                    lines.insert(line_number, content + '\n' if not content.endswith('\n') else content)
                    new_content = ''.join(lines)
                    file_path.write_text(new_content, encoding='utf-8')
                    return f'{file_path.name} updated: inserted content at line {line_number}.'

                case _:
                    return ToolResult(is_success=False, error=f'Unknown operation "{operation}".')

        case 'delete':
            file_path = memory_path / path if not Path(path).is_absolute() else Path(path)
            if not file_path.exists():
                return ToolResult(is_success=False, error=f'{file_path.name} not found.')

            file_path.unlink()
            return f'{file_path.name} deleted from {file_path.parent.relative_to(memory_path.parent).as_posix()}.'

    return ToolResult(is_success=False, error="Invalid mode. Use 'view', 'write', 'read', 'update', or 'delete'.")
