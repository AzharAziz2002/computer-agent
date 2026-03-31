"""Parse Playwright aria_snapshot YAML and build element ref index.

Two formats are supported:
  - 'role'  (default): parses ariaSnapshot() YAML, assigns [ref=eN] in output,
             resolves via get_by_role().
  - 'ai'   : parses _snapshotForAI() output which already contains [ref=eN] ids;
             resolves via aria-ref=eN Playwright selector.
"""

import re
from urllib.parse import urlparse
from medusa.orchestrator.browser.state import ElementRef

# ── URL filtering ─────────────────────────────────────────────────────

MAX_URL_LENGTH = 150      # truncate regular URLs longer than this
AD_URL_LENGTH = 60        # stricter limit for ad/tracking URLs

# Ad / tracking domains — truncated aggressively (domain + short path)
AD_DOMAINS = {
    'googleadservices.com', 'doubleclick.net', 'googlesyndication.com',
    'adservice.google.com', 'pagead2.googlesyndication.com',
}

# Pattern: '  - /url: <url>'
_URL_LINE_RE = re.compile(r'^(\s*-\s*/url:\s*)(.+)$')


def _filter_url_line(line: str) -> str | None:
    """Truncate /url: text-node lines. Ad URLs get a stricter limit."""
    m = _URL_LINE_RE.match(line)
    if not m:
        return line
    prefix, url = m.group(1), m.group(2).strip()

    # Pick truncation limit — stricter for ad/tracking domains
    limit = MAX_URL_LENGTH
    try:
        host = urlparse(url).hostname or ''
        if any(host == ad or host.endswith('.' + ad) for ad in AD_DOMAINS):
            limit = AD_URL_LENGTH
    except Exception:
        pass

    if len(url) > limit:
        url = url[:limit] + '...'
    return f'{prefix}{url}'


# Roles that get [ref=] and can be interacted with (click, type, etc.)
INTERACTIVE_ROLES = {
    'link', 'button', 'textbox', 'checkbox', 'radio', 'combobox', 'listbox',
    'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option',
    'tab', 'switch', 'slider', 'spinbutton', 'searchbox',
    'treeitem',
}

# Roles that get [ref=] only when they have a name (headings, cells — useful landmarks)
CONTENT_ROLES = {
    'heading', 'cell', 'gridcell', 'columnheader', 'rowheader',
    'listitem', 'article', 'region', 'main', 'navigation',
}

# Structural / container roles — pass through as context, no ref
STRUCTURAL_ROLES = {
    'generic', 'group', 'list', 'table', 'row', 'rowgroup',
    'grid', 'treegrid', 'menu', 'menubar', 'toolbar',
    'tablist', 'tree', 'directory', 'document', 'application',
    'presentation', 'none',
}

# Pattern: '  - role "name" rest'
ARIA_LINE_PATTERN = re.compile(r'^(\s*-\s*)(\w+)(?:\s+"([^"]*)")?(.*)$')

# Pattern to extract [ref=eN] from AI snapshot lines
AI_REF_PATTERN = re.compile(r'\[ref=(e\d+)\]', re.IGNORECASE)


# ── Helpers ──────────────────────────────────────────────────────────

def _get_indent_level(line: str) -> int:
    """Return the indent depth of a line (2 spaces = 1 level)."""
    stripped = line.lstrip()
    return (len(line) - len(stripped)) // 2


def _match_snapshot_line(
    line: str,
    max_depth: int | None = None,
) -> dict | None:
    """Parse a single snapshot line into structured parts.

    Returns {prefix, role_raw, role, name, suffix} or None if line
    doesn't match, exceeds max_depth, or is a closing tag.
    """
    if max_depth is not None and _get_indent_level(line) > max_depth:
        return None
    m = ARIA_LINE_PATTERN.match(line)
    if not m:
        return None
    prefix, role_raw, name, suffix = m.groups()
    if role_raw.startswith('/'):
        return None
    return {
        'prefix': prefix,
        'role_raw': role_raw,
        'role': role_raw.lower(),
        'name': name,
        'suffix': suffix or '',
    }


def _compact_tree(text: str) -> str:
    """Remove empty structural branches while keeping containers that have
    interactive descendants ([ref=] lines deeper in the tree).

    A line is kept if:
      1. It contains [ref=  (it's an annotated element), or
      2. It contains ':' and doesn't end with ':'  (inline content), or
      3. At least one descendant (deeper indent) contains [ref=.
    """
    lines = text.split('\n')
    result = []

    for i, line in enumerate(lines):
        # Rule 1: has a ref annotation
        if '[ref=' in line:
            result.append(line)
            continue

        # Rule 2: has inline content (e.g. `  - heading "Title": some text`)
        if ':' in line and not line.rstrip().endswith(':'):
            result.append(line)
            continue

        # Rule 3: has relevant children
        current_indent = _get_indent_level(line)
        has_relevant_children = False
        for j in range(i + 1, len(lines)):
            child_indent = _get_indent_level(lines[j])
            if child_indent <= current_indent:
                break
            if '[ref=' in lines[j]:
                has_relevant_children = True
                break

        if has_relevant_children:
            result.append(line)

    return '\n'.join(result)


# ── Role Name Tracker ────────────────────────────────────────────────

class _RoleNameTracker:
    """Tracks role+name occurrences for nth disambiguation."""

    def __init__(self):
        self._counts: dict[str, int] = {}
        self._refs_by_key: dict[str, list[str]] = {}

    def _key(self, role: str, name: str | None) -> str:
        return f'{role}:{name or ""}'

    def get_next_index(self, role: str, name: str | None) -> int:
        key = self._key(role, name)
        current = self._counts.get(key, 0)
        self._counts[key] = current + 1
        return current

    def track_ref(self, role: str, name: str | None, ref_id: str):
        key = self._key(role, name)
        self._refs_by_key.setdefault(key, []).append(ref_id)

    def get_duplicate_keys(self) -> set[str]:
        return {key for key, refs in self._refs_by_key.items() if len(refs) > 1}


def _remove_nth_from_non_duplicates(
    ref_map: dict[str, ElementRef],
    tracker: _RoleNameTracker,
):
    """Clear nth on refs whose role+name is unique (not duplicated)."""
    duplicates = tracker.get_duplicate_keys()
    for elem in ref_map.values():
        key = tracker._key(elem.role, elem.name)
        if key not in duplicates:
            elem.nth = 0


# ── SnapshotParser (role format — ariaSnapshot YAML) ─────────────────

class SnapshotParser:
    """Parses ariaSnapshot() YAML, assigns [ref=eN] to interactive/content elements.

    Output format:  '  - button "Submit" [ref=e1]'
    Resolution:     get_by_role(role, name=name, exact=True).nth(nth)
    """

    def __init__(self):
        self._ref_map: dict[str, ElementRef] = {}

    def parse(
        self,
        snapshot_yaml: str,
        options: dict | None = None,
    ) -> tuple[str, dict[str, ElementRef]]:
        """Parse snapshot YAML → (formatted_output, ref_map).

        Options:
            interactive: only include interactive elements (flat list, no indent)
            compact: remove empty structural branches (preserves context containers)
            depth: max indent depth to include
        """
        opts = options or {}
        interactive = bool(opts.get('interactive'))
        compact = bool(opts.get('compact'))
        max_depth: int | None = opts.get('depth')

        self._ref_map = {}
        tracker = _RoleNameTracker()
        counter = 0

        def next_ref() -> str:
            nonlocal counter
            counter += 1
            return f'e{counter}'

        lines = snapshot_yaml.strip().splitlines()

        if interactive:
            # Interactive mode: flat list of only interactive elements (no indentation)
            result = []
            for line in lines:
                parsed = _match_snapshot_line(line, max_depth)
                if not parsed:
                    continue
                role = parsed['role']
                name = parsed['name']
                suffix = parsed['suffix']
                if role not in INTERACTIVE_ROLES:
                    continue

                ref_id = next_ref()
                nth = tracker.get_next_index(role, name)
                tracker.track_ref(role, name, ref_id)
                self._ref_map[ref_id] = ElementRef(
                    ref_id=ref_id, role=role, name=name or '', nth=nth,
                )

                enhanced = f'- {parsed["role_raw"]}'
                if name:
                    enhanced += f' "{name}"'
                enhanced += f' [ref={ref_id}]'
                if nth > 0:
                    enhanced += f' [nth={nth}]'
                # Keep brackets from suffix (e.g. [checked], [disabled])
                if '[' in suffix:
                    enhanced += suffix

                result.append(enhanced)

            _remove_nth_from_non_duplicates(self._ref_map, tracker)
            text = '\n'.join(result) or '(no interactive elements)'
            return text, self._ref_map

        # Full mode: process every line, assign refs to interactive/content roles
        result = []
        for line in lines:
            parsed = _match_snapshot_line(line, max_depth)
            if not parsed:
                # Non-matching lines (text nodes, /url: lines, etc.) — depth-check, filter, pass through
                if max_depth is not None and _get_indent_level(line) > max_depth:
                    continue
                filtered = _filter_url_line(line)
                if filtered is not None:
                    result.append(filtered)
                continue

            role = parsed['role']
            name = parsed['name']
            prefix = parsed['prefix']
            role_raw = parsed['role_raw']
            suffix = parsed['suffix']

            is_interactive = role in INTERACTIVE_ROLES
            is_content = role in CONTENT_ROLES
            is_structural = role in STRUCTURAL_ROLES

            # Compact: skip unnamed structural elements (compactTree handles branch pruning later)
            if compact and is_structural and not name:
                continue

            should_have_ref = is_interactive or (is_content and name)
            if not should_have_ref:
                result.append(line)
                continue

            ref_id = next_ref()
            nth = tracker.get_next_index(role, name)
            tracker.track_ref(role, name, ref_id)
            self._ref_map[ref_id] = ElementRef(
                ref_id=ref_id, role=role, name=name or '', nth=nth,
            )

            enhanced = f'{prefix}{role_raw}'
            if name:
                enhanced += f' "{name}"'
            enhanced += f' [ref={ref_id}]'
            if nth > 0:
                enhanced += f' [nth={nth}]'
            if suffix:
                enhanced += suffix

            result.append(enhanced)

        _remove_nth_from_non_duplicates(self._ref_map, tracker)
        text = '\n'.join(result) or '(empty)'
        if compact:
            text = _compact_tree(text)
        return text, self._ref_map

    def resolve_ref(self, page, ref_id: str):
        """Resolve ref_id → Playwright Locator via get_by_role."""
        if ref_id not in self._ref_map:
            available = ', '.join(sorted(self._ref_map.keys(), key=lambda r: int(r[1:])))
            raise ValueError(
                f'Ref "{ref_id}" not found. Take a new snapshot to refresh element refs. '
                f'Available refs: {available or "none"}'
            )
        elem = self._ref_map[ref_id]
        locator = page.get_by_role(elem.role, name=elem.name, exact=True)
        if elem.nth > 0:
            locator = locator.nth(elem.nth)
        return locator


# ── AiSnapshotParser (_snapshotForAI format) ─────────────────────────

class AiSnapshotParser:
    """Handles Playwright _snapshotForAI() output.

    The AI snapshot already contains Playwright's own [ref=eN] aria-ref ids.
    We preserve these directly instead of generating new ones — this makes
    refs stable across re-renders and avoids parser confusion.
    Resolution uses  page.locator('aria-ref=eN')  — no role lookup needed.
    """

    def __init__(self):
        self._ref_map: dict[str, ElementRef] = {}

    def parse(
        self,
        ai_text: str,
        options: dict | None = None,
    ) -> tuple[str, dict[str, ElementRef]]:
        """Parse AI snapshot text, preserving Playwright's own ref ids.

        Returns (formatted_output, ref_map) where ref_map contains
        ElementRef entries for every element with [ref=eN] in the output.
        """
        opts = options or {}
        interactive = bool(opts.get('interactive'))
        compact = bool(opts.get('compact'))
        max_depth: int | None = opts.get('depth')

        self._ref_map = {}
        lines = str(ai_text or '').splitlines()

        if interactive:
            # Interactive mode: flat list, only interactive roles with refs
            result = []
            for line in lines:
                parsed = _match_snapshot_line(line, max_depth)
                if not parsed:
                    continue
                role = parsed['role']
                name = parsed['name']
                suffix = parsed['suffix']
                if role not in INTERACTIVE_ROLES:
                    continue

                ref_match = AI_REF_PATTERN.search(suffix)
                if not ref_match:
                    continue
                ref_id = ref_match.group(1)
                self._ref_map[ref_id] = ElementRef(
                    ref_id=ref_id, role=role, name=name or '',
                )

                enhanced = f'- {parsed["role_raw"]}'
                if name:
                    enhanced += f' "{name}"'
                enhanced += suffix
                result.append(enhanced)

            text = '\n'.join(result) or '(no interactive elements)'
            return text, self._ref_map

        # Full mode: keep all lines, extract refs from matched elements
        result = []
        for line in lines:
            if max_depth is not None and _get_indent_level(line) > max_depth:
                continue

            parsed = _match_snapshot_line(line)  # depth already checked above
            if not parsed:
                filtered = _filter_url_line(line)
                if filtered is not None:
                    result.append(filtered)
                continue

            role = parsed['role']
            name = parsed['name']
            suffix = parsed['suffix']
            is_structural = role in STRUCTURAL_ROLES

            if compact and is_structural and not name:
                continue

            # Extract existing ref from suffix
            ref_match = AI_REF_PATTERN.search(suffix)
            if ref_match:
                ref_id = ref_match.group(1)
                self._ref_map[ref_id] = ElementRef(
                    ref_id=ref_id, role=role, name=name or '',
                )

            result.append(line)

        text = '\n'.join(result) or '(empty)'
        if compact:
            text = _compact_tree(text)
        return text, self._ref_map

    def resolve_ref(self, page, ref_id: str):
        """Resolve ref_id → Playwright Locator via aria-ref selector."""
        if ref_id not in self._ref_map:
            available = ', '.join(sorted(self._ref_map.keys(), key=lambda r: int(r[1:])))
            raise ValueError(
                f'Ref "{ref_id}" not found in last AI snapshot. Take a new snapshot first. '
                f'Available refs: {available or "none"}'
            )
        return page.locator(f'aria-ref={ref_id}')
