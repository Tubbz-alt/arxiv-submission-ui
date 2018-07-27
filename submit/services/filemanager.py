"""
Integration with the :mod:`filemanager` service API.

The file management service is responsible for accepting and processing user
uploads used for submissions. The core resource for the file management service
is the upload "workspace", which contains one or many files. We associate the
workspace with a submission prior to finalization. The workspace URI is used
for downstream processing, e.g. compilation.

A key requirement for this integration is the ability to stream uploads to
the file management service as they are being received by this UI application.
"""
from typing import Tuple
import json
from urllib.parse import urlparse, urlunparse, urlencode
import dateutil.parser
import requests
from requests.packages.urllib3.util.retry import Retry

from arxiv import status
from werkzeug.datastructures import FileStorage

from submit.domain import UploadStatus, FileStatus, Error


class RequestFailed(IOError):
    """The file management service returned an unexpected status code."""

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


class Oversize(BadRequest):
    """The upload was too large."""


class BadResponse(RequestFailed):
    """The response from the file management service was malformed."""


class ConnectionFailed(IOError):
    """Could not connect to the file management service."""


class SecurityException(ConnectionFailed):
    """Raised when SSL connection fails."""


class Download(object):
    """Wrapper around response content."""

    def __init__(self, response: requests.Response) -> None:
        """Initialize with a :class:`requests.Response` object."""
        self._response = response

    def read(self) -> bytes:
        """Read response content."""
        return self._response.content


class FileManagementService(object):
    """Encapsulates a connection with the file management service."""

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

    def _parse_upload_status(self, data: dict) -> UploadStatus:
        return UploadStatus(
            identifier=data['identifier'],
            checksum=data['checksum'],
            size=data['size'],
            file_list=[FileStatus(
                path=file_data['path'],
                name=file_data['name'],
                file_type=file_data['file_type'],
                added=dateutil.parser.parse(file_data['added']),
                size=int(file_data['size']),
                ancillary=bool(file_data['ancillary']),
                errors=[Error(
                    type=error_data['type'],
                    message=error_data['message'],
                    more_info=error_data['more_info']
                ) for error_data in file_data['errors']]
            ) for file_data in data['file_list']],
            errors=[Error(
                type=error_data['type'],
                message=error_data['message'],
                more_info=error_data['more_info']
            ) for error_data in data['errors']]
        )

    def _path(self, path: str, query: dict = {}) -> str:
        o = urlparse(self._endpoint)
        path = path.lstrip('/')
        return urlunparse((
            o.scheme, o.netloc, f"{o.path}{path}",
            None, urlencode(query), None
        ))

    def _make_request(self, method: str, path: str, expected_code: int = 200,
                      **kw) -> requests.Response:
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
        elif resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE:
            raise Oversize(f'Too large: {resp.content}')
        elif resp.status_code >= status.HTTP_400_BAD_REQUEST:
            raise BadRequest(f'Bad request: {resp.content}',
                             data=resp.content)
        elif resp.status_code is not expected_code:
            raise RequestFailed(f'Unexpected status code: {resp.status_code}')
        return resp

    def request(self, method: str, path: str, expected_code: int = 200, **kw) \
            -> Tuple[dict, dict]:
        """Perform an HTTP request, and handle any exceptions."""
        resp = self._make_request(method, path, expected_code, **kw)

        # There should be nothing in a 204 response.
        if resp.status_code is status.HTTP_204_NO_CONTENT:
            return {}, resp.headers
        try:
            return resp.json(), resp.headers
        except json.decoder.JSONDecodeError as e:
            raise BadResponse('Could not decode: {resp.content}') from e

    def request_file(self, path: str, expected_code: int = 200, **kw) \
            -> Tuple[Download, dict]:
        """Perform a GET request for a file, and handle any exceptions."""
        kw.update({'stream': True})
        resp = self._make_request('get', expected_code, **kw)
        return Download(resp), resp.headers

    def get_service_status(self) -> dict:
        """Get the status of the file management service."""
        return self.request('get', 'status')

    def upload_package(self, pointer: FileStorage) -> Tuple[dict, dict]:
        """
        Stream an upload to the file management service.

        If the file is an archive (zip, tar-ball, etc), it will be unpacked.
        A variety of processing and sanitization routines are performed, and
        any errors or warnings (including deleted files) will be included in
        the response body.

        Parameters
        ----------
        pointer : :class:`FileStorage`
            File upload stream from the client.

        Returns
        -------
        dict
            A description of the upload package.
        dict
            Response headers.
        """
        files = {'file': (pointer.filename, pointer, pointer.mimetype)}
        return self.request('post', '/', files=files,
                            expected_code=status.HTTP_201_CREATED)

    def get_upload_status(self, upload_id: str) -> Tuple[UploadStatus, dict]:
        """
        Retrieve metadata about an accepted and processed upload package.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.

        Returns
        -------
        dict
            A description of the upload package.
        dict
            Response headers.

        """
        data, headers = self.request('get', f'/{upload_id}')
        upload_status = self._parse_upload_status(data)
        return upload_status, headers

    def add_file(self, upload_id: str, pointer: FileStorage) \
            -> Tuple[dict, dict]:
        """
        Upload a file or package to an existing upload workspace.

        If the file is an archive (zip, tar-ball, etc), it will be unpacked. A
        variety of processing and sanitization routines are performed. Existing
        files will be overwritten by files of the  same name. and any errors or
        warnings (including deleted files) will be included in the response
        body.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.
        pointer : :class:`FileStorage`
            File upload stream from the client.

        Returns
        -------
        dict
            A description of the upload package.
        dict
            Response headers.

        """
        print('add file', upload_id)
        data, headers = self.request('post', f'/{upload_id}',
                                     files={'file': pointer},
                                     expected_code=status.HTTP_201_CREATED)
        print('::', data, headers)
        upload_status = self._parse_upload_status(data)
        print('::', upload_status)
        return upload_status, headers

    def delete_workspace(self, upload_id: str) -> Tuple[dict, dict]:
        """
        Delete the entire workspace.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.

        Returns
        -------
        dict
            An empty dict.
        dict
            Response headers.

        """
        return self.request('delete', f'/{upload_id}', expected_code=204)

    def delete_all(self, upload_id: str) -> Download:
        """
        Delete all files in the workspace.

        Does not delete the workspace itself.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.

        Returns
        -------
        dict
            An empty dict.
        dict
            Response headers.

        """
        return self.request('post', f'/{upload_id}/delete_all',
                            expected_code=status.HTTP_204_NO_CONTENT)

    def get_file_content(self, upload_id: str, file_path: str) \
            -> Tuple[Download, dict]:
        """
        Get the content of a single file from the upload workspace.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.
        file_path : str
            Path-like key for individual file in upload workspace.

        Returns
        -------
        :class:`Download`
            A ``read() -> bytes``-able wrapper around response content.
        dict
            Response headers.
        """
        return self.request_file(f'/{upload_id}/{file_path}/content')

    def delete_file(self, upload_id: str, file_path: str) -> Tuple[dict, dict]:
        """
        Delete a single file from the upload workspace.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.
        file_path : str
            Path-like key for individual file in upload workspace.

        Returns
        -------
        dict
            An empty dict.
        dict
            Response headers.
        """
        return self.request('delete', f'/{upload_id}/{file_path}',
                            expected_code=status.HTTP_204_NO_CONTENT)

    def get_upload_content(self, upload_id: str) -> Tuple[Download, dict]:
        """
        Retrieve the sanitized/processed upload package.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.

        Returns
        -------
        :class:`Download`
            A ``read() -> bytes``-able wrapper around response content.
        dict
            Response headers.

        """
        return self.request_file(f'/{upload_id}/content')

    def lock_upload(self, upload_id: str) -> Tuple[dict, dict]:
        """
        Lock workspace (read-only mode) while other services are processing.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.

        Returns
        -------
        dict
            A description of the upload package.
        dict
            Response headers.

        """
        return self.request('post', f'/{upload_id}/lock',
                            expected_code=status.HTTP_201_CREATED)

    def unlock_upload(self, upload_id: str) -> Tuple[dict, dict]:
        """
         Unlock workspace and enable write mode.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.

        Returns
        -------
        dict
            A description of the upload package.
        dict
            Response headers.

        """
        return self.request('post', f'/{upload_id}/unlock',
                            expected_code=status.HTTP_201_CREATED)

    def release_upload(self, upload_id: str) -> Tuple[dict, dict]:
        """
        Release workspace.

        File management service is free to remove uploaded files, or schedule
        files for removal at later time.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.

        Returns
        -------
        dict
            A description of the upload package.
        dict
            Response headers.

        """
        return self.request('post', f'/{upload_id}/release',
                            expected_code=status.HTTP_201_CREATED)

    def get_logs(self, upload_id: str) -> Tuple[dict, dict]:
        """
        Retrieve log files related to upload workspace.

        Indicates history or actions on workspace.

        Parameters
        ----------
        upload_id : str
            Unique long-lived identifier for the upload.

        Returns
        -------
        dict
            Log data for the upload workspace.
        dict
            Response headers.

        """
        return self.request('post', f'/{upload_id}/logs')
