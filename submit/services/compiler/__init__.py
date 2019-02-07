"""
Integration with the :mod:`compiler` service API.

The compiler is responsible for building PDF, DVI, and other goodies from
LaTeX sources. In the submission UI, we specifically want to build a PDF so
that the user can preview their submission. Additionally, we want to show the
submitter the TeX log so that they can identify any potential problems with
their sources.
"""
from typing import Tuple, Optional, List, Union
import json
import re
from functools import wraps
from collections import defaultdict
from urllib.parse import urlparse, urlunparse, urlencode
import dateutil.parser
import requests
from requests.packages.urllib3.util.retry import Retry
from enum import Enum

from arxiv import status
from arxiv.base import logging
from arxiv.base.globals import get_application_config, get_application_global
from werkzeug.datastructures import FileStorage

from submit.domain import CompilationStatus, Upload, FileStatus, \
    CompilationProduct, FileError

logger = logging.getLogger(__name__)


class RequestFailed(IOError):
    """The compiler service returned an unexpected status code."""

    def __init__(self, msg: str, data: dict = {}) -> None:
        """Attach (optional) data to the exception."""
        self.data = data
        super(RequestFailed, self).__init__(msg)


class RequestUnauthorized(RequestFailed):
    """Client/user is not authenticated."""


class RequestForbidden(RequestFailed):
    """Client/user is not allowed to perform this request."""


class BadRequest(RequestFailed):
    """The request was malformed or otherwise improper."""


class BadResponse(RequestFailed):
    """The response from the compiler service was malformed."""


class ConnectionFailed(IOError):
    """Could not connect to the compiler service."""


class SecurityException(ConnectionFailed):
    """Raised when SSL connection fails."""


class NoSuchResource(RequestFailed):
    """The requested resource does not exist."""


class Download(object):
    """Wrapper around response content."""

    def __init__(self, response: requests.Response) -> None:
        """Initialize with a :class:`requests.Response` object."""
        self._response = response

    def read(self) -> bytes:
        """Read response content."""
        return self._response.content


class CompilerService(object):
    """Encapsulates a connection with the compiler service."""

    class Compilers(Enum):
        """Compilers known to be supported by the compiler service."""

        foo = 'foo'

    def __init__(self, endpoint: str, verify_cert: bool = True,
                 headers: dict = {}) -> None:
        """
        Initialize an HTTP session.

        Parameters
        ----------
        endpoints : str
            One or more endpoints for metadata retrieval. If more than one
            are provided, calls to :meth:`.retrieve` will cycle through those
            endpoints for each call.
        verify_cert : bool
            Whether or not SSL certificate verification should enforced.
        headers : dict
            Headers to be included on all requests.

        """
        logger.debug('New CompilerService with endpoint %s', endpoint)
        self._session = requests.Session()
        self._verify_cert = verify_cert
        self._retry = Retry(  # type: ignore
            total=10,
            read=10,
            connect=10,
            status=10,
            backoff_factor=0.5
        )
        self._adapter = requests.adapters.HTTPAdapter(max_retries=self._retry)
        self._session.mount(f'{urlparse(endpoint).scheme}://', self._adapter)
        if not endpoint.endswith('/'):
            endpoint += '/'
        self._endpoint = endpoint
        self._session.headers.update(headers)

        self.format = 'pdf'

    def _parse_compilation_status(self, data: dict) -> CompilationStatus:

        return CompilationStatus(

        )

    def _parse_task_id(self, task_uri: str) -> str:
        parts = urlparse(task_uri)
        task_id = re.match(r'^/task/([^/]+)', parts.path).group(1)
        return task_id

    def _path(self, path: str, query: dict = {}) -> str:
        o = urlparse(self._endpoint)
        path = path.lstrip('/')
        return urlunparse((
            o.scheme, o.netloc, f"{o.path}{path}",
            None, urlencode(query), None
        ))

    def _make_request(self, method: str, path: str,
                      expected_codes: List[int] = [200], **kw) \
            -> requests.Response:
        kw.update({'allow_redirects': False})
        try:
            resp = getattr(self._session, method)(self._path(path), **kw)
        except requests.exceptions.SSLError as e:
            raise SecurityException('SSL failed: %s' % e) from e
        except requests.exceptions.ConnectionError as e:
            raise ConnectionFailed('Could not connect: %s' % e) from e
        if resp.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            raise RequestFailed(f'Status: {resp.status_code}; {resp.content}')
        elif resp.status_code == status.HTTP_401_UNAUTHORIZED:
            raise RequestUnauthorized(f'Not authorized: {resp.content}')
        elif resp.status_code == status.HTTP_403_FORBIDDEN:
            raise RequestForbidden(f'Forbidden: {resp.content}')
        elif resp.status_code == status.HTTP_404_NOT_FOUND:
            logger.debug(resp.json())
            raise NoSuchResource('Resource does not exist', data=resp.json())
        elif resp.status_code >= status.HTTP_400_BAD_REQUEST:
            raise BadRequest(f'Bad request: {resp.content}',
                             data=resp.content)
        elif resp.status_code not in expected_codes:
            raise RequestFailed(f'Unexpected status code: {resp.status_code}')
        return resp

    def set_auth_token(self, token: str) -> None:
        """Set the authn/z token to use in subsequent requests."""
        self._session.headers.update({'Authorization': token})

    def request(self, method: str, path: str, expected_codes: int = 200,
                **kwargs) -> Tuple[dict, dict]:
        """Perform an HTTP request, and handle any exceptions."""
        resp = self._make_request(method, path, expected_codes, **kwargs)

        # There should be nothing in a 204 response.
        if resp.status_code is status.HTTP_204_NO_CONTENT:
            return {}, resp.headers
        try:
            return resp.json(), resp.headers
        except json.decoder.JSONDecodeError as e:
            raise BadResponse('Could not decode: {resp.content}') from e

    def get_service_status(self) -> dict:
        """Get the status of the compiler service."""
        return self.request('get', 'status')

    def request_compilation(self, upload_id: int,
                            compiler: Optional[Compilers] = None) \
            -> CompilationStatus:
        """
        Request compilation for an upload workspace.

        Parameters
        ----------
        upload_id : int
            Unique identifier for the upload workspace.
        compiler : str or None
            Name of the preferred compiler.

        Returns
        -------
        :class:`CompilationStatus`
            The current state of the compilation.

        """
        checksum = 'not-right-now'
        logger.debug(f"Requesting Compilation for {upload_id}.{self.format}")
        data, headers = self.request('post', f'/',
                                     json={'source_id': upload_id,
                                           'checksum': checksum,
                                           'format': self.format},
                                     expected_codes=[
                                        status.HTTP_202_ACCEPTED,
                                        status.HTTP_302_FOUND,
                                        status.HTTP_303_SEE_OTHER,
                                     ])
        task_id = self._parse_task_id(headers['Location'])
        return self.get_task_status(upload_id, checksum, self.format)

    def get_compilation_product(self, upload_id: int) \
            -> Union[CompilationStatus, CompilationProduct]:
        """
        Get the compilation product for an upload workspace, if it exists.

        The file management service will check its latest PDF product against
        the checksum of the upload workspace. If there is a match, it returns
        the file. Otherwise, if there is a compilation task with a matching
        checksum, redirects to the task status endpoint. Otherwise, a 404 is
        returned resulting in :class:`NoSuchResource` exception.
        """
        expected_codes = [
           status.HTTP_200_OK,
           status.HTTP_302_FOUND
        ]
        response = self._make_request('get', f'/task/{task_id}',
                                      expected_codes, stream=True)

        if 'Location' in response.headers:
            task_id = self._parse_task_id(response.headers['Location'])
            return get_task_status(upload_id, task_id)
        return CompilationProduct(
            upload_id=upload_id,
            stream=Download(response)
        )

    def get_task_status(self, upload_id: int, checksum: str, format: str) \
            -> CompilationStatus:
        """Get the status of a compilation task."""
        data, headers = self.request('get', f'/task/{upload_id}/{checksum}/{format}',
                                     expected_codes=[
                                        status.HTTP_200_OK,
                                        status.HTTP_303_SEE_OTHER
                                     ])
        return CompilationStatus(
            source_id=upload_id,
            checksum=checksum,
            format=format,
            status=CompilationStatus.Statuses(data['status']['status'])
        )


def init_app(app: object = None) -> None:
    """Set default configuration parameters for an application instance."""
    config = get_application_config(app)
    config.setdefault('COMPILER_ENDPOINT', 'http://compiler-api:8100/')
    config.setdefault('COMPILER_VERIFY', True)


def get_session(app: object = None) -> CompilerService:
    """Get a new session with the compiler endpoint."""
    config = get_application_config(app)
    endpoint = config.get('COMPILER_ENDPOINT', 'http://compiler-api:8100/')
    verify_cert = config.get('COMPILER_VERIFY', True)
    logger.debug('Create CompilerService with endpoint %s', endpoint)
    return CompilerService(endpoint, verify_cert=verify_cert)


def current_session() -> CompilerService:
    """Get/create :class:`.CompilerService` for this context."""
    g = get_application_global()
    if not g:
        return get_session()
    elif 'filemanager' not in g:
        g.filemanager = get_session()   # type: ignore
    return g.filemanager    # type: ignore


@wraps(CompilerService.set_auth_token)
def set_auth_token(token: str) -> None:
    """See :meth:`CompilerService.set_auth_token`."""
    return current_session().set_auth_token(token)


@wraps(CompilerService.get_compilation_product)
def get_compilation_product(upload_id: int) -> \
        Union[CompilationStatus, CompilationProduct]:
    """See :meth:`CompilerService.get_compilation_product`."""
    return current_session().get_compilation_product(upload_id)


@wraps(CompilerService.request_compilation)
def request_compilation(upload_id: int,
                        compiler: Optional[CompilerService.Compilers] = None) \
        -> CompilationStatus:
    """See :meth:`CompilerService.request_compilation`."""
    return current_session().request_compilation(upload_id, compiler=compiler)


@wraps(CompilerService.get_task_status)
def get_task_status(upload_id: int, task_id: str) -> CompilationStatus:
    """See :meth:`CompilerService.get_task_status`."""
    return current_session().get_task_status(upload_id, task_id)
