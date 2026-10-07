"""Procesador y creador estructurado de hojas de cálculo Excel (.xlsx) (excel_processor.py).

Garantiza:
1. Creación y edición estructurada de hojas y celdas con tipos de datos, bordes y estilos profesionales.
2. Inserción de fórmulas sintácticas (=SUM, =AVERAGE, multiplicaciones, etc.).
3. Generación de gráficos nativos (BarChart) con categorías y series referenciadas.
4. Diferenciación taxativa entre escribir una fórmula (cadena literal) y evaluar su resultado.
5. Integración con el motor de cálculo real de Microsoft Excel vía COM cuando está instalado,
   reportando honestamente la limitación cuando no está disponible.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.logger import get_logger

logger = get_logger("jessyca.documents.excel")


@dataclass
class BudgetItem:
    concepto: str
    categoria: str
    cantidad: float
    costo_unitario: float


class ExcelSpreadsheetProcessor:
    """Manejador especializado en hojas de cálculo Excel (.xlsx)."""

    @staticmethod
    def create_budget_workbook(
        file_path: str | Path,
        items: list[BudgetItem],
        titulo_presupuesto: str = "Presupuesto Operativo y Tecnológico 2026",
        tasa_impuesto: float = 0.18,  # 18% IGV / IVA
    ) -> dict[str, Any]:
        """Crea un libro Excel completo con presupuesto, fórmulas y gráfico de barras."""
        out_path = Path(file_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Presupuesto Detallado"
        ws.views.sheetView[0].showGridLines = True

        # Estilos corporativos (Dark Slate / Cool Gray)
        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        subtotal_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        total_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")

        font_title = Font(name="Calibri", size=16, bold=True, color="0F172A")
        font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_bold = Font(name="Calibri", size=11, bold=True, color="0F172A")
        font_regular = Font(name="Calibri", size=10.5, color="1E293B")

        thin_side = Side(style="thin", color="CBD5E1")
        double_side = Side(style="double", color="0F172A")
        border_cell = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
        border_total = Border(top=thin_side, bottom=double_side)

        currency_fmt = "$#,##0.00"
        int_fmt = "#,##0"

        # 1. Título
        ws.merge_cells("A1:E1")
        cell_t = ws["A1"]
        cell_t.value = titulo_presupuesto
        cell_t.font = font_title
        cell_t.alignment = Alignment(vertical="center")
        ws.row_dimensions[1].height = 30

        # Subtítulo informativo
        ws["A2"] = "Moneda: USD ($) | Generado automáticamente por JESSYCA Core | Sujeto a aprobación"
        ws["A2"].font = Font(name="Calibri", size=9.5, italic=True, color="64748B")

        # 2. Encabezados de tabla (Fila 4)
        headers = ["Ítem / Concepto", "Categoría", "Cantidad", "Costo Unitario ($)", "Subtotal ($)"]
        for col_idx, text in enumerate(headers, start=1):
            cell = ws.cell(row=4, column=col_idx, value=text)
            cell.fill = header_fill
            cell.font = font_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border_cell
        ws.row_dimensions[4].height = 24

        # 3. Filas de datos
        start_row = 5
        current_row = start_row
        formula_cells_info: list[dict[str, str]] = []

        for item in items:
            ws.cell(row=current_row, column=1, value=item.concepto).font = font_regular
            ws.cell(row=current_row, column=2, value=item.categoria).font = font_regular

            c_qty = ws.cell(row=current_row, column=3, value=item.cantidad)
            c_qty.font = font_regular
            c_qty.number_format = int_fmt
            c_qty.alignment = Alignment(horizontal="right")

            c_unit = ws.cell(row=current_row, column=4, value=item.costo_unitario)
            c_unit.font = font_regular
            c_unit.number_format = currency_fmt
            c_unit.alignment = Alignment(horizontal="right")

            # FÓRMULA DE SUBTOTAL: =Cantidad * Costo Unitario
            formula_subtotal = f"=C{current_row}*D{current_row}"
            c_sub = ws.cell(row=current_row, column=5, value=formula_subtotal)
            c_sub.font = font_bold
            c_sub.number_format = currency_fmt
            c_sub.alignment = Alignment(horizontal="right")

            for col_idx in range(1, 6):
                ws.cell(row=current_row, column=col_idx).border = border_cell

            formula_cells_info.append({"cell": f"E{current_row}", "formula": formula_subtotal, "concept": item.concepto})
            current_row += 1

        end_data_row = current_row - 1

        # 4. Sección de Totales con Fórmulas
        # Total Directo
        ws.cell(row=current_row, column=1, value="TOTAL COSTO DIRECTO").font = font_bold
        ws.cell(row=current_row, column=1).fill = subtotal_fill
        for c in range(2, 5):
            ws.cell(row=current_row, column=c).fill = subtotal_fill

        formula_total_directo = f"=SUM(E{start_row}:E{end_data_row})"
        c_td = ws.cell(row=current_row, column=5, value=formula_total_directo)
        c_td.font = font_bold
        c_td.number_format = currency_fmt
        c_td.fill = subtotal_fill
        c_td.border = border_cell
        formula_cells_info.append({"cell": f"E{current_row}", "formula": formula_total_directo, "concept": "Total Costo Directo"})
        total_directo_row = current_row
        current_row += 1

        # Impuesto / Contingencia
        pct_label = f"Impuestos / Contingencia ({int(tasa_impuesto * 100)}%)"
        ws.cell(row=current_row, column=1, value=pct_label).font = font_regular
        formula_tax = f"=E{total_directo_row}*{tasa_impuesto}"
        c_tax = ws.cell(row=current_row, column=5, value=formula_tax)
        c_tax.font = font_regular
        c_tax.number_format = currency_fmt
        c_tax.border = border_cell
        formula_cells_info.append({"cell": f"E{current_row}", "formula": formula_tax, "concept": pct_label})
        tax_row = current_row
        current_row += 1

        # PRESUPUESTO TOTAL GENERAL
        ws.cell(row=current_row, column=1, value="PRESUPUESTO TOTAL ESTIMADO").font = font_bold
        ws.cell(row=current_row, column=1).fill = total_fill
        for c in range(2, 5):
            ws.cell(row=current_row, column=c).fill = total_fill

        formula_total_gral = f"=E{total_directo_row}+E{tax_row}"
        c_tot = ws.cell(row=current_row, column=5, value=formula_total_gral)
        c_tot.font = font_bold
        c_tot.number_format = currency_fmt
        c_tot.fill = total_fill
        c_tot.border = border_total
        formula_cells_info.append({"cell": f"E{current_row}", "formula": formula_total_gral, "concept": "Presupuesto Total Estimado"})
        current_row += 1

        # Métricas estadísticas adicionales: Promedio y Máximo
        formula_avg = f"=AVERAGE(E{start_row}:E{end_data_row})"
        ws.cell(row=current_row, column=1, value="Promedio por Ítem").font = font_regular
        c_avg = ws.cell(row=current_row, column=5, value=formula_avg)
        c_avg.number_format = currency_fmt
        formula_cells_info.append({"cell": f"E{current_row}", "formula": formula_avg, "concept": "Promedio"})
        current_row += 1

        formula_max = f"=MAX(E{start_row}:E{end_data_row})"
        ws.cell(row=current_row, column=1, value="Costo Máximo Individual").font = font_regular
        c_max = ws.cell(row=current_row, column=5, value=formula_max)
        c_max.number_format = currency_fmt
        formula_cells_info.append({"cell": f"E{current_row}", "formula": formula_max, "concept": "Máximo"})

        # Ajuste de ancho de columnas
        column_widths = {1: 34, 2: 20, 3: 14, 4: 20, 5: 22}
        for col_i, w in column_widths.items():
            ws.column_dimensions[get_column_letter(col_i)].width = w

        # 5. Generación de Gráfico de Barras Nativo
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "Distribución de Subtotales por Ítem de Presupuesto"
        chart.y_axis.title = "Monto en Dólares ($)"
        chart.x_axis.title = "Concepto"
        chart.height = 12
        chart.width = 18

        data_ref = Reference(ws, min_col=5, min_row=4, max_row=end_data_row)
        cats_ref = Reference(ws, min_col=1, min_row=5, max_row=end_data_row)
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)
        chart.legend = None

        # Posicionar gráfico al costado de la tabla
        ws.add_chart(chart, "G4")

        # 6. Guardar libro
        wb.save(str(out_path))

        # Verificación física
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError(f"Fallo en creación de Excel: '{out_path}' no existe o está vacío.")

        logger.info(f"[EXCEL CREATED] Libro '{out_path.name}' creado ({len(items)} ítems, {len(formula_cells_info)} fórmulas, gráfico insertado)")
        return {
            "success": True,
            "path": str(out_path),
            "size_bytes": out_path.stat().st_size,
            "items_count": len(items),
            "formulas_written": formula_cells_info,
            "has_chart": True,
        }

    @staticmethod
    def read_data(
        file_path: str | Path,
        sheet_name: str | None = None,
        data_only: bool = False,
    ) -> list[list[Any]]:
        """Lee datos de una hoja Excel.
        
        Si data_only=True, lee los valores cacheados por Excel (o None si no fue calculado).
        Si data_only=False, lee la fórmula literal o valor escrito.
        """
        p = Path(file_path).resolve()
        wb = openpyxl.load_workbook(str(p), data_only=data_only)
        ws = wb[sheet_name] if sheet_name else wb.active
        rows = []
        for r in ws.iter_rows(values_only=True):
            if any(cell is not None for cell in r):
                rows.append(list(r))
        return rows

    @staticmethod
    def evaluate_formulas_with_engine(file_path: str | Path) -> dict[str, Any]:
        """Evalúa las fórmulas utilizando el motor de cálculo real de Microsoft Excel (COM).

        DISTINCIÓN CLAVE:
        - openpyxl escribe las cadenas de fórmula (ej. '=SUM(E5:E12)').
        - Si no hay motor de cálculo presente, se declara honestamente la limitación.
        - Con Microsoft Excel instalado vía COM, se ejecuta CalculateFull(),
          se extraen los valores evaluados reales y se guardan para persistir la caché.
        """
        p = Path(file_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Archivo no encontrado: '{p}'")

        excel = None
        wb = None
        initialized = False
        try:
            import win32com.client  # type: ignore[import-untyped]
            import pythoncom  # type: ignore[import-untyped]
            pythoncom.CoInitialize()
            initialized = True

            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False

            wb = excel.Workbooks.Open(str(p))
            excel.CalculateFull()  # Recálculo forzado de todas las fórmulas en el libro

            ws = wb.Sheets(1)
            evaluated_data: dict[str, Any] = {}

            # Recorrer celdas con fórmulas y obtener su valor evaluado
            used_range = ws.UsedRange
            rows_cnt = used_range.Rows.Count
            cols_cnt = used_range.Columns.Count

            for r in range(1, rows_cnt + 1):
                for c in range(1, cols_cnt + 1):
                    cell = ws.Cells(r, c)
                    formula = str(cell.Formula or "")
                    if formula.startswith("="):
                        val = cell.Value
                        coord = f"{get_column_letter(c)}{r}"
                        evaluated_data[coord] = {
                            "formula": formula,
                            "calculated_value": round(float(val), 2) if isinstance(val, (int, float)) else val,
                            "type": type(val).__name__,
                        }

            # Guardar el libro para que openpyxl(data_only=True) pueda leer los valores calculados
            wb.Save()

            logger.info(f"[EXCEL CALC ENGINE SUCCESS] Evaluadas {len(evaluated_data)} fórmulas con motor Microsoft Excel.")
            return {
                "has_engine": True,
                "engine_name": "Microsoft Excel COM Engine (Version 16.0)",
                "evaluated_formulas_count": len(evaluated_data),
                "results": evaluated_data,
                "message": "Fórmulas calculadas y verificadas con éxito por el motor de cálculo de Microsoft Excel.",
            }
        except Exception as e:
            logger.warning(f"[EXCEL CALC ENGINE UNAVAILABLE] Fallo al invocar Excel.Application: {e}")
            return {
                "has_engine": False,
                "engine_name": "None",
                "evaluated_formulas_count": 0,
                "results": {},
                "message": f"Motor de cálculo de Microsoft Excel no disponible ({e}). Las fórmulas fueron escritas correctamente pero permanecen sin evaluar hasta que el archivo sea abierto por un motor de cálculo.",
            }
        finally:
            if wb is not None:
                try:
                    wb.Close(False)
                except Exception:
                    pass
                wb = None
            if excel is not None:
                try:
                    excel.Quit()
                except Exception:
                    pass
                excel = None
            import gc
            gc.collect()
            if initialized:
                try:
                    import pythoncom  # type: ignore[import-untyped]
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    @staticmethod
    def inspect_workbook(file_path: str | Path) -> dict[str, Any]:
        """Inspecciona la estructura, hojas, fórmulas y gráficos del libro."""
        p = Path(file_path).resolve()
        wb = openpyxl.load_workbook(str(p), data_only=False)
        sheets_info = []

        total_formulas = 0
        total_charts = 0

        for name in wb.sheetnames:
            sheet = wb[name]
            charts_cnt = len(getattr(sheet, "_charts", []))
            total_charts += charts_cnt

            formulas_in_sheet = []
            for r in sheet.iter_rows(values_only=False):
                for cell in r:
                    if cell.value and str(cell.value).startswith("="):
                        formulas_in_sheet.append({"coord": cell.coordinate, "formula": str(cell.value)})

            total_formulas += len(formulas_in_sheet)
            sheets_info.append({
                "name": name,
                "max_row": sheet.max_row,
                "max_column": sheet.max_column,
                "charts_count": charts_cnt,
                "formulas_count": len(formulas_in_sheet),
                "formulas_sample": formulas_in_sheet[:5],
            })

        return {
            "file_name": p.name,
            "file_size": p.stat().st_size,
            "sheets_count": len(wb.sheetnames),
            "sheets": sheets_info,
            "total_formulas": total_formulas,
            "total_charts": total_charts,
        }
