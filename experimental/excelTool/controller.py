"""
ExcelController — programmatic Excel control via xlwings COM automation.

Provides file, sheet, range, table, chart, pivot table, calculation,
and named range operations. Uses xlwings for Pythonic API and falls
back to .api (raw COM) for advanced features.

Reference: sbroenne/mcp-server-excel C# COM patterns.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import xlwings as xw

from .constants import (
    AGGREGATION_MAP,
    CHART_TYPE_MAP,
    MSO_CHART,
    VALID_EXTENSIONS,
    XL_CALCULATION_AUTOMATIC,
    XL_CALCULATION_MANUAL,
    XL_CALCULATION_SEMIAUTOMATIC,
    XL_CELL_TYPE_LAST_CELL,
    XL_COLUMN_FIELD,
    XL_DATA_FIELD,
    XL_DATABASE,
    XL_GUESS,
    XL_PAGE_FIELD,
    XL_PIVOT_TABLE_VERSION_14,
    XL_ROW_FIELD,
    XL_SHEET_HIDDEN,
    XL_SHEET_VERY_HIDDEN,
    XL_SHEET_VISIBLE,
    XL_SRC_RANGE,
    XL_YES,
    XL_ASCENDING,
    XL_DESCENDING,
)


class ExcelError(Exception):
    """Raised when an Excel operation fails."""


class ExcelController:
    """High-level Excel automation controller.

    Manages a persistent connection to an Excel application instance
    and an open workbook. All operations go through this controller.
    """

    def __init__(self, visible: bool = True, app: xw.App | None = None):
        if app:
            self._app = app
        elif xw.apps:
            # Reuse an already-running Excel instance
            self._app = xw.apps.active
        else:
            self._app = xw.App(visible=visible, add_book=False)
        self._app.display_alerts = False
        self._app.screen_updating = True
        self._book: xw.Book | None = None

    @property
    def app(self) -> xw.App:
        return self._app

    @property
    def book(self) -> xw.Book:
        if self._book is None:
            raise ExcelError("No workbook is open. Call open(), create(), or connect() first.")
        return self._book

    # ─────────────────────────────────────────────
    # FILE / SESSION
    # ─────────────────────────────────────────────

    def list_open_workbooks(self) -> list[dict]:
        """List all workbooks currently open across all Excel instances."""
        results = []
        for app in xw.apps:
            for book in app.books:
                results.append({
                    "name": book.name,
                    "full_path": book.fullname,
                    "sheets": [s.name for s in book.sheets],
                    "app_pid": app.pid,
                })
        return results

    def connect(self, name_or_path: str) -> dict:
        """Connect to an already-open workbook by name (e.g. 'report.xlsx')
        or full path. The workbook must already be open in Excel.

        This is the key method for controlling files the user has open."""
        # Try by name across all apps first
        for app in xw.apps:
            for book in app.books:
                if book.name.lower() == name_or_path.lower() or \
                   book.fullname.lower() == str(Path(name_or_path).resolve()).lower():
                    self._app = app
                    self._book = book
                    return {
                        "success": True,
                        "file_path": book.fullname,
                        "sheets": [s.name for s in book.sheets],
                        "app_pid": app.pid,
                    }
        # If not found, try xw.Book() which searches all instances
        try:
            self._book = xw.Book(name_or_path)
            self._app = self._book.app
            return {
                "success": True,
                "file_path": self._book.fullname,
                "sheets": [s.name for s in self._book.sheets],
                "app_pid": self._app.pid,
            }
        except Exception as e:
            raise ExcelError(
                f"Workbook '{name_or_path}' not found in any running Excel instance. "
                f"Open it in Excel first, or use open() to open from disk. Error: {e}"
            )

    def test_file(self, file_path: str) -> dict:
        """Validate a file before opening."""
        p = Path(file_path).resolve()
        ext = p.suffix.lower()
        exists = p.exists()
        return {
            "file_path": str(p),
            "exists": exists,
            "extension": ext,
            "is_valid": exists and ext in VALID_EXTENSIONS,
            "size": p.stat().st_size if exists else 0,
        }

    def open(self, file_path: str) -> dict:
        """Open a workbook. If it's already open in Excel, connects to it
        instead of opening a duplicate (which Excel blocks)."""
        p = Path(file_path).resolve()
        if not p.exists():
            raise ExcelError(f"File not found: {p}")
        if p.suffix.lower() not in VALID_EXTENSIONS:
            raise ExcelError(f"Unsupported extension: {p.suffix}")

        # Check if already open in any Excel instance
        for app in xw.apps:
            for book in app.books:
                if book.fullname.lower() == str(p).lower():
                    self._app = app
                    self._book = book
                    return {
                        "success": True,
                        "file_path": str(p),
                        "sheets": [s.name for s in self._book.sheets],
                        "already_open": True,
                    }

        self._book = self._app.books.open(str(p))
        return {"success": True, "file_path": str(p), "sheets": [s.name for s in self._book.sheets]}

    def create(self, file_path: str | None = None) -> dict:
        """Create a new workbook, optionally saving to file_path."""
        self._book = self._app.books.add()
        if file_path:
            p = Path(file_path).resolve()
            self._book.save(str(p))
        return {
            "success": True,
            "file_path": str(self._book.fullname),
            "sheets": [s.name for s in self._book.sheets],
        }

    def save(self, file_path: str | None = None) -> dict:
        """Save the current workbook."""
        if file_path:
            self.book.save(str(Path(file_path).resolve()))
        else:
            self.book.save()
        return {"success": True, "file_path": str(self.book.fullname)}

    def close(self, save: bool = True) -> dict:
        """Close the current workbook."""
        name = str(self.book.fullname)
        if save:
            self.book.save()
        self.book.close()
        self._book = None
        return {"success": True, "file_path": name}

    def quit(self) -> dict:
        """Close workbook (if open) and quit Excel."""
        if self._book is not None:
            try:
                self._book.close()
            except Exception:
                pass
            self._book = None
        self._app.quit()
        return {"success": True}

    # ─────────────────────────────────────────────
    # SHEETS
    # ─────────────────────────────────────────────

    def sheet_list(self) -> list[dict]:
        """List all worksheets."""
        results = []
        for i, s in enumerate(self.book.sheets, 1):
            results.append({
                "name": s.name,
                "index": i,
                "visible": s.api.Visible == XL_SHEET_VISIBLE,
            })
        return results

    def sheet_create(self, name: str, after: str | None = None, before: str | None = None) -> dict:
        """Add a new worksheet."""
        kwargs: dict[str, Any] = {}
        if after:
            kwargs["after"] = self.book.sheets[after]
        elif before:
            kwargs["before"] = self.book.sheets[before]
        sheet = self.book.sheets.add(name=name, **kwargs)
        return {"success": True, "name": sheet.name}

    def sheet_rename(self, old_name: str, new_name: str) -> dict:
        """Rename a worksheet."""
        self.book.sheets[old_name].name = new_name
        return {"success": True, "name": new_name}

    def sheet_delete(self, name: str) -> dict:
        """Delete a worksheet."""
        self.book.sheets[name].delete()
        return {"success": True}

    def sheet_copy(self, source: str, new_name: str) -> dict:
        """Copy a worksheet within the same workbook."""
        src = self.book.sheets[source]
        src.api.Copy(After=self.book.sheets[-1].api)
        copied = self.book.sheets[self.book.sheets.count - 1]
        copied.name = new_name
        return {"success": True, "name": new_name}

    def sheet_move(self, name: str, before: str | None = None, after: str | None = None) -> dict:
        """Move a worksheet to a new position."""
        sheet = self.book.sheets[name]
        if before:
            sheet.api.Move(Before=self.book.sheets[before].api)
        elif after:
            sheet.api.Move(After=self.book.sheets[after].api)
        else:
            sheet.api.Move(After=self.book.sheets[-1].api)
        return {"success": True}

    def sheet_visibility(self, name: str, visible: bool | None = None, very_hidden: bool = False) -> dict:
        """Get or set sheet visibility."""
        sheet = self.book.sheets[name]
        if visible is None:
            v = sheet.api.Visible
            return {"name": name, "visible": v == XL_SHEET_VISIBLE, "very_hidden": v == XL_SHEET_VERY_HIDDEN}
        if visible:
            sheet.api.Visible = XL_SHEET_VISIBLE
        elif very_hidden:
            sheet.api.Visible = XL_SHEET_VERY_HIDDEN
        else:
            sheet.api.Visible = XL_SHEET_HIDDEN
        return {"success": True}

    def sheet_tab_color(self, name: str, color: tuple[int, int, int] | None = None) -> dict:
        """Get or set sheet tab color as (R, G, B)."""
        sheet = self.book.sheets[name]
        if color is None:
            c = sheet.api.Tab.Color
            return {"name": name, "color": c}
        r, g, b = color
        sheet.api.Tab.Color = r + (g << 8) + (b << 16)
        return {"success": True}

    # ─────────────────────────────────────────────
    # RANGES
    # ─────────────────────────────────────────────

    def _resolve_range(self, sheet_name: str, address: str, clip_to_used: bool = False) -> xw.Range:
        """Get an xlwings Range object, optionally clipped to the used range.

        Clipping prevents full-column reads (e.g. 'J:J' = 1M rows) from blowing up memory/tokens.
        Uses Excel's Application.Intersect to find the overlap between the requested range and UsedRange.
        """
        sheet = self.book.sheets[sheet_name]
        rng = sheet.range(address)
        if clip_to_used:
            used = sheet.used_range
            if used is not None:
                intersected = sheet.api.Application.Intersect(rng.api, used.api)
                if intersected is not None:
                    rng = sheet.range(intersected.Address)
        return rng

    @staticmethod
    def _trim_trailing_empty(rows: list[list]) -> list[list]:
        """
        Remove trailing rows where every cell is None or empty string.

        Why this exists:
          Excel's UsedRange often extends past the last real data row — e.g. if a
          user selects rows 301-1000 and clicks "Clear Contents", those cells become
          empty but UsedRange still includes them (it tracks the "dirty" rectangle,
          not actual values). This inflates read results with hundreds of null rows.

        What it does:
          Pops rows from the END only. Empty rows in the middle of data are preserved
          because they represent intentional gaps (e.g. row 3 empty between row 2 and
          row 4 data).

        Edge cases handled:
          - Sparse data with gaps in the middle → gaps preserved, only bottom empties removed
          - Entire range is empty (wrong column read) → returns [[None]] (single empty row)
          - Formulas in later rows → formula cells aren't None, so those rows survive
          - Cleared content with formatting still on cells → formatting doesn't affect
            .value (which returns None), so those rows get stripped correctly
        """
        while rows and all(v is None or v == "" for v in rows[-1]):
            rows.pop()
        return rows if rows else [[None]]

    @staticmethod
    def _normalize_values(values, rng) -> list[list]:
        """
        Normalize xlwings range values into a consistent 2D list (rows × columns).

        Why this is needed:
          xlwings returns different shapes depending on the range dimensions:
            - Single cell  → scalar (e.g. 42)
            - Single row   → flat list [v1, v2, v3]
            - Single column → flat list [v1, v2, v3]  (SAME as single row!)
            - 2D range     → list of lists [[v1, v2], [v3, v4]]

          The ambiguity between single-row and single-column (both return flat lists)
          means we must check the actual range shape via rng.rows.count / rng.columns.count
          to determine the correct orientation.

        Returns:
          Always a list of lists: [[row1_col1, row1_col2], [row2_col1, row2_col2], ...]
        """
        if values is None:
            return [[None]]
        if not isinstance(values, list):
            return [[values]]
        if values and not isinstance(values[0], list):
            # Flat list — could be single row OR single column.
            # Check the actual range dimensions to decide orientation.
            if rng.columns.count == 1 and rng.rows.count > 1:
                # Single column: transpose flat list into column of rows
                return [[v] for v in values]
            else:
                # Single row (or 1×1 edge case): keep as single row
                return [values]
        return values

    def range_read(self, sheet_name: str, address: str) -> dict:
        """
        Read values from a range.

        Safety pipeline:
          1. clip_to_used — full-column addresses like 'J:J' (1,048,576 rows) are
             intersected with UsedRange so only the data region is read.
          2. _normalize_values — converts xlwings' inconsistent return shapes into
             a proper 2D list, using actual range dimensions to distinguish single-row
             from single-column (both return flat lists from xlwings).
          3. _trim_trailing_empty — strips bottom rows that are all None/empty,
             which handles stale UsedRange extents from cleared-but-not-deleted cells.

        Together these prevent token overflow: 'J:J' on a 300-row dataset returns
        ~300 rows, not 1M (clip) and not 1000 if rows 301-1000 were cleared (trim).
        """
        rng = self._resolve_range(sheet_name, address, clip_to_used=True)
        values = rng.value
        rows = self._normalize_values(values, rng)
        rows = self._trim_trailing_empty(rows)
        return {
            "sheet": sheet_name,
            "address": rng.address,
            "row_count": len(rows),
            "column_count": len(rows[0]) if rows else 0,
            "values": rows,
        }

    def range_write(self, sheet_name: str, address: str, values: list[list]) -> dict:
        """Write values to a range. Formulas are auto-detected (strings starting with '=')."""
        rng = self._resolve_range(sheet_name, address)
        # Check for formulas
        has_formula = any(
            isinstance(v, str) and v.startswith("=")
            for row in values
            for v in row
        )
        if has_formula:
            # Write cell by cell for mixed formula/value content
            sheet = self.book.sheets[sheet_name]
            start_row = rng.row
            start_col = rng.column
            for r_idx, row in enumerate(values):
                for c_idx, val in enumerate(row):
                    cell = sheet.cells(start_row + r_idx, start_col + c_idx)
                    if isinstance(val, str) and val.startswith("="):
                        cell.formula = val
                    else:
                        cell.value = val
        else:
            rng.value = values
        return {"success": True, "address": rng.address}

    def range_read_formulas(self, sheet_name: str, address: str) -> dict:
        """
        Read formulas from a range.

        Same safety pipeline as range_read:
          1. clip_to_used — prevents reading 1M rows for full-column addresses
          2. COM .Formula returns a tuple-of-tuples (not a list), so we convert via
             _com_array_to_list. Single cells return a plain string.
          3. _trim_trailing_empty — strips trailing empties (formula empty cells
             return "" not None from COM .Formula property)
        """
        rng = self._resolve_range(sheet_name, address, clip_to_used=True)
        formulas = rng.api.Formula
        # Normalize COM array to Python list
        if isinstance(formulas, str):
            rows = [[formulas]]
        elif hasattr(formulas, '__iter__'):
            rows = _com_array_to_list(formulas)
        else:
            rows = [[formulas]]
        rows = self._trim_trailing_empty(rows)
        return {"sheet": sheet_name, "address": rng.address, "formulas": rows}

    def range_clear(self, sheet_name: str, address: str, contents_only: bool = False) -> dict:
        """Clear a range (contents only or everything including formatting)."""
        rng = self._resolve_range(sheet_name, address)
        if contents_only:
            rng.clear_contents()
        else:
            rng.clear()
        return {"success": True}

    def range_format(
        self,
        sheet_name: str,
        address: str,
        bold: bool | None = None,
        italic: bool | None = None,
        font_size: float | None = None,
        font_color: tuple[int, int, int] | None = None,
        bg_color: tuple[int, int, int] | None = None,
        number_format: str | None = None,
        h_align: str | None = None,
        v_align: str | None = None,
        wrap_text: bool | None = None,
    ) -> dict:
        """Apply formatting to a range."""
        rng = self._resolve_range(sheet_name, address)
        api = rng.api

        if bold is not None:
            api.Font.Bold = bold
        if italic is not None:
            api.Font.Italic = italic
        if font_size is not None:
            api.Font.Size = font_size
        if font_color is not None:
            r, g, b = font_color
            api.Font.Color = r + (g << 8) + (b << 16)
        if bg_color is not None:
            r, g, b = bg_color
            api.Interior.Color = r + (g << 8) + (b << 16)
        if number_format is not None:
            api.NumberFormat = number_format
        if h_align is not None:
            from .constants import XL_HALIGN_LEFT, XL_HALIGN_CENTER, XL_HALIGN_RIGHT
            align_map = {"left": XL_HALIGN_LEFT, "center": XL_HALIGN_CENTER, "right": XL_HALIGN_RIGHT}
            if h_align in align_map:
                api.HorizontalAlignment = align_map[h_align]
        if v_align is not None:
            from .constants import XL_VALIGN_TOP, XL_VALIGN_CENTER, XL_VALIGN_BOTTOM
            align_map = {"top": XL_VALIGN_TOP, "center": XL_VALIGN_CENTER, "bottom": XL_VALIGN_BOTTOM}
            if v_align in align_map:
                api.VerticalAlignment = align_map[v_align]
        if wrap_text is not None:
            api.WrapText = wrap_text

        return {"success": True}

    def range_merge(self, sheet_name: str, address: str) -> dict:
        """Merge cells in range."""
        self._resolve_range(sheet_name, address).api.Merge()
        return {"success": True}

    def range_unmerge(self, sheet_name: str, address: str) -> dict:
        """Unmerge cells in range."""
        self._resolve_range(sheet_name, address).api.UnMerge()
        return {"success": True}

    def range_autofit(self, sheet_name: str, address: str, columns: bool = True, rows: bool = True) -> dict:
        """Autofit columns and/or rows for a range."""
        rng = self._resolve_range(sheet_name, address)
        if columns:
            rng.columns.autofit()
        if rows:
            rng.rows.autofit()
        return {"success": True}

    def range_sort(
        self,
        sheet_name: str,
        address: str,
        key_column: int = 1,
        ascending: bool = True,
        has_header: bool = True,
    ) -> dict:
        """Sort a range by a column."""
        rng = self._resolve_range(sheet_name, address)
        key_cell = rng.columns[key_column - 1][0]  # xlwings is 0-indexed for slicing
        order = XL_ASCENDING if ascending else XL_DESCENDING
        header = XL_YES if has_header else XL_GUESS
        rng.api.Sort(
            Key1=key_cell.api,
            Order1=order,
            Header=header,
        )
        return {"success": True}

    def range_find(self, sheet_name: str, search_text: str, address: str | None = None) -> dict | None:
        """Find first cell containing search_text. Returns None if not found."""
        sheet = self.book.sheets[sheet_name]
        search_range = sheet.range(address).api if address else sheet.api.Cells
        found = search_range.Find(What=search_text)
        if found is None:
            return None
        return {"address": found.Address, "value": found.Value2}

    def range_replace(self, sheet_name: str, find_text: str, replace_text: str, address: str | None = None) -> dict:
        """Find and replace text in a range or entire sheet."""
        sheet = self.book.sheets[sheet_name]
        search_range = sheet.range(address).api if address else sheet.api.Cells
        replaced = search_range.Replace(What=find_text, Replacement=replace_text)
        return {"success": bool(replaced)}

    def range_insert_rows(self, sheet_name: str, address: str, count: int = 1) -> dict:
        """Insert rows above the specified range."""
        rng = self._resolve_range(sheet_name, address)
        for _ in range(count):
            rng.api.EntireRow.Insert()
        return {"success": True}

    def range_delete_rows(self, sheet_name: str, address: str) -> dict:
        """Delete the rows covered by the range."""
        rng = self._resolve_range(sheet_name, address)
        rng.api.EntireRow.Delete()
        return {"success": True}

    def range_insert_columns(self, sheet_name: str, address: str, count: int = 1) -> dict:
        """Insert columns to the left of the specified range."""
        rng = self._resolve_range(sheet_name, address)
        for _ in range(count):
            rng.api.EntireColumn.Insert()
        return {"success": True}

    def range_delete_columns(self, sheet_name: str, address: str) -> dict:
        """Delete the columns covered by the range."""
        rng = self._resolve_range(sheet_name, address)
        rng.api.EntireColumn.Delete()
        return {"success": True}

    def range_used(self, sheet_name: str) -> dict:
        """Get the used range address of a sheet."""
        sheet = self.book.sheets[sheet_name]
        used = sheet.used_range
        return {
            "address": used.address,
            "row_count": used.rows.count,
            "column_count": used.columns.count,
            "last_cell": used.last_cell.address,
        }

    def range_summary(self, sheet_name: str, address: str) -> dict:
        """
        Get statistical summary of a numeric range without returning all values.

        Why this exists:
          When the agent needs min/max/avg/count of a column (e.g. Annual Salary),
          reading all 1000 values into the context window just to compute stats is
          wasteful and risks token overflow. This uses Excel's built-in worksheet
          functions (COUNTA, MIN, MAX, AVERAGE, SUM, MEDIAN) which run inside Excel
          and return only the 6 summary numbers.

        Uses Application.WorksheetFunction — the same engine Excel uses for cell
        formulas, so results are identical to what =MIN(J2:J1001) would produce.
        """
        rng = self._resolve_range(sheet_name, address, clip_to_used=True)
        ws_func = self._app.api.WorksheetFunction
        try:
            return {
                "address": rng.address,
                "count": int(ws_func.CountA(rng.api)),
                "numeric_count": int(ws_func.Count(rng.api)),
                "sum": ws_func.Sum(rng.api),
                "min": ws_func.Min(rng.api),
                "max": ws_func.Max(rng.api),
                "average": round(ws_func.Average(rng.api), 2),
                "median": ws_func.Median(rng.api),
            }
        except Exception as e:
            return {"address": rng.address, "error": f"Summary failed (range may not be numeric): {e}"}

    def range_set_hyperlink(
        self, sheet_name: str, address: str, url: str, display_text: str | None = None
    ) -> dict:
        """Add a hyperlink to a cell."""
        rng = self._resolve_range(sheet_name, address)
        sheet = self.book.sheets[sheet_name]
        sheet.api.Hyperlinks.Add(
            Anchor=rng.api,
            Address=url,
            TextToDisplay=display_text or url,
        )
        return {"success": True}

    def range_set_validation(
        self,
        sheet_name: str,
        address: str,
        validation_type: str = "list",
        formula: str = "",
    ) -> dict:
        """Set data validation on a range. type='list' with formula='A,B,C'."""
        rng = self._resolve_range(sheet_name, address)
        # xlValidateList = 3
        val_type_map = {"list": 3, "whole": 1, "decimal": 2, "date": 4, "text_length": 6}
        vt = val_type_map.get(validation_type, 3)
        rng.api.Validation.Delete()
        # xlValidAlertStop = 1, xlBetween = 1
        rng.api.Validation.Add(Type=vt, AlertStyle=1, Operator=1, Formula1=formula)
        return {"success": True}

    # ─────────────────────────────────────────────
    # TABLES (ListObjects)
    # ─────────────────────────────────────────────

    def _find_table(self, table_name: str):
        """Find a table (ListObject) by name across all sheets. Returns (sheet_api, table_api)."""
        for sheet in self.book.sheets:
            for lo in sheet.api.ListObjects:
                if lo.Name.lower() == table_name.lower():
                    return sheet, lo
        raise ExcelError(f"Table '{table_name}' not found in workbook.")

    def table_list(self) -> list[dict]:
        """List all tables in the workbook."""
        tables = []
        for sheet in self.book.sheets:
            for lo in sheet.api.ListObjects:
                cols = [lo.ListColumns(i).Name for i in range(1, lo.ListColumns.Count + 1)]
                row_count = 0
                if lo.DataBodyRange is not None:
                    row_count = lo.DataBodyRange.Rows.Count
                tables.append({
                    "name": lo.Name,
                    "sheet": sheet.name,
                    "range": lo.Range.Address,
                    "has_headers": bool(lo.ShowHeaders),
                    "show_totals": bool(lo.ShowTotals),
                    "row_count": row_count,
                    "column_count": lo.ListColumns.Count,
                    "columns": cols,
                    "style": getattr(lo.TableStyle, "Name", "") if lo.TableStyle else "",
                })
        return tables

    def table_create(
        self,
        sheet_name: str,
        range_address: str,
        table_name: str,
        has_headers: bool = True,
        style: str | None = None,
    ) -> dict:
        """Create a table from a range."""
        sheet = self.book.sheets[sheet_name]
        rng_api = sheet.range(range_address).api

        # Auto-expand single cell to CurrentRegion (matches C# behavior)
        if ":" not in range_address:
            cr = rng_api.CurrentRegion
            if cr.Cells.Count > 1:
                rng_api = cr

        header_opt = XL_YES if has_headers else XL_GUESS
        table = sheet.api.ListObjects.Add(XL_SRC_RANGE, rng_api, None, header_opt)
        table.Name = table_name

        if style:
            table.TableStyle = style

        return {"success": True, "name": table_name, "range": table.Range.Address}

    def table_read(self, table_name: str) -> dict:
        """Get table metadata."""
        _, lo = self._find_table(table_name)
        cols = [lo.ListColumns(i).Name for i in range(1, lo.ListColumns.Count + 1)]
        row_count = lo.DataBodyRange.Rows.Count if lo.DataBodyRange else 0
        return {
            "name": lo.Name,
            "range": lo.Range.Address,
            "has_headers": bool(lo.ShowHeaders),
            "show_totals": bool(lo.ShowTotals),
            "row_count": row_count,
            "column_count": lo.ListColumns.Count,
            "columns": cols,
        }

    def table_get_data(self, table_name: str, visible_only: bool = False) -> dict:
        """Get all data from a table as a 2D list."""
        _, lo = self._find_table(table_name)
        headers = [lo.ListColumns(i).Name for i in range(1, lo.ListColumns.Count + 1)]
        data = []
        if lo.DataBodyRange is not None:
            if visible_only:
                # Use SpecialCells to get only visible cells
                try:
                    visible = lo.DataBodyRange.SpecialCells(12)  # xlCellTypeVisible
                    raw = visible.Value2
                except Exception:
                    raw = lo.DataBodyRange.Value2
            else:
                raw = lo.DataBodyRange.Value2
            data = _com_array_to_list(raw) if raw is not None else []
        return {"headers": headers, "data": data, "row_count": len(data)}

    def table_add_row(self, table_name: str, values: list | None = None) -> dict:
        """Append a row to a table."""
        _, lo = self._find_table(table_name)
        new_row = lo.ListRows.Add()
        if values:
            for i, val in enumerate(values):
                new_row.Range.Cells(1, i + 1).Value2 = val
        return {"success": True, "row_index": new_row.Index}

    def table_add_column(self, table_name: str, column_name: str, position: int | None = None) -> dict:
        """Add a column to a table."""
        _, lo = self._find_table(table_name)
        if position is not None:
            col = lo.ListColumns.Add(position)
        else:
            col = lo.ListColumns.Add()
        col.Name = column_name
        return {"success": True, "name": column_name}

    def table_rename(self, table_name: str, new_name: str) -> dict:
        """Rename a table."""
        _, lo = self._find_table(table_name)
        lo.Name = new_name
        return {"success": True, "name": new_name}

    def table_delete(self, table_name: str) -> dict:
        """Convert table back to range (unlist), effectively deleting the table structure."""
        _, lo = self._find_table(table_name)
        lo.Unlist()
        return {"success": True}

    def table_resize(self, table_name: str, new_range: str) -> dict:
        """Resize a table to a new range."""
        sheet, lo = self._find_table(table_name)
        rng = sheet.range(new_range).api
        lo.Resize(rng)
        return {"success": True, "range": lo.Range.Address}

    def table_toggle_totals(self, table_name: str, show: bool) -> dict:
        """Show or hide the totals row."""
        _, lo = self._find_table(table_name)
        lo.ShowTotals = show
        return {"success": True}

    def table_set_column_total(
        self, table_name: str, column_name: str, function: str = "sum"
    ) -> dict:
        """Set a totals row function for a column. Functions: sum, count, average, max, min, none."""
        _, lo = self._find_table(table_name)
        # Find column
        col = None
        for i in range(1, lo.ListColumns.Count + 1):
            if lo.ListColumns(i).Name.lower() == column_name.lower():
                col = lo.ListColumns(i)
                break
        if col is None:
            raise ExcelError(f"Column '{column_name}' not found in table '{table_name}'.")
        # xlTotalsCalculation values
        func_map = {
            "none": 0, "sum": 109, "count": 110, "average": 101,
            "max": 104, "min": 105, "stddev": 107, "var": 108, "count_nums": 102,
        }
        if function.lower() not in func_map:
            raise ExcelError(f"Unknown function '{function}'. Use: {', '.join(func_map.keys())}")
        lo.ShowTotals = True
        col.TotalsCalculation = func_map[function.lower()]
        return {"success": True}

    def table_sort(
        self, table_name: str, column_name: str, ascending: bool = True
    ) -> dict:
        """Sort a table by column."""
        _, lo = self._find_table(table_name)
        # Find column range for sort key
        col = None
        for i in range(1, lo.ListColumns.Count + 1):
            if lo.ListColumns(i).Name.lower() == column_name.lower():
                col = lo.ListColumns(i)
                break
        if col is None:
            raise ExcelError(f"Column '{column_name}' not found.")
        order = XL_ASCENDING if ascending else XL_DESCENDING
        lo.Sort.SortFields.Clear()
        lo.Sort.SortFields.Add(Key=col.DataBodyRange, Order=order)
        lo.Sort.Apply()
        return {"success": True}

    def table_filter(self, table_name: str, column_name: str, criteria: str) -> dict:
        """Apply an AutoFilter to a table column."""
        _, lo = self._find_table(table_name)
        col_idx = None
        for i in range(1, lo.ListColumns.Count + 1):
            if lo.ListColumns(i).Name.lower() == column_name.lower():
                col_idx = i
                break
        if col_idx is None:
            raise ExcelError(f"Column '{column_name}' not found.")
        lo.Range.AutoFilter(Field=col_idx, Criteria1=criteria)
        return {"success": True}

    def table_clear_filters(self, table_name: str) -> dict:
        """Clear all filters from a table."""
        _, lo = self._find_table(table_name)
        if lo.AutoFilter is not None:
            lo.AutoFilter.ShowAllData()
        return {"success": True}

    def table_set_style(self, table_name: str, style: str) -> dict:
        """Set table style (e.g. 'TableStyleMedium2')."""
        _, lo = self._find_table(table_name)
        lo.TableStyle = style
        return {"success": True}

    # ─────────────────────────────────────────────
    # CHARTS
    # ─────────────────────────────────────────────

    def _find_chart_shape(self, chart_name: str):
        """Find a chart shape by name. Returns (sheet, shape) or raises."""
        for sheet in self.book.sheets:
            for shape in sheet.api.Shapes:
                if shape.Type == MSO_CHART and shape.Name.lower() == chart_name.lower():
                    return sheet, shape
        raise ExcelError(f"Chart '{chart_name}' not found.")

    def chart_list(self) -> list[dict]:
        """List all charts in the workbook."""
        charts = []
        for sheet in self.book.sheets:
            for shape in sheet.api.Shapes:
                if shape.Type == MSO_CHART:
                    ch = shape.Chart
                    charts.append({
                        "name": shape.Name,
                        "sheet": sheet.name,
                        "chart_type": ch.ChartType,
                        "has_title": bool(ch.HasTitle),
                        "title": ch.ChartTitle.Text if ch.HasTitle else None,
                        "left": shape.Left,
                        "top": shape.Top,
                        "width": shape.Width,
                        "height": shape.Height,
                    })
        return charts

    def chart_create(
        self,
        sheet_name: str,
        source_range: str,
        chart_type: str = "column_clustered",
        chart_name: str | None = None,
        left: float = 0,
        top: float = 0,
        width: float = 400,
        height: float = 300,
        target_range: str | None = None,
    ) -> dict:
        """Create a chart from a range."""
        ct = CHART_TYPE_MAP.get(chart_type)
        if ct is None:
            raise ExcelError(f"Unknown chart type '{chart_type}'. Use: {', '.join(CHART_TYPE_MAP.keys())}")

        sheet = self.book.sheets[sheet_name]
        sheet_api = sheet.api

        # Resolve position from target_range if given
        if target_range:
            tr = sheet.range(target_range).api
            left, top, width, height = tr.Left, tr.Top, tr.Width, tr.Height

        # Auto-position below content if no explicit position
        elif left == 0 and top == 0:
            used = sheet.used_range
            top = used.last_cell.top + used.last_cell.height + 10

        shape = sheet_api.Shapes.AddChart(
            XlChartType=ct,
            Left=left,
            Top=top,
            Width=width,
            Height=height,
        )
        chart = shape.Chart

        # Set source data
        full_addr = f"'{sheet_name}'!{source_range}" if "!" not in source_range else source_range
        source_rng = self._app.api.Range(full_addr)
        chart.SetSourceData(source_rng)

        if chart_name:
            shape.Name = chart_name

        return {
            "success": True,
            "name": shape.Name,
            "chart_type": chart_type,
            "left": shape.Left,
            "top": shape.Top,
            "width": shape.Width,
            "height": shape.Height,
        }

    def chart_create_from_table(
        self,
        table_name: str,
        sheet_name: str,
        chart_type: str = "column_clustered",
        chart_name: str | None = None,
        left: float = 0,
        top: float = 0,
        width: float = 400,
        height: float = 300,
    ) -> dict:
        """Create a chart from a table's data."""
        _, lo = self._find_table(table_name)
        ct = CHART_TYPE_MAP.get(chart_type)
        if ct is None:
            raise ExcelError(f"Unknown chart type '{chart_type}'.")

        sheet = self.book.sheets[sheet_name]

        if left == 0 and top == 0:
            used = sheet.used_range
            top = used.last_cell.top + used.last_cell.height + 10

        shape = sheet.api.Shapes.AddChart(XlChartType=ct, Left=left, Top=top, Width=width, Height=height)
        shape.Chart.SetSourceData(lo.Range)

        if chart_name:
            shape.Name = chart_name

        return {"success": True, "name": shape.Name, "chart_type": chart_type}

    def chart_set_title(self, chart_name: str, title: str) -> dict:
        """Set or update a chart's title."""
        _, shape = self._find_chart_shape(chart_name)
        shape.Chart.HasTitle = True
        shape.Chart.ChartTitle.Text = title
        return {"success": True}

    def chart_set_type(self, chart_name: str, chart_type: str) -> dict:
        """Change a chart's type."""
        ct = CHART_TYPE_MAP.get(chart_type)
        if ct is None:
            raise ExcelError(f"Unknown chart type '{chart_type}'.")
        _, shape = self._find_chart_shape(chart_name)
        shape.Chart.ChartType = ct
        return {"success": True}

    def chart_set_source(self, chart_name: str, sheet_name: str, source_range: str) -> dict:
        """Change a chart's data source."""
        _, shape = self._find_chart_shape(chart_name)
        full_addr = f"'{sheet_name}'!{source_range}" if "!" not in source_range else source_range
        source_rng = self._app.api.Range(full_addr)
        shape.Chart.SetSourceData(source_rng)
        return {"success": True}

    def chart_move(
        self, chart_name: str,
        left: float | None = None, top: float | None = None,
        width: float | None = None, height: float | None = None,
    ) -> dict:
        """Move or resize a chart."""
        _, shape = self._find_chart_shape(chart_name)
        if left is not None:
            shape.Left = left
        if top is not None:
            shape.Top = top
        if width is not None:
            shape.Width = width
        if height is not None:
            shape.Height = height
        return {"success": True}

    def chart_delete(self, chart_name: str) -> dict:
        """Delete a chart."""
        _, shape = self._find_chart_shape(chart_name)
        shape.Delete()
        return {"success": True}

    def chart_set_legend(self, chart_name: str, show: bool, position: str | None = None) -> dict:
        """Show/hide chart legend. Position: bottom, top, left, right, corner."""
        _, shape = self._find_chart_shape(chart_name)
        shape.Chart.HasLegend = show
        if show and position:
            pos_map = {"bottom": -4107, "top": -4160, "left": -4131, "right": -4152, "corner": 2}
            if position in pos_map:
                shape.Chart.Legend.Position = pos_map[position]
        return {"success": True}

    def chart_set_axis_title(
        self, chart_name: str, axis: str, title: str
    ) -> dict:
        """Set axis title. axis='x' (category) or 'y' (value)."""
        _, shape = self._find_chart_shape(chart_name)
        ch = shape.Chart
        # xlCategory = 1, xlValue = 2
        axis_type = 1 if axis.lower() == "x" else 2
        ax = ch.Axes(axis_type)
        ax.HasTitle = True
        ax.AxisTitle.Text = title
        return {"success": True}

    # ─────────────────────────────────────────────
    # PIVOT TABLES
    # ─────────────────────────────────────────────

    def _find_pivot_table(self, name: str):
        """Find a PivotTable by name. Returns (sheet, pivot_table_api)."""
        for sheet in self.book.sheets:
            for pt in sheet.api.PivotTables():
                if pt.Name.lower() == name.lower():
                    return sheet, pt
        raise ExcelError(f"PivotTable '{name}' not found.")

    def pivot_list(self) -> list[dict]:
        """List all PivotTables."""
        pivots = []
        for sheet in self.book.sheets:
            for pt in sheet.api.PivotTables():
                pivots.append({
                    "name": pt.Name,
                    "sheet": sheet.name,
                    "source": str(pt.SourceData) if hasattr(pt, 'SourceData') else "unknown",
                    "range": pt.TableRange2.Address,
                })
        return pivots

    def pivot_create_from_range(
        self,
        source_sheet: str,
        source_range: str,
        dest_sheet: str,
        dest_cell: str,
        pivot_name: str,
    ) -> dict:
        """Create a PivotTable from a worksheet range."""
        book_api = self.book.api

        # Validate source
        src_ws = book_api.Worksheets(source_sheet)
        src_rng = src_ws.Range(source_range)
        if src_rng.Rows.Count < 2:
            raise ExcelError("Source range must have headers + at least 1 data row.")

        # Create PivotCache (xlDatabase=1, xlPivotTableVersion14=4)
        source_ref = f"'{source_sheet}'!{source_range}"
        cache = book_api.PivotCaches().Create(
            SourceType=XL_DATABASE,
            SourceData=source_ref,
            Version=XL_PIVOT_TABLE_VERSION_14,
        )

        # Create PivotTable
        dest_ws = book_api.Worksheets(dest_sheet)
        dest_rng = dest_ws.Range(dest_cell)
        pt = cache.CreatePivotTable(
            TableDestination=dest_rng,
            TableName=pivot_name,
        )
        pt.RefreshTable()

        # Get available fields from headers
        header_row = src_rng.Rows(1)
        headers_raw = header_row.Value2
        fields = _extract_headers(headers_raw)

        return {
            "success": True,
            "name": pivot_name,
            "sheet": dest_sheet,
            "range": pt.TableRange2.Address,
            "source": source_ref,
            "available_fields": fields,
        }

    def pivot_create_from_table(
        self,
        table_name: str,
        dest_sheet: str,
        dest_cell: str,
        pivot_name: str,
    ) -> dict:
        """Create a PivotTable from an Excel Table."""
        _, lo = self._find_table(table_name)
        book_api = self.book.api

        if lo.Range.Rows.Count < 2:
            raise ExcelError(f"Table '{table_name}' must have at least 1 data row.")

        headers = [lo.ListColumns(i).Name for i in range(1, lo.ListColumns.Count + 1)]

        source_ref = f"{lo.Parent.Name}!{lo.Name}"
        cache = book_api.PivotCaches().Create(SourceType=XL_DATABASE, SourceData=source_ref)

        dest_ws = book_api.Worksheets(dest_sheet)
        dest_rng = dest_ws.Range(dest_cell)
        pt = cache.CreatePivotTable(TableDestination=dest_rng, TableName=pivot_name)
        pt.RefreshTable()

        return {
            "success": True,
            "name": pivot_name,
            "sheet": dest_sheet,
            "range": pt.TableRange2.Address,
            "available_fields": headers,
        }

    def pivot_add_field(
        self,
        pivot_name: str,
        field_name: str,
        area: str,
        position: int | None = None,
        function: str = "sum",
        custom_name: str | None = None,
        number_format: str | None = None,
    ) -> dict:
        """Add a field to a PivotTable area.

        area: 'row', 'column', 'filter', 'value'
        function: 'sum', 'count', 'average', 'max', 'min' (for value fields only)
        """
        _, pt = self._find_pivot_table(pivot_name)

        area_map = {
            "row": XL_ROW_FIELD,
            "column": XL_COLUMN_FIELD,
            "filter": XL_PAGE_FIELD,
            "value": XL_DATA_FIELD,
        }
        if area not in area_map:
            raise ExcelError(f"Invalid area '{area}'. Use: row, column, filter, value")

        pf = pt.PivotFields(field_name)
        orientation = area_map[area]

        if area == "value":
            # For value fields, set orientation and function
            pf.Orientation = orientation
            func_const = AGGREGATION_MAP.get(function.lower(), AGGREGATION_MAP["sum"])
            pf.Function = func_const
            if custom_name:
                pf.Caption = custom_name
            if number_format:
                pf.NumberFormat = number_format
        else:
            pf.Orientation = orientation
            if position is not None:
                pf.Position = position
            if custom_name:
                pf.Caption = custom_name

        return {"success": True}

    def pivot_remove_field(self, pivot_name: str, field_name: str) -> dict:
        """Remove a field from PivotTable (set orientation to hidden=0)."""
        _, pt = self._find_pivot_table(pivot_name)
        pf = pt.PivotFields(field_name)
        pf.Orientation = 0  # xlHidden
        return {"success": True}

    def pivot_list_fields(self, pivot_name: str) -> dict:
        """List all fields and their current area assignment."""
        _, pt = self._find_pivot_table(pivot_name)
        area_names = {0: "hidden", 1: "row", 2: "column", 3: "filter", 4: "value"}
        fields = []
        for pf in pt.PivotFields():
            fields.append({
                "name": pf.Name,
                "caption": pf.Caption,
                "area": area_names.get(pf.Orientation, "unknown"),
                "position": pf.Position if pf.Orientation != 0 else None,
            })
        return {"fields": fields}

    def pivot_refresh(self, pivot_name: str) -> dict:
        """Refresh a PivotTable."""
        _, pt = self._find_pivot_table(pivot_name)
        pt.RefreshTable()
        return {"success": True}

    def pivot_set_layout(self, pivot_name: str, layout: str = "tabular") -> dict:
        """Set PivotTable layout: 'compact', 'tabular', 'outline'."""
        _, pt = self._find_pivot_table(pivot_name)
        if layout == "compact":
            pt.RowAxisLayout(0)  # xlCompactRow
        elif layout == "tabular":
            pt.RowAxisLayout(1)  # xlTabularRow
        elif layout == "outline":
            pt.RowAxisLayout(2)  # xlOutlineRow
        else:
            raise ExcelError(f"Unknown layout '{layout}'. Use: compact, tabular, outline")
        return {"success": True}

    def pivot_set_subtotals(self, pivot_name: str, field_name: str, show: bool) -> dict:
        """Show or hide subtotals for a row/column field."""
        _, pt = self._find_pivot_table(pivot_name)
        pf = pt.PivotFields(field_name)
        if show:
            # xlAutomatic subtotals
            pf.Subtotals = [True] + [False] * 11  # 12-element tuple, first = Auto
        else:
            pf.Subtotals = [False] * 12
        return {"success": True}

    def pivot_set_grand_totals(self, pivot_name: str, rows: bool | None = None, columns: bool | None = None) -> dict:
        """Show/hide grand totals for rows and/or columns."""
        _, pt = self._find_pivot_table(pivot_name)
        if rows is not None:
            pt.RowGrand = rows
        if columns is not None:
            pt.ColumnGrand = columns
        return {"success": True}

    def pivot_sort_field(self, pivot_name: str, field_name: str, ascending: bool = True) -> dict:
        """Sort a PivotTable field."""
        _, pt = self._find_pivot_table(pivot_name)
        pf = pt.PivotFields(field_name)
        order = XL_ASCENDING if ascending else XL_DESCENDING
        pf.AutoSort(order, field_name)
        return {"success": True}

    def pivot_filter_field(self, pivot_name: str, field_name: str, values: list[str]) -> dict:
        """Filter a PivotTable field to show only specific values."""
        _, pt = self._find_pivot_table(pivot_name)
        pf = pt.PivotFields(field_name)
        # Clear existing filter, then set visible items
        pf.ClearAllFilters()
        # Hide all items, then show only the ones in values
        for item in pf.PivotItems():
            item.Visible = item.Name in values
        return {"success": True}

    def pivot_delete(self, pivot_name: str) -> dict:
        """Delete a PivotTable by clearing its range."""
        _, pt = self._find_pivot_table(pivot_name)
        pt.TableRange2.Clear()
        return {"success": True}

    def pivot_set_field_number_format(
        self, pivot_name: str, field_name: str, number_format: str
    ) -> dict:
        """Set number format for a value field (e.g. '#,##0.00', '0%')."""
        _, pt = self._find_pivot_table(pivot_name)
        pf = pt.PivotFields(field_name)
        pf.NumberFormat = number_format
        return {"success": True}

    # ─────────────────────────────────────────────
    # CALCULATION
    # ─────────────────────────────────────────────

    def calc_get_mode(self) -> dict:
        """Get the current calculation mode."""
        mode = self._app.api.Calculation
        mode_name = {
            XL_CALCULATION_AUTOMATIC: "automatic",
            XL_CALCULATION_MANUAL: "manual",
            XL_CALCULATION_SEMIAUTOMATIC: "semiautomatic",
        }.get(mode, f"unknown({mode})")
        return {"mode": mode_name, "raw": mode}

    def calc_set_mode(self, mode: str) -> dict:
        """Set calculation mode: 'automatic', 'manual', 'semiautomatic'."""
        mode_map = {
            "automatic": XL_CALCULATION_AUTOMATIC,
            "manual": XL_CALCULATION_MANUAL,
            "semiautomatic": XL_CALCULATION_SEMIAUTOMATIC,
        }
        if mode not in mode_map:
            raise ExcelError(f"Unknown mode '{mode}'. Use: automatic, manual, semiautomatic")
        self._app.api.Calculation = mode_map[mode]
        return {"success": True, "mode": mode}

    def calc_calculate(self, scope: str = "workbook", sheet_name: str | None = None) -> dict:
        """Force recalculation. scope: 'workbook', 'sheet', 'app'."""
        if scope == "workbook":
            self.book.api.Calculate()
        elif scope == "sheet" and sheet_name:
            self.book.sheets[sheet_name].api.Calculate()
        elif scope == "app":
            self._app.api.Calculate()
        else:
            raise ExcelError("For scope='sheet', provide sheet_name.")
        return {"success": True}

    # ─────────────────────────────────────────────
    # NAMED RANGES
    # ─────────────────────────────────────────────

    def named_range_list(self) -> list[dict]:
        """List all named ranges in the workbook."""
        results = []
        for name in self.book.api.Names:
            try:
                results.append({
                    "name": name.Name,
                    "refers_to": name.RefersTo,
                    "value": name.Value,
                    "visible": bool(name.Visible),
                })
            except Exception:
                # Some names may be invalid/broken
                results.append({"name": name.Name, "error": "cannot read"})
        return results

    def named_range_create(
        self, name: str, refers_to: str, scope: str = "workbook", sheet_name: str | None = None
    ) -> dict:
        """Create a named range. refers_to should be like '=Sheet1!$A$1:$B$10'."""
        if not refers_to.startswith("="):
            refers_to = f"={refers_to}"
        if scope == "workbook":
            self.book.api.Names.Add(Name=name, RefersTo=refers_to)
        elif scope == "sheet" and sheet_name:
            self.book.sheets[sheet_name].api.Names.Add(Name=name, RefersTo=refers_to)
        else:
            raise ExcelError("For scope='sheet', provide sheet_name.")
        return {"success": True, "name": name}

    def named_range_delete(self, name: str) -> dict:
        """Delete a named range."""
        for n in self.book.api.Names:
            if n.Name.lower() == name.lower():
                n.Delete()
                return {"success": True}
        raise ExcelError(f"Named range '{name}' not found.")

    def named_range_update(self, name: str, refers_to: str) -> dict:
        """Update a named range's reference."""
        if not refers_to.startswith("="):
            refers_to = f"={refers_to}"
        for n in self.book.api.Names:
            if n.Name.lower() == name.lower():
                n.RefersTo = refers_to
                return {"success": True}
        raise ExcelError(f"Named range '{name}' not found.")

    # ─────────────────────────────────────────────
    # CONDITIONAL FORMATTING
    # ─────────────────────────────────────────────

    def cond_format_add_rule(
        self,
        sheet_name: str,
        address: str,
        rule_type: str,
        operator: str | None = None,
        formula: str | None = None,
        value1: Any = None,
        value2: Any = None,
        font_color: tuple[int, int, int] | None = None,
        bg_color: tuple[int, int, int] | None = None,
    ) -> dict:
        """Add a conditional formatting rule.

        rule_type: 'cell_value', 'formula', 'duplicate', 'unique', 'top10', 'above_average'
        operator (for cell_value): 'between', 'greater', 'less', 'equal', 'not_equal',
                                    'greater_equal', 'less_equal'
        """
        rng = self._resolve_range(sheet_name, address).api

        # xlCellValue=1, xlExpression=2
        type_map = {"cell_value": 1, "formula": 2}
        op_map = {
            "between": 1, "not_between": 2, "equal": 3, "not_equal": 4,
            "greater": 5, "less": 6, "greater_equal": 7, "less_equal": 8,
        }

        if rule_type == "cell_value":
            op = op_map.get(operator or "equal", 3)
            kwargs = {"Type": 1, "Operator": op}
            if value1 is not None:
                kwargs["Formula1"] = str(value1)
            if value2 is not None:
                kwargs["Formula2"] = str(value2)
            fmt = rng.FormatConditions.Add(**kwargs)
        elif rule_type == "formula":
            if not formula:
                raise ExcelError("Formula required for rule_type='formula'.")
            fmt = rng.FormatConditions.Add(Type=2, Formula1=formula)
        elif rule_type == "duplicate":
            fmt = rng.FormatConditions.AddUniqueValues()
            fmt.DupeUnique = 1  # xlDuplicate
        elif rule_type == "unique":
            fmt = rng.FormatConditions.AddUniqueValues()
            fmt.DupeUnique = 0  # xlUnique
        elif rule_type == "top10":
            fmt = rng.FormatConditions.AddTop10()
            if value1 is not None:
                fmt.TopBottom = 1  # xlTop10Top
                fmt.Rank = int(value1)
        elif rule_type == "above_average":
            fmt = rng.FormatConditions.AddAboveAverage()
        else:
            raise ExcelError(f"Unknown rule_type '{rule_type}'.")

        # Apply formatting
        if font_color:
            r, g, b = font_color
            fmt.Font.Color = r + (g << 8) + (b << 16)
        if bg_color:
            r, g, b = bg_color
            fmt.Interior.Color = r + (g << 8) + (b << 16)

        return {"success": True, "rule_count": rng.FormatConditions.Count}

    def cond_format_clear(self, sheet_name: str, address: str) -> dict:
        """Clear all conditional formatting from a range."""
        rng = self._resolve_range(sheet_name, address).api
        rng.FormatConditions.Delete()
        return {"success": True}

    # ─────────────────────────────────────────────
    # SCREENSHOT
    # ─────────────────────────────────────────────

    def screenshot(self, sheet_name: str | None = None, range_address: str | None = None, path: str | None = None) -> dict:
        """Take a screenshot of the workbook, a sheet, or a range. Saves as PNG."""
        save_path = Path(path) if path else Path(os.environ.get("TEMP", "/tmp")) / "excel_screenshot.png"

        if range_address and sheet_name:
            rng = self._resolve_range(sheet_name, range_address)
            rng.api.CopyPicture(1, 2)  # xlScreen=1, xlBitmap=2
        elif sheet_name:
            sheet = self.book.sheets[sheet_name]
            sheet.used_range.api.CopyPicture(1, 2)
        else:
            sheet = self.book.sheets.active
            sheet.used_range.api.CopyPicture(1, 2)

        # Paste into a temp chart and export
        ws = self.book.sheets.active.api
        chart_obj = ws.ChartObjects().Add(0, 0, 800, 600)
        chart_obj.Chart.Paste()
        chart_obj.Chart.Export(str(save_path))
        chart_obj.Delete()

        return {"success": True, "path": str(save_path)}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _com_array_to_list(com_value) -> list[list]:
    """Convert COM VARIANT 2D array or single value to Python list of lists."""
    if com_value is None:
        return []
    if not isinstance(com_value, tuple):
        return [[com_value]]
    # COM returns tuple of tuples for 2D ranges
    result = []
    for row in com_value:
        if isinstance(row, tuple):
            result.append(list(row))
        else:
            result.append([row])
    return result


def _extract_headers(header_value) -> list[str]:
    """Extract header strings from a COM range value."""
    if header_value is None:
        return []
    rows = _com_array_to_list(header_value)
    if not rows:
        return []
    return [str(v) for v in rows[0] if v is not None]
