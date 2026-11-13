"""P100 reporting exports: pure Excel workbook builders (openpyxl) over plain dataclasses.

``tong_quan_xlsx`` -- the Tổng quan report; ``ke_hoach_xlsx`` -- the Kế hoạch report. The builders
hold no database access and invent no number: every figure is an input (from the app's service
functions, see ``collect``) or a formula over the sheet's own cells. No explanatory text goes into
a file (titles, headers, numbers only).
"""

from __future__ import annotations
