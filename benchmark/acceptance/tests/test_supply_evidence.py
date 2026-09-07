import copy
import json
import tempfile
import unittest
from pathlib import Path

from benchmark.acceptance.common import atomic,sha
from benchmark.acceptance.supply_evidence import collect,aggregate,provenance_fields,signature_counts,license_text_sha


class SupplyEvidenceTests(unittest.TestCase):
    def test_provenance_binds_all_three_fields(self):
        asset={'name':'engine.tar.gz','sha256':'artifact-hash'}
        release={'repository':'owner/repo','commit':'commit-hash','tag':'v1'}
        verified={'signature':{'certificate':{'sourceRepositoryURI':'https://github.com/owner/repo','sourceRepositoryDigest':'commit-hash','sourceRepositoryRef':'refs/tags/v1'}},
                  'statement':{'subject':[{'name':'engine.tar.gz','digest':{'sha256':'artifact-hash'}}]}}
        self.assertEqual(aggregate(provenance_fields(asset,release,verified,'proof.json')),'passed')
        for key in ['sourceRepositoryURI','sourceRepositoryDigest']:
            bad=copy.deepcopy(verified);bad['signature']['certificate'][key]='different'
            self.assertEqual(aggregate(provenance_fields(asset,release,bad,'proof.json')),'failed')
        bad=copy.deepcopy(verified);bad['statement']['subject'][0]['digest']['sha256']='tampered'
        self.assertEqual(aggregate(provenance_fields(asset,release,bad,'proof.json')),'failed')
        self.assertEqual(aggregate(provenance_fields(asset,release,{},'proof.json')),'blocked')

    def test_npm_exit_zero_does_not_invent_counts(self):
        self.assertEqual(signature_counts({'exitCode':0,'stdout':''}),{'audited':None,'signatures':None,'attestations':None})
        self.assertEqual(signature_counts({'stdout':'audited 9 packages in 11s\n9 packages have verified registry signatures\n8 packages have verified attestations'}),
                         {'audited':9,'signatures':9,'attestations':8})

    def test_license_normalization_only_allows_line_endings(self):
        self.assertEqual(license_text_sha('Apache License\nCopyright A\n'),license_text_sha('Apache License\r\nCopyright A\r\n'))
        self.assertNotEqual(license_text_sha('Copyright A\n'),license_text_sha('Copyright B\n'))
        self.assertNotEqual(license_text_sha('Copyright A\n'),license_text_sha('Copyright  A\n'))

    def test_component_license_gap_is_not_empty_list_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pkg=root/'package';meta=pkg/'node_modules/@deckflow/deckprobe/package.json'
            atomic(meta,{'name':'@deckflow/deckprobe','version':'2.4.0','license':'MIT'})
            mcp=pkg/'node_modules/@deckflow/deckprobe-mcp/package.json'
            atomic(mcp,{'name':'@deckflow/deckprobe-mcp','version':'0.1.1','license':'MIT'})
            target={'release':{'folder':str(root),'release':{'tag':'v2.4.0','repository':'owner/repo','commit':'x'},'assets':[],'extracted':{},'provenance':[]},
                    'packages':{'folder':str(pkg),'id':'pkg','lockSha256':'none','mcp':{'version':'0.1.1'},
                                'runtimeFiles':{str(meta.relative_to(pkg)):sha(meta),str(mcp.relative_to(pkg)):sha(mcp)}}}
            result=collect(root/'run',target)
            self.assertEqual(result['release_licenses']['status'],'failed')
            self.assertEqual(result['npm_signatures']['status'],'blocked')
            self.assertTrue(any(f['label']=='LICENSE · 随包文件存在' and f['actual'] is False
                                for g in result['release_licenses']['audit']['groups'] for f in g['rows']))


if __name__=='__main__':unittest.main()
