"""시트 -> CSV / 엑셀(xlsx) 파일. 행은 Participation·ContentPost·Payment 등 어떤 객체든 Column.get으로 읽는다."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse
from django.utils.http import content_disposition_header
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .columns import display

DATETIME_FORMAT = "yyyy-mm-dd hh:mm"
DATE_FORMAT = "yyyy-mm-dd"
OVERDUE_FILL = PatternFill("solid", fgColor="FECACA")  # 업로드 예정일 경과 행


def to_csv(rows, columns) -> bytes:
    """UTF-8 BOM 포함 — 엑셀에서 더블클릭으로 열어도 한글이 깨지지 않는다."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c.label for c in columns])
    for row in rows:
        writer.writerow([_csv_safe(display(c.get(row))) for c in columns])
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(rows, columns, *, title="시트", highlight=None) -> bytes:
    """`highlight(row)`가 참인 행은 빨간 배경으로 칠한다 (예: 업로드 예정일 경과)."""
    wb = Workbook()
    ws = wb.active
    ws.title = _sheet_title(title)

    ws.append([c.label for c in columns])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E2E8F0")
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        ws.append([_xlsx_value(c.get(row)) for c in columns])
        marked = highlight is not None and highlight(row)
        for cell in ws[ws.max_row]:
            if cell.data_type == "f":  # openpyxl이 '='로 시작하는 문자열을 수식으로 해석 -> 글자로 고정
                cell.data_type = "s"
            if marked:
                cell.fill = OVERDUE_FILL

    for idx, col in enumerate(columns, start=1):
        letter = get_column_letter(idx)
        ws.column_dimensions[letter].width = col.width
        for cell in ws[letter][1:]:
            if isinstance(cell.value, datetime):
                cell.number_format = DATETIME_FORMAT
            elif isinstance(cell.value, date):
                cell.number_format = DATE_FORMAT
            elif isinstance(cell.value, int):
                cell.number_format = "#,##0"
            elif isinstance(cell.value, (float, Decimal)):
                cell.number_format = "#,##0.00"
    ws.freeze_panes = "B2"
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(text):
    # 수식 주입 방지: 엑셀이 수식으로 해석할 수 있는 첫 글자 앞에 ' 를 붙인다
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _xlsx_value(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)  # 이미 현지 시각으로 변환된 값 (엑셀은 시간대 미지원)
    if isinstance(value, bool):
        return display(value)
    return "" if value is None else value


def _sheet_title(name):
    # 엑셀 워크시트 이름: 31자 이내, []:*?/\ 불가
    for ch in "[]:*?/\\":
        name = name.replace(ch, " ")
    return name.strip()[:31] or "시트"


XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def export_response(rows, columns, fmt, *, filename, title="시트", highlight=None):
    """rows -> 다운로드 응답. filename은 확장자 없이."""
    if fmt == "xlsx":
        body, content_type = to_xlsx(rows, columns, title=title, highlight=highlight), XLSX_CONTENT_TYPE
    else:
        body, content_type = to_csv(rows, columns), "text/csv; charset=utf-8"
    return HttpResponse(
        body,
        content_type=content_type,
        headers={"Content-Disposition": content_disposition_header(True, f"{filename}.{fmt}")},
    )
