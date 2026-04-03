/**
 * Google Apps Script — 週次レポートメール通知
 *
 * 【設置手順】
 * 1. Google Sheets（X_SHEET_ID）を開く
 *    → https://docs.google.com/spreadsheets/d/1N1WMN0hjdfRlDyvQOa0TSyHQOvl3GG6L4Zf4QqoZXo0
 * 2. メニュー → 拡張機能 → Apps Script
 * 3. 以下のコードを貼り付けて保存
 * 4. 左メニュー「トリガー」（時計アイコン）をクリック
 * 5. 「トリガーを追加」→ 以下を設定:
 *    - 実行する関数: onWeeklyReportAdded
 *    - イベントソース: スプレッドシートから
 *    - イベントの種類: 変更時
 *    → 保存（Googleアカウントの権限承認が必要）
 *
 * ※ 初回は手動実行して権限を承認してください
 */

// ========== ↓ ここからApps Scriptに貼り付け ↓ ==========

function onWeeklyReportAdded(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("週次レポート");
  if (!sheet) return;

  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return; // ヘッダーのみ

  // 最新行のデータを取得
  var data = sheet.getRange(lastRow, 1, 1, 10).getValues()[0];
  var period    = data[0]; // 期間
  var pv        = data[1]; // PV
  var pvChange  = data[2]; // PV前週比
  var uu        = data[3]; // UU
  var sessions  = data[4]; // セッション
  var searchClk = data[5]; // 検索クリック
  var searchImp = data[6]; // 表示回数
  var avgPos    = data[7]; // 平均順位
  var affClicks = data[8]; // アフィクリック
  var genDate   = data[9]; // 生成日時

  // 直近に同じデータで送信済みでないか確認（重複防止）
  var props = PropertiesService.getScriptProperties();
  var lastSent = props.getProperty("lastSentPeriod");
  if (lastSent === String(period)) return;

  // メール本文作成
  var subject = "📊 週次レポート | " + period;

  var arrow = function(change) {
    if (!change || change === "-") return "";
    return parseFloat(change) > 0 ? " 📈" : parseFloat(change) < 0 ? " 📉" : "";
  };

  var body = "";
  body += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n";
  body += "📊 Outdoor Gear Lab 週次レポート\n";
  body += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n";
  body += "期間: " + period + "\n\n";

  body += "🔹 サイト全体\n";
  body += "  PV: " + Number(pv).toLocaleString() + arrow(pvChange) + " (前週比 " + pvChange + ")\n";
  body += "  ユーザー: " + Number(uu).toLocaleString() + "\n";
  body += "  セッション: " + Number(sessions).toLocaleString() + "\n\n";

  body += "🔹 Google 検索\n";
  body += "  検索クリック: " + Number(searchClk).toLocaleString() + "\n";
  body += "  表示回数: " + Number(searchImp).toLocaleString() + "\n";
  body += "  平均掲載順位: " + avgPos + "\n\n";

  body += "🔹 アフィリエイト\n";
  body += "  クリック数: " + affClicks + "\n\n";

  body += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n";
  body += "📄 詳細レポート:\n";
  body += "https://docs.google.com/spreadsheets/d/1N1WMN0hjdfRlDyvQOa0TSyHQOvl3GG6L4Zf4QqoZXo0\n\n";
  body += "生成日時: " + genDate + "\n";

  // メール送信
  GmailApp.sendEmail("naohide78@gmail.com", subject, body);

  // 送信済みフラグ更新
  props.setProperty("lastSentPeriod", String(period));
}

// 手動テスト用
function testSendReport() {
  onWeeklyReportAdded();
}

// ========== ↑ ここまでApps Scriptに貼り付け ↑ ==========
