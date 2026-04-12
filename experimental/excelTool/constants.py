"""Excel COM constants and enum mappings for xlwings/.api calls."""

# --- XlListObjectSourceType ---
XL_SRC_RANGE = 1
XL_SRC_EXTERNAL = 2

# --- XlYesNoGuess (for table header detection) ---
XL_YES = 1
XL_NO = 2
XL_GUESS = 0

# --- XlCalculation ---
XL_CALCULATION_AUTOMATIC = -4105
XL_CALCULATION_MANUAL = -4135
XL_CALCULATION_SEMIAUTOMATIC = 2

# --- XlSheetVisibility ---
XL_SHEET_VISIBLE = -1
XL_SHEET_HIDDEN = 0
XL_SHEET_VERY_HIDDEN = 2

# --- XlPivotTableSourceType ---
XL_DATABASE = 1
XL_EXTERNAL = 2

# --- XlPivotTableVersionList ---
XL_PIVOT_TABLE_VERSION_14 = 4

# --- XlPivotFieldOrientation ---
XL_ROW_FIELD = 1
XL_COLUMN_FIELD = 2
XL_PAGE_FIELD = 3   # filter
XL_DATA_FIELD = 4   # values

# --- XlConsolidationFunction (for PivotTable value aggregation) ---
XL_SUM = -4157
XL_COUNT = -4112
XL_AVERAGE = -4106
XL_MAX = -4136
XL_MIN = -4139
XL_COUNT_NUMS = -4113
XL_STD_DEV = -4155
XL_VAR = -4164

AGGREGATION_MAP = {
    "sum": XL_SUM,
    "count": XL_COUNT,
    "average": XL_AVERAGE,
    "max": XL_MAX,
    "min": XL_MIN,
    "count_nums": XL_COUNT_NUMS,
    "stddev": XL_STD_DEV,
    "var": XL_VAR,
}

# --- XlChartType ---
CHART_TYPE_MAP = {
    "column_clustered": 51,
    "column_stacked": 52,
    "column_stacked_100": 53,
    "bar_clustered": 57,
    "bar_stacked": 58,
    "bar_stacked_100": 59,
    "line": 4,
    "line_markers": 65,
    "line_stacked": 63,
    "pie": 5,
    "pie_exploded": 69,
    "doughnut": -4120,
    "area": 1,
    "area_stacked": 76,
    "scatter": -4169,
    "scatter_lines": 74,
    "scatter_smooth": 73,
    "radar": -4151,
    "combo": -1,  # placeholder — combo needs AddChart2
    "waterfall": 1 + 150,  # xl constants for newer chart types
    "treemap": 117 + 35,
    "histogram": 118,
}

# --- XlShapeType ---
MSO_CHART = 3

# --- XlPivotTableLayoutRowType ---
XL_COMPACT_ROW = 0
XL_TABULAR_ROW = 1
XL_OUTLINE_ROW = 2

# --- XlSortOrder ---
XL_ASCENDING = 1
XL_DESCENDING = 2

# --- XlCellType ---
XL_CELL_TYPE_LAST_CELL = 11

# --- XlDeleteShiftDirection ---
XL_SHIFT_UP = -4162

# --- XlInsertShiftDirection ---
XL_SHIFT_DOWN = -4121

# --- XlBordersIndex ---
XL_EDGE_LEFT = 7
XL_EDGE_TOP = 8
XL_EDGE_BOTTOM = 9
XL_EDGE_RIGHT = 10
XL_INSIDE_VERTICAL = 11
XL_INSIDE_HORIZONTAL = 12

# --- XlLineStyle ---
XL_CONTINUOUS = 1
XL_DASH = -4115
XL_NONE = -4142

# --- XlHAlign ---
XL_HALIGN_LEFT = -4131
XL_HALIGN_CENTER = -4108
XL_HALIGN_RIGHT = -4152

# --- XlVAlign ---
XL_VALIGN_TOP = -4160
XL_VALIGN_CENTER = -4108
XL_VALIGN_BOTTOM = -4107

# --- Supported file extensions ---
VALID_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
