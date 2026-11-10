"""Build the STATZWeb copy of Cori's inventory workbook (BulkOrders + carried-through sheets)."""

from copy import copy
from io import BytesIO

from django.utils import timezone

from inventory.models import InventoryItem, InventorySyncRun
from inventory.sync.parser import (
    EXPORT_STAMP,
    INVENTORY_SHEET_TITLE,
    find_inventory_sheet,
    load_workbook_bytes,
    to_iso_utc,
)

FONT_NAME = 'Aptos Narrow'
FONT_SIZE = 11
CURRENCY_FORMAT = '"$"#,##0.00_);[Red]\\("$"#,##0.00\\)'
HEADERS = (
    'NSN', 'Description', 'Part Number', 'Manufacturer', 'Quantity', 'Quantity Remaining',
    'Purchase Price', 'Total Cost', 'Location', 'STATZ ID', 'STATZ Version',
)
COLUMN_WIDTHS = {
    'A': 20.43, 'B': 34.14, 'C': 26.57, 'D': 18.57, 'E': 10, 'F': 19,
    'G': 14, 'H': 14, 'I': 22, 'J': 10, 'K': 24,
}
HIDDEN_COLUMNS = ('J', 'K')
FIRST_DATA_ROW = 3
BORDERED_COLUMNS = 9
CURRENCY_COLUMNS = (7, 8)
XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def export_filename():
    return f'Inventory_Tracker_{timezone.localdate():%Y-%m-%d}.xlsx'


def _blank(value):
    return None if value is None or value == '' else value


def _latest_applied_bytes():
    data = (
        InventorySyncRun.objects.filter(status=InventorySyncRun.STATUS_APPLIED)
        .order_by('-applied_at')
        .values_list('file_bytes', flat=True)
        .first()
    )
    return bytes(data) if data else None


class _Styles:
    def __init__(self):
        from contracts.utils.excel_utils import Alignment, Border, Font, PatternFill, Side

        thin = Side()(style='thin')
        self.font = Font()(name=FONT_NAME, size=FONT_SIZE)
        self.header_font = Font()(name=FONT_NAME, size=FONT_SIZE, bold=True, color='FFFFFFFF')
        self.header_fill = PatternFill()(fill_type='solid', start_color='FF000000', end_color='FF000000')
        self.center = Alignment()(horizontal='center', vertical='center')
        self.border = Border()(left=thin, right=thin, top=thin, bottom=thin)

    def header(self, cell):
        cell.font = self.header_font
        cell.fill = self.header_fill
        cell.alignment = self.center
        cell.border = self.border

    def currency(self, cell):
        cell.font = self.font
        cell.number_format = CURRENCY_FORMAT
        cell.alignment = self.center


def _item_values(item, row):
    return (
        item.nsn, item.description, item.partnumber, item.manufacturer,
        item.quantity, item.quantity_remaining, item.purchaseprice,
        f'=IF(OR(E{row}="",G{row}=""),"",E{row}*G{row})',
        item.itemlocation, item.id, to_iso_utc(item.last_modified),
    )


def _write_inventory_sheet(ws, items, exported_at, styles):
    for coordinate, value in (('A1', 'Current Inventory'), ('J1', EXPORT_STAMP), ('K1', to_iso_utc(exported_at))):
        ws[coordinate] = value
        ws[coordinate].font = styles.font
    for column, title in enumerate(HEADERS, start=1):
        styles.header(ws.cell(row=2, column=column, value=title))

    for row, item in enumerate(items, start=FIRST_DATA_ROW):
        for column, value in enumerate(_item_values(item, row), start=1):
            cell = ws.cell(row=row, column=column, value=_blank(value))
            cell.font = styles.font
            if column <= BORDERED_COLUMNS:
                cell.border = styles.border
            if column in CURRENCY_COLUMNS:
                styles.currency(cell)

    last = FIRST_DATA_ROW - 1 + len(items)
    end = max(last, FIRST_DATA_ROW)
    totals = (
        ('TOTAL', f'=SUM(H{FIRST_DATA_ROW}:H{end})'),
        ('ON-HAND VALUE', (
            f'=SUMPRODUCT((F3:F{end}="")*E3:E{end}*G3:G{end})'
            f'+SUMPRODUCT((F3:F{end}<>"")*F3:F{end}*G3:G{end})'
        )),
    )
    for offset, (label, formula) in enumerate(totals, start=2):
        styles.header(ws.cell(row=last + offset, column=7, value=label))
        styles.currency(ws.cell(row=last + offset, column=8, value=formula))

    for letter, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[letter].width = width
    for letter in HIDDEN_COLUMNS:
        ws.column_dimensions[letter].hidden = True
    ws.freeze_panes = 'A3'
    ws.auto_filter.ref = f'A2:I{last}'


def _copy_extra_sheets(source_bytes, wb):
    source = load_workbook_bytes(source_bytes, data_only=False)
    inventory_ws, _ = find_inventory_sheet(source)
    skip_title = inventory_ws.title if inventory_ws is not None else None
    for src in source.worksheets:
        if src.title == skip_title or src.title in wb.sheetnames:
            continue
        dst = wb.create_sheet(src.title)
        for row in src.iter_rows():
            for cell in row:
                if cell.value is None and not cell.has_style:
                    continue
                target = dst.cell(row=cell.row, column=cell.column, value=cell.value)
                if cell.has_style:
                    target.number_format = cell.number_format
                    target.font = copy(cell.font)
                    target.fill = copy(cell.fill)
                    target.alignment = copy(cell.alignment)
        for merged in src.merged_cells.ranges:
            dst.merge_cells(str(merged))
        for key, dimension in src.column_dimensions.items():
            if dimension.width:
                target_dimension = dst.column_dimensions[key]
                target_dimension.width = dimension.width
                target_dimension.min = dimension.min
                target_dimension.max = dimension.max


def build_export():
    """Return (filename, xlsx_bytes) for the current inventory."""
    from contracts.utils.excel_utils import Workbook

    exported_at = timezone.now()
    items = list(InventoryItem.objects.order_by('id'))
    source_bytes = _latest_applied_bytes()

    wb = Workbook()()
    wb.properties.creator = 'STATZWeb'
    ws = wb.active
    ws.title = INVENTORY_SHEET_TITLE
    _write_inventory_sheet(ws, items, exported_at, _Styles())
    if source_bytes:
        _copy_extra_sheets(source_bytes, wb)

    buffer = BytesIO()
    wb.save(buffer)
    return export_filename(), buffer.getvalue()
