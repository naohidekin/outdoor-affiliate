import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from runtime import Runtime, safe_publication_diagnostic

class PublicationDiagnosticsTests(unittest.TestCase):
    def runtime(self):
        r=Runtime.__new__(Runtime)
        r.config={'seoGuardConfig':'/test-only','repo':'.','node':'node'}
        r.env={}
        return r
    def test_sanitization(self):
        self.assertEqual(safe_publication_diagnostic({'phase':'public_readback','message':'secret','dbCode':'42883','httpStatus':404}),{'phase':'public_readback','dbCode':'42883','httpStatus':404})
        self.assertEqual(safe_publication_diagnostic({'phase':'secret','httpStatus':True,'dbCode':'secret-value'}),{})
    def test_exit13_and_invalid_stdout_preserved_without_stdout(self):
        with patch('runtime.subprocess.run',return_value=SimpleNamespace(returncode=13,stdout='secret')):
            with self.assertRaises(ValueError) as caught:
                self.runtime()._publish('stage-revision',{'bundle':{},'revision':'x'})
        self.assertEqual(caught.exception.diagnostic,{'phase':'subprocess','exitCode':13})
        self.assertNotIn('secret',str(caught.exception))
    def test_structured_error_is_sanitized(self):
        out=json.dumps({'error':'publication_result_unknown','diagnostic':{'phase':'cache_revalidation','message':'secret'}})
        with patch('runtime.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=out)):
            with self.assertRaises(ValueError) as caught:
                self.runtime()._publish('stage-revision',{'bundle':{},'revision':'x'})
        self.assertEqual(caught.exception.diagnostic,{'phase':'cache_revalidation','exitCode':1})
    def test_timeout_is_saved_without_arguments(self):
        with patch('runtime.subprocess.run',side_effect=subprocess.TimeoutExpired(['secret'],180)):
            with self.assertRaises(ValueError) as caught:
                self.runtime()._publish('stage-revision',{'bundle':{},'revision':'x'})
        self.assertEqual(caught.exception.diagnostic,{'phase':'subprocess','timedOut':True})
if __name__=='__main__':
    unittest.main()
