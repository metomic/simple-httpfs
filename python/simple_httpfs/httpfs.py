import array
import collections
import functools
import itertools
import logging
import os
import os.path as op
import re
import requests
import sys
import tempfile
import traceback

from errno import EIO, ENOENT, EACCES, EFBIG
from fuse import FUSE, FuseOSError, LoggingMixIn, Operations
from stat import S_IFDIR, S_IFREG
from time import sleep, time
from threading import Timer
from urllib.parse import urlparse

FALSY = {0, "0", False, "false", "False", "FALSE", "off", "OFF"}

MAX_PATH_LENGTH = 96
MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_BYTES", 1024 * 1024 * 10))
MAX_CACHED_FILES = int(os.environ.get("MAX_CACHED_FILES", 32))

# Note that worst-case, peak memory usage for this service will be up to
# MAX_FILE_SIZE_BYTES * MAX_CACHED_FILES
# e.g. 320MB with default config + constant stream of 10MB files

class HttpFetcher:
    SSL_VERIFY = os.environ.get("SSL_VERIFY", True) not in FALSY

    def __init__(self, logger):
        self.logger = logger
        if not self.SSL_VERIFY:
            logger.warning(
                "You have set ssl certificates to not be verified. "
                "This may leave you vulnerable. "
                "http://docs.python-requests.org/en/master/user/advanced/#ssl-cert-verification"
            )

    def __eq__(self, other):
        return self.SSL_VERIFY == other.SSL_VERIFY

    def __hash__(self):
        return hash(self.SSL_VERIFY)

    def get_size(self, url):
        try:
            head = requests.head(url, allow_redirects=True, verify=self.SSL_VERIFY)
            self.logger.debug(f"HEAD {url} status code: {head.status_code}")

            try:
                head.raise_for_status()
            except requests.HTTPError as e:
                raise FuseOSError(ENOENT)

            return int(head.headers["Content-Length"])

        except:
            head = requests.get(
                url,
                allow_redirects=True,
                verify=self.SSL_VERIFY,
                headers={"Range": "bytes=0-1"},
		        timeout=5
            )
            self.logger.debug(f"GET {url} status code: {head.status_code}")

            try:
                head.raise_for_status()
            except requests.HTTPError as e:
                raise FuseOSError(ENOENT)

            crange = head.headers["Content-Range"]
            match = re.search(r"/(\d+)$", crange)
            if match:
                return int(match.group(1))

            self.logger.error(traceback.format_exc())
            raise FuseOSError(ENOENT)

    def get_data(self, url):
        headers = {"Accept-Encoding": ""}

        r = requests.get(url, headers=headers, timeout=5)
        self.logger.info("Fetched %s - status code: %s", url, r.status_code)

        if r.status_code != 200:
            raise FuseOSError(ENOENT)

        return r.content


class HttpFs(LoggingMixIn, Operations):
    """
    A read only http/https filesystem.

    """

    def __init__(
        self,
        schema,
        logger=None,
    ):
        self.schema = schema
        self.logger = logger
        self.total_requests = 0

        if not self.logger:
            self.logger = logging.getLogger(__name__)

        if schema == "http" or schema == "https":
            self.fetcher = HttpFetcher(self.logger)
        else:
            raise ("Unknown schema: {}".format(schema))

    def __eq__(self, other):
        return self.schema == other.schema

    def __hash__(self):
        return hash(self.schema)

    @functools.lru_cache(maxsize=4096)
    def getSize(self, url):
        return self.fetcher.get_size(url)

    @functools.lru_cache(maxsize=4096)
    def getattr(self, path, fh=None):
        self.logger.debug(f"getattr: {path}")

        if path == "/"  or len(path.split("/")) < 3:
            # It's a directory
            return dict(st_mode=(S_IFDIR | 0o555), st_nlink=2)

        if len(path) > MAX_PATH_LENGTH:
            # Enforce a max URL length
            raise FuseOSError(ENOENT)

        url = f"{self.schema}:/{path}"

        try:
            size = self.getSize(url)
            if size is None:
                raise Exception("File didn't exist on upstream")
        except:
            return dict(st_mode=(S_IFDIR | 0o555), st_nlink=2)

        return dict(
            st_mode=(S_IFREG | 0o644),
            st_nlink=1,
            st_size=size,
            st_ctime=time(),
            st_mtime=time(),
            st_atime=time(),
        )

    def unlink(self, path):
        return 0

    def create(self, path, mode, fi=None):
        return 0

    def write(self, path, buf, size, offset, fip):
        return 0

    def read(self, path, size, offset, fh):
        url = f"{self.schema}:/{path}"

        # Note: most recent file content stored in memory in LRU cache
        # This is optimised for our (Metomic, classifier engine sidecar) use case (linear reads of one file at a time)
        # YMMV when using this with applications that try to read several files at random offsets
        block_data = self.get_url_mm(url, fh)

        # We can use our in-memory buffered contents with the standard file utilities,
        # so we just seek to the offset requested + read the size requested. pow!
        block_data.seek(offset)

        return block_data.read(size)


    def destroy(self, path):
        pass

    @functools.lru_cache(maxsize=MAX_CACHED_FILES)
    def get_url_mm(self, url, fh=None):
        self.logger.info(f"Fetching url: {url}")

        response = requests.get(url, stream=True)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise FuseOSError(ENOENT)

        byte_size = 0

        # We're using "SpooledTemporaryFile" which is actually entirely in-memory with this configuration
        # ...but allows access using the file-style interface methods, which is great (read / write / seek, etc)
        f = tempfile.SpooledTemporaryFile()
        for chunk in response.iter_content(chunk_size=None): # chunk_size=None will write the data as soon as it's available
            byte_size += len(chunk)
            if byte_size > MAX_FILE_SIZE_BYTES:
                raise FuseOSError(EFBIG)

            f.write(chunk)

        return f
