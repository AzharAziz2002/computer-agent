from pydantic import Field
from typing import Any, Literal, Optional
from medusa.orchestrator.tools.base import SharedBaseModel


class ExcelAction(SharedBaseModel):
    """Unified schema for all Excel operations via xlwings COM automation."""

    action: Literal[
        'file', 'sheet', 'range', 'table', 'chart', 'pivot',
        'calc', 'named_range', 'cond_format', 'screenshot',
    ] = Field(
        ...,
        description=(
            "file: workbook lifecycle (open, save, close, connect) | "
            "sheet: worksheet management | "
            "range: read/write/format cells | "
            "table: Excel table (ListObject) operations | "
            "chart: chart CRUD and styling | "
            "pivot: PivotTable creation and field management | "
            "calc: calculation mode control | "
            "named_range: named range CRUD | "
            "cond_format: conditional formatting rules | "
            "screenshot: capture sheet/range as PNG"
        )
    )

    operation: Optional[Literal[
        # file
        'list_workbooks', 'connect', 'test', 'open', 'create', 'save', 'close', 'quit',
        # sheet
        'list', 'rename', 'delete', 'copy', 'move', 'visibility', 'tab_color',
        # range (list/create/read shared with above)
        'read', 'write', 'read_formulas', 'clear', 'format', 'merge', 'unmerge',
        'autofit', 'sort', 'find', 'replace', 'insert_rows', 'delete_rows',
        'insert_columns', 'delete_columns', 'used', 'set_hyperlink', 'set_validation',
        # table
        'get_data', 'add_row', 'add_column', 'resize', 'toggle_totals',
        'set_column_total', 'filter', 'clear_filters', 'set_style',
        # chart
        'create_from_table', 'set_title', 'set_type', 'set_source',
        'set_legend', 'set_axis_title',
        # pivot
        'create_from_range', 'add_field', 'remove_field', 'list_fields',
        'refresh', 'set_layout', 'set_subtotals', 'set_grand_totals',
        'sort_field', 'filter_field', 'set_field_number_format',
        # calc
        'get_mode', 'set_mode', 'calculate',
        # named_range
        'update',
        # cond_format
        'add_rule',
    ]] = Field(
        None,
        description=(
            "Sub-operation within the action category.\n"
            "file: list_workbooks | connect | test | open | create | save | close | quit\n"
            "sheet: list | create | rename | delete | copy | move | visibility | tab_color\n"
            "range: read | write | read_formulas | clear | format | merge | unmerge | autofit | sort | find | replace | insert_rows | delete_rows | insert_columns | delete_columns | used | set_hyperlink | set_validation\n"
            "table: list | create | read | get_data | add_row | add_column | rename | delete | resize | toggle_totals | set_column_total | sort | filter | clear_filters | set_style\n"
            "chart: list | create | create_from_table | set_title | set_type | set_source | move | delete | set_legend | set_axis_title\n"
            "pivot: list | create_from_range | create_from_table | add_field | remove_field | list_fields | refresh | set_layout | set_subtotals | set_grand_totals | sort_field | filter_field | delete | set_field_number_format\n"
            "calc: get_mode | set_mode | calculate\n"
            "named_range: list | create | delete | update\n"
            "cond_format: add_rule | clear\n"
            "screenshot: (no operation needed)"
        )
    )

    # ── File / Session ──────────────────────────────────────────────────────
    file_path: Optional[str] = Field(
        None, description="[file: open, create, save, test] Absolute path to the workbook file."
    )
    name_or_path: Optional[str] = Field(
        None, description="[file: connect] Workbook name (e.g. 'report.xlsx') or full path of an already-open workbook."
    )
    save_on_close: Optional[bool] = Field(
        None, description="[file: close] Whether to save before closing. Default True."
    )

    # ── Sheets ──────────────────────────────────────────────────────────────
    name: Optional[str] = Field(
        None, description="[sheet: create, rename, delete, copy, move, visibility, tab_color] Sheet name to act on."
    )
    old_name: Optional[str] = Field(
        None, description="[sheet: rename] Current sheet name."
    )
    new_name: Optional[str] = Field(
        None, description="[sheet: rename | table: rename] New name."
    )
    source: Optional[str] = Field(
        None, description="[sheet: copy] Source sheet name to copy."
    )
    before: Optional[str] = Field(
        None, description="[sheet: create, move] Insert/move before this sheet."
    )
    after: Optional[str] = Field(
        None, description="[sheet: create, move] Insert/move after this sheet."
    )
    visible: Optional[bool] = Field(
        None, description="[sheet: visibility] True=show, False=hide. Omit to query."
    )
    very_hidden: Optional[bool] = Field(
        None, description="[sheet: visibility] True=very hidden (UI-inaccessible). Only when visible=False."
    )
    color: Optional[list[int]] = Field(
        None, description="[sheet: tab_color] RGB [R, G, B] e.g. [255, 0, 0]. Omit to query."
    )

    # ── Ranges ──────────────────────────────────────────────────────────────
    sheet_name: Optional[str] = Field(
        None, description="[range, chart, cond_format, screenshot] Sheet name."
    )
    address: Optional[str] = Field(
        None, description="[range] Cell/range address e.g. 'A1', 'A1:D10', 'B:B'."
    )
    values: Optional[list] = Field(
        None, description="[range: write] 2D list — strings starting with '=' are formulas. [table: add_row] 1D list of row values."
    )
    contents_only: Optional[bool] = Field(
        None, description="[range: clear] True=values only, False=values+formatting."
    )
    bold: Optional[bool] = Field(None, description="[range: format] Bold.")
    italic: Optional[bool] = Field(None, description="[range: format] Italic.")
    font_size: Optional[float] = Field(None, description="[range: format] Font size in points.")
    font_color: Optional[list[int]] = Field(None, description="[range: format | cond_format: add_rule] RGB [R, G, B] text color.")
    bg_color: Optional[list[int]] = Field(None, description="[range: format | cond_format: add_rule] RGB [R, G, B] fill color.")
    number_format: Optional[str] = Field(None, description="[range: format | pivot: set_field_number_format] e.g. '#,##0.00', '0%'.")
    h_align: Optional[Literal['left', 'center', 'right']] = Field(None, description="[range: format] Horizontal alignment.")
    v_align: Optional[Literal['top', 'center', 'bottom']] = Field(None, description="[range: format] Vertical alignment.")
    wrap_text: Optional[bool] = Field(None, description="[range: format] Wrap text.")
    key_column: Optional[int] = Field(None, description="[range: sort] 1-based column index to sort by.")
    ascending: Optional[bool] = Field(None, description="[range: sort | table: sort | pivot: sort_field] Ascending=True, Descending=False.")
    has_header: Optional[bool] = Field(None, description="[range: sort] Range has a header row.")
    search_text: Optional[str] = Field(None, description="[range: find] Text to search for.")
    find_text: Optional[str] = Field(None, description="[range: replace] Text to find.")
    replace_text: Optional[str] = Field(None, description="[range: replace] Replacement text.")
    count: Optional[int] = Field(None, description="[range: insert_rows, insert_columns] Number to insert.")
    columns: Optional[bool] = Field(None, description="[range: autofit] Autofit column widths.")
    rows_autofit: Optional[bool] = Field(None, description="[range: autofit] Autofit row heights.")
    url: Optional[str] = Field(None, description="[range: set_hyperlink] Hyperlink URL.")
    display_text: Optional[str] = Field(None, description="[range: set_hyperlink] Display text.")
    validation_type: Optional[Literal['list', 'whole', 'decimal', 'date', 'text_length']] = Field(
        None, description="[range: set_validation] Validation type."
    )
    formula: Optional[str] = Field(
        None, description="[range: set_validation] e.g. 'A,B,C' for list. [cond_format: add_rule] Formula for rule_type='formula'."
    )

    # ── Tables ──────────────────────────────────────────────────────────────
    table_name: Optional[str] = Field(None, description="[table, chart: create_from_table, pivot: create_from_table] Table name.")
    range_address: Optional[str] = Field(None, description="[table: create] Range for the new table e.g. 'A1:D10'.")
    has_headers: Optional[bool] = Field(None, description="[table: create] Range has header row.")
    style: Optional[str] = Field(None, description="[table: create, set_style] Style name e.g. 'TableStyleMedium2'.")
    visible_only: Optional[bool] = Field(None, description="[table: get_data] Only visible (unfiltered) rows.")
    column_name: Optional[str] = Field(None, description="[table: add_column, set_column_total, sort, filter] Column name.")
    position: Optional[int] = Field(None, description="[table: add_column | pivot: add_field] 1-based position.")
    new_range: Optional[str] = Field(None, description="[table: resize] New range address.")
    show: Optional[bool] = Field(None, description="[table: toggle_totals | chart: set_legend | pivot: set_subtotals] Show/hide.")
    function: Optional[str] = Field(
        None, description="[table: set_column_total] sum|count|average|max|min|none. [pivot: add_field] Aggregation function."
    )
    criteria: Optional[str] = Field(None, description="[table: filter] AutoFilter criteria e.g. '>100'.")

    # ── Charts ──────────────────────────────────────────────────────────────
    chart_name: Optional[str] = Field(None, description="[chart] Chart name.")
    chart_type: Optional[str] = Field(
        None, description="[chart: create, create_from_table, set_type] e.g. 'column_clustered', 'line', 'pie', 'bar_clustered', 'area', 'scatter'."
    )
    source_range: Optional[str] = Field(None, description="[chart: create, set_source | pivot: create_from_range] Data range e.g. 'A1:B10'.")
    target_range: Optional[str] = Field(None, description="[chart: create] Position chart over this range.")
    left: Optional[float] = Field(None, description="[chart: create, move] Left in points.")
    top: Optional[float] = Field(None, description="[chart: create, move] Top in points.")
    width: Optional[float] = Field(None, description="[chart: create, move] Width in points.")
    height: Optional[float] = Field(None, description="[chart: create, move] Height in points.")
    title: Optional[str] = Field(None, description="[chart: set_title, set_axis_title] Title text.")
    legend_position: Optional[Literal['bottom', 'top', 'left', 'right', 'corner']] = Field(
        None, description="[chart: set_legend] Legend position."
    )
    axis: Optional[Literal['x', 'y']] = Field(None, description="[chart: set_axis_title] 'x' (category) or 'y' (value).")

    # ── Pivot Tables ────────────────────────────────────────────────────────
    pivot_name: Optional[str] = Field(None, description="[pivot] PivotTable name.")
    source_sheet: Optional[str] = Field(None, description="[pivot: create_from_range] Source data sheet.")
    dest_sheet: Optional[str] = Field(None, description="[pivot: create_from_range, create_from_table] Destination sheet.")
    dest_cell: Optional[str] = Field(None, description="[pivot: create_from_range, create_from_table] Top-left cell e.g. 'A1'.")
    field_name: Optional[str] = Field(None, description="[pivot: add_field, remove_field, set_subtotals, sort_field, filter_field, set_field_number_format] Field name.")
    area: Optional[Literal['row', 'column', 'filter', 'value']] = Field(None, description="[pivot: add_field] Target area.")
    custom_name: Optional[str] = Field(None, description="[pivot: add_field] Custom field caption.")
    layout: Optional[Literal['compact', 'tabular', 'outline']] = Field(None, description="[pivot: set_layout] Layout style.")
    pivot_rows: Optional[bool] = Field(None, description="[pivot: set_grand_totals] Grand totals for rows.")
    pivot_columns: Optional[bool] = Field(None, description="[pivot: set_grand_totals] Grand totals for columns.")
    filter_values: Optional[list[str]] = Field(None, description="[pivot: filter_field] Values to keep visible.")

    # ── Calculation ─────────────────────────────────────────────────────────
    calc_mode: Optional[Literal['automatic', 'manual', 'semiautomatic']] = Field(
        None, description="[calc: set_mode] Calculation mode."
    )
    calc_scope: Optional[Literal['workbook', 'sheet', 'app']] = Field(
        None, description="[calc: calculate] Scope."
    )

    # ── Named Ranges ────────────────────────────────────────────────────────
    range_name: Optional[str] = Field(None, description="[named_range] Named range identifier.")
    refers_to: Optional[str] = Field(None, description="[named_range: create, update] e.g. '=Sheet1!$A$1:$B$10'.")
    scope: Optional[Literal['workbook', 'sheet']] = Field(None, description="[named_range: create] Scope.")

    # ── Conditional Formatting ──────────────────────────────────────────────
    rule_type: Optional[Literal['cell_value', 'formula', 'duplicate', 'unique', 'top10', 'above_average']] = Field(
        None, description="[cond_format: add_rule] Rule type."
    )
    operator: Optional[Literal['between', 'not_between', 'equal', 'not_equal', 'greater', 'less', 'greater_equal', 'less_equal']] = Field(
        None, description="[cond_format: add_rule] Operator for cell_value rules."
    )
    value1: Optional[Any] = Field(None, description="[cond_format: add_rule] First value or top-N rank.")
    value2: Optional[Any] = Field(None, description="[cond_format: add_rule] Second value (for 'between').")

    # ── Screenshot ──────────────────────────────────────────────────────────
    path: Optional[str] = Field(None, description="[screenshot] Output PNG path. Defaults to TEMP dir.")
    range_address_screenshot: Optional[str] = Field(
        None, description="[screenshot] Range to capture e.g. 'A1:H20'. Omit for full used range."
    )
