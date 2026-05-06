"""
FANZA ランキングサイト生成スクリプト（Chrome自動操作版）
- ランキング上位20件を取得
- ランダムで3件を選出して処理
- 各動画の後ろ45秒を切り出し
- 既存のChromeをリモートデバッグで操作してX投稿
- 1ツイート目：コメント + 動画
- 返信：「続きはこちら」+ アフィリエイトリンク

【タスクスケジューラー設定】
  6:55 → chrome_start.bat を実行（Chrome起動）
  7:00 → python fanza_site_gen.py を実行

生成物:
  site/index.html
  site/videos/
"""

import requests
import os
import re
import time
import random
import tempfile
import subprocess
import threading
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright

# ==============================
# 設定
# ==============================
API_ID            = "3Hg6dFtBHZEpRg5nqbss"
API_AFFILIATE_ID  = "amam2442-990"
REAL_AFFILIATE_ID = "amam2442-004"
OUTPUT_DIR        = os.path.join(os.path.dirname(__file__), "site")
VIDEO_DIR         = os.path.join(OUTPUT_DIR, "videos")

# Chromeリモートデバッグ設定
CHROME_DEBUG_URL = "http://localhost:9222"

# 自分のXのユーザー名（@なし）
X_USERNAME = "zizi3141"  # 例: "your_username"

# 同ジャンルアカウントへの返信設定
REPLY_SEARCH_KEYWORDS = [
    "FANZA",
    "アダルト動画",
    "エロ動画",
    "AV女優",
    "新作AV",
    "おすすめAV",
    "神作品",
    "AV解禁",
    "おすすめ女優",
    "ランキング1位",
]
REPLY_MAX_COUNT = 3

# ランキング取得件数
RANKING_HITS  = 20
PROCESS_COUNT = 1

# Ctrl+C で終了するためのフラグ
_stop_event = threading.Event()

API_URL = "https://api.dmm.com/affiliate/v3/ItemList"
PARAMS = {
    "api_id":       API_ID,
    "affiliate_id": API_AFFILIATE_ID,
    "site":         "FANZA",
    "service":      "digital",
    "floor":        "videoa",
    "hits":         RANKING_HITS,
    "offset":       1,
    "sort":         "rank",
    "output":       "json",
}

def fix_affiliate_url(url):
    return url.replace(API_AFFILIATE_ID, REAL_AFFILIATE_ID)

# ==============================
# ffmpegパス解決（Windows対応）
# ==============================
def find_command(name):
    import shutil
    path = shutil.which(name)
    if path:
        return path
    candidates = [
        rf"C:\bin\{name}.exe",
        rf"C:\ffmpeg\bin\{name}.exe",
        rf"C:\Program Files\ffmpeg\bin\{name}.exe",
        rf"C:\Users\{os.environ.get('USERNAME','')}\ffmpeg\bin\{name}.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return name

FFMPEG  = find_command("ffmpeg")
FFPROBE = find_command("ffprobe")

# ==============================
# コメントプール（感想のみ・名前なし）
# ==============================
COMMENT_POOL = [
    "結局これに尽きる",
    "見てないやつ全員損",
    "今週これしかない",
    "ずっとこれでいい",
    "これが正解だった",
    "9割の人が知らないやつ",
    "沼る自信しかない",
    "見た瞬間に全部わかった",
    "これは反則",
    "今月これしか勝たん",
    "普通に神だった",
    "予想の3倍よかった",
    "深夜に見るな。止まらなくなる",
    "今夜の時間の使い方はこれ",
    "明日後悔するとわかってても見る",
    "1回で終われなかったやつ",
    "基準が変わってしまった",
    "見る前に戻れない",
    "また見てしまった",
    "これ知ってる人と話したい",
    "なんで今まで知らなかったんだ",
    "見た後しばらく何も見れなかった",
    "全部持っていかれた",
    "語彙力が消えた",
    "ランキング信じてよかった",
    "今週いちばんの当たり",
    "埋もれてたのが謎",
    "今すぐ広まってほしい",
    "知ってる人だけ得してる",
    "これ見つけた人天才",
    "タイムラインに流れてきてよかった",
    "保存した",
    "これ系一番好き",
    "ほんとに止まらなくなる",
    "こういうの求めてた",
]

# ==============================
# 返信コメントプール
# ==============================
REPLY_COMMENT_POOL = [
    "わかりすぎて笑った",
    "自分もこれ好きです",
    "センス一致してて嬉しい",
    "同じこと思ってた",
    "これ沼るやつですよね",
    "普通によかったですよね",
    "また見たくなってきた",
    "趣味合う人いた",
    "これ知ってる人と繋がりたかった",
    "自分も同じ派です",
    "わかる、止まらなくなる",
    "これは反則ですよね",
    "見てよかったやつ",
    "好きな人多そう",
    "またランキング上がりそう",
]

# ==============================
# アフィリエイト返信テンプレート
# ==============================
AFFILIATE_REPLY_TEMPLATES = [
    "続きはこちら👇\n{url}",
    "フル動画はこちら👇\n{url}",
    "▶️ 本編を見る\n{url}",
    "気になった方はこちら👇\n{url}",
    "詳細・購入はこちら👇\n{url}",
]

def build_comment(item):
    return random.choice(COMMENT_POOL)

# ==============================
# FANZA APIからランキング取得
# ==============================
def fetch_ranking():
    print(f"ランキング上位{RANKING_HITS}件取得中...")
    resp = requests.get(API_URL, params=PARAMS, timeout=10)
    resp.raise_for_status()
    items = resp.json()["result"]["items"]
    print(f"  {len(items)}件取得")
    return items

# ==============================
# ランダムで3件選出
# ==============================
def select_random_items(items, count=PROCESS_COUNT):
    selected = random.sample(items, min(count, len(items)))
    print(f"\nランダム選出（{len(selected)}件）:")
    for i, item in enumerate(selected):
        print(f"  [{i+1}] {item.get('title','')[:50]}...")
    return selected

# ==============================
# Playwrightでmp4 URL取得
# ==============================
def get_mp4_url(cid):
    iframe_url = f"https://www.dmm.co.jp/litevideo/-/part/=/cid={cid}/size=1280_720/"
    mp4_url = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        captured = []
        page.on("request", lambda r: captured.append(r.url) if ".mp4" in r.url else None)
        try:
            page.goto(iframe_url, timeout=20000, wait_until="networkidle")
            time.sleep(5)
            if captured:
                mp4_url = captured[0]
            else:
                html = page.content()
                found = re.findall(r'["\']([^"\']*cc3001[^"\']*\.mp4[^"\']*)["\']', html)
                if found:
                    mp4_url = "https:" + found[0] if found[0].startswith("//") else found[0]
        except Exception as e:
            print(f"  エラー: {e}")
        finally:
            browser.close()
    return mp4_url

# ==============================
# 動画ダウンロード
# ==============================
def download_video(mp4_url):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer":    "https://www.dmm.co.jp/",
    }
    resp = requests.get(mp4_url, headers=headers, stream=True, timeout=120)
    resp.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    for chunk in resp.iter_content(chunk_size=1024 * 1024):
        tmp.write(chunk)
    tmp.close()
    return tmp.name

# ==============================
# 後ろから45秒切り出し
# ==============================
def trim_last_45sec(input_path, output_path):
    no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)],
        capture_output=True, text=True,
        creationflags=no_window
    )
    duration = float(probe.stdout.strip())
    start = max(0, duration - 45)
    subprocess.run(
        [FFMPEG, "-y", "-ss", str(start), "-i", str(input_path),
         "-t", "45", "-c:v", "libx264", "-c:a", "aac",
         "-movflags", "+faststart", str(output_path)],
        capture_output=True, check=True,
        creationflags=no_window
    )
    print(f"  切り出し完了: {os.path.getsize(output_path)/1024/1024:.1f}MB")

# ==============================
# サムネイル生成
# ==============================
def generate_thumbnail(video_path, thumb_path):
    no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.run(
        [FFMPEG, "-y", "-ss", "0", "-i", str(video_path),
         "-vframes", "1", "-q:v", "2", str(thumb_path)],
        capture_output=True, check=True,
        creationflags=no_window
    )
    print(f"  サムネイル生成完了")

# ==============================
# ポップアップを閉じる
# ==============================
def close_popup(page):
    """表示されているポップアップやダイアログを閉じる"""
    try:
        # 「後で」「閉じる」「スキップ」系のボタンを探して閉じる
        for selector in [
            '[data-testid="confirmationSheetConfirm"]',
            '[data-testid="app-bar-close"]',
            'div[role="button"]:has-text("後で")',
            'div[role="button"]:has-text("閉じる")',
            'div[role="button"]:has-text("スキップ")',
            'div[role="button"]:has-text("今はしない")',
        ]:
            btn = page.locator(selector)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                time.sleep(1)
                print("  ポップアップを閉じました")
                return True
    except Exception:
        pass
    return False

# ==============================
# スレッド投稿（動画 + アフィリエイト返信）
# ==============================
def post_thread_via_chrome(d, page):
    video_path = os.path.abspath(os.path.join(VIDEO_DIR, d["video_file"]))

    try:
        # ─── 1ツイート目：コメント + 動画 ───
        print("  📝 1ツイート目を投稿中...")
        page.goto("https://x.com/home", timeout=30000)
        time.sleep(3)

        # ポップアップが出ていたら閉じる
        close_popup(page)

        # 投稿ボックスをクリック
        page.locator('[data-testid="tweetTextarea_0"]').wait_for(timeout=15000)
        tweet_box = page.locator('[data-testid="tweetTextarea_0"]').first
        tweet_box.click()
        time.sleep(1)

        # コメントのみ（タイトルなし）
        main_text = d['ai_comment']
        tweet_box.fill(main_text)
        time.sleep(1)

        # ─── 動画アップロード ───
        print("  🎬 動画をアップロード中...")

        # 投稿ボックスがアクティブな状態でメディアボタンをクリック
        # まずメディアボタンを探してクリックしてからファイルをセット
        try:
            # 方法1: data-testid="attachments" ボタンをクリック後にファイルセット
            media_btn = page.locator('[data-testid="attachments"]').first
            media_btn.wait_for(timeout=5000)
            # ファイル選択ダイアログが開く前にセット
            page.locator('input[accept*="video"]').first.set_input_files(video_path)
            print("  ✅ 動画セット完了（video input）")
        except Exception:
            try:
                # 方法2: accept属性なしのfile inputに直接セット
                inputs = page.locator('input[type="file"]').all()
                for inp in inputs:
                    try:
                        inp.set_input_files(video_path)
                        print("  ✅ 動画セット完了（file input）")
                        break
                    except Exception:
                        continue
            except Exception as e2:
                print(f"  ⚠️ ファイルセットエラー: {e2}")

        # 動画処理完了を待つ（最大5分）
        # アップロード中のインジケーターが消えるまで待機してから投稿
        print("  ⏳ 動画の処理中（最大5分）...")
        time.sleep(5)  # 最初に少し待つ

        for i in range(300):
            if _stop_event.is_set():
                return False
            try:
                # アップロード中のプログレスバーが消えているか確認
                uploading = page.locator('[data-testid="progressBar"]').count()
                processing = page.locator('div:has-text("処理中")').count()

                btn = page.locator('[data-testid="tweetButtonInline"]').first
                is_enabled = btn.is_enabled()

                if i % 10 == 0:
                    print(f"    待機中... {i}秒 (投稿ボタン有効:{is_enabled})")

                if is_enabled and uploading == 0:
                    print(f"  ✅ 動画処理完了（{i}秒）")
                    break
            except Exception:
                pass
            time.sleep(1)

        # 念のため3秒追加待機
        time.sleep(3)

        # 投稿ボタンをクリック（リトライあり）
        for attempt in range(3):
            try:
                btn = page.locator('[data-testid="tweetButtonInline"]').first
                if btn.is_enabled():
                    btn.click()
                    print(f"  ✅ 投稿ボタンをクリックしました（試行{attempt+1}）")
                    break
                else:
                    print(f"  ⚠️ 投稿ボタンがまだ無効です（試行{attempt+1}）、5秒待機...")
                    time.sleep(5)
            except Exception as e:
                print(f"  ⚠️ ボタンクリックエラー: {e}")
                time.sleep(3)
        time.sleep(8)  # 投稿完了まで余裕を持って待つ
        print("  ✅ 1ツイート目投稿完了")

        # ポップアップが出たら閉じる
        close_popup(page)
        time.sleep(2)

        # ─── 自分のプロフィールから最新ツイートURLを取得 ───
        if X_USERNAME:
            page.goto(f"https://x.com/{X_USERNAME}", timeout=30000)
        else:
            page.goto("https://x.com/home", timeout=30000)
        time.sleep(3)

        # ポップアップが出たら閉じる
        close_popup(page)

        # 最新ツイートのステータスURLを取得
        tweet_link = page.locator('[data-testid="tweet"] a[href*="/status/"]').first
        tweet_href = tweet_link.get_attribute("href")
        tweet_url  = f"https://x.com{tweet_href}" if tweet_href.startswith("/") else tweet_href
        print(f"  🔗 投稿URL: {tweet_url}")

        # ─── 返信：アフィリエイトリンク ───
        print("  💬 返信（アフィリエイトリンク）を投稿中...")
        page.goto(tweet_url, timeout=30000)
        time.sleep(3)

        # ポップアップが出たら閉じる
        close_popup(page)

        # 返信ボタンをクリック
        reply_btn = page.locator('[data-testid="reply"]').first
        reply_btn.wait_for(timeout=10000)
        reply_btn.click()
        time.sleep(4)  # ポップアップ（返信ダイアログ）が開くまで待つ

        # 返信テキストを準備
        reply_template = random.choice(AFFILIATE_REPLY_TEMPLATES)
        reply_text = reply_template.format(url=d["affiliate_url"])

        # ポップアップ内の返信ボックスを探す
        # ダイアログ内に表示されるtextareaに入力する
        reply_box = None
        for selector in [
            '[role="dialog"] [data-testid="tweetTextarea_0"]',
            '[data-testid="tweetTextarea_0"]',
        ]:
            try:
                loc = page.locator(selector).last
                loc.wait_for(timeout=5000)
                if loc.is_visible():
                    reply_box = loc
                    print(f"  返信ボックス発見: {selector}")
                    break
            except Exception:
                continue

        if reply_box is None:
            print("  ⚠️ 返信ボックスが見つかりません")
            return False

        # クリックしてフォーカスを当ててからテキスト入力
        reply_box.click()
        time.sleep(1)
        reply_box.fill(reply_text)
        time.sleep(2)
        print(f"  テキスト入力完了: {reply_text[:30]}...")

        # ポップアップ内の送信ボタンをクリック
        # ダイアログ内の送信ボタンを探す
        sent = False
        for selector in [
            '[role="dialog"] [data-testid="tweetButton"]',
            '[data-testid="tweetButton"]',
        ]:
            try:
                btns = page.locator(selector).all()
                for btn in reversed(btns):  # 最後のボタンから試す
                    if btn.is_visible() and btn.is_enabled():
                        btn.click()
                        sent = True
                        print("  ✅ 返信送信ボタンをクリック")
                        break
                if sent:
                    break
            except Exception:
                continue

        if not sent:
            # キーボードショートカットで送信を試みる
            print("  ボタンが見つからないためCtrl+Enterで送信を試みます")
            reply_box.press("Control+Enter")
            sent = True

        time.sleep(5)
        print("  ✅ 返信投稿完了（アフィリエイトリンク）")
        return True

    except Exception as e:
        print(f"  ❌ 投稿エラー: {e}")
        try:
            page.screenshot(path="x_error.png")
            print("  エラー画面を x_error.png に保存しました")
        except Exception:
            pass
        return False

# ==============================
# 返信テンプレート（x_reply.py と共通方式）
# ==============================
REPLY_PARTS_A = [
    "これ保存したやつ",
    "普通に3回見た",
    "こういうの一番危ない",
    "ちょっと好きすぎる",
    "これ見つけたの天才",
    "これ系ほんと刺さる",
    "なんか見てたら時間溶けた",
    "寝る前に見るやつじゃない",
    "ついつい何度も見てしまう",
    "こういうの求めてた",
    "タイプすぎて困る",
    "また見てしまった",
]
REPLY_PARTS_B = ["", "", "", "笑", "w", "…", "まじで", "やばい", "わかる"]

def generate_reply_text():
    return (random.choice(REPLY_PARTS_A) + random.choice(REPLY_PARTS_B)).strip()

def do_reply(page, tweet):
    """返信ボックスを開いてテキストを入力・送信する（x_reply.py方式）"""
    tweet.locator('[data-testid="reply"]').first.click()
    time.sleep(4)
    close_popup(page)

    reply_text = generate_reply_text()

    reply_box = None
    for selector in [
        '[role="dialog"] [data-testid="tweetTextarea_0"]',
        '[data-testid="tweetTextarea_0"]',
        'div[contenteditable="true"]',
    ]:
        try:
            loc = page.locator(selector).last
            loc.wait_for(timeout=6000)
            if loc.is_visible():
                reply_box = loc
                break
        except Exception:
            continue

    if reply_box is None:
        page.keyboard.press("Escape")
        time.sleep(2)
        return False, ""

    reply_box.click()
    time.sleep(1)
    reply_box.fill("")
    time.sleep(0.5)
    page.keyboard.type(reply_text, delay=50)
    time.sleep(2)

    sent = False
    for selector in [
        '[role="dialog"] [data-testid="tweetButton"]',
        '[data-testid="tweetButton"]',
    ]:
        try:
            btns = page.locator(selector).all()
            for btn in reversed(btns):
                if btn.is_visible() and btn.is_enabled():
                    btn.click()
                    sent = True
                    break
            if sent:
                break
        except Exception:
            continue

    if not sent:
        reply_box.press("Control+Enter")

    time.sleep(4)
    close_popup(page)
    return True, reply_text

# ==============================
# 同ジャンルアカウントへの返信（3キーワード同時実行）
# ==============================
def reply_to_similar_accounts(page):
    # 検索キーワードから3つ選んでそれぞれ返信
    keywords = random.sample(REPLY_SEARCH_KEYWORDS, min(3, len(REPLY_SEARCH_KEYWORDS)))
    total_replied = 0

    for keyword in keywords:
        if _stop_event.is_set():
            break

        search_url = (
            f"https://x.com/search?q="
            f"{keyword.replace(' ', '%20')}%20"
            f"lang%3Aja"
            f"&f=live"
        )

        try:
            print(f"\n🔍 検索: 「{keyword}」")
            page.goto(search_url, timeout=30000)
            time.sleep(4)
            close_popup(page)

            # スクロールして読み込み
            for _ in range(2):
                page.evaluate("window.scrollBy(0, 800)")
                time.sleep(2)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)

            tweets = page.locator('[data-testid="tweet"]').all()
            print(f"  {len(tweets)}件取得")

            replied_count = 0
            for tweet in tweets[:10]:
                if _stop_event.is_set():
                    break
                if replied_count >= 2:  # キーワードごとに2件まで
                    break
                try:
                    author = tweet.locator('[data-testid="User-Name"]').first.inner_text()
                    if X_USERNAME.lower() in author.lower():
                        continue

                    ok, text = do_reply(page, tweet)
                    if ok:
                        print(f"  ✅ 返信: {text}")
                        replied_count += 1
                        total_replied += 1
                        wait = random.randint(15, 30)
                        print(f"  {wait}秒待機...")
                        _stop_event.wait(timeout=wait)
                    else:
                        print("  ⚠️ 返信ボックスが見つかりません")

                except Exception as e:
                    print(f"  ❌ エラー: {e}")
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass
                    time.sleep(3)

            print(f"  「{keyword}」返信完了: {replied_count}件")

        except Exception as e:
            print(f"  ❌ 検索エラー: {e}")

    print(f"\n  合計返信完了: {total_replied}件")

# ==============================
# 即時投稿（スレッド形式）
# ==============================
def post_all_immediately(items_data):
    print("\n--- X(Twitter) スレッド投稿開始（Chrome自動操作）---")
    print("構成: 1ツイート目（コメント+動画）→ 返信（アフィリエイトリンク）\n")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL)
            print("✅ Chromeに接続しました")
        except Exception as e:
            print(f"❌ Chrome接続エラー: {e}")
            print("chrome_start.bat が実行されているか確認してください")
            return None

        context = browser.contexts[0]
        page    = context.new_page()

        # 1件だけ投稿（タスクスケジューラーで3回実行する想定）
        d = items_data[0]
        print(f"\n📢 投稿開始...")
        post_thread_via_chrome(d, page)

        print("\n✅ 全件のスレッド投稿が完了しました")

        # 投稿完了後にChromeを終了
        print("\n🔒 Chrome を終了します...")
        page.close()
        browser.close()

        # Chromeプロセスも終了（Windowsの場合）
        # ポート9222を使っているプロセスを特定して終了
        if sys.platform == "win32":
            try:
                # netstatでポート9222のPIDを取得して終了
                result = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True, text=True
                )
                for line in result.stdout.splitlines():
                    if "9222" in line and "LISTENING" in line:
                        pid = line.strip().split()[-1]
                        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                        print(f"✅ Chrome終了完了 (PID: {pid})")
                        break
            except Exception as e:
                print(f"⚠️ Chrome終了エラー: {e}")

        return True

# ==============================
# HTML生成
# ==============================
def generate_html(items_data):
    cards_html = ""
    for i, d in enumerate(items_data):
        ai_comment = d.get("ai_comment", "")
        rank_class = "top3" if i < 3 else ""
        cards_html += f"""
        <div class="card" onclick="openModal('{d['video_file']}', '{d['affiliate_url']}')">
          <div class="video-wrapper">
            <img class="thumb" src="videos/{d['thumb_file']}" alt="{d['title']}" loading="lazy">
            <div class="play-overlay">
              <div class="play-circle">
                <svg viewBox="0 0 24 24"><polygon points="6,4 20,12 6,20" fill="#e85d5d"/></svg>
              </div>
            </div>
            <div class="rank {rank_class}">{i + 1}</div>
          </div>
          <div class="card-info">
            <div class="card-title">{d['title']}</div>
            {'<div class="card-comment">' + ai_comment + '</div>' if ai_comment else ''}
            <div class="card-meta">
              {'<span class="card-actress">👤 ' + d['actresses'] + '</span>' if d['actresses'] else ''}
              {'<span class="card-review">★ ' + str(d['review_avg']) + '（' + str(d['review_cnt']) + '件）</span>' if d['review_avg'] else ''}
              {'<span class="card-price">' + d['price'] + '円〜</span>' if d['price'] else ''}
            </div>
          </div>
        </div>"""

    generated_at = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>毎日エロ動画ランキング</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&display=swap');
  :root {{
    --bg:#fafaf8; --surface:#fff; --border:#ebebeb;
    --accent:#e85d5d; --accent2:#f0a060; --text:#1a1a1a; --muted:#999;
    --comment-bg:#fff8f0; --comment-border:#ffe0b0;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Noto Sans JP',sans-serif; }}
  header {{ padding:16px 24px; background:#fff; border-bottom:1px solid var(--border); display:flex; align-items:center; gap:12px; position:sticky; top:0; z-index:10; box-shadow:0 1px 8px rgba(0,0,0,0.04); }}
  header .logo {{ font-size:15px; font-weight:700; letter-spacing:1px; }}
  header .badge {{ font-size:10px; font-weight:700; color:var(--accent); border:1px solid var(--accent); padding:2px 7px; border-radius:2px; }}
  header .sub {{ font-size:11px; color:var(--muted); margin-left:auto; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; padding:24px; max-width:1400px; margin:0 auto; }}
  .card {{ background:#fff; border-radius:10px; overflow:hidden; border:1px solid var(--border); box-shadow:0 2px 12px rgba(0,0,0,0.04); cursor:pointer; transition:box-shadow .2s,transform .2s; }}
  .card:hover {{ box-shadow:0 6px 24px rgba(0,0,0,0.1); transform:translateY(-2px); }}
  .video-wrapper {{ position:relative; padding-top:56.25%; background:#111; overflow:hidden; border-radius:10px 10px 0 0; }}
  .thumb {{ position:absolute; top:0; left:0; width:100%; height:100%; object-fit:cover; }}
  .play-overlay {{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; z-index:2; background:rgba(0,0,0,0.15); transition:background .2s; }}
  .card:hover .play-overlay {{ background:rgba(0,0,0,0.25); }}
  .play-circle {{ width:52px; height:52px; background:rgba(255,255,255,0.93); border-radius:50%; display:flex; align-items:center; justify-content:center; box-shadow:0 4px 16px rgba(0,0,0,0.25); transition:transform .15s; }}
  .card:hover .play-circle {{ transform:scale(1.1); }}
  .play-circle svg {{ width:22px; height:22px; margin-left:3px; }}
  .rank {{ position:absolute; top:10px; left:10px; background:rgba(255,255,255,0.92); color:var(--text); font-size:11px; font-weight:700; width:28px; height:28px; display:flex; align-items:center; justify-content:center; border-radius:50%; z-index:3; box-shadow:0 1px 4px rgba(0,0,0,0.15); }}
  .rank.top3 {{ background:linear-gradient(135deg,#ffd700,#ffaa00); color:#fff; }}
  .card-info {{ padding:12px 14px 14px; }}
  .card-title {{ font-size:12px; font-weight:500; line-height:1.6; margin-bottom:6px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .card-comment {{ font-size:11px; color:#c07020; line-height:1.5; margin-bottom:8px; background:var(--comment-bg); border-left:3px solid var(--comment-border); padding:5px 8px; border-radius:0 4px 4px 0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .card-meta {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .card-actress {{ font-size:11px; color:var(--muted); }}
  .card-review {{ font-size:11px; color:var(--accent2); font-weight:700; }}
  .card-price {{ font-size:11px; color:var(--accent); font-weight:700; margin-left:auto; }}
  .modal-bg {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:1000; align-items:center; justify-content:center; }}
  .modal-bg.active {{ display:flex; }}
  .modal {{ background:#000; border-radius:12px; overflow:hidden; width:90vw; max-width:900px; position:relative; box-shadow:0 20px 60px rgba(0,0,0,0.6); }}
  .modal video {{ width:100%; display:block; max-height:80vh; object-fit:contain; background:#000; }}
  .modal .close-btn {{ position:absolute; top:12px; right:12px; background:rgba(255,255,255,0.15); border:none; color:#fff; width:36px; height:36px; border-radius:50%; cursor:pointer; font-size:18px; display:flex; align-items:center; justify-content:center; backdrop-filter:blur(4px); transition:background .2s; z-index:10; }}
  .modal .close-btn:hover {{ background:rgba(255,255,255,0.3); }}
  .modal .progress-bar {{ position:absolute; bottom:0; left:0; height:3px; width:0%; background:linear-gradient(90deg,var(--accent),var(--accent2)); z-index:10; }}
  footer {{ padding:24px; text-align:center; color:var(--muted); font-size:11px; border-top:1px solid var(--border); margin-top:8px; }}
</style>
</head>
<body>
<header>
  <span class="logo">毎日エロ動画ランキング</span>
  <span class="badge">18+</span>
  <span class="sub">AI厳選・{generated_at}更新</span>
</header>
<div class="grid">{cards_html}</div>
<div class="modal-bg" id="modalBg" onclick="closeModalOnBg(event)">
  <div class="modal" id="modal">
    <button class="close-btn" onclick="closeModal()">✕</button>
    <video id="modalVideo" controls autoplay playsinline></video>
    <div class="progress-bar" id="modalProgress"></div>
  </div>
</div>
<footer>※18歳未満の方はご利用いただけません。成人向けコンテンツを含みます。</footer>
<script>
let currentTimer=null;
const WATCH_SECONDS=45;
function openModal(videoFile,affiliateUrl){{
  const modalBg=document.getElementById("modalBg"),video=document.getElementById("modalVideo"),progress=document.getElementById("modalProgress");
  if(currentTimer)clearTimeout(currentTimer);
  video.src="videos/"+videoFile; video.load(); video.play();
  progress.style.transition="none"; progress.style.width="0%";
  requestAnimationFrame(()=>{{requestAnimationFrame(()=>{{progress.style.transition="width "+WATCH_SECONDS+"s linear";progress.style.width="100%";}});}});
  modalBg.classList.add("active");
  currentTimer=setTimeout(()=>{{window.location.href=affiliateUrl;}},WATCH_SECONDS*1000);
}}
function closeModal(){{
  const video=document.getElementById("modalVideo"),progress=document.getElementById("modalProgress");
  video.pause(); video.src=""; document.getElementById("modalBg").classList.remove("active");
  progress.style.transition="none"; progress.style.width="0%";
  if(currentTimer){{clearTimeout(currentTimer);currentTimer=null;}}
}}
function closeModalOnBg(e){{if(e.target===document.getElementById("modalBg"))closeModal();}}
document.addEventListener("keydown",e=>{{if(e.key==="Escape")closeModal();}});
</script>
</body>
</html>"""

# ==============================
# メイン
# ==============================
def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    os.makedirs(VIDEO_DIR, exist_ok=True)

    all_items      = fetch_ranking()
    selected_items = select_random_items(all_items, count=PROCESS_COUNT)
    items_data     = []

    for i, item in enumerate(selected_items):
        cid           = item["content_id"]
        title         = item.get("title", "")
        actresses     = "・".join([a["name"] for a in item.get("iteminfo", {}).get("actress", [])[:2]])
        price         = item.get("prices", {}).get("price", "")
        review        = item.get("review", {})
        review_avg    = review.get("average", "")
        review_cnt    = review.get("count", "")
        affiliate_url = fix_affiliate_url(item.get("affiliateURL", ""))
        ai_comment    = build_comment(item)

        print(f"\n[{i+1}/{PROCESS_COUNT}] {title[:50]}...")
        print(f"  💬 {ai_comment}")

        video_file = f"{cid}.mp4"
        thumb_file = f"{cid}.jpg"
        video_path = os.path.join(VIDEO_DIR, video_file)
        thumb_path = os.path.join(VIDEO_DIR, thumb_file)

        if os.path.exists(video_path) and os.path.exists(thumb_path):
            print("  スキップ（既に処理済み）")
        else:
            print("  動画URL取得中...")
            mp4_url = get_mp4_url(cid)
            if not mp4_url:
                print("  動画URLが見つかりませんでした。スキップ")
                continue
            print("  ダウンロード中...")
            tmp_path = download_video(mp4_url)
            try:
                trim_last_45sec(tmp_path, video_path)
                generate_thumbnail(video_path, thumb_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        items_data.append({
            "cid":           cid,
            "title":         title,
            "actresses":     actresses,
            "price":         price,
            "review_avg":    review_avg,
            "review_cnt":    review_cnt,
            "affiliate_url": affiliate_url,
            "video_file":    video_file,
            "thumb_file":    thumb_file,
            "ai_comment":    ai_comment,
        })

    if not items_data:
        print("\n❌ 処理できた動画がありませんでした")
        return

    print("\nHTML生成中...")
    html = generate_html(items_data)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ 完了！ {len(items_data)}件の動画でサイトを生成しました")
    print(f"  サイトフォルダ: {OUTPUT_DIR}")

    result = post_all_immediately(items_data)
    if result:
        print("\n✅ 全処理完了")
    else:
        print("\n❌ 投稿に失敗しました")

if __name__ == "__main__":
    main()