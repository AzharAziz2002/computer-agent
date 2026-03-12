"""Search command validation and failure tracking middleware."""

import re


class SearchValidator:
    """Intercepts shell commands to enforce search best practices."""

    # Commands that should be rewritten — each entry is (pattern, block_message)
    REWRITE_RULES: list[tuple[re.Pattern, str]] = [
        (
            re.compile(r'\b(Get-ChildItem|gci)\b.*-Recurse', re.IGNORECASE),
            '[BLOCKED] Do not use Get-ChildItem -Recurse for searching — it is extremely slow on large drives. '
            'Use fd instead. Example: fd <keyword> -e <ext> D:\\'
        ),
        (
            re.compile(r'\b(Get-ChildItem|gci)\b.*(-Include|-Filter)\s+["\']?\*\.', re.IGNORECASE),
            '[BLOCKED] Do not use Get-ChildItem with wildcard filters for searching. '
            'Use fd instead. Example: fd <keyword> -e <ext> D:\\'
        ),
        (
            re.compile(r'\b(where|where\.exe)\b.*\*\.', re.IGNORECASE),
            '[BLOCKED] Do not use where/where.exe for file searching. '
            'Use fd instead. Example: fd <keyword> -e <ext> D:\\'
        ),
    ]

    def __init__(self):
        self._consecutive_failures: int = 0
        self._max_failures: int = 2

    def validate(self, command: str) -> tuple[bool, str]:
        """Check command against rewrite rules and extension-only guard.

        Returns (ok, message). If ok is False, message explains why the
        command was blocked and suggests a corrected form.
        """
        for pattern, message in self.REWRITE_RULES:
            if pattern.search(command):
                return False, message

        if self._is_extension_only(command):
            return False, (
                '[BLOCKED] Extension-only file search is not allowed. '
                'You must include a filename keyword in the search. '
                'If you do not know the filename, stop and ask the user: '
                '"What is the name of the file you are looking for?" '
                'Do not guess or search by extension alone. '
                'Example when filename is known: fd batman -e mp4 D:\\'
            )

        return True, ''

    def track_result(self, command: str, response: str, status: int = 0) -> str | None:
        """Track consecutive empty/failed search results. Returns a stop message after threshold."""
        if not self._is_search_command(command):
            return None

        if self._is_empty_result(response, status):
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_failures:
                count = self._consecutive_failures
                self._consecutive_failures = 0
                return (
                    f'[SEARCH LIMIT] {count} consecutive searches returned no results. '
                    'STOP searching and ask the user to confirm the filename or narrow the search scope. '
                    'Respond in text only — do not call another tool.'
                )
        else:
            self._consecutive_failures = 0

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_search_command(command: str) -> bool:
        """Detect whether the command is a file-search operation."""
        return bool(re.search(
            r'\b(fd|rg|Get-ChildItem|gci|where|where\.exe)\b', command, re.IGNORECASE
        ))

    @staticmethod
    def _is_empty_result(response: str, status: int = 0) -> bool:
        """Detect empty, no-match, or error search output."""
        # Non-zero exit code means the command errored
        if status != 0:
            return True

        if not response or not response.strip():
            return True

        lines = [l.strip() for l in response.strip().splitlines() if l.strip()]
        if not lines:
            return True

        text = '\n'.join(lines)
        NO_RESULT_PATTERNS = [
            r'No matches',
            r'Cannot find (path|item)',
            r'does not exist',
            r'Access (is )?denied',
            r'not recognized as (the name of a cmdlet|an internal)',
            r'\b0 files? found\b',
            r'\b0 directories? found\b',
        ]
        for pattern in NO_RESULT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True

        return False

    @staticmethod
    def _is_extension_only(command: str) -> bool:
        """Block fd/GCI searches that filter by extension only with no filename keyword."""
        # fd: strip known flags/paths — if nothing remains, no keyword was given
        if re.search(r'\bfd\b', command, re.IGNORECASE):
            rest = re.sub(r'\bfd\b', '', command, flags=re.IGNORECASE)
            rest = re.sub(r'(-e|--extension)\s+\S+', '', rest)
            rest = re.sub(r'(--type|-t)\s+\S+', '', rest)
            rest = re.sub(r'-[a-zA-Z]\b', '', rest)
            rest = re.sub(r'["\'][A-Za-z]:\\[^"\']*["\']', '', rest)  # quoted Windows paths
            rest = re.sub(r'[A-Za-z]:\\?\S*', '', rest)               # unquoted Windows paths
            rest = re.sub(r'[./~]\S*', '', rest)                      # relative paths / bare dot
            rest = re.sub(r'2>\s*\S+', '', rest)                      # redirects
            rest = re.sub(r'["\']', '', rest)                         # leftover quotes
            return not rest.strip()

        # Get-ChildItem: -Include or -Filter with only *.ext patterns, no filename keyword
        if re.search(r'\b(Get-ChildItem|gci)\b', command, re.IGNORECASE):
            m = re.search(r'(?:-Include|-Filter)\s+(["\']?.+?)(?=\s+-|\s*$)', command, re.IGNORECASE)
            if m:
                val = m.group(1).replace('"', '').replace("'", '')
                parts = [p.strip() for p in val.split(',')]
                if all(re.fullmatch(r'\*\.[a-zA-Z0-9]+', p) for p in parts if p):
                    return True

        return False
