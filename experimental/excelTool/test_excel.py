"""
Smoke test for ExcelController — run on Windows with Excel installed.

Usage:
    python -m experimental.excelTool.test_excel

Creates a temp workbook, exercises all operation categories, then cleans up.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Add project root to path so we can import
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experimental.excelTool.controller import ExcelController, ExcelError


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def ok(msg: str, result=None):
    print(f"  [OK] {msg}")
    if result and isinstance(result, dict):
        for k, v in result.items():
            if k != "values" and k != "data":
                print(f"        {k}: {v}")


def run_tests():
    tmp_path = os.path.join(tempfile.gettempdir(), "excel_tool_test.xlsx")
    ctrl = ExcelController(visible=True)

    try:
        # ── FILE OPS ──
        section("File Operations")
        result = ctrl.create(tmp_path)
        ok("create workbook", result)

        result = ctrl.save()
        ok("save workbook", result)

        # ── SHEET OPS ──
        section("Sheet Operations")
        sheets = ctrl.sheet_list()
        ok(f"list sheets ({len(sheets)} found)", sheets[0] if sheets else {})

        ctrl.sheet_create("TestSheet")
        ok("create sheet 'TestSheet'")

        ctrl.sheet_rename("TestSheet", "DataSheet")
        ok("rename to 'DataSheet'")

        ctrl.sheet_copy("DataSheet", "DataCopy")
        ok("copy sheet")

        ctrl.sheet_move("DataCopy", after="DataSheet")
        ok("move sheet")

        ctrl.sheet_tab_color("DataSheet", (0, 112, 192))
        ok("set tab color")

        ctrl.sheet_delete("DataCopy")
        ok("delete copied sheet")

        # ── RANGE OPS ──
        section("Range Operations")
        data = [
            ["Name", "Age", "Score", "City"],
            ["Alice", 30, 95.5, "NYC"],
            ["Bob", 25, 88.0, "LA"],
            ["Carol", 35, 92.3, "CHI"],
            ["Dave", 28, 76.8, "NYC"],
            ["Eve", 32, 99.1, "LA"],
        ]
        ctrl.range_write("DataSheet", "A1", data)
        ok("write 6x4 data block")

        result = ctrl.range_read("DataSheet", "A1:D6")
        ok(f"read range ({result['row_count']}x{result['column_count']})")

        ctrl.range_format("DataSheet", "A1:D1", bold=True, bg_color=(0, 112, 192), font_color=(255, 255, 255))
        ok("format header row")

        ctrl.range_format("DataSheet", "C2:C6", number_format="0.0")
        ok("set number format")

        ctrl.range_autofit("DataSheet", "A1:D6")
        ok("autofit columns")

        ctrl.range_sort("DataSheet", "A1:D6", key_column=3, ascending=False)
        ok("sort by Score descending")

        result = ctrl.range_find("DataSheet", "Alice")
        ok("find 'Alice'", result)

        ctrl.range_replace("DataSheet", "NYC", "New York")
        ok("replace NYC -> New York")

        ctrl.range_merge("DataSheet", "F1:G1")
        ok("merge cells")
        ctrl.range_unmerge("DataSheet", "F1:G1")
        ok("unmerge cells")

        result = ctrl.range_used("DataSheet")
        ok("used range", result)

        ctrl.range_set_hyperlink("DataSheet", "F2", "https://example.com", "Example Link")
        ok("set hyperlink")

        ctrl.range_set_validation("DataSheet", "F3", "list", "Option1,Option2,Option3")
        ok("set validation list")

        # ── TABLE OPS ──
        section("Table Operations")
        ctrl.table_create("DataSheet", "A1:D6", "SalesData", style="TableStyleMedium2")
        ok("create table 'SalesData'")

        tables = ctrl.table_list()
        ok(f"list tables ({len(tables)} found)")

        result = ctrl.table_read("SalesData")
        ok("read table info", result)

        result = ctrl.table_get_data("SalesData")
        ok(f"get table data ({result['row_count']} rows)")

        ctrl.table_add_row("SalesData", ["Frank", 29, 85.5, "Boston"])
        ok("add row to table")

        ctrl.table_add_column("SalesData", "Grade")
        ok("add column 'Grade'")

        ctrl.table_toggle_totals("SalesData", True)
        ok("show totals row")

        ctrl.table_set_column_total("SalesData", "Score", "average")
        ok("set Score total = average")

        ctrl.table_sort("SalesData", "Score", ascending=False)
        ok("sort table by Score")

        ctrl.table_set_style("SalesData", "TableStyleLight9")
        ok("change table style")

        # ── CHART OPS ──
        section("Chart Operations")
        result = ctrl.chart_create("DataSheet", "A1:D6", "column_clustered", "TestChart")
        ok("create column chart", result)

        ctrl.chart_set_title("TestChart", "Sales Analysis")
        ok("set chart title")

        ctrl.chart_set_axis_title("TestChart", "x", "Employee")
        ok("set X axis title")

        ctrl.chart_set_axis_title("TestChart", "y", "Value")
        ok("set Y axis title")

        ctrl.chart_set_legend("TestChart", True, "bottom")
        ok("set legend position")

        ctrl.chart_move("TestChart", width=500, height=350)
        ok("resize chart")

        charts = ctrl.chart_list()
        ok(f"list charts ({len(charts)} found)")

        ctrl.chart_set_type("TestChart", "bar_clustered")
        ok("change chart type to bar")

        # ── PIVOT TABLE OPS ──
        section("PivotTable Operations")
        ctrl.sheet_create("PivotSheet")
        result = ctrl.pivot_create_from_range(
            "DataSheet", "A1:D6", "PivotSheet", "A1", "TestPivot"
        )
        ok("create PivotTable from range", result)

        ctrl.pivot_add_field("TestPivot", "City", "row")
        ok("add City as row field")

        ctrl.pivot_add_field("TestPivot", "Score", "value", function="average", number_format="0.0")
        ok("add Score as value (average)")

        fields = ctrl.pivot_list_fields("TestPivot")
        ok(f"list fields ({len(fields['fields'])} total)")

        ctrl.pivot_set_layout("TestPivot", "tabular")
        ok("set tabular layout")

        ctrl.pivot_set_grand_totals("TestPivot", rows=True, columns=False)
        ok("configure grand totals")

        ctrl.pivot_refresh("TestPivot")
        ok("refresh PivotTable")

        pivots = ctrl.pivot_list()
        ok(f"list PivotTables ({len(pivots)} found)")

        # ── CALCULATION OPS ──
        section("Calculation")
        result = ctrl.calc_get_mode()
        ok("get calc mode", result)

        ctrl.calc_set_mode("manual")
        ok("set manual calc")

        ctrl.calc_calculate()
        ok("force calculate")

        ctrl.calc_set_mode("automatic")
        ok("restore automatic calc")

        # ── NAMED RANGES ──
        section("Named Ranges")
        ctrl.named_range_create("ScoreRange", "=DataSheet!$C$2:$C$6")
        ok("create named range")

        names = ctrl.named_range_list()
        ok(f"list named ranges ({len(names)} found)")

        ctrl.named_range_update("ScoreRange", "=DataSheet!$C$2:$C$7")
        ok("update named range")

        ctrl.named_range_delete("ScoreRange")
        ok("delete named range")

        # ── CONDITIONAL FORMATTING ──
        section("Conditional Formatting")
        ctrl.cond_format_add_rule(
            "DataSheet", "C2:C7",
            rule_type="cell_value", operator="greater", value1="90",
            bg_color=(146, 208, 80),  # green
        )
        ok("add cell value > 90 rule (green)")

        ctrl.cond_format_add_rule(
            "DataSheet", "C2:C7",
            rule_type="cell_value", operator="less", value1="80",
            font_color=(255, 0, 0),  # red text
        )
        ok("add cell value < 80 rule (red text)")

        # ── SCREENSHOT ──
        section("Screenshot")
        result = ctrl.screenshot("DataSheet")
        ok("take screenshot", result)

        # ── CLEANUP ──
        section("Cleanup")
        ctrl.chart_delete("TestChart")
        ok("delete chart")

        ctrl.table_toggle_totals("SalesData", False)
        ok("hide totals")

        ctrl.save()
        ok("final save")

        print(f"\n{'='*60}")
        print(f"  ALL TESTS PASSED — workbook at: {tmp_path}")
        print(f"{'='*60}\n")

    except ExcelError as e:
        print(f"\n  [FAIL] ExcelError: {e}")
        raise
    except Exception as e:
        print(f"\n  [FAIL] {type(e).__name__}: {e}")
        raise
    finally:
        try:
            ctrl.close(save=True)
        except Exception:
            pass


if __name__ == "__main__":
    run_tests()
