"""
FANZA ランキングサイト生成スクリプト
- ランキング上位10件の動画を後ろから45秒切り出し
- 各動画の最初のフレームをサムネイルとして生成
- HTMLサイトを生成（videos/フォルダに動画・サムネイルを配置）

【使い方】
python3 fanza_site_gen.py

生成物:
  site/index.html   ← これをサーバーにアップロード
  site/videos/      ← 動画・サムネイルファイル
"""

import requests
import json
import os
import sys
import re
import time
import tempfile
import subprocess
import shutil

from playwright.sync_api import sync_playwright

# ==============================
# 設定
# ==============================
API_ID = "3Hg6dFtBHZEpRg5nqbss"
API_AFFILIATE_ID = "amam2442-990"
REAL_AFFILIATE_ID = "amam2442-004"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "")
VIDEO_DIR = os.path.join(OUTPUT_DIR, "videos")

API_URL = "https://api.dmm.com/affiliate/v3/ItemList"
PARAMS = {
    "api_id": API_ID,
    "affiliate_id": API_AFFILIATE_ID,
    "site": "FANZA",
    "service": "digital",
    "floor": "videoa",
    "hits": 10,
    "offset": 1,
    "sort": "rank",
    "output": "json",
}

def fix_affiliate_url(url):
    return url.replace(API_AFFILIATE_ID, REAL_AFFILIATE_ID)

# ==============================
# FANZA APIからランキング取得
# ==============================
def fetch_ranking():
    print("ランキング取得中...")
    resp = requests.get(API_URL, params=PARAMS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    items = data["result"]["items"]
    print(f"  {len(items)}件取得")
    return items

# ==============================
# Playwrightでmp4 URL取得
# ==============================
def get_mp4_url(cid):
    iframe_url = f"https://www.dmm.co.jp/litevideo/-/part/=/cid={cid}/size=1280_720/"
    mp4_url = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
        "Referer": "https://www.dmm.co.jp/",
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
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_path],
        capture_output=True, text=True
    )
    duration = float(probe.stdout.strip())
    start = max(0, duration - 45)
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-i", input_path,
         "-t", "45", "-c:v", "libx264", "-c:a", "aac",
         "-movflags", "+faststart", output_path],
        capture_output=True, check=True
    )
    print(f"  切り出し完了: {os.path.getsize(output_path)/1024/1024:.1f}MB")

# ==============================
# サムネイル生成（最初のフレーム）
# ==============================
def generate_thumbnail(video_path, thumb_path):
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "0", "-i", video_path,
         "-vframes", "1", "-q:v", "2", thumb_path],
        capture_output=True, check=True
    )
    print(f"  サムネイル生成完了")

# ==============================
# HTML生成
# ==============================
def generate_html(items_data):
    cards_html = ""
    for i, d in enumerate(items_data):
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
            <div class="card-meta">
              {'<span class="card-actress">👤 ' + d['actresses'] + '</span>' if d['actresses'] else ''}
              {'<span class="card-review">★ ' + str(d['review_avg']) + '（' + str(d['review_cnt']) + '件）</span>' if d['review_avg'] else ''}
              {'<span class="card-price">' + d['price'] + '円〜</span>' if d['price'] else ''}
            </div>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>毎日エロ動画ランキング</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&display=swap');
  :root {{
    --bg: #fafaf8;
    --surface: #ffffff;
    --border: #ebebeb;
    --accent: #e85d5d;
    --accent2: #f0a060;
    --text: #1a1a1a;
    --muted: #999;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Noto Sans JP',sans-serif; }}

  header {{
    padding:16px 24px;
    background:#fff;
    border-bottom:1px solid var(--border);
    display:flex;
    align-items:center;
    gap:12px;
    position:sticky;
    top:0;
    z-index:10;
    box-shadow:0 1px 8px rgba(0,0,0,0.04);
  }}
  header .logo {{ font-size:15px; font-weight:700; letter-spacing:1px; }}
  header .badge {{ font-size:10px; font-weight:700; color:var(--accent); border:1px solid var(--accent); padding:2px 7px; border-radius:2px; }}
  header .sub {{ font-size:11px; color:var(--muted); margin-left:auto; }}

  .grid {{
    display:grid;
    grid-template-columns:repeat(auto-fill, minmax(280px,1fr));
    gap:16px;
    padding:24px;
    max-width:1400px;
    margin:0 auto;
  }}

  .card {{
    background:#fff;
    border-radius:10px;
    overflow:hidden;
    border:1px solid var(--border);
    box-shadow:0 2px 12px rgba(0,0,0,0.04);
    cursor:pointer;
    transition:box-shadow 0.2s, transform 0.2s;
  }}
  .card:hover {{ box-shadow:0 6px 24px rgba(0,0,0,0.1); transform:translateY(-2px); }}

  .video-wrapper {{ position:relative; padding-top:56.25%; background:#111; overflow:hidden; border-radius:10px 10px 0 0; }}
  .thumb {{ position:absolute; top:0; left:0; width:100%; height:100%; object-fit:cover; }}

  .play-overlay {{
    position:absolute; inset:0; display:flex; align-items:center; justify-content:center; z-index:2;
    background:rgba(0,0,0,0.15);
    transition:background 0.2s;
  }}
  .card:hover .play-overlay {{ background:rgba(0,0,0,0.25); }}
  .play-circle {{
    width:52px; height:52px; background:rgba(255,255,255,0.93); border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    box-shadow:0 4px 16px rgba(0,0,0,0.25);
    transition:transform 0.15s;
  }}
  .card:hover .play-circle {{ transform:scale(1.1); }}
  .play-circle svg {{ width:22px; height:22px; margin-left:3px; }}

  .rank {{
    position:absolute; top:10px; left:10px;
    background:rgba(255,255,255,0.92); color:var(--text);
    font-size:11px; font-weight:700; width:28px; height:28px;
    display:flex; align-items:center; justify-content:center;
    border-radius:50%; z-index:3;
    box-shadow:0 1px 4px rgba(0,0,0,0.15);
  }}
  .rank.top3 {{ background:linear-gradient(135deg,#ffd700,#ffaa00); color:#fff; }}

  .card-info {{ padding:12px 14px 14px; }}
  .card-title {{
    font-size:12px; font-weight:500; line-height:1.6; margin-bottom:8px;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
  }}
  .card-meta {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .card-actress {{ font-size:11px; color:var(--muted); }}
  .card-review {{ font-size:11px; color:var(--accent2); font-weight:700; }}
  .card-price {{ font-size:11px; color:var(--accent); font-weight:700; margin-left:auto; }}

  /* モーダル */
  .modal-bg {{
    display:none;
    position:fixed; inset:0;
    background:rgba(0,0,0,0.85);
    z-index:1000;
    align-items:center;
    justify-content:center;
  }}
  .modal-bg.active {{ display:flex; }}

  .modal {{
    background:#000;
    border-radius:12px;
    overflow:hidden;
    width:90vw;
    max-width:900px;
    position:relative;
    box-shadow:0 20px 60px rgba(0,0,0,0.6);
  }}

  .modal video {{
    width:100%;
    display:block;
    max-height:80vh;
    object-fit:contain;
    background:#000;
  }}

  .modal .close-btn {{
    position:absolute; top:12px; right:12px;
    background:rgba(255,255,255,0.15); border:none; color:#fff;
    width:36px; height:36px; border-radius:50%; cursor:pointer;
    font-size:18px; display:flex; align-items:center; justify-content:center;
    backdrop-filter:blur(4px);
    transition:background 0.2s;
    z-index:10;
  }}
  .modal .close-btn:hover {{ background:rgba(255,255,255,0.3); }}

  /* プログレスバー */
  .modal .progress-bar {{
    position:absolute; bottom:0; left:0; height:3px; width:0%;
    background:linear-gradient(90deg, var(--accent), var(--accent2));
    z-index:10;
  }}

  footer {{
    padding:24px; text-align:center; color:var(--muted); font-size:11px;
    border-top:1px solid var(--border); margin-top:8px;
  }}
</style>
</head>
<body>

<header>
  <span class="logo">毎日エロ動画ランキング</span>
  <span class="badge">18+</span>
  <span class="sub">人気ランキング順</span>
</header>

<div class="grid">
{cards_html}
</div>

<!-- モーダル -->
<div class="modal-bg" id="modalBg" onclick="closeModalOnBg(event)">
  <div class="modal" id="modal">
    <button class="close-btn" onclick="closeModal()">✕</button>
    <video id="modalVideo" controls autoplay playsinline></video>
    <div class="progress-bar" id="modalProgress"></div>
  </div>
</div>

<footer>※18歳未満の方はご利用いただけません。成人向けコンテンツを含みます。</footer>

<script>
let currentTimer = null;
let currentAffiliate = null;
const WATCH_SECONDS = 45;

function openModal(videoFile, affiliateUrl) {{
  const modalBg = document.getElementById("modalBg");
  const video = document.getElementById("modalVideo");
  const progress = document.getElementById("modalProgress");

  // 前のタイマーをクリア
  if (currentTimer) clearTimeout(currentTimer);
  currentAffiliate = affiliateUrl;

  // 動画をセット
  video.src = "videos/" + videoFile;
  video.load();
  video.play();

  // プログレスバーリセット
  progress.style.transition = "none";
  progress.style.width = "0%";
  requestAnimationFrame(() => {{
    requestAnimationFrame(() => {{
      progress.style.transition = "width " + WATCH_SECONDS + "s linear";
      progress.style.width = "100%";
    }});
  }});

  // モーダルを開く
  modalBg.classList.add("active");

  // 45秒後にアフィリエイトリンクへ
  currentTimer = setTimeout(() => {{
    window.location.href = affiliateUrl;
  }}, WATCH_SECONDS * 1000);
}}

function closeModal() {{
  const modalBg = document.getElementById("modalBg");
  const video = document.getElementById("modalVideo");
  const progress = document.getElementById("modalProgress");

  video.pause();
  video.src = "";
  modalBg.classList.remove("active");
  progress.style.transition = "none";
  progress.style.width = "0%";

  if (currentTimer) {{
    clearTimeout(currentTimer);
    currentTimer = null;
  }}
}}

function closeModalOnBg(e) {{
  if (e.target === document.getElementById("modalBg")) {{
    closeModal();
  }}
}}

// Escキーで閉じる
document.addEventListener("keydown", e => {{
  if (e.key === "Escape") closeModal();
}});
</script>
</body>
</html>"""

# ==============================
# メイン
# ==============================
def main():
    os.makedirs(VIDEO_DIR, exist_ok=True)

    items = fetch_ranking()
    items_data = []

    for i, item in enumerate(items):
        cid = item["content_id"]
        title = item.get("title", "")
        actresses = "・".join([a["name"] for a in item.get("iteminfo", {}).get("actress", [])[:2]])
        price = item.get("prices", {}).get("price", "")
        review = item.get("review", {})
        review_avg = review.get("average", "")
        review_cnt = review.get("count", "")
        affiliate_url = fix_affiliate_url(item.get("affiliateURL", ""))

        video_file = f"{cid}.mp4"
        thumb_file = f"{cid}.jpg"
        video_path = os.path.join(VIDEO_DIR, video_file)
        thumb_path = os.path.join(VIDEO_DIR, thumb_file)

        print(f"\n[{i+1}/10] {title[:40]}...")

        # 既に処理済みならスキップ
        if os.path.exists(video_path) and os.path.exists(thumb_path):
            print("  スキップ（既に処理済み）")
        else:
            # mp4 URL取得
            print("  動画URL取得中...")
            mp4_url = get_mp4_url(cid)
            if not mp4_url:
                print("  動画URLが見つかりませんでした。スキップ")
                continue

            # ダウンロード
            print("  ダウンロード中...")
            tmp_path = download_video(mp4_url)

            try:
                # 後ろ45秒切り出し
                trim_last_45sec(tmp_path, video_path)

                # サムネイル生成（切り出し後の最初のフレーム）
                generate_thumbnail(video_path, thumb_path)
            finally:
                os.unlink(tmp_path)

        items_data.append({
            "cid": cid,
            "title": title,
            "actresses": actresses,
            "price": price,
            "review_avg": review_avg,
            "review_cnt": review_cnt,
            "affiliate_url": affiliate_url,
            "video_file": video_file,
            "thumb_file": thumb_file,
        })

    # HTML生成
    print("\nHTML生成中...")
    html = generate_html(items_data)
    html_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ 完了！")
    print(f"  サイトフォルダ: {OUTPUT_DIR}")
    print(f"  確認コマンド: cd {OUTPUT_DIR} && python3 -m http.server 8000")
    print(f"  ブラウザで: http://localhost:8000")

if __name__ == "__main__":
    main()