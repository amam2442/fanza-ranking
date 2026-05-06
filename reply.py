"""
X リプライスクリプト（シンプル版）
- キーワード検索した投稿に返信
- 特定ユーザーの投稿に返信

【使い方】
python x_reply.py

【タスクスケジューラー設定例】
  12:00 → python x_reply.py
  19:00 → python x_reply.py
  23:00 → python x_reply.py
"""

import os
import sys
import time
import random
import subprocess
from datetime import datetime

from playwright.sync_api import sync_playwright

# ==============================
# 設定
# ==============================
CHROME_DEBUG_URL = "http://localhost:9222"
X_USERNAME       = "zizi3141"
X_PROFILE_URL    = f"https://x.com/{X_USERNAME}"  # 自分のプロフィールURL

# アフィリエイトリンク（返信に添付するURL）
AFFILIATE_URL = "https://al.dmm.co.jp/?lurl=https%3A%2F%2Fwww.dmm.co.jp%2F&af_id=amam2442-004"

# アダルト系キーワード（おすすめTLのツイートをフィルタリング）
ADULT_KEYWORDS = [
    "AV", "FANZA", "アダルト", "エロ", "女優", "グラビア",
    "下着", "水着", "セクシー", "ランジェリー", "デカい",
    "美女", "かわいい子", "スタイル", "おすすめ動画",
]

# 検索キーワード（毎回ランダムで3つ選んで返信）
SEARCH_KEYWORDS = [
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

# 特定ユーザーへの返信（@なしで追加）
TARGET_USERS = [
    # "username1",
    # "username2",
]

# キーワードごとの返信件数
REPLIES_PER_KEYWORD = 2

# 特定ユーザーごとの返信件数
REPLIES_PER_USER = 2

# ==============================
# 返信テンプレート（ポジティブ＋プロフィール誘導）
# ==============================
REPLY_PARTS_A = [
    "最高すぎる",
    "これほんとに好き",
    "センスが好きすぎる",
    "見つけられてよかった",
    "こういうの大事にしたい",
    "元気もらえた",
    "好きな人いて嬉しい",
    "趣味合う人見つけた",
    "投稿してくれてありがとう",
    "これは保存案件",
    "見てよかった",
    "幸せな気持ちになった",
    "また見に来ます",
    "自分もこういうの好きで",
    "同じ趣味の人いた",
]
REPLY_PARTS_B = ["", "", "", "笑", "ほんとに", "まじで", "です"]

# プロフィール誘導文（自然な流れで誘導）
PROFILE_LEAD = [
    "自分のページにも似たようなの載せてるんで良かったら",
    "同じ系統好きな人は自分のとこも覗いてみてください",
    "自分もまとめてるんで気が向いたら見てみてください",
    "似たの集めてるんでよかったら",
    "興味あれば自分のページも見てみてください",
]

def generate_reply():
    a = random.choice(REPLY_PARTS_A)
    b = random.choice(REPLY_PARTS_B)
    base = (a + b).strip()

    # 約50%の確率でプロフィール誘導を追加（毎回だとスパムっぽい）
    if random.random() < 0.5:
        lead = random.choice(PROFILE_LEAD)
        return f"{base}\n{lead}→ @{X_USERNAME}"
    return base

# ==============================
# ポップアップを閉じる
# ==============================
def close_popup(page):
    try:
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
                return True
    except Exception:
        pass
    return False

# ==============================
# 返信実行（1ツイートに対して）
# ==============================
def do_reply(page, tweet):
    # 返信ボタンクリック（close_popupは呼ばない）
    tweet.locator('[data-testid="reply"]').first.click()
    time.sleep(5)  # ダイアログが開くまで十分待つ

    reply_text = generate_reply()

    # 返信ボックスを探す（ダイアログ内を優先）
    reply_box = None
    for selector in [
        '[role="dialog"] [data-testid="tweetTextarea_0"]',
        '[data-testid="tweetTextarea_0"]',
        '[role="dialog"] div[contenteditable="true"]',
        'div[contenteditable="true"]',
    ]:
        try:
            loc = page.locator(selector).last
            loc.wait_for(timeout=6000)
            if loc.is_visible():
                reply_box = loc
                print(f"  返信ボックス発見: {selector}")
                break
        except Exception:
            continue

    if reply_box is None:
        print("  ⚠️ 返信ボックスが見つかりません")
        page.keyboard.press("Escape")
        time.sleep(2)
        return False, ""

    # クリックしてフォーカスを当てる
    reply_box.click()
    time.sleep(1)

    # keyboard.typeで1文字ずつ入力（fill()はXで反映されないことがある）
    page.keyboard.type(reply_text, delay=80)
    time.sleep(2)
    print(f"  テキスト入力: {reply_text}")

    # 送信ボタンをクリック
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
                    print("  送信ボタンクリック")
                    break
            if sent:
                break
        except Exception:
            continue

    if not sent:
        print("  Ctrl+Enterで送信")
        reply_box.press("Control+Enter")

    time.sleep(5)
    return True, reply_text

# ==============================
# いいね数をパース
# ==============================
def parse_likes(tweet):
    try:
        text = tweet.locator('[data-testid="like"]').first.inner_text().strip()
        if not text:
            return 0
        if "K" in text:
            return int(float(text.replace("K", "")) * 1000)
        if "万" in text:
            return int(float(text.replace("万", "")) * 10000)
        if text.replace(",", "").isdigit():
            return int(text.replace(",", ""))
        return 0
    except Exception:
        return 0

# ==============================
# ツイートを収集してソートする共通関数
# ==============================
def collect_tweets_sorted(page, label):
    """現在のページからツイートを収集していいね数順に返す"""
    time.sleep(4)
    close_popup(page)

    # スクロールして読み込み
    for _ in range(8):
        page.evaluate("window.scrollBy(0, 1000)")
        time.sleep(2)
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(2)

    tweets = page.locator('[data-testid="tweet"]').all()
    print(f"  {label}: {len(tweets)}件取得")

    tweet_likes = []
    for tweet in tweets:
        try:
            author = tweet.locator('[data-testid="User-Name"]').first.inner_text()
            if X_USERNAME.lower() in author.lower():
                continue
            likes = parse_likes(tweet)
            tweet_likes.append((likes, tweet))
        except Exception:
            continue

    tweet_likes.sort(key=lambda x: x[0], reverse=True)
    return tweet_likes


def reply_to_sorted_tweets(page, tweet_likes, limit, label):
    """いいね数順のツイートリストに返信する"""
    total = 0
    for likes, tweet in tweet_likes:
        if total >= limit:
            break
        try:
            ok, text = do_reply(page, tweet)
            if ok:
                print(f"  ✅ [{label}] 返信（いいね{likes}件）: {text}")
                total += 1
                wait = random.randint(15, 30)
                print(f"  {wait}秒待機...")
                time.sleep(wait)
            else:
                print(f"  ⚠️ 返信ボックスが見つかりません（いいね{likes}件）")
        except Exception as e:
            print(f"  ❌ エラー: {e}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            time.sleep(3)
    return total


# ==============================
# おすすめタイムラインから返信
# ==============================
def run_explore_replies(page):
    """
    おすすめ（For You）タイムラインから返信
    """
    print("\n📱 【おすすめ】タイムラインから取得中...")
    page.goto("https://x.com/home", timeout=30000)
    tweet_likes = collect_tweets_sorted(page, "おすすめ")
    print(f"  いいね数上位: {[l for l, _ in tweet_likes[:5]]}")
    total = reply_to_sorted_tweets(page, tweet_likes, REPLIES_PER_KEYWORD * 2, "おすすめ")
    print(f"  おすすめ返信完了: {total}件")
    return total


def run_following_replies(page):
    """
    フォロー中タイムラインから返信
    """
    print("\n👥 【フォロー中】タイムラインから取得中...")
    # フォロー中タブに切り替え
    page.goto("https://x.com/home", timeout=30000)
    time.sleep(3)
    close_popup(page)
    try:
        following_tab = page.locator('a[href="/home"][role="tab"]').last
        if following_tab.count() == 0:
            # タブのテキストで探す
            following_tab = page.get_by_role("tab", name="フォロー中")
            if following_tab.count() == 0:
                following_tab = page.get_by_role("tab", name="Following")
        following_tab.first.click()
        time.sleep(2)
    except Exception:
        # URLで直接アクセス
        page.goto("https://x.com/?timeline=following", timeout=30000)
        time.sleep(3)
    tweet_likes = collect_tweets_sorted(page, "フォロー中")
    print(f"  いいね数上位: {[l for l, _ in tweet_likes[:5]]}")
    total = reply_to_sorted_tweets(page, tweet_likes, REPLIES_PER_KEYWORD * 2, "フォロー中")
    print(f"  フォロー中返信完了: {total}件")
    return total


def run_search_replies(page):
    """
    キーワード検索から返信（ランダム3キーワード）
    """
    keywords = random.sample(SEARCH_KEYWORDS, min(3, len(SEARCH_KEYWORDS)))
    total = 0
    for keyword in keywords:
        search_url = (
            f"https://x.com/search?q="
            f"{keyword.replace(' ', '%20')}%20lang%3Aja"
            f"&f=live"
        )
        print(f"\n🔍 【検索】「{keyword}」から取得中...")
        page.goto(search_url, timeout=30000)
        tweet_likes = collect_tweets_sorted(page, keyword)
        print(f"  いいね数上位: {[l for l, _ in tweet_likes[:5]]}")
        replied = reply_to_sorted_tweets(page, tweet_likes, REPLIES_PER_KEYWORD, keyword)
        print(f"  「{keyword}」返信完了: {replied}件")
        total += replied
    return total



# ==============================
# 特定ユーザーへの返信
# ==============================
def run_user_replies(page):
    if not TARGET_USERS:
        return 0

    total = 0
    # ランダムで3人選ぶ
    selected_users = random.sample(TARGET_USERS, min(3, len(TARGET_USERS)))
    for username in selected_users:
        print(f"\n👤 @{username} の投稿に返信中...")
        page.goto(f"https://x.com/{username}", timeout=30000)
        time.sleep(4)
        close_popup(page)

        tweets = page.locator('[data-testid="tweet"]').all()
        print(f"  {len(tweets)}件取得")

        replied = 0
        for tweet in tweets[:10]:
            if replied >= REPLIES_PER_USER:
                break
            try:
                author = tweet.locator('[data-testid="User-Name"]').first.inner_text()
                if X_USERNAME.lower() in author.lower():
                    continue

                ok, text = do_reply(page, tweet)
                if ok:
                    print(f"  ✅ @{username} に返信: {text}")
                    replied += 1
                    total += 1
                    wait = random.randint(15, 30)
                    print(f"  {wait}秒待機...")
                    time.sleep(wait)
                else:
                    print("  ⚠️ 返信ボックスが見つかりません")

            except Exception as e:
                print(f"  ❌ エラー: {e}")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                time.sleep(3)

        print(f"  @{username} 完了: {replied}件")
        total += replied

    return total

# ==============================
# Chrome起動確認・起動
# ==============================
def ensure_chrome_running():
    import socket

    def is_running():
        try:
            s = socket.create_connection(("localhost", 9222), timeout=2)
            s.close()
            return True
        except Exception:
            return False

    if is_running():
        print("✅ Chromeはすでに起動中")
        return True

    print("🔄 Chromeを起動します...")

    # Chromeのパスを自動検索
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        rf"C:\Users\{os.environ.get('USERNAME', '')}\AppData\Local\Google\Chrome\Application\chrome.exe",
    ]
    chrome_exe = None
    for path in chrome_paths:
        if os.path.exists(path):
            chrome_exe = path
            break

    if chrome_exe is None:
        print("❌ Chromeが見つかりません")
        return False

    # Chromeをリモートデバッグモードで起動
    subprocess.Popen(
        [
            chrome_exe,
            "--remote-debugging-port=9222",
            "--user-data-dir=C:\\chrome_debug",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )

    # 起動完了まで最大15秒待機
    print("  起動中...")
    for i in range(15):
        time.sleep(1)
        if is_running():
            print(f"  ✅ Chrome起動完了（{i+1}秒）")
            return True

    print("❌ Chrome起動タイムアウト")
    return False

# ==============================
# メイン
# ==============================
def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"=== X リプライスクリプト ===")
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not ensure_chrome_running():
        return

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL)
            print("✅ Chromeに接続しました")
        except Exception as e:
            print(f"❌ Chrome接続エラー: {e}")
            return

        context = browser.contexts[0]
        page    = context.new_page()

        try:
            ex_replied      = run_explore_replies(page)
            follow_replied  = run_following_replies(page)
            search_replied  = run_search_replies(page)
            user_replied    = run_user_replies(page)
            total = ex_replied + follow_replied + search_replied + user_replied
            print(f"\n✅ 処理完了 | おすすめ:{ex_replied}件 / フォロー中:{follow_replied}件 / 検索:{search_replied}件 / ユーザー:{user_replied}件 / 合計:{total}件")
        except Exception as e:
            print(f"❌ エラー: {e}")
        finally:
            page.close()
            browser.close()

            # Chrome終了（ポート9222のプロセスを終了）
            if sys.platform == "win32":
                try:
                    result = subprocess.run(
                        ["netstat", "-ano"], capture_output=True, text=True
                    )
                    for line in result.stdout.splitlines():
                        if "9222" in line and "LISTENING" in line:
                            pid = line.strip().split()[-1]
                            subprocess.run(
                                ["taskkill", "/F", "/PID", pid],
                                capture_output=True
                            )
                            print(f"🔒 Chrome終了 (PID: {pid})")
                            break
                except Exception as e:
                    print(f"⚠️ Chrome終了エラー: {e}")

if __name__ == "__main__":
    main()