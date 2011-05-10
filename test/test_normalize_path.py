import os.path
import unittest

import provision.config as config

class Test(unittest.TestCase):

    def test_normalize_path_absolute(self):
        assert config.normalize_path('/foo/bar', '/baz') == '/foo/bar'

    def test_normalize_path_relative(self):
        assert config.normalize_path('foo/bar', '/baz') == '/baz/foo/bar'

    def test_normalize_path_user(self):
        assert config.normalize_path('~', '/baz') == os.path.expanduser('~')
