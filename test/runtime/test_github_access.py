import json
import os
from pathlib import Path
import sys
import sysconfig
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from singer_runtime import source_config, read_catalog, tap_output, SourceError
from github_fixture import github_fixture, observations

class AccessTests(unittest.TestCase):
    def extract(self, scenario='normal', token=None):
        source={'repositories':['demo/repo'],'skip_parent_streams':True}
        if token is not None:source['auth_token']=token
        executable=Path(sys.executable).parent/'tap-github'
        with github_fixture(Path(sysconfig.get_paths()['purelib']),scenario) as requests:
            catalog=read_catalog(executable,source,30)
            for stream in catalog['streams']:
                for meta in stream['metadata']:
                    meta.setdefault('metadata',{})['selected']=stream['stream']=='issues'
            # A real inherited token must never be consulted by the child.
            with patch.dict(os.environ,{'GITHUB_TOKEN':'ambient-fixture-must-not-be-used'}):
                messages=[json.loads(x) for x in tap_output(executable,source,catalog,30)]
            self.assertFalse(any('/graphql' in p for p in requests))
            self.assertTrue(observations)
            self.assertTrue(all(o['authorised']==(token is not None) for o in observations))
            return [x['record'] for x in messages if x.get('type')=='RECORD' and x.get('stream')=='issues']
    def test_anonymous_real_reader_pagination_and_no_ambient_auth(self):
        self.assertEqual([x['id'] for x in self.extract()],[1,2])
    def test_explicit_token_real_reader(self):
        self.assertEqual(len(self.extract(token='synthetic-fixture')),2)
    def test_empty_repository(self):
        self.assertEqual(self.extract('empty'),[])
    def test_http_failures_are_not_empty_success(self):
        for scenario,code in [('missing','GITHUB_NOT_FOUND'),('forbidden','GITHUB_FORBIDDEN'),('rate','GITHUB_RATE_LIMIT'),('interrupted','GITHUB_UNAVAILABLE')]:
            with self.subTest(scenario=scenario),self.assertRaises(SourceError) as caught:
                self.extract(scenario)
            self.assertEqual(caught.exception.code,code)
    def test_invalid_token_does_not_fall_back(self):
        with self.assertRaises(SourceError) as caught:self.extract(token='invalid-fixture')
        self.assertEqual(caught.exception.code,'GITHUB_AUTH')
        self.assertTrue(all(x['authorised'] for x in observations))
    def test_auth_configuration_rejects_conflicting_or_missing_token(self):
        for settings in [dict(authentication='anonymous',auth_token='secret'),dict(authentication='token'),dict(authentication='token',auth_token='')]:
            with self.subTest(settings=settings),self.assertRaises(ValueError):
                source_config({'connector':'github@1.29.2','sourceSettings':{**settings,'repositories':['demo/repo']}})
        for repo in ['invalid','../repo','owner/repo?evil','owner/repo/extra']:
            with self.subTest(repo=repo),self.assertRaises(ValueError):source_config({'connector':'github@1.29.2','sourceSettings':{'repositories':[repo]}})
