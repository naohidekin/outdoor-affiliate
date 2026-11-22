"""Small bounded GraphQL transport for Buffer's public API."""
import json
import re
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


BUFFER_ENDPOINT = 'https://api.buffer.com'
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


POST_FIELDS = """
id channelId channelService dueAt sentAt externalLink isCustomScheduled shareMode status text
assets { id type mimeType source thumbnail }
metadata {
  ... on TwitterPostMetadata {
    threadCount
    thread { text assets { id type mimeType source thumbnail } }
  }
}
"""


class BufferAPI:
    """GraphQL client with one fixed host and an injectable HTTP transport."""

    def __init__(self, api_key, *, transport=None, endpoint=BUFFER_ENDPOINT, timeout=20):
        parsed = urlparse(endpoint)
        if (parsed.scheme != 'https' or parsed.hostname != 'api.buffer.com' or parsed.path not in ('', '/')
                or parsed.port is not None or parsed.query or parsed.fragment or parsed.username):
            raise ValueError('buffer_endpoint_invalid')
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError('buffer_api_key_missing')
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout
        self.transport = transport or self._http
        self.rate_limit_headers = {}
        self.rate_limits = []
        self.retry_after = None

    @staticmethod
    def _http(url, headers, body, timeout):
        request = Request(url, data=body, headers=headers, method='POST')
        try:
            response = build_opener(_NoRedirect).open(request, timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError('buffer_response_too_large')
            return response.status, body, list(response.headers.items())

    def execute(self, query, variables):
        body = json.dumps({'query': query, 'variables': variables}, ensure_ascii=False,
                          allow_nan=False, separators=(',', ':')).encode()
        headers = {'Authorization': 'Bearer ' + self.api_key, 'Content-Type': 'application/json',
                   'Accept': 'application/json'}
        try:
            response = self.transport(self.endpoint, headers, body, self.timeout)
            if isinstance(response, tuple) and len(response) == 3:
                status, raw, response_headers = response
            elif isinstance(response, tuple):
                status, (raw, response_headers) = 200, response
            else:
                status, raw, response_headers = 200, response, []
            if isinstance(raw, (bytes, bytearray)) and len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError('buffer_response_too_large')
            pairs = list(response_headers.items()) if isinstance(response_headers, dict) else list(response_headers)
            selected = [(key, value) for key, value in pairs
                        if key.lower() in ('ratelimit', 'ratelimit-policy', 'retry-after')]
            self.rate_limit_headers = {}
            for key, value in selected:
                self.rate_limit_headers.setdefault(key.lower(), []).extend(
                    re.split(r',\s*(?=")', value))
            self.rate_limits = self._parse_rate_limits(self.rate_limit_headers)
            retry = self.rate_limit_headers.get('retry-after', [])
            self.retry_after = int(retry[-1]) if retry and retry[-1].isdigit() else None
            value = json.loads(raw) if isinstance(raw, (bytes, bytearray, str)) else raw
        except Exception:
            raise ValueError('buffer_transport_unknown') from None
        errors = value.get('errors', []) if isinstance(value, dict) else []
        if status == 429 or any((error.get('extensions') or {}).get('code') == 'RATE_LIMIT_EXCEEDED'
                                for error in errors if isinstance(error, dict)):
            raise ValueError('buffer_rate_limited')
        if status != 200:
            raise ValueError('buffer_transport_unknown')
        if not isinstance(value, dict) or value.get('errors') or not isinstance(value.get('data'), dict):
            raise ValueError('buffer_response_invalid')
        return value['data']

    @staticmethod
    def _parse_rate_limits(headers):
        statuses, policies = {}, {}
        for value in headers.get('ratelimit', []):
            name = re.search(r'"([^"]+)"', value)
            remaining, reset = re.search(r'(?:^|;)\s*r=(\d+)', value), re.search(r'(?:^|;)\s*t=(\d+)', value)
            if name and remaining and reset:
                statuses[name.group(1)] = {'remaining': int(remaining.group(1)),
                                           'resetAfter': int(reset.group(1))}
        for value in headers.get('ratelimit-policy', []):
            name = re.search(r'"([^"]+)"', value)
            quota, window = re.search(r'(?:^|;)\s*q=(\d+)', value), re.search(r'(?:^|;)\s*w=(\d+)', value)
            if name and quota and window:
                policies[name.group(1)] = {'quota': int(quota.group(1)), 'window': int(window.group(1))}
        return [dict(name=name, **policy, **statuses[name]) for name, policy in policies.items()
                if name in statuses and policy['window'] in (900, 86400, 2592000)]

    def preflight(self, organization_id, channel_id):
        data = self.execute("""query BufferPreflight(
          $organization: OrganizationFilterInput!, $channel: ChannelInput!
        ) {
          account { organizations(filter: $organization) { id } }
          channel(input: $channel) {
            id organizationId name service serviceId isDisconnected isLocked isQueuePaused
            timezone postingSchedule { day paused times }
            linkShortening { isEnabled }
          }
        }""", {'organization': {'organizationId': organization_id},
                 'channel': {'id': channel_id}})
        organizations = ((data.get('account') or {}).get('organizations'))
        channel = data.get('channel')
        if (not isinstance(organizations, list)
                or [item.get('id') for item in organizations] != [organization_id]
                or not isinstance(channel, dict) or channel.get('id') != channel_id):
            raise ValueError('buffer_binding_mismatch')
        return channel

    def discover_channel(self, channel_id, x_account_id, *, max_organizations=3):
        """Read-only bounded discovery used before an organization binding is approved."""
        data = self.execute("""query BufferOrganizations {
          account { organizations { id } }
        }""", {})
        organizations = ((data.get('account') or {}).get('organizations'))
        if (not isinstance(organizations, list) or not organizations
                or len(organizations) > max_organizations
                or any(not isinstance(item, dict) or not isinstance(item.get('id'), str)
                       for item in organizations)):
            raise ValueError('buffer_organization_discovery_unbounded')
        matches = []
        for organization in organizations:
            result = self.execute("""query BufferChannels($input: ChannelsInput!) {
              channels(input: $input) {
                id organizationId name service serviceId isDisconnected isLocked isQueuePaused
                linkShortening { isEnabled }
              }
            }""", {'input': {'organizationId': organization['id']}})
            channels = result.get('channels')
            if not isinstance(channels, list) or len(channels) > 100:
                raise ValueError('buffer_channel_discovery_unbounded')
            matches.extend(channel for channel in channels if isinstance(channel, dict)
                           and channel.get('id') == channel_id
                           and channel.get('organizationId') == organization['id']
                           and channel.get('service') == 'twitter'
                           and channel.get('serviceId') == x_account_id)
        if len(matches) != 1:
            raise ValueError('buffer_binding_mismatch')
        return {'organizationId': matches[0]['organizationId'], 'channelId': channel_id,
                'xAccountId': x_account_id, 'channel': matches[0]}

    def posts(self, organization_id, channel_id, start, end):
        data = self.execute("""query BufferPosts($input: PostsInput!) {
          posts(input: $input, first: 100) { edges { node { %s } } pageInfo { hasNextPage } }
        }""" % POST_FIELDS, {'input': {'organizationId': organization_id, 'filter': {
            'channelIds': [channel_id], 'createdAt': {'start': start, 'end': end},
            'status': ['draft', 'scheduled', 'sending', 'sent']}}})
        result = data.get('posts')
        if not isinstance(result, dict) or (result.get('pageInfo') or {}).get('hasNextPage') is True:
            raise ValueError('buffer_posts_unbounded')
        edges = result.get('edges')
        if not isinstance(edges, list):
            raise ValueError('buffer_response_invalid')
        return [edge.get('node') for edge in edges if isinstance(edge, dict)]

    def post(self, post_id):
        data = self.execute("""query BufferPost($input: PostInput!) {
          post(input: $input) { %s }
        }""" % POST_FIELDS, {'input': {'id': post_id}})
        return data.get('post')

    def pending_posts(self, organization_id, channel_id):
        """All outstanding reservations, including old-created/custom posts."""
        if any(not isinstance(value, str) or not value.strip()
               for value in (organization_id, channel_id)):
            raise ValueError('buffer_binding_mismatch')
        data = self.execute("""query BufferPendingPosts($input: PostsInput!) {
          posts(input: $input, first: 100) {
            edges { node { %s } } pageInfo { hasNextPage }
          }
        }""" % POST_FIELDS, {'input': {'organizationId': organization_id, 'filter': {
            'channelIds': [channel_id], 'status': ['draft', 'scheduled', 'sending']}}})
        result = data.get('posts')
        if (not isinstance(result, dict)
                or not isinstance(result.get('pageInfo'), dict)
                or result['pageInfo'].get('hasNextPage') is not False):
            raise ValueError('buffer_pending_posts_incomplete')
        edges = result.get('edges')
        if (not isinstance(edges, list) or len(edges) > 100
                or any(not isinstance(edge, dict) or not isinstance(edge.get('node'), dict)
                       for edge in edges)):
            raise ValueError('buffer_pending_posts_invalid')
        posts, seen = [], set()
        for edge in edges:
            post = edge['node']
            post_id = post.get('id')
            status = post.get('status')
            if (not isinstance(post_id, str) or not post_id.strip() or post_id in seen
                    or post.get('channelId') != channel_id
                    or post.get('channelService') != 'twitter'
                    or status not in ('draft', 'scheduled', 'sending')):
                raise ValueError('buffer_pending_posts_invalid')
            due_at = post.get('dueAt')
            if status in ('scheduled', 'sending') or due_at is not None:
                # An unknown sending time is not an empty reservation. Surface
                # uncertainty to the publisher; never synthesize a timestamp.
                if (not isinstance(due_at, str) or not re.fullmatch(
                        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?'
                        r'(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', due_at)
                        or due_at.endswith('-00:00')):
                    raise ValueError('buffer_pending_posts_invalid')
                try:
                    parsed = datetime.fromisoformat(due_at.replace('Z', '+00:00'))
                    if parsed.utcoffset() is None:
                        raise ValueError
                except ValueError:
                    raise ValueError('buffer_pending_posts_invalid') from None
            seen.add(post_id)
            posts.append(post)
        return posts

    def create_post(self, value):
        data = self.execute("""mutation BufferCreatePost($input: CreatePostInput!) {
          createPost(input: $input) {
            __typename
            ... on PostActionSuccess { post { %s } }
            ... on MutationError { message }
          }
        }""" % POST_FIELDS, {'input': value})
        return self._action(data.get('createPost'))

    def edit_post(self, value):
        data = self.execute("""mutation BufferEditPost($input: EditPostInput!) {
          editPost(input: $input) {
            __typename
            ... on PostActionSuccess { post { %s } }
            ... on MutationError { message }
          }
        }""" % POST_FIELDS, {'input': value})
        return self._action(data.get('editPost'))

    @staticmethod
    def _action(payload):
        if not isinstance(payload, dict) or payload.get('__typename') != 'PostActionSuccess':
            raise ValueError('buffer_action_rejected')
        post = payload.get('post')
        if not isinstance(post, dict) or not isinstance(post.get('id'), str) or not post['id']:
            raise ValueError('buffer_response_invalid')
        return post
