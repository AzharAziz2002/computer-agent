
# claude-haiku-4-5-20251001
# claude-sonnet-4-6
MODEL = "claude-sonnet-4-6"
TYPE = "computer_20251124"
WIDTH_PX=1024
HEIGHT_PX=576

ACTIONS = [
"mouse_move",
"left_click",
"right_click",
"double_click",
"scroll",
"type",
"key",
"cursor_position",
"wait",
"screenshot"
]






TOOL = [
    {
        "type": "computer_20251124",
        "name": "computer",
        "display_width_px": 1024,
        "display_height_px": 576,
        "display_number": 1,
    }
]
BETAS = [
    "computer-use-2025-11-24",
    "prompt-caching-2024-07-31",
]
THINKING = {
    "type": "enabled",
    "budget_tokens": 1024,
}
MAX_TOKENS = 19000
