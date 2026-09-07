import tempfile
import unittest
from pathlib import Path
from benchmark.acceptance.corpus import zip_bytes
from benchmark.acceptance.mapping_rules import typed_assets,resolve

class MappingTests(unittest.TestCase):
 def test_part_names_not_content_hashes(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'x.docx';p.write_bytes(zip_bytes({'[Content_Types].xml':'<Types><Default Extension="png" ContentType="image/png"/></Types>', 'word/media/a.png':b'same','word/media/b.png':b'same','docProps/thumbnail.png':b'other'}))
   rows=typed_assets({'path':str(p),'sha256':'test'})
   self.assertEqual(rows[0]['expected'],2)
   self.assertEqual(rows[0]['evidence']['parts'],['word/media/a.png','word/media/b.png'])
 def test_similar_name_not_equivalent(self):
  cat={'tool_version':'2.5.0','targets':{'word.unique_image_asset_count':{'profile_details':{'docx':{'supported_levels':['deep']}}}}}
  sample={'format':'docx'}
  self.assertEqual(resolve(sample,{'factKey':'images.package.unique_image_bytes_count','definition':'content hashes'},cat)['status'],'unsupported')
  self.assertEqual(resolve(sample,{'factKey':'images.word.typed_asset_parts','definition':'typed scoped parts'},cat)['check']['target'],'word.unique_image_asset_count')
  self.assertEqual(resolve(sample,{'factKey':'iwork.build_count','definition':'ambiguous'},cat)['status'],'unmapped')
