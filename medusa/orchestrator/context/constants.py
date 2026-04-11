# ── Block removal ──
BLOCK_REMOVE = True       # drop old turns when count exceeds BLOCK_LIMIT
BLOCK_LIMIT = 3           # max turns to keep (when BLOCK_REMOVE=True)

# ── Screenshot removal ──
SCREENSHOT_REMOVE = True  # drop screenshots older than SCREENSHOT_LIMIT turns
SCREENSHOT_LIMIT = 2      # how many turns back to keep screenshots

# ── Prompt caching (Anthropic) ──
USER_QUERY_CACHE = True  # cache the first user query with ephemeral breakpoint
SCREENSHOT_CACHE = False   # cache screenshots with ephemeral breakpoints

# ── Cache budget ──
MAX_CACHE_BREAKPOINTS = 4
RESERVED_CACHE_BREAKPOINTS = 1   # system_prompt(1) + tools_schema(1)
SCREENSHOT_CACHE_SLOTS = MAX_CACHE_BREAKPOINTS - RESERVED_CACHE_BREAKPOINTS  # = 2
