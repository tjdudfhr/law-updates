import json, re, time, hashlib, sys
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TARGET_URLS = [
    # 검색어 없이 '시행 예정' 전체 목록
    "https://www.law.go.kr/LSW/lsSc.do?menuId=1&subMenuId=15&tabMenuId=81&eventGubun=060101"
]

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"}

def norm_date(s: str|None):
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

        # 표 기반 라벨 추출
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

def parse_list_with_playwright(url):
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            locale="ko-KR",
            viewport={"width": 1360, "height": 900}
        )
        page = context.new_page()
        page.set_extra_http_headers({"Accept-Language": "ko-KR,ko;q=0.9"})
        page.goto(url, wait_until="networkidle", timeout=60000)

        # 1) 테이블 행(우선)
        rows = page.query_selector_all("table tbody tr")
        for tr in rows:
            a = tr.query_selector("a[href]")
            if not a: continue
            title = (a.inner_text() or "").strip()
            href = a.get_attribute("href") or ""
            href = urljoin(url, href)
            row_text = (tr.inner_text() or "").strip()
            date = norm_date(row_text)
            if title and href:
                out.append({"title": title, "url": href, "date": date})

        # 2) ul>li 보완
        if not out:
            lis = page.query_selector_all("ul li")
            for li in lis:
                a = li.query_selector("a[href]")
                if not a: continue
                title = (a.inner_text() or "").strip()
                href = urljoin(url, a.get_attribute("href") or "")
                date = norm_date((li.inner_text() or "").strip())
                if title and href:
                    out.append({"title": title, "url": href, "date": date})

        print(f"[INFO] list items from {url}: {len(out)}", file=sys.stderr)
        context.close(); browser.close()
    return out

def main():
    results = []
    seen = set()
    for u in TARGET_URLS:
        items = parse_list_with_playwright(u)
        for it in items[:15]:  # 상위 15건만 상세 파싱
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
