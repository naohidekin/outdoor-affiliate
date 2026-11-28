"""Owner-facing explanations only; never changes gates or retries effects."""
import re

# These editorial validation failures need internal correction, not owner action.
INTERNAL_REASONS = {
    'Two to three distinct internal article links required',
    'Article length outside existing SKILL limits',
}

SOCIAL_RECONCILIATION_REASONS = {
    'buffer_publication_requires_reconciliation',
    'social_publication_requires_reconciliation',
    'social_publication_unverified',
    'buffer_schedule_notice_requires_reconciliation',
    'social_posted_notice_requires_reconciliation',
}

REASONS = {
    'buffer_publication_requires_reconciliation': (
        '記事は公開済みです。X投稿の結果をまだ確認できていません。',
        '本人の操作は不要です。二重投稿を避けるため、再投稿せずに記録を確認します。'),
    'social_publication_requires_reconciliation': (
        '記事は公開済みです。X投稿の結果をまだ確認できていません。',
        '本人の操作は不要です。二重投稿を避けるため、再投稿せずに記録を確認します。'),
    'social_publication_unverified': (
        '記事は公開済みです。X上の公開をまだ確認できていません。',
        '本人の操作は不要です。再投稿せずに記録を確認します。'),
    'buffer_schedule_notice_requires_reconciliation': (
        '記事は公開済みです。Xの予約通知が届いたか確認できていません。',
        '本人の操作は不要です。通知の記録を確認します。'),
    'social_posted_notice_requires_reconciliation': (
        '記事は公開済みです。X投稿の完了通知が届いたか確認できていません。',
        '本人の操作は不要です。通知の記録を確認します。'),
    'daily_metrics_not_fresh': (
        '当日分の集計を確認できず、新しい企画の調査に進んでいません。',
        '本人の操作は不要です。集計の実行記録を確認します。'),
    'daily_metrics_collection_failed': (
        '当日分のアクセス集計を保存できませんでした。',
        '本人の操作は不要です。失敗した集計処理を確認します。'),
    'weekly_research_requires_reconciliation': (
        '週次企画の処理が終了したか確認できていません。',
        '本人の操作は不要です。処理をやり直さず、保存済みの結果を確認します。'),
    'Two to three distinct internal article links required': (
        '本文の関連記事リンクが規定の2〜3本になっていません。',
        '本人の操作は不要です。関連記事リンクの修正対象として内部で保持します。'),
    'Article length outside existing SKILL limits': (
        '本文の文字数が記事形式ごとの規定範囲から外れています。',
        '本人の操作は不要です。文字数の調整対象として内部で保持します。'),
    'source_product_image_or_affiliate_verification_incomplete': (
        '商品の仕様・写真・購入リンクの確認がそろっていないため、制作を止めています。',
        '「商品情報を再調査して」と返信できます。正しい商品ページをご存じなら、そのURLも添えてください。'),
    'delivery_requires_reconciliation': (
        '確認用の内容をSlackへ送れたか確定できていません。重複送信を避けるため止めています。',
        '「届いているか調べて」と返信してください。内容を再送する前に送信記録を確認します。'),
    'editorial_manager_requires_attention': (
        '記事制作の管理処理で確認が必要になりました。具体的な原因は記録の調査が必要です。',
        '「制作が止まった原因を調べて」と返信してください。'),
}


def thread_url(scope):
    channel, ts = scope.get('channel_id', ''), scope.get('thread_ts', '')
    if not re.fullmatch(r'[CG][A-Z0-9]+', channel) or not re.fullmatch(r'\d{10}\.\d{6}', ts):
        return ''
    return 'https://app.slack.com/archives/' + channel + '/p' + ts.replace('.', '')


def attention_text(items, scope, details=None):
    details = details or {}
    items = sorted(items, key=lambda item: (item.get('error') or {}).get('reason') in SOCIAL_RECONCILIATION_REASONS)
    only_social = bool(items) and all((item.get('error') or {}).get('reason') in SOCIAL_RECONCILIATION_REASONS for item in items)
    heading = '【X投稿の確認】' if only_social else '【記事制作が止まっています】'
    lines = [heading, '公開の承認依頼ではありません。以下の確認が必要です。']
    social_section = only_social
    for index, item in enumerate(items, 1):
        if not social_section and (item.get('error') or {}).get('reason') in SOCIAL_RECONCILIATION_REASONS:
            lines += ['', '', '【X投稿の確認】']
            social_section = True
        title = str(item.get('title') or '')
        if title == item.get('id') or title in ('editorial-manager', 'runtime'):
            title = '記事制作の処理'
        # Plain text, no active Slack mention or user-supplied link markup.
        title = re.sub(r'[<>\r\n]', ' ', title)[:200]
        reason, action = REASONS.get((item.get('error') or {}).get('reason'), (
            '処理を続けられませんでした。具体的な原因はまだ確認できていません。',
            '「原因を調べて」と返信してください。確認できた原因と次の対応をお伝えします。'))
        lines += (['', ''] if index > 1 else ['']) + [str(index) + '. ' + title, '理由：' + reason]
        summary = research_summary(details.get(item.get('id'), ''))
        if summary:
            lines.append('未確認の内容：' + summary)
        lines.append('依頼できること：' + action)
    lines += ['', '回答・修正の入口：この通知のスレッドで@を入力して候補からmaruを選び、番号と依頼を書いてください。',
              '例：「maru、1の商品情報を再調査して」',
              'この通知は公開承認ボタンではありません。送信結果不明のものは確認前に再送しません。']
    url = thread_url(scope)
    if url:
        lines += ['相談スレッドを開く：' + url]
    return '\n'.join(lines)


def research_summary(raw):
    """Summarize known issue categories, retaining no raw diagnostics/IDs."""
    summaries = []
    for index, line in enumerate(str(raw).splitlines()[:6], 1):
        categories = []
        if '仕様:' in line:
            categories.append('公式の仕様')
        if '商品画像の同一性未確認' in line or 'image unavailable' in line:
            categories.append('商品写真が同じ製品か')
        if '購入先未確認:' in line:
            stores = [('rakuten', '楽天'), ('amazon', 'Amazon'), ('yahoo', 'Yahoo!')]
            found = [jp for key, jp in stores if key in line.split('購入先未確認:', 1)[1].split(';',1)[0]]
            categories.append('購入リンク' + ('（' + '・'.join(found) + '）' if found else ''))
        if 'manufacturer page unavailable' in line:
            categories.append('メーカー公式ページの取得')
        if categories:
            name = re.sub(r'[<>\r\n]', ' ', line.split(':', 1)[0])[:100]
            summaries.append((name or '掲載商品') + '：' + '、'.join(categories))
    return '／'.join(summaries)
