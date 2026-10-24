"""只读检查：以 UTF-8 输出工作簿结构、合并单元格与全部单元格内容。"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import openpyxl

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = Path(sys.argv[1])
wb = openpyxl.load_workbook(path, data_only=True)
print(f"文件: {path.name}")
print(f"工作表: {wb.sheetnames}")
for ws in wb.worksheets:
    print(f"\n{'='*72}\n[sheet] {ws.title}  dims={ws.dimensions}  max_row={ws.max_row} max_col={ws.max_column}")
    if ws.merged_cells.ranges:
        print(f"合并单元格: {[str(r) for r in ws.merged_cells.ranges]}")
    print("内容:")
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 100)):
        cells = [
            f"{c.coordinate}={c.value!r}"
            for c in row
            if c.value is not None and str(c.value).strip() != ""
        ]
        if cells:
            print("  " + " | ".join(cells))
