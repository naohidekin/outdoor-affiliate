"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface UnifiedStats {
  kodomo: {
    totalPosts: number;
    draftCount: number;
    approvedCount: number;
    postedCount: number;
    wisePassCount: number;
    wisePassRate: number;
  };
  sanpedi: {
    totalPosts: number;
    draftCount: number;
    approvedCount: number;
    postedCount: number;
    wisePassCount: number;
    wisePassRate: number;
  };
}

export default function XPostsUnifiedPage() {
  const [stats, setStats] = useState<UnifiedStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        setLoading(true);
        const res = await fetch("/api/x-posts-unified");
        if (!res.ok) {
          throw new Error("統計取得に失敗しました");
        }
        const data = await res.json();
        setStats(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "エラーが発生しました");
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, []);

  if (loading) {
    return (
      <div className="p-8">
        <p className="text-gray-500">読み込み中…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
          {error}
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="p-8">
        <p className="text-gray-500">データが利用できません</p>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">X投稿統合管理</h1>
        <p className="text-gray-500 mt-1">kodomocarelab と san-pedinvestor のポスト情報を統合表示します</p>
      </div>

      {/* Overall Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        {/* Kodomo Stats */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold text-gray-900">こどもケアラボ</h2>
            <Link
              href="/admin/kodomo"
              className="text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              詳細を見る →
            </Link>
          </div>

          <div className="space-y-3">
            {/* WISE Pass Rate */}
            <div className="flex items-center justify-between p-3 bg-gradient-to-r from-amber-50 to-amber-100/50 rounded-lg border border-amber-200">
              <span className="text-sm font-medium text-amber-900">WISE合格率</span>
              <span className="text-xl font-bold text-amber-700">{stats.kodomo.wisePassRate}%</span>
              <span className="text-xs text-amber-600">({stats.kodomo.wisePassCount}/{stats.kodomo.totalPosts})</span>
            </div>

            {/* Status breakdown */}
            <div className="grid grid-cols-3 gap-2">
              <div className="p-2 bg-yellow-50 rounded-lg border border-yellow-200 text-center">
                <p className="text-xs text-yellow-700 font-medium">下書き</p>
                <p className="text-lg font-bold text-yellow-800">{stats.kodomo.draftCount}</p>
              </div>
              <div className="p-2 bg-blue-50 rounded-lg border border-blue-200 text-center">
                <p className="text-xs text-blue-700 font-medium">承認済</p>
                <p className="text-lg font-bold text-blue-800">{stats.kodomo.approvedCount}</p>
              </div>
              <div className="p-2 bg-green-50 rounded-lg border border-green-200 text-center">
                <p className="text-xs text-green-700 font-medium">投稿済</p>
                <p className="text-lg font-bold text-green-800">{stats.kodomo.postedCount}</p>
              </div>
            </div>

            <div className="text-xs text-gray-500 pt-2 border-t border-gray-200">
              合計: <span className="font-semibold text-gray-700">{stats.kodomo.totalPosts}</span> 件
            </div>
          </div>
        </div>

        {/* San-Pedi Stats */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold text-gray-900">アンブロ（san-pedinvestor）</h2>
            <Link
              href="/admin/amble"
              className="text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              詳細を見る →
            </Link>
          </div>

          <div className="space-y-3">
            {/* WISE Pass Rate */}
            <div className="flex items-center justify-between p-3 bg-gradient-to-r from-cyan-50 to-cyan-100/50 rounded-lg border border-cyan-200">
              <span className="text-sm font-medium text-cyan-900">WISE合格率</span>
              <span className="text-xl font-bold text-cyan-700">{stats.sanpedi.wisePassRate}%</span>
              <span className="text-xs text-cyan-600">({stats.sanpedi.wisePassCount}/{stats.sanpedi.totalPosts})</span>
            </div>

            {/* Status breakdown */}
            <div className="grid grid-cols-3 gap-2">
              <div className="p-2 bg-yellow-50 rounded-lg border border-yellow-200 text-center">
                <p className="text-xs text-yellow-700 font-medium">下書き</p>
                <p className="text-lg font-bold text-yellow-800">{stats.sanpedi.draftCount}</p>
              </div>
              <div className="p-2 bg-blue-50 rounded-lg border border-blue-200 text-center">
                <p className="text-xs text-blue-700 font-medium">承認済</p>
                <p className="text-lg font-bold text-blue-800">{stats.sanpedi.approvedCount}</p>
              </div>
              <div className="p-2 bg-green-50 rounded-lg border border-green-200 text-center">
                <p className="text-xs text-green-700 font-medium">投稿済</p>
                <p className="text-lg font-bold text-green-800">{stats.sanpedi.postedCount}</p>
              </div>
            </div>

            <div className="text-xs text-gray-500 pt-2 border-t border-gray-200">
              合計: <span className="font-semibold text-gray-700">{stats.sanpedi.totalPosts}</span> 件
            </div>
          </div>
        </div>
      </div>

      {/* Consolidated Summary */}
      <div className="bg-gradient-to-r from-slate-900 to-slate-800 rounded-xl p-6 text-white">
        <h3 className="text-lg font-bold mb-4">全体統計</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div>
            <p className="text-sm text-gray-300">総投稿数</p>
            <p className="text-2xl font-bold mt-1">{stats.kodomo.totalPosts + stats.sanpedi.totalPosts}</p>
          </div>
          <div>
            <p className="text-sm text-gray-300">下書き</p>
            <p className="text-2xl font-bold text-yellow-300 mt-1">{stats.kodomo.draftCount + stats.sanpedi.draftCount}</p>
          </div>
          <div>
            <p className="text-sm text-gray-300">承認済</p>
            <p className="text-2xl font-bold text-blue-300 mt-1">{stats.kodomo.approvedCount + stats.sanpedi.approvedCount}</p>
          </div>
          <div>
            <p className="text-sm text-gray-300">投稿済</p>
            <p className="text-2xl font-bold text-green-300 mt-1">{stats.kodomo.postedCount + stats.sanpedi.postedCount}</p>
          </div>
          <div>
            <p className="text-sm text-gray-300">WISE合格率</p>
            <p className="text-2xl font-bold text-emerald-300 mt-1">
              {stats.kodomo.totalPosts + stats.sanpedi.totalPosts > 0
                ? Math.round(
                    ((stats.kodomo.wisePassCount + stats.sanpedi.wisePassCount) /
                      (stats.kodomo.totalPosts + stats.sanpedi.totalPosts)) *
                      100
                  )
                : 0}
              %
            </p>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="mt-8 bg-gray-50 rounded-lg p-4 border border-gray-200">
        <h3 className="text-sm font-bold text-gray-700 mb-3">WISE Framework合格基準</h3>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="bg-green-100 text-green-800 px-2 py-1 rounded font-mono">W (シャレ) ≥2</span>
          <span className="bg-green-100 text-green-800 px-2 py-1 rounded font-mono">I (本質) ≥2</span>
          <span className="bg-green-100 text-green-800 px-2 py-1 rounded font-mono">S (切実) ≥2</span>
          <span className="bg-green-100 text-green-800 px-2 py-1 rounded font-mono">E (深さ) ≥2</span>
          <span className="bg-green-100 text-green-800 px-2 py-1 rounded font-mono">AI (人間らしさ) ≥3</span>
        </div>
      </div>
    </div>
  );
}
