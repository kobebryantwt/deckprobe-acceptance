import tempfile
from pathlib import Path
import unittest

from benchmark.acceptance.common import sha
from benchmark.acceptance.corpus import pdf_bytes, ooxml
from benchmark.acceptance.purpose_audit import inspect_public, intent, EXT, JS


class PurposeTests(unittest.TestCase):
    def inspect(self, data, fmt):
        with tempfile.TemporaryDirectory() as root:
            file=Path(root)/('input.'+fmt);file.write_bytes(data)
            return inspect_public({'private':False,'path':str(file),'sha256':sha(file),'format':fmt})

    def test_pdf_positive_and_negative_features(self):
        links=self.inspect(pdf_bytes(1,link=True),'pdf')
        self.assertEqual(links['linkCount'],1)
        self.assertEqual(links['links'][0]['uri'],'https://deckprobe-canary.invalid/never-follow')
        self.assertFalse(links['javascript'])
        js=self.inspect(pdf_bytes(1,javascript=True),'pdf')
        self.assertTrue(js['javascript']);self.assertEqual(js['linkCount'],0)
        control=self.inspect(pdf_bytes(1),'pdf')
        self.assertEqual(control['linkCount'],0);self.assertFalse(control['javascript'])

    def test_office_relationships_and_word_paragraphs(self):
        for fmt in ['pptx','xlsx']:
            self.assertEqual(self.inspect(ooxml(fmt,external=True)[0],fmt)['linkCount'],1)
            self.assertEqual(self.inspect(ooxml(fmt)[0],fmt)['linkCount'],0)
        self.assertEqual(self.inspect(ooxml('docx',3)[0],'docx')['paragraphCount'],3)

    def test_intent_exposes_primary_target_and_unsupported_count(self):
        s={'id':'pdf-external-link','format':'pdf','private':False,'answers':[]}
        purpose=intent(s)
        self.assertEqual(purpose['checks'][0]['target'],EXT)
        self.assertNotIn('type',purpose['checks'][1])
        s['id']='pdf-javascript'
        self.assertEqual(intent(s)['checks'][0]['target'],JS)


if __name__=='__main__':unittest.main()
