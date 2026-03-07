INTERACTIVE_CONTROL_TYPE_NAMES=set([
    'ButtonControl',
    'ListItemControl',
    'MenuItemControl',
    'EditControl',
    'CheckBoxControl',
    'RadioButtonControl',
    'ComboBoxControl',
    'HyperlinkControl',
    'SplitButtonControl',
    'TabItemControl',
    'TreeItemControl',
    'DataItemControl',
    'HeaderItemControl',
    'TextBoxControl',
    'SpinnerControl',
    'ScrollBarControl'
])

INTERACTIVE_ROLES = {
    # Buttons
    'PushButton', 'SplitButton', 'ButtonDropDown', 'ButtonMenu', 
    'ButtonDropDownGrid', 'OutlineButton',
    
    # Links
    'Link',
    
    # Inputs & Selection
    'Text', 'IpAddress', 'HotkeyField', 'ComboBox', 'DropList',
    'CheckButton', 'RadioButton',
    
    # Menus & Tabs
    'MenuItem', 'ListItem', 'PageTab',
    
    # Trees
    'OutlineItem',
    
    # Values
    'Slider', 'SpinButton', 'Dial', 'ScrollBar', 'Grip',
    
    # Grids
    'ColumnHeader', 'RowHeader', 'Cell'
}

DOCUMENT_CONTROL_TYPE_NAMES=set([
    'DocumentControl'
])

STRUCTURAL_CONTROL_TYPE_NAMES = set([
    'PaneControl',
    'GroupControl',
    'CustomControl'
])

INFORMATIVE_CONTROL_TYPE_NAMES=set([
    'TextControl',
    'ImageControl',
    'StatusBarControl',
    # 'ProgressBarControl',
    # 'ToolTipControl',
    # 'TitleBarControl',
    # 'SeparatorControl',
    # 'HeaderControl',
    # 'HeaderItemControl',
])

DEFAULT_ACTIONS=set([
    'Click',
    'Press',
    'Jump',
    'Check',
    'Uncheck',
    'Double Click'
])

THREAD_MAX_RETRIES = 3

# Pre-computed unions for hot-path checks (avoid recomputing per call)
SCROLLABLE_EXCLUSION_TYPES = INTERACTIVE_CONTROL_TYPE_NAMES | INFORMATIVE_CONTROL_TYPE_NAMES
INTERACTIVE_AND_DOCUMENT_TYPES = INTERACTIVE_CONTROL_TYPE_NAMES | DOCUMENT_CONTROL_TYPE_NAMES
KEYBOARD_FOCUSABLE_TYPE_OVERRIDES = frozenset({'EditControl','ButtonControl','CheckBoxControl','RadioButtonControl','TabItemControl'})
OFFSCREEN_EXCEPTION_TYPES = frozenset({"GroupControl","EditControl","TitleBarControl"})
OFFSCREEN_EXCEPTION_CLASSES = frozenset({"Popup","Windows.UI.Core.CoreComponentInputSource","Shell_TrayWnd","Shell_SecondaryTrayWnd"})
BROWSER_SKIP_TYPES = frozenset({'DataItemControl','ListItemControl'})