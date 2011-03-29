import argparse
import os.path
import random
import re
import string
import sys

import socket; socket.setdefaulttimeout(30.0) # give APIs plenty of time

import libcloud.types

__doc__ = """Two-step application configuration

Configuration of provision apps is a two step process.

The first step specifies which directories to use for configuring
defaults, defining resource bundles, setting API keys and the
like. This allows users to easily use site-specific configuration
directories outside the source tree.

The second step specifies which bundles to install on the new node,
and any other details specific to the deployment.

Each bundle represents a set of files to be copied and scripts to be
run during node deployment."""

PROVIDERS = {
    'rackspace': libcloud.types.Provider.RACKSPACE}

IMAGE_NAMES = {
    'karmic': 'Ubuntu 9.10 (karmic)',
    'lucid': 'Ubuntu 10.04 LTS (lucid)'}

DEFAULT_IMAGE_NAME = 'lucid'
DEFAULT_LOCATION_ID = 0
DEFAULT_SIZE_ID = 0

DEFAULT_PUBKEY = open(os.path.expanduser('~/.ssh/id_rsa.pub')).read()

# Note that the last directory in the path cannot start with a '.'
# due to module naming restrictions
LOCAL_DEFAULTS = os.path.expanduser('~/.provision/secrets')

DEFAULT_TARGETDIR = '/root/deploy'

DEFAULT_NAME_PREFIX = 'deploy-test-'

DESTROYABLE_PREFIXES = [DEFAULT_NAME_PREFIX]

# Set to None or '' to ignore metadata
NODE_METADATA_CONTAINER_NAME = 'node_meta'

SPLIT_RE = re.compile('split-lines:\W*true', re.IGNORECASE)

CODEPATH = os.path.dirname(__file__)

SCRIPTSDIR = 'scripts'
FILESDIR = 'files'
PUBKEYSDIR = 'pubkeys'

PUBKEYS = []
SUBMAP = {}
BUNDLEMAP = {}

COMMON_BUNDLES = []

PATH = None

import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger('provision')


class Bundle(object):

    """Encapsulates mappings from file and script paths on the target
    node to their local, source paths"""

    def __init__(self, scriptmap=None, filemap=None):
        """
        @type scriptmap: C{dict}
        @keyword scriptmap: Maps target path to source path for scripts

        @type filemap: C{dict}
        @keyword filemap: Maps target path to source path for files
        """
        self.scriptmap = scriptmap or {}
        self.filemap = filemap or {}

def makemap(filenames, sourcedir, targetdir=None):

    """Return a dict which maps filenames coming from a single local
    source directory to a single target directory.  Most useful for
    scripts, whose location when run is often unimportant, and so can
    all be placed in common directory."""

    join = os.path.join
    if targetdir is None: targetdir = DEFAULT_TARGETDIR
    return dict((join(targetdir, f), join(sourcedir, f)) for f in filenames)

def add_bundle(name, scripts=[], files=[], scriptsdir=SCRIPTSDIR, filesdir=FILESDIR):

    """High level, simplified interface for creating a bundle which
    takes the bundle name, a list of script file names in a common
    scripts directory, and a list of absolute target file paths, of
    which the basename is also located in a common files directory.
    It converts those lists into maps and then calls new_bundle() to
    actually create the Bundle and add it to BUNDLEMAP"""

    join = os.path.join
    scriptmap = makemap(scripts, join(PATH, scriptsdir))
    filemap = dict(zip(files, [join(PATH, filesdir, os.path.basename(f)) for f in files]))
    new_bundle(name, scriptmap, filemap)

def new_bundle(name, scriptmap, filemap=None):

    """Create a bundle and add to available bundles"""

    #logger.debug('new bundle %s' % name)
    if name in BUNDLEMAP:
        logger.warn('overwriting bundle %s' % name)
    BUNDLEMAP[name] = Bundle(scriptmap, filemap)

def random_str(length=6, charspace=string.ascii_lowercase+string.digits):
    return ''.join(random.sample(charspace, length))

class DictObj(object):

    """Wraps a dict so its keys are accessed like properties, using dot notation"""

    def __init__(self, d):
        self.__dict__['d'] = d

    def __setattr__(self, key, value):
        if self.__dict__['d'].get(key):
            logger.warn('overwriting config.{0}'.format(key))
        self.__dict__['d'][key] = value

    def __getattr__(self, key):
        return self.__dict__['d'][key]


def import_by_path(path):

    """Append the path to sys.path, then attempt to import module with
    path's basename, finally making certain to remove appended path.

    http://stackoverflow.com/questions/1096216/override-namespace-in-python"""

    sys.path.append(os.path.dirname(path))
    try:
        return __import__(os.path.basename(path))
    except ImportError:
        logger.warn('unable to import {0}'.format(path))
    finally:
        del sys.path[-1]

def init_module(path):

    """Attempt to import a Python module located at path.  If
    successful, and if the newly imported module has an init()
    function, then set the global PATH in order to simplify the
    add_bundle() interface and call init() on the module, passing the
    current global namespace, conveniently converted into a DictObj so
    that it can be accessed with normal module style dot notation
    instead of as a dict.

    http://stackoverflow.com/questions/990422/how-to-get-a-reference-to-current-modules-attributes-in-python"""

    mod = import_by_path(path)
    if mod is not None and hasattr(mod, 'init'):
        logger.debug('calling init on {0}'.format(mod))
        global PATH
        PATH = path
        mod.init(DictObj(globals()))

def load_pubkeys(loadpath, pubkeys):

    """Append the file contents in loadpath directory onto pubkeys list"""

    filenames = os.listdir(loadpath)
    logger.debug('loading authorized pubkeys {0}'.format(filenames))
    for filename in filenames:
        pubkeys.append(open(os.path.join(loadpath, filename)).read())

def normalize_path(path):

    """If path is not absolute, assume it's relative to CODEPATH"""

    if os.path.isabs(path):
        return path
    else:
        return os.path.join(CODEPATH, path)

def configure(paths):

    """Iterate on each configuration path, collecting all public keys
    destined for the new node's root account's authorized keys.
    Additionally attempt to import path as python module."""

    if not paths:
        return
    for path in [normalize_path(p) for p in paths]:
        logger.debug('configuration path {0}'.format(path))
        pubkeys_path = os.path.join(path, PUBKEYSDIR)
        if os.path.exists(pubkeys_path):
            load_pubkeys(pubkeys_path, PUBKEYS)
        init_module(path)

def configure_cwd(paths):

    """Configure with non-absolute paths relative to current working dir"""

    cwd = os.getcwd()
    configure([os.path.join(cwd, p) for p in paths if not os.path.isabs(p)])

def parser():

    """Return an parser for setting multiple configuration paths"""

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config_paths', default=[], action='append')
    return parser

def add_auth_args(parser, config):

    """Return an parser for configuring authentication parameters"""

    parser.add_argument('-p', '--provider', default=config.DEFAULT_PROVIDER)
    parser.add_argument('-u', '--userid', default=config.DEFAULT_USERID)
    parser.add_argument('-k', '--secret_key', default=config.DEFAULT_SECRET_KEY)
    return parser

def reconfig(main_parser):

    """Parse any config paths and reconfigure defaults with them
    http://docs.python.org/library/argparse.html#partial-parsing
    Return parsed remaining arguments"""

    parsed, remaining_args = parser().parse_known_args()
    configure_cwd(parsed.config_paths)
    return main_parser().parse_args(remaining_args)

defaults = ['defaults', 'secrets']
if os.path.exists(LOCAL_DEFAULTS):
    defaults.append(LOCAL_DEFAULTS)
configure(defaults)

