#!/usr/bin/env node
// Narrow OAuth1 bridge. Never logs credentials, input text, media or provider errors.
import { TwitterApi } from 'twitter-api-v2';
import { pathToFileURL } from 'node:url';

const fail = () => { process.stdout.write('{"error":"x_api_unavailable"}\n'); process.exitCode = 1; };
export function projectReadback(post) {
  if (!post || typeof post !== 'object') throw Error('lookup');
  return { id: post.id, authorId: post.author_id, text: post.text,
    // Preserve numeric entity offsets and the media_key exactly; the checker
    // validates either documented code-point or UTF-16 positions.
    urls: (post.entities?.urls ?? []).map(url => ({ start: url.start, end: url.end,
      url: url.url, expanded_url: url.expanded_url, media_key: url.media_key })),
    mediaKeys: post.attachments?.media_keys ?? [],
    replyTo: (post.referenced_tweets ?? []).find(ref => ref.type === 'replied_to')?.id ?? null };
}

async function main() {
try {
  let raw = '';
  for await (const chunk of process.stdin) {
    raw += chunk;
    if (raw.length > 16 * 1024 * 1024) throw Error('oversize');
  }
  const request = JSON.parse(raw);
  const { action, payload } = request;
  if (!['preflight', 'upload', 'maincreate', 'replycreate', 'read'].includes(action) ||
      !payload || typeof payload !== 'object' || Array.isArray(payload)) throw Error('action');
  const names = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET'];
  if (names.some(name => !process.env[name])) throw Error('auth');
  const client = new TwitterApi({ appKey: process.env.X_API_KEY, appSecret: process.env.X_API_SECRET,
    accessToken: process.env.X_ACCESS_TOKEN, accessSecret: process.env.X_ACCESS_SECRET });
  let output;
  if (action === 'preflight') {
    const result = await client.v2.me();
    if (!/^\d+$/.test(result?.data?.id ?? '')) throw Error('identity');
    output = { userId: result.data.id };
  } else if (action === 'upload') {
    if (!['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(payload.mime) ||
        typeof payload.data !== 'string' || !/^[A-Za-z0-9+/]+={0,2}$/.test(payload.data)) throw Error('media');
    const bytes = Buffer.from(payload.data, 'base64');
    if (bytes.length < 32 || bytes.length > 8 * 1024 * 1024 || bytes.toString('base64') !== payload.data) throw Error('media');
    // Official /2/media/upload returns both the media ID and its readback key.
    const result = await client.v2.post('media/upload', {
      media: payload.data, media_category: payload.mime === 'image/gif' ? 'tweet_gif' : 'tweet_image',
    });
    if (!/^\d+$/.test(result?.data?.id ?? '') || typeof result?.data?.media_key !== 'string' ||
        !Number.isInteger(result?.data?.expires_after_secs)) throw Error('upload');
    output = { mediaId: result.data.id, mediaKey: result.data.media_key,
      expiresAfterSecs: result.data.expires_after_secs };
  } else if (action === 'maincreate') {
    if (typeof payload.text !== 'string' || !payload.text.trim() || !Array.isArray(payload.mediaIds) ||
        payload.mediaIds.length < 1 || payload.mediaIds.length > 4 ||
        payload.mediaIds.some(id => typeof id !== 'string' || !/^\d+$/.test(id))) throw Error('post');
    const result = await client.v2.tweet(payload.text, { media: { media_ids: payload.mediaIds } });
    if (!/^\d+$/.test(result?.data?.id ?? '')) throw Error('post');
    output = { id: result.data.id };
  } else if (action === 'replycreate') {
    if (typeof payload.text !== 'string' || !payload.text.trim() || !/^\d+$/.test(payload.parentId ?? '')) throw Error('reply');
    const result = await client.v2.tweet(payload.text, { reply: { in_reply_to_tweet_id: payload.parentId } });
    if (!/^\d+$/.test(result?.data?.id ?? '')) throw Error('reply');
    output = { id: result.data.id };
  } else {
    if (!/^\d+$/.test(payload.id ?? '')) throw Error('lookup');
    const result = await client.v2.singleTweet(payload.id, {
      'tweet.fields': 'author_id,attachments,entities,referenced_tweets',
      expansions: 'attachments.media_keys',
      'media.fields': 'media_key',
    });
    const post = result?.data;
    if (!post || post.id !== payload.id) throw Error('lookup');
    output = projectReadback(post);
  }
  process.stdout.write(JSON.stringify(output) + '\n');
} catch {
  fail();
}
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
