import json
from medusa.orchestrator.tools.excel_schema import ExcelAction
from medusa.orchestrator.registry.views import ToolResult
from medusa.tool import Tool

# Module-level singleton — persists across tool calls within a session
_excel: object = None


def _get_controller():
    """Lazily create the ExcelController singleton."""
    global _excel
    if _excel is None:
        from experimental.excelTool.controller import ExcelController
        _excel = ExcelController(visible=True)
    return _excel


_MAX_RESULT_CHARS = 80_000  # ~20K tokens — safe headroom under 200K context limit


def _dump(result) -> str:
    """Serialize controller result to a compact JSON string, truncating if too large."""
    if isinstance(result, (dict, list)):
        text = json.dumps(result, default=str)
    else:
        text = str(result)
    if len(text) > _MAX_RESULT_CHARS:
        # Try to truncate row data intelligently for range reads
        if isinstance(result, dict) and "values" in result:
            rows = result["values"]
            total = len(rows)
            # Keep first 500 rows + summary
            truncated = rows[:500]
            result_copy = {**result, "values": truncated, "_truncated": True, "_total_rows": total, "_shown_rows": len(truncated)}
            text = json.dumps(result_copy, default=str)
        else:
            text = text[:_MAX_RESULT_CHARS] + f"\n... [TRUNCATED — result was {len(text):,} chars, showing first {_MAX_RESULT_CHARS:,}]"
    return text


@Tool('Excel', args_schema=ExcelAction)
def excel(action: str, **kwargs) -> str:
    """
    Programmatic Excel control — read/write data, format cells, manage sheets,
    tables, charts, pivot tables, and named ranges without using the mouse.

    Workflow:
      1. Open or connect to a workbook: action='file', operation='open'|'connect'
      2. Perform operations (range, table, chart, pivot, …)
      3. Save: action='file', operation='save'
      4. Close or leave open: action='file', operation='close'|'quit'

    All operations return a JSON result. Errors raise and are reported as tool failures.
    """
    xl = _get_controller()
    op = kwargs.get('operation')

    match action:

        # ── FILE ──────────────────────────────────────────────────────────
        case 'file':
            match op:
                case 'list_workbooks':
                    return _dump(xl.list_open_workbooks())
                case 'connect':
                    return _dump(xl.connect(kwargs['name_or_path']))
                case 'test':
                    return _dump(xl.test_file(kwargs['file_path']))
                case 'open':
                    return _dump(xl.open(kwargs['file_path']))
                case 'create':
                    return _dump(xl.create(kwargs.get('file_path')))
                case 'save':
                    return _dump(xl.save(kwargs.get('file_path')))
                case 'close':
                    save_flag = kwargs.get('save_on_close')
                    return _dump(xl.close(save=True if save_flag is None else save_flag))
                case 'quit':
                    result = xl.quit()
                    global _excel
                    _excel = None
                    return _dump(result)

        # ── SHEET ─────────────────────────────────────────────────────────
        case 'sheet':
            match op:
                case 'list':
                    return _dump(xl.sheet_list())
                case 'create':
                    return _dump(xl.sheet_create(
                        name=kwargs['name'],
                        after=kwargs.get('after'),
                        before=kwargs.get('before'),
                    ))
                case 'rename':
                    return _dump(xl.sheet_rename(kwargs['old_name'], kwargs['new_name']))
                case 'delete':
                    return _dump(xl.sheet_delete(kwargs['name']))
                case 'copy':
                    return _dump(xl.sheet_copy(kwargs['source'], kwargs['new_name']))
                case 'move':
                    return _dump(xl.sheet_move(
                        name=kwargs['name'],
                        before=kwargs.get('before'),
                        after=kwargs.get('after'),
                    ))
                case 'visibility':
                    return _dump(xl.sheet_visibility(
                        name=kwargs['name'],
                        visible=kwargs.get('visible'),
                        very_hidden=kwargs.get('very_hidden', False),
                    ))
                case 'tab_color':
                    raw = kwargs.get('color')
                    color = tuple(raw) if raw else None
                    return _dump(xl.sheet_tab_color(kwargs['name'], color=color))

        # ── RANGE ─────────────────────────────────────────────────────────
        case 'range':
            match op:
                case 'read':
                    return _dump(xl.range_read(kwargs['sheet_name'], kwargs['address']))
                case 'write':
                    return _dump(xl.range_write(kwargs['sheet_name'], kwargs['address'], kwargs['values']))
                case 'read_formulas':
                    return _dump(xl.range_read_formulas(kwargs['sheet_name'], kwargs['address']))
                case 'clear':
                    return _dump(xl.range_clear(
                        kwargs['sheet_name'], kwargs['address'],
                        contents_only=kwargs.get('contents_only', False),
                    ))
                case 'format':
                    raw_fc = kwargs.get('font_color')
                    raw_bg = kwargs.get('bg_color')
                    return _dump(xl.range_format(
                        sheet_name=kwargs['sheet_name'],
                        address=kwargs['address'],
                        bold=kwargs.get('bold'),
                        italic=kwargs.get('italic'),
                        font_size=kwargs.get('font_size'),
                        font_color=tuple(raw_fc) if raw_fc else None,
                        bg_color=tuple(raw_bg) if raw_bg else None,
                        number_format=kwargs.get('number_format'),
                        h_align=kwargs.get('h_align'),
                        v_align=kwargs.get('v_align'),
                        wrap_text=kwargs.get('wrap_text'),
                    ))
                case 'merge':
                    return _dump(xl.range_merge(kwargs['sheet_name'], kwargs['address']))
                case 'unmerge':
                    return _dump(xl.range_unmerge(kwargs['sheet_name'], kwargs['address']))
                case 'autofit':
                    return _dump(xl.range_autofit(
                        kwargs['sheet_name'], kwargs['address'],
                        columns=kwargs.get('columns', True),
                        rows=kwargs.get('rows_autofit', True),
                    ))
                case 'sort':
                    return _dump(xl.range_sort(
                        sheet_name=kwargs['sheet_name'],
                        address=kwargs['address'],
                        key_column=kwargs.get('key_column', 1),
                        ascending=kwargs.get('ascending', True),
                        has_header=kwargs.get('has_header', True),
                    ))
                case 'find':
                    result = xl.range_find(
                        kwargs['sheet_name'], kwargs['search_text'],
                        address=kwargs.get('address'),
                    )
                    return _dump(result) if result is not None else "Not found."
                case 'replace':
                    return _dump(xl.range_replace(
                        kwargs['sheet_name'], kwargs['find_text'], kwargs['replace_text'],
                        address=kwargs.get('address'),
                    ))
                case 'insert_rows':
                    return _dump(xl.range_insert_rows(
                        kwargs['sheet_name'], kwargs['address'],
                        count=kwargs.get('count', 1),
                    ))
                case 'delete_rows':
                    return _dump(xl.range_delete_rows(kwargs['sheet_name'], kwargs['address']))
                case 'insert_columns':
                    return _dump(xl.range_insert_columns(
                        kwargs['sheet_name'], kwargs['address'],
                        count=kwargs.get('count', 1),
                    ))
                case 'delete_columns':
                    return _dump(xl.range_delete_columns(kwargs['sheet_name'], kwargs['address']))
                case 'used':
                    return _dump(xl.range_used(kwargs['sheet_name']))
                case 'set_hyperlink':
                    return _dump(xl.range_set_hyperlink(
                        kwargs['sheet_name'], kwargs['address'], kwargs['url'],
                        display_text=kwargs.get('display_text'),
                    ))
                case 'set_validation':
                    return _dump(xl.range_set_validation(
                        kwargs['sheet_name'], kwargs['address'],
                        validation_type=kwargs.get('validation_type', 'list'),
                        formula=kwargs.get('formula', ''),
                    ))

        # ── TABLE ─────────────────────────────────────────────────────────
        case 'table':
            match op:
                case 'list':
                    return _dump(xl.table_list())
                case 'create':
                    return _dump(xl.table_create(
                        sheet_name=kwargs['sheet_name'],
                        range_address=kwargs['range_address'],
                        table_name=kwargs['table_name'],
                        has_headers=kwargs.get('has_headers', True),
                        style=kwargs.get('style'),
                    ))
                case 'read':
                    return _dump(xl.table_read(kwargs['table_name']))
                case 'get_data':
                    return _dump(xl.table_get_data(
                        kwargs['table_name'],
                        visible_only=kwargs.get('visible_only', False),
                    ))
                case 'add_row':
                    return _dump(xl.table_add_row(kwargs['table_name'], values=kwargs.get('values')))
                case 'add_column':
                    return _dump(xl.table_add_column(
                        kwargs['table_name'], kwargs['column_name'],
                        position=kwargs.get('position'),
                    ))
                case 'rename':
                    return _dump(xl.table_rename(kwargs['table_name'], kwargs['new_name']))
                case 'delete':
                    return _dump(xl.table_delete(kwargs['table_name']))
                case 'resize':
                    return _dump(xl.table_resize(kwargs['table_name'], kwargs['new_range']))
                case 'toggle_totals':
                    return _dump(xl.table_toggle_totals(kwargs['table_name'], kwargs['show']))
                case 'set_column_total':
                    return _dump(xl.table_set_column_total(
                        kwargs['table_name'], kwargs['column_name'],
                        function=kwargs.get('function', 'sum'),
                    ))
                case 'sort':
                    return _dump(xl.table_sort(
                        kwargs['table_name'], kwargs['column_name'],
                        ascending=kwargs.get('ascending', True),
                    ))
                case 'filter':
                    return _dump(xl.table_filter(
                        kwargs['table_name'], kwargs['column_name'], kwargs['criteria']
                    ))
                case 'clear_filters':
                    return _dump(xl.table_clear_filters(kwargs['table_name']))
                case 'set_style':
                    return _dump(xl.table_set_style(kwargs['table_name'], kwargs['style']))

        # ── CHART ─────────────────────────────────────────────────────────
        case 'chart':
            match op:
                case 'list':
                    return _dump(xl.chart_list())
                case 'create':
                    return _dump(xl.chart_create(
                        sheet_name=kwargs['sheet_name'],
                        source_range=kwargs['source_range'],
                        chart_type=kwargs.get('chart_type', 'column_clustered'),
                        chart_name=kwargs.get('chart_name'),
                        left=kwargs.get('left', 0),
                        top=kwargs.get('top', 0),
                        width=kwargs.get('width', 400),
                        height=kwargs.get('height', 300),
                        target_range=kwargs.get('target_range'),
                    ))
                case 'create_from_table':
                    return _dump(xl.chart_create_from_table(
                        table_name=kwargs['table_name'],
                        sheet_name=kwargs['sheet_name'],
                        chart_type=kwargs.get('chart_type', 'column_clustered'),
                        chart_name=kwargs.get('chart_name'),
                        left=kwargs.get('left', 0),
                        top=kwargs.get('top', 0),
                        width=kwargs.get('width', 400),
                        height=kwargs.get('height', 300),
                    ))
                case 'set_title':
                    return _dump(xl.chart_set_title(kwargs['chart_name'], kwargs['title']))
                case 'set_type':
                    return _dump(xl.chart_set_type(kwargs['chart_name'], kwargs['chart_type']))
                case 'set_source':
                    return _dump(xl.chart_set_source(
                        kwargs['chart_name'], kwargs['sheet_name'], kwargs['source_range']
                    ))
                case 'move':
                    return _dump(xl.chart_move(
                        kwargs['chart_name'],
                        left=kwargs.get('left'),
                        top=kwargs.get('top'),
                        width=kwargs.get('width'),
                        height=kwargs.get('height'),
                    ))
                case 'delete':
                    return _dump(xl.chart_delete(kwargs['chart_name']))
                case 'set_legend':
                    return _dump(xl.chart_set_legend(
                        kwargs['chart_name'], kwargs['show'],
                        position=kwargs.get('legend_position'),
                    ))
                case 'set_axis_title':
                    return _dump(xl.chart_set_axis_title(
                        kwargs['chart_name'], kwargs['axis'], kwargs['title']
                    ))

        # ── PIVOT ─────────────────────────────────────────────────────────
        case 'pivot':
            match op:
                case 'list':
                    return _dump(xl.pivot_list())
                case 'create_from_range':
                    return _dump(xl.pivot_create_from_range(
                        source_sheet=kwargs['source_sheet'],
                        source_range=kwargs['source_range'],
                        dest_sheet=kwargs['dest_sheet'],
                        dest_cell=kwargs['dest_cell'],
                        pivot_name=kwargs['pivot_name'],
                    ))
                case 'create_from_table':
                    return _dump(xl.pivot_create_from_table(
                        table_name=kwargs['table_name'],
                        dest_sheet=kwargs['dest_sheet'],
                        dest_cell=kwargs['dest_cell'],
                        pivot_name=kwargs['pivot_name'],
                    ))
                case 'add_field':
                    return _dump(xl.pivot_add_field(
                        pivot_name=kwargs['pivot_name'],
                        field_name=kwargs['field_name'],
                        area=kwargs['area'],
                        position=kwargs.get('position'),
                        function=kwargs.get('function', 'sum'),
                        custom_name=kwargs.get('custom_name'),
                        number_format=kwargs.get('number_format'),
                    ))
                case 'remove_field':
                    return _dump(xl.pivot_remove_field(kwargs['pivot_name'], kwargs['field_name']))
                case 'list_fields':
                    return _dump(xl.pivot_list_fields(kwargs['pivot_name']))
                case 'refresh':
                    return _dump(xl.pivot_refresh(kwargs['pivot_name']))
                case 'set_layout':
                    return _dump(xl.pivot_set_layout(
                        kwargs['pivot_name'],
                        layout=kwargs.get('layout', 'tabular'),
                    ))
                case 'set_subtotals':
                    return _dump(xl.pivot_set_subtotals(
                        kwargs['pivot_name'], kwargs['field_name'], kwargs['show']
                    ))
                case 'set_grand_totals':
                    return _dump(xl.pivot_set_grand_totals(
                        kwargs['pivot_name'],
                        rows=kwargs.get('pivot_rows'),
                        columns=kwargs.get('pivot_columns'),
                    ))
                case 'sort_field':
                    return _dump(xl.pivot_sort_field(
                        kwargs['pivot_name'], kwargs['field_name'],
                        ascending=kwargs.get('ascending', True),
                    ))
                case 'filter_field':
                    return _dump(xl.pivot_filter_field(
                        kwargs['pivot_name'], kwargs['field_name'], kwargs['filter_values']
                    ))
                case 'delete':
                    return _dump(xl.pivot_delete(kwargs['pivot_name']))
                case 'set_field_number_format':
                    return _dump(xl.pivot_set_field_number_format(
                        kwargs['pivot_name'], kwargs['field_name'], kwargs['number_format']
                    ))

        # ── CALC ──────────────────────────────────────────────────────────
        case 'calc':
            match op:
                case 'get_mode':
                    return _dump(xl.calc_get_mode())
                case 'set_mode':
                    return _dump(xl.calc_set_mode(kwargs['calc_mode']))
                case 'calculate':
                    return _dump(xl.calc_calculate(
                        scope=kwargs.get('calc_scope', 'workbook'),
                        sheet_name=kwargs.get('sheet_name'),
                    ))

        # ── NAMED_RANGE ───────────────────────────────────────────────────
        case 'named_range':
            match op:
                case 'list':
                    return _dump(xl.named_range_list())
                case 'create':
                    return _dump(xl.named_range_create(
                        name=kwargs['range_name'],
                        refers_to=kwargs['refers_to'],
                        scope=kwargs.get('scope', 'workbook'),
                        sheet_name=kwargs.get('sheet_name'),
                    ))
                case 'delete':
                    return _dump(xl.named_range_delete(kwargs['range_name']))
                case 'update':
                    return _dump(xl.named_range_update(kwargs['range_name'], kwargs['refers_to']))

        # ── COND_FORMAT ───────────────────────────────────────────────────
        case 'cond_format':
            match op:
                case 'add_rule':
                    raw_fc = kwargs.get('font_color')
                    raw_bg = kwargs.get('bg_color')
                    return _dump(xl.cond_format_add_rule(
                        sheet_name=kwargs['sheet_name'],
                        address=kwargs['address'],
                        rule_type=kwargs['rule_type'],
                        operator=kwargs.get('operator'),
                        formula=kwargs.get('formula'),
                        value1=kwargs.get('value1'),
                        value2=kwargs.get('value2'),
                        font_color=tuple(raw_fc) if raw_fc else None,
                        bg_color=tuple(raw_bg) if raw_bg else None,
                    ))
                case 'clear':
                    return _dump(xl.cond_format_clear(kwargs['sheet_name'], kwargs['address']))

        # ── SCREENSHOT ────────────────────────────────────────────────────
        case 'screenshot':
            return _dump(xl.screenshot(
                sheet_name=kwargs.get('sheet_name'),
                range_address=kwargs.get('range_address_screenshot'),
                path=kwargs.get('path'),
            ))

    return ToolResult(is_success=False, error=f"Unknown action='{action}' operation='{op}'")
