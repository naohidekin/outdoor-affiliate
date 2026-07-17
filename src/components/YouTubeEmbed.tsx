"use client";

import { useState } from "react";
import Image from "next/image";

// YouTube埋め込み（ファサード方式）。
// 初期表示はサムネイル画像だけを描画し、クリックされて初めてiframeを差し込む。
// 動画1本ごとに数百KBのYouTubeスクリプトを読まずに済むため、ページ速度を守れる。
// 記事内タグ: {{youtube:動画ID}} または {{youtube:動画ID|キャプション（チャンネル名クレジット）}}
export default function YouTubeEmbed({
  videoId,
  caption,
}: {
  videoId: string;
  caption?: string;
}) {
  const [playing, setPlaying] = useState(false);

  return (
    <figure className="my-6">
      <div className="relative w-full aspect-video rounded-xl overflow-hidden bg-black">
        {playing ? (
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0`}
            title={caption || "YouTube動画"}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
            className="absolute inset-0 w-full h-full border-0"
          />
        ) : (
          <button
            type="button"
            onClick={() => setPlaying(true)}
            className="group absolute inset-0 w-full h-full cursor-pointer"
            aria-label={`動画を再生: ${caption || videoId}`}
          >
            <Image
              src={`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`}
              alt={caption || "YouTube動画のサムネイル"}
              fill
              sizes="(max-width: 768px) 100vw, 720px"
              className="object-cover"
              loading="lazy"
            />
            {/* 再生ボタン */}
            <span className="absolute inset-0 flex items-center justify-center">
              <span className="flex items-center justify-center w-16 h-11 rounded-xl bg-black/70 group-hover:bg-red-600 transition-colors">
                <svg viewBox="0 0 24 24" className="w-7 h-7 fill-white ml-0.5" aria-hidden>
                  <path d="M8 5v14l11-7z" />
                </svg>
              </span>
            </span>
          </button>
        )}
      </div>
      {caption && (
        <figcaption className="mt-2 text-xs text-slate-500 text-center">
          ▶ {caption}（YouTube）
        </figcaption>
      )}
    </figure>
  );
}
