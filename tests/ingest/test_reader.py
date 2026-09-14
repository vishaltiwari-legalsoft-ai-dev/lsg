"""read_table: CSV in cp1252 with a semicolon delimiter, an XLSX, blank and
duplicate headers, an xlsx disguised as .csv."""

from __future__ import annotations

from lge.ingest.reader import read_table


def test_csv_semicolon_cp1252(tmp_path):
    p = tmp_path / "list.csv"
    p.write_bytes("Firm;Website;Notes\nCaf\xe9 Law;cafelaw.com;caf\xe9\n\n;x;\n".encode("cp1252"))
    t = read_table(p)
    assert t.format == "csv" and t.delimiter == ";" and t.encoding == "cp1252"
    assert t.headers == ["Firm", "Website", "Notes"]
    assert t.rows[0] == {"Firm": "Café Law", "Website": "cafelaw.com", "Notes": "café"}
    assert len(t.rows) == 2  # the blank line is dropped, the partial row is kept


def test_blank_and_duplicate_headers_get_names(tmp_path):
    p = tmp_path / "h.csv"
    p.write_text("Name,,Name,Email\nA,1,B,a@b.com\n", encoding="utf-8")
    t = read_table(p)
    assert t.headers == ["Name", "col_2", "Name_2", "Email"]
    assert t.rows[0]["Name_2"] == "B"


def test_xlsx_first_sheet(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append([None, None])  # leading blank row
    ws.append(["Firm", "Website", "Attorneys"])
    ws.append(["Doe & Roe", "doeroe.com", 4])
    ws.append([None, None, None])
    wb.create_sheet("Other")
    p = tmp_path / "list.xlsx"
    wb.save(p)
    t = read_table(p)
    assert t.format == "xlsx" and t.sheet == "Leads"
    assert t.headers == ["Firm", "Website", "Attorneys"]
    assert t.rows == [{"Firm": "Doe & Roe", "Website": "doeroe.com", "Attorneys": "4"}]
    assert any("2 sheet(s)" in n for n in t.notes)

    disguised = tmp_path / "list.csv"
    disguised.write_bytes(p.read_bytes())
    assert read_table(disguised).format == "xlsx"
