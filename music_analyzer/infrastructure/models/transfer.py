"""HTTPS-only, official-host-only, bounded streaming transfer; no inference."""
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import URLError
from http.client import HTTPException

from music_analyzer.application.dto.models import ModelError
from music_analyzer.infrastructure.models.manifest import official_url


class OfficialRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official_url(newurl):
            raise ModelError('Refused non-official or non-HTTPS model redirect.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HTTPSTransfer:
    def download(self, url: str, destination: str, expected_size: int) -> None:
        if not official_url(url):
            raise ModelError('Refused non-official or non-HTTPS model URL.')
        try:
            request = Request(url, headers={'User-Agent': 'music-analyzer/0.1', 'Accept-Encoding': 'identity'})
            with build_opener(OfficialRedirectHandler()).open(request, timeout=30) as response:
                if response.status != 200 or not official_url(response.geturl()):
                    raise ModelError('Unexpected model HTTP response; retry.')
                length = response.headers.get('Content-Length')
                if length is not None and int(length) != expected_size:
                    raise ModelError('Publisher asset size changed; review manifest before retry.')
                count = 0
                with open(destination, 'xb') as target:
                    while chunk := response.read(min(64 * 1024, expected_size - count + 1)):
                        count += len(chunk)
                        if count > expected_size:
                            raise ModelError('Download exceeds manifest size; retry after review.')
                        target.write(chunk)
                if count != expected_size:
                    raise ModelError('Incomplete model download; retry.')
        except (OSError, URLError, HTTPException, ValueError) as error:
            raise ModelError(f'Model transfer failed: {error}; check HTTPS connectivity and retry.') from error
