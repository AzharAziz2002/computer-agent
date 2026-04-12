# experimental/

Prototyping area for features before they're integrated into Medusa's core.

## excelTool/

**Status:** Standalone prototype — not connected to Medusa yet.

**Purpose:** Programmatic Excel control via xlwings COM automation. Replaces mouse/keyboard interaction with direct API calls for full-fidelity Excel operations.

**Reference implementation:** `D:\Code\Python\MCP\mcp-server-excel` (sbroenne/mcp-server-excel, C# COM, 213 source files, ~50K LOC). The C# COM patterns were translated to Python xlwings equivalents.

### Architecture

```
experimental/excelTool/
├── __init__.py          # Package exports ExcelController
├── constants.py         # Excel COM enums (XlCalculation, XlChartType, etc.)
├── controller.py        # ExcelController — all operations in one class
└── test_excel.py        # Smoke test exercising all operation categories
```

### ExcelController — Operation Categories

| Category | Methods | Count | COM Access |
|---|---|---|---|
| **File/Session** | open, create, save, close, quit, test_file | 6 | xlwings native |
| **Sheets** | list, create, rename, delete, copy, move, visibility, tab_color | 8 | xlwings + .api |
| **Ranges** | read, write, read_formulas, clear, format, merge/unmerge, autofit, sort, find, replace, insert/delete rows/cols, used, hyperlink, validation | 16 | xlwings + .api |
| **Tables** | list, create, read, get_data, add_row, add_column, rename, delete, resize, toggle_totals, set_column_total, sort, filter, clear_filters, set_style | 15 | .api (ListObjects) |
| **Charts** | list, create, create_from_table, set_title, set_type, set_source, move, delete, set_legend, set_axis_title | 10 | .api (Shapes/Chart) |
| **PivotTables** | list, create_from_range, create_from_table, add_field, remove_field, list_fields, refresh, set_layout, set_subtotals, set_grand_totals, sort_field, filter_field, delete, set_field_number_format | 14 | .api (PivotCaches/PivotTable) |
| **Calculation** | get_mode, set_mode, calculate | 3 | .api |
| **Named Ranges** | list, create, delete, update | 4 | .api (Names) |
| **Conditional Formatting** | add_rule (cell_value/formula/duplicate/unique/top10/above_average), clear | 2 | .api (FormatConditions) |
| **Screenshot** | screenshot (sheet/range → PNG) | 1 | .api (CopyPicture + ChartExport) |
| **Total** | | **79 operations** | |

### Dependencies

- `xlwings` — Python Excel COM wrapper (must be installed: `uv add xlwings`)
- Excel 2016+ installed on Windows

### Running Tests

From the project root (on Windows, in PowerShell):
```bash
.venv/Scripts/python.exe -m experimental.excelTool.test_excel
```

### What's NOT Implemented Yet (future phases)

- VBA macro execution
- Power Query / M Code operations
- Data Model / DAX measures
- Slicer management
- OLEDB/ODBC data connections
- Cross-workbook sheet copy/move
- Window management (freeze panes, split, zoom)

### Integration Plan (when connecting to Medusa)

1. Create `medusa/orchestrator/tools/excel_schema.py` — Pydantic schema with action dispatch
2. Create `medusa/orchestrator/tools/excel_tool.py` — @Tool wrapper calling ExcelController methods
3. Register in `medusa/orchestrator/core.py` Registry
4. Add `xlwings` to `pyproject.toml` dependencies
5. Move `ExcelController` from experimental/ to `medusa/orchestrator/excel/controller.py`
