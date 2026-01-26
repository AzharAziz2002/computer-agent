
# claude-haiku-4-5-20251001
# claude-sonnet-4-5-20250929
MODEL = "claude-haiku-4-5-20251001"
TYPE = "computer_20250124"
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





TOOLS = {    
    "type": TYPE,
    "name": "computer",
    "description": (
        "Low-level computer interaction interface. Use to inspect the screen, "
        "move/press the mouse, type keys, scroll, take screenshots, and wait. "
        "Arguments depend on the requested action; 'action' is required."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ACTIONS,
                "description": "The action to perform. Must be one of the supported actions."
            },
            "coordinate": {
                "type": "array",
                "items": [{"type": "integer"}, {"type": "integer"}],
                "minItems": 2,
                "maxItems": 2,
                "description": "Optional [x, y] coordinates in the model's downscaled coordinate space (width=1024)."
            },
            "text": {
                "type": "string",
                "description": "Text used by `type` action or the `key` action (key name)."
            },
            "scroll_direction": {
                "type": "string",
                "enum": ["up", "down", "left", "right"],
                "description": "Direction to scroll (required for `scroll`)."
            },
            "scroll_amount": {
                "type": "integer",
                "minimum": 1,
                "description": "How many scroll 'steps' to perform (required for `scroll`)."
            },
            "duration": {
                "type": "number",
                "minimum": 0,
                "description": "Seconds to wait (for `wait`), or duration for long hold/drag actions."
            },
            "key": {
                "type": "string",
                "description": "Modifier key name for actions that accept a modifier (not used by default in your current tool)."
            }
        },
        "required": ["action"],
        "additionalProperties": False
    },    
    "examples": [
        {"action": "screenshot"},
        {"action": "left_click"},
        {"action": "left_click", "coordinate": [500, 300]},
        {"action": "mouse_move", "coordinate": [600, 400]},
        {"action": "type", "text": "Hello, world!"},
        {"action": "scroll", "coordinate": [512, 350], "scroll_direction": "down", "scroll_amount": 3},
        {"action": "wait", "duration": 3},
        {"action": "cursor_position"}
    ],
    
    "display_width_px": 1024,
    "display_height_px": 576,
    "display_number": 1
}
TOOL = [
    {
        "type": "computer_20250124",
        "name": "computer",
        "display_width_px": 1024,
        "display_height_px": 576,
        "display_number": 1,
    }
]
BETAS = [
    "computer-use-2025-01-24",
    "prompt-caching-2024-07-31",
]
THINKING = {
    "type": "enabled",
    "budget_tokens": 1024,
}
MAX_TOKENS = 19000
