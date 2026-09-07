from pathlib import Path
import tempfile
import unittest
from benchmark.acceptance.corpus import pdf_bytes, ooxml, zip_bytes
from benchmark.acceptance.fact_inventory import inspect


class InventoryTests(unittest.TestCase):
    def read(self,data,fmt):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/('input.'+fmt);p.write_bytes(data)
            return {a['factKey']:a for a in inspect(p,fmt)}

    def test_pdf_links_and_unknown_visual_tables(self):
        facts=self.read(pdf_bytes(1,link=True),'pdf')
        self.assertEqual(facts['links.external_reference_count']['expected'],1)
        self.assertEqual(facts['links.external_unique_targets']['expected'],['https://deckprobe-canary.invalid/never-follow'])
        self.assertEqual(facts['pdf.annotation_count']['expected'],1)
        self.assertEqual(facts['pdf.form_field_count']['expected'],0)
        self.assertEqual(facts['tables.visual_count']['valueState'],'unknown')
        self.assertIsNone(facts['tables.visual_count']['expected'])

    def test_nested_word_tables_and_math_objects(self):
        data=zip_bytes({'word/document.xml':'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body><w:tbl><w:tr><w:tc><w:tbl/></w:tc></w:tr></w:tbl><m:oMathPara><m:oMath/></m:oMathPara></w:body></w:document>'})
        facts=self.read(data,'docx')
        self.assertEqual(facts['word.table_count']['expected'],2)
        self.assertEqual(facts['formulas.word.math_object_count']['expected'],1)

    def test_formula_cells_and_duplicate_image_resources(self):
        data=zip_bytes({'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets/></workbook>',
            'xl/worksheets/sheet1.xml':'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1"><f t="shared" si="0">1+1</f></c><c r="A2"><f t="shared" si="0"/></c><c r="A3"><v>2</v></c></row></sheetData></worksheet>',
            'xl/media/a.png':b'same test bytes','xl/media/b.png':b'same test bytes'})
        facts=self.read(data,'xlsx')
        self.assertEqual(facts['formulas.excel.stored_formula_cell_count']['expected'],2)
        self.assertEqual(facts['images.package.image_part_count']['expected'],2)
        self.assertEqual(facts['images.package.unique_image_bytes_count']['expected'],1)


if __name__=='__main__':unittest.main()
