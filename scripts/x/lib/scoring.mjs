// scripts/x/lib/scoring.mjs
// 近似重複チェック（char 3-gram SimHash, 64-bit）。amble 実装を踏襲。
// 既存 account-config.json の safety.similarityThreshold と併用する。
import { readJsonl, POSTS_PATH } from "./file-lock.mjs";

function fnv1a32(str) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    hash ^= str.charCodeAt(i);
    hash = (hash * 0x01000193) >>> 0;
  }
  return hash;
}

function charTrigrams(text) {
  const clean = text.replace(/\s+/g, "");
  const grams = [];
  for (let i = 0; i <= clean.length - 3; i++) grams.push(clean.slice(i, i + 3));
  return grams;
}

export function charTrigramSimHash(text) {
  const grams = charTrigrams(text);
  if (grams.length === 0) return 0n;
  const bits = 64;
  const counts = new Array(bits).fill(0);
  for (const gram of grams) {
    const h1 = fnv1a32(gram);
    const h2 = fnv1a32(gram + "\x00");
    const hash64 = (BigInt(h1) << 32n) | BigInt(h2);
    for (let i = 0; i < bits; i++) {
      if ((hash64 >> BigInt(i)) & 1n) counts[i]++;
      else counts[i]--;
    }
  }
  let fp = 0n;
  for (let i = 0; i < bits; i++) if (counts[i] > 0) fp |= 1n << BigInt(i);
  return fp;
}

function hammingDistance(a, b) {
  let xor = a ^ b;
  let dist = 0;
  while (xor > 0n) {
    dist += Number(xor & 1n);
    xor >>= 1n;
  }
  return dist;
}

export function simhashSimilarity(a, b) {
  return 1 - hammingDistance(a, b) / 64;
}

export function simhashToHex(hash) {
  return "0x" + hash.toString(16).padStart(16, "0");
}

export function hexToSimhash(hex) {
  return BigInt(hex);
}

/**
 * 新テキストが既存投稿と近すぎないか判定。
 * @returns {{ pass, maxSimilarity, mostSimilarId, hash }}
 */
export function checkSimilarity(newText, existingPosts = null, threshold = 0.7) {
  if (!existingPosts) {
    existingPosts = readJsonl(POSTS_PATH).filter(
      (p) => p.status !== "rejected" && p.similarityHash
    );
  }
  const recent = existingPosts.slice(-120);
  const newHash = charTrigramSimHash(newText);
  let maxSimilarity = 0;
  let mostSimilarId = null;
  for (const post of recent) {
    const postHash =
      typeof post.similarityHash === "string"
        ? hexToSimhash(post.similarityHash)
        : BigInt(post.similarityHash);
    const sim = simhashSimilarity(newHash, postHash);
    if (sim > maxSimilarity) {
      maxSimilarity = sim;
      mostSimilarId = post.id;
    }
  }
  return {
    pass: maxSimilarity < threshold,
    maxSimilarity: Math.round(maxSimilarity * 1000) / 1000,
    mostSimilarId,
    hash: simhashToHex(newHash),
  };
}
