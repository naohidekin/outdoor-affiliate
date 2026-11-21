"""Additive writing instructions only; no I/O, model calls, gates or schema changes."""


DRAFT_SPECIFICITY_PROMPT = """同じ上位Opusの1呼出し内で、本文を書く前に出典対応と論理を整理する。
H2ごとに読者の場面を決め、実在する出典IDと確認済み事実を結び、対象／表示・入力／条件／具体行動／判断の違い／例外・未確認を整理する。各節は異なる判断の問いを解く。brief.headingsとbrief.factsに節と根拠の対応・適用範囲・不足を保持し、引用はprotectedへ。内部の対応表や出典IDを読者向け本文へ写さない。
記事を貫く独自論点を最低1つ、出典から説明できる判断の違いとして置く。本文を同じ型の場面・引用・注意・まとめで反復せず、読者が選ぶ対象や次の確認行動まで具体化する。仮想の場面は仮想と明示し、実在の利用者事例や本人の経験にしない。
数値のない非商品ガイドでは対象・表示・条件・操作を具体化し、数字や体験を強要しない。数値根拠が必要な商品比較等の要件は維持する。必要な根拠の不足はbrief.factsに未確認として明示し、推測で補わない。未確認は不可・不存在を意味しない。架空体験・数字・効果・個別適合・安全保証を加えず、逆命題も導かない（AならBから、BならAやAでなければBでないと断定しない）。
一度説明した事実・免責・引用・一般論の言い換えで文量を埋めない。調査記事の説明は簡潔にし、必要な限定は該当する主張のそばに残す。ギア男の自然な口調で、公式引用・protectedは文体NGの置換対象から除外して原文を守る。
返却は既存の{article,brief}のみ。返却キーを増やさない。既存の字数・品質閾値・予算・承認を維持し、根拠のない文章で形式だけ満たさない。"""


FACTUAL_SPECIFICITY_PROMPT = """出典の条件はそのまま保つ。「表示がない」と「表示が読めない」は別であり、読めない場合へ不存在の場合の結論を適用しない。表示場所は出典がその場所にあると明記した項目だけに結び、品番・色名の所在から本体JANなど別項目の所在や、全製品での見やすさを広げて断定しない。型番の数字から容量・数量・寸法を推定せず、明示された仕様だけを使う。
公式資料の検索・照合・操作を読者の行動として案内する箇所には、提供された該当公式URLの完全一致リンクを本文にも置く。brief.linksやreferencesへの収録だけで本文リンクを置いた扱いにせず、未使用の資料数を埋めるためのリンク追加や未提供URLの生成はしない。"""


POLISH_STYLE_PROMPT = """Geminiは上位確定仕様の意味を変えない校正だけを行う。eligibleの段落内の重複・迂言・定型接続を減らし、ギア男の自然な口調と文のリズムへ整える。
構成・結論の変更、情報・例・条件の追加、数字・URL・CTAの変更は禁止。出典の限定や否定の意味も保持し、足りない根拠や論理をGeminiで補わない。公式引用・protectedは文体NGの置換対象外とし、既存の固定範囲を動かさない。
返却は既存の{edits:[{index,text}]}のみ。変更不要ならedits:[]。採点・承認を行わない。"""


def get_draft_specificity_prompt():
    """Return the instruction appended to the existing upper-editor draft call."""
    return DRAFT_SPECIFICITY_PROMPT + "\n" + FACTUAL_SPECIFICITY_PROMPT


def get_polish_style_prompt():
    """Return the instruction appended to the existing fixed-meaning polish call."""
    return POLISH_STYLE_PROMPT
