"""Parse Playwright aria_snapshot YAML and build element ref index."""

import re
from medusa.orchestrator.browser.state import ElementRef


# Roles that get refs — actionable via click, type, etc.
INTERACTIVE_ROLES = {
    'link', 'button', 'textbox', 'checkbox', 'radio', 'combobox',
    'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option',
    'tab', 'switch', 'slider', 'spinbutton', 'searchbox',
    'treeitem', 'listitem',
}

# Pattern: '- role "name"' or '- role "name" [attr=val]' or '- role "name":'
ARIA_LINE_PATTERN = re.compile(
    r'^(\s*)- (\w+)(?:\s+"([^"]*)")?(.*)$'
)


class SnapshotParser:
    """Parses aria_snapshot YAML output and assigns refs to interactive elements."""

    def __init__(self):
        self._ref_counter: int = 0
        self._ref_map: dict[str, ElementRef] = {}

    def parse(self, snapshot_yaml: str) -> tuple[str, dict[str, ElementRef]]:
        """Parse snapshot YAML, return (formatted_output, ref_map).

        formatted_output: human-readable string with [eN] refs on interactive elements.
        ref_map: dict mapping ref_id -> ElementRef for resolution.
        """
        self._ref_counter = 0
        self._ref_map = {}

        lines = snapshot_yaml.strip().splitlines()

        # First pass: count (role, name) occurrences to detect duplicates
        role_count: dict[tuple[str, str], int] = {}
        for line in lines:
            match = ARIA_LINE_PATTERN.match(line)
            if match:
                _, role, name, _ = match.groups()
                key = (role, name or '')
                role_count[key] = role_count.get(key, 0) + 1

        # Second pass: assign refs and build output
        role_seen: dict[tuple[str, str], int] = {}
        output_lines = []

        for line in lines:
            match = ARIA_LINE_PATTERN.match(line)
            if not match:
                # Non-element lines (text content, etc.) pass through
                output_lines.append(line)
                continue

            indent, role, name, rest = match.groups()
            name = name or ''
            rest = rest.strip()
            # Remove trailing colon (container marker in YAML)
            display_rest = f' {rest}' if rest and rest != ':' else ''

            if role in INTERACTIVE_ROLES:
                key = (role, name)
                nth = role_seen.get(key, 0)
                role_seen[key] = nth + 1

                ref_id = f'e{self._ref_counter}'
                self._ref_counter += 1

                total = role_count.get(key, 1)
                self._ref_map[ref_id] = ElementRef(
                    ref_id=ref_id,
                    role=role,
                    name=name,
                    nth=nth if total > 1 else 0,
                )

                display_name = f' "{name}"' if name else ''
                output_lines.append(f'{indent}[{ref_id}] {role}{display_name}{display_rest}')
            else:
                display_name = f' "{name}"' if name else ''
                output_lines.append(f'{indent}{role}{display_name}{display_rest}')

        return '\n'.join(output_lines), self._ref_map

    def resolve_ref(self, page, ref_id: str):
        """Resolve a ref_id back to a Playwright Locator.

        Uses page.get_by_role(role, name=name, exact=True).nth(nth).
        """
        if ref_id not in self._ref_map:
            available = ', '.join(sorted(self._ref_map.keys(), key=lambda r: int(r[1:])))
            raise ValueError(
                f'Ref "{ref_id}" not found. Take a new snapshot to refresh element refs. '
                f'Available refs: {available}'
            )

        elem = self._ref_map[ref_id]
        locator = page.get_by_role(elem.role, name=elem.name, exact=True)
        if elem.nth > 0:
            locator = locator.nth(elem.nth)
        return locator
