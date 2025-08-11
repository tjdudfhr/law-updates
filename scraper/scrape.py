import json, re, time, hashlib, sys, pathlib
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TARGET_URLS = [
   # 행정규칙 목록 (서버 렌더링, 데이터 확실)
    "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=",
    # 자치법규 목록
    "https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq="
]

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"}

def norm_date(s: str | None):
    if not s: return None
    s = s.replace("/", ".").replace("-", ".")
    m = re.search(r"(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})", s)
    if not m: return None
    y, mm, d = map(int, m.groups())
    return f"{y:04d}-{mm:02d}-{d:02d}"

def make_id(title, url, date):
    return hashlib.md5((title + (date or '') + url).encode('utf-8')).hexdigest()

def get_html(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    if not r.encoding or r.encoding.lower() == 'iso-8859-1':
        r.encoding = r.apparent_encoding
    r.raise_for_status()
    return r.text

def first_text(soup, selectors):
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(" ", strip=True)
            if t: return t
    return ""

def parse_detail(url):
    try:
        html = get_html(url)
        s = BeautifulSoup(html, "html.parser")

        label_map = {}
        for row in s.select("table tr"):
            th = row.find("th"); td = row.find("td")
            if th and td:
                key = th.get_text(" ", strip=True)
                val = td.get_text(" ", strip=True)
                if key and val: label_map[key] = val

        def find_in_labels(*keys):
            for k in keys:
                for label, val in label_map.items():
                    if k in label and val:
                        return val
            return ""

        summary = first_text(s, [".summary", "#summary"]) or find_in_labels("주요", "골자")
        reason  = first_text(s, [".reason", "#reason"])  or find_in_labels("사유", "필요성")
        eff     = first_text(s, [".effective-date", "#effectiveDate"]) or find_in_labels("시행", "발효")
        lawtype = first_text(s, [".law-type", ".category"]) or find_in_labels("유형", "구분")
        articles = [li.get_text(" ", strip=True) for li in s.select(".articles li, .amend-articles li, .article-list li")]

        return {
            "summary": summary,
            "reason": reason,
            "effectiveDate": norm_date(eff),
            "lawType": lawtype if lawtype else None,
            "articles": articles
        }
    except Exception:
        return {}

def write_debug(name: str, content: str | bytes):
    p = pathlib.Path("docs/_debug")
    p.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        (p / name).write_bytes(content)
    else:
        (p / name).write_text(content, encoding="utf-8")

def extract_items_from_frame(frame, base_url, tag="main"):
    items = []
    selectors = [
        "table tbody tr a[href]", "table tr a[href]",
        ".tbl_list a[href]", ".result_list a[href]",
        "ul li a[href]"
    ]
    anchors = []
    for sel in selectors:
        try:
            anchors += frame.query_selector_all(sel)
        except Exception:
            pass
    print(f"[INFO] {tag}: anchors found = {len(anchors)}", file=sys.stderr)

    seen = set()
    for a in anchors:
        try:
            title = (a.inner_text() or "").strip()
            if not title: continue
            href = a.get_attribute("href") or ""
            onclick = a.get_attribute("onclick") or ""
            url = None
            if href and href.lower().startswith("http"):
                url = href
            elif href and not href.lower().startswith("javascript") and href != "#":
                url = urljoin(base_url, href)
            else:
                m = re.search(r"https?://[^'\"()]+", onclick or "")
                if m: url = m.group(0)
            if not url: continue

            # 너무 잡스럽게 안 모으도록 최소 필터(법령 상세로 보이는 링크 우선)
            if "law.go.kr" not in url and "ls" not in url.lower():
                continue

            key = (title, url)
            if key in seen: continue
            seen.add(key)

            # 같은 행의 텍스트에서 날짜 힌트
            row_text = ""
            try:
                row_text = a.evaluate("(el)=> (el.closest('tr') && el.closest('tr').innerText) || ''")
            except Exception:
                pass
            date = norm_date(row_text)
            items.append({"title": title, "url": url, "date": date})
        except Exception:
            continue
    return items

def parse_list_with_playwright(url):
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1360, "height": 900}
        )
        # 간단한 탐지 회피
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = context.new_page()
        page.set_extra_http_headers({"Accept-Language": "ko-KR,ko;q=0.9"})
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)  # 살짝 지연

        # 디버그 저장: HTML + 전체 스크린샷
        try:
            write_debug("main.html", page.content())
            write_debug("page.png", page.screenshot(full_page=True))
        except Exception:
            pass

        frames = page.frames
        for i, f in enumerate(frames[:5]):
            try:
                write_debug(f"frame{i}.html", f.content())
            except Exception:
                pass

        # 메인 프레임
        out += extract_items_from_frame(page.main_frame, url, tag="main")
        # 모든 하위 프레임
        for i, f in enumerate(frames):
            out += extract_items_from_frame(f, url, tag=f"frame{i}")

        # 중복 제거
        uniq, seen = [], set()
        for it in out:
            k = (it["title"], it["url"])
            if k in seen: continue
            seen.add(k); uniq.append(it)
        out = uniq

        print(f"[INFO] frames: {len(frames)}; total items: {len(out)}", file=sys.stderr)
        context.close(); browser.close()
    return out

def main():
    results = []
    seen = set()
    for u in TARGET_URLS:
        items = parse_list_with_playwright(u)
        for it in items[:20]:
            if not it["title"] or not it["url"]: continue
            _id = make_id(it["title"], it["url"], it.get("date"))
            if _id in seen: continue
            seen.add(_id)
            detail = parse_detail(it["url"])
            results.append({
                "id": _id,
                "title": it["title"],
                "summary": detail.get("summary",""),
                "articles": detail.get("articles",[]),
                "reason": detail.get("reason",""),
                "effectiveDate": detail.get("effectiveDate") or it.get("date"),
                "announcedDate": it.get("date"),
                "lawType": detail.get("lawType"),
                "source": {"name": "국가법령정보센터", "url": it["url"]}
            })
    results.sort(key=lambda x: (x.get("effectiveDate") or x.get("announcedDate") or ""), reverse=True)
    feed = {"generatedAt": int(time.time()), "items": results}
    print(json.dumps(feed, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
