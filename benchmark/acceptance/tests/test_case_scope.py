import unittest
from benchmark.acceptance.case_scope import plan

class ScopeTests(unittest.TestCase):
    def test_purpose_selects_gt_not_generic_known_or_zero_values(self):
        def sample(id,keys,purpose):
            return {'id':id,'purpose':{'checks':purpose},'answers':[{'id':id+':'+k,'kind':'fact','factKey':k,'question':k} for k in keys]}
        p={'samples':[
            sample('encrypted-docx',['security.encrypted','images.pending_scope','word.table_count'],[]),
            sample('pdf-external-link',['security.has_external_relationships','pdf.page_count','links.external_reference_count'],[{'factKeys':['security.has_external_relationships','links.external_reference_count']}]),
            {'id':'pdf-mismatch','purpose':{'checks':[{'type':'error'}]},'answers':[
                {'id':'error','kind':'contract','check':{'type':'error'}},
                {'id':'image','kind':'fact','factKey':'images.pending_scope'}]}]}
        scopes,_=plan(p);selected={x['answerId'] for x in scopes if x['mode']=='case'}
        self.assertEqual(selected,{'encrypted-docx:security.encrypted','pdf-external-link:security.has_external_relationships','pdf-external-link:links.external_reference_count','error'})
