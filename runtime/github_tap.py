"""Narrow REST adapter for the pinned upstream issues reader.

No GraphQL lookup, ambient tokens, or automatic authentication fallback.
Upstream schemas, issue parsing and Singer output remain unchanged.
"""
import json
import sys
from pathlib import Path
import requests
from singer_sdk.authenticators import APIAuthenticatorBase
from tap_github.tap import TapGitHub
from tap_github.repository_streams import RepositoryStream, IssuesStream


class AccessError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate(response):
    status = response.status_code
    if status == 429 or (status == 403 and (response.headers.get('X-RateLimit-Remaining') == '0' or response.headers.get('Retry-After'))):
        raise AccessError('GITHUB_RATE_LIMIT')
    if status == 401: raise AccessError('GITHUB_AUTH')
    if status == 403: raise AccessError('GITHUB_FORBIDDEN')
    if status == 404: raise AccessError('GITHUB_NOT_FOUND')
    if status >= 500: raise AccessError('GITHUB_UNAVAILABLE')
    if not 200 <= status < 300: raise AccessError('GITHUB_RESPONSE')


class ExplicitAuth(APIAuthenticatorBase):
    def __init__(self, token):
        super().__init__()
        if token: self.auth_headers = {'Authorization': 'Bearer ' + token}
    def set_organization(self, org): pass
    def update_rate_limit(self, headers): pass
    def get_next_auth_token(self): raise AccessError('GITHUB_AUTH')


class RestAccess:
    @property
    def authenticator(self):
        if self._authenticator is None:
            self._authenticator = ExplicitAuth(self.config.get('auth_token'))
        return self._authenticator
    def validate_response(self, response):
        validate(response)


class Repositories(RestAccess, RepositoryStream):
    def get_repo_ids(self, repo_list):
        result = []
        with requests.Session() as session:
            # Ignore .netrc and inherited credentials; the runtime passes only explicit auth.
            session.trust_env = False
            for org, repo in repo_list:
                response = session.get('https://api.github.com/repos/' + org + '/' + repo,
                    headers={**self.http_headers, **self.authenticator.auth_headers},
                    timeout=30, allow_redirects=False)
                validate(response)
                value = response.json()
                owner, name = value['full_name'].split('/')
                result.append({'org': owner, 'repo': name, 'repo_id': value['id']})
        return result


class Issues(RestAccess, IssuesStream):
    parent_stream_type = Repositories


class IngestronGitHub(TapGitHub):
    def discover_streams(self):
        return [Repositories(self), Issues(self)]


if __name__ == '__main__':
    flag = sys.argv.index('--ingestron-error-file')
    error_file = Path(sys.argv[flag + 1])
    del sys.argv[flag:flag + 2]
    try:
        IngestronGitHub.cli()
    except AccessError as error:
        error_file.write_text(json.dumps({'code': error.code}))
        raise SystemExit(1) from None
    except requests.RequestException:
        error_file.write_text(json.dumps({'code': 'GITHUB_NETWORK'}))
        raise SystemExit(1) from None
