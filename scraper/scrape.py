import requests, json, re, time, hashlib
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# 제공해주신 목록 URL(필요시 여기 배열에 다른 목록 URL을 추가할 수 있어요)
TARGET_URLS = [
    "https://www.law.go.kr/LSW/lsSc.do?menuId=1&subMenuId=15&tabMenuId=81&eventGubun=060101"
]

HEADERS = {"User-Agent": "LawUpdatesBot/1.0 (+contact@example.com)"}

def get_html(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    if not r.encoding or r.encoding.lower() == 'iso-8859-1':
        r.encoding = r.apparent_encoding
    r.raise_for_status()
    return r.text

def norm_date(s):
    if not s: return None
    s = s.replace('/', '.').replace('-', '.')
    m = re.search(r'(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})', s)
    if not m: return None
    y, mth, d = map(int, m.groups())
    return f"{y:04d}-{mth:02d}-{d:02d}"

def make_id(title, url, date):
    return hashlib.md5((title + (date or '') + url).encode('utf-8')).hexdigest()

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

        # 표 기반(th/td) 라벨 파싱
        label_map = {}
        for row in s.select("table tr"):
            th = row.find("th")
            td = row.find("td")
            if th and td:
                key = th.get_text(" ", strip=True)
                val = td.get_text(" ", strip=True)
                if key and val:
                    label_map[key] = val

        def find_in_labels(*keys):
            for k in keys:
                for label, val in label_map.items():
                    if k in label:
                        if val: return val
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

def parse_list(url):
    html = get_html(url)
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # 1) 테이블 행 우선 탐색
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("a[href]")
        if not a: continue
        title = a.get_text(strip=True)
        href = urljoin(url, a.get("href") or "")
        row_text = tr.get_text(" ", strip=True)
        date = norm_date(row_text)
        items.append({"title": title, "url": href, "date": date})

    # 2) 리스트(ul>li) 보완
    if not items:
        for li in soup.select("ul li"):
            a = li.select_one("a[href]")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(url, a.get("href") or "")
            date = norm_date(li.get_text(" ", strip=True))
            items.append({"title": title, "url": href, "date": date})

    # 상세 진입해 보강(상위 12건)
    out = []
    for it in items[:12]:
        detail = parse_detail(it["url"])
        out.append({
            "id": make_id(it["title"], it["url"], it.get("date")),
            "title": it["title"],
            "summary": detail.get("summary",""),
            "articles": detail.get("articles",[]),
            "reason": detail.get("reason",""),
            "effectiveDate": detail.get("effectiveDate") or it.get("date"),
            "announcedDate": it.get("date"),
            "lawType": detail.get("lawType"),
            "source": {"name": "국가법령정보센터", "url": it["url"]}
        })
    return out

def main():
    results = []
    seen = set()
    for u in TARGET_URLS:
        for it in parse_list(u):
            if it["id"] in seen: continue
            seen.add(it["id"])
            results.append(it)
    # 최신순 정렬
    results.sort(key=lambda x: (x.get("effectiveDate") or x.get("announcedDate") or ""), reverse=True)
    feed = {"generatedAt": int(time.time()), "items": results}
    # GitHub Actions에서 docs/index.json으로 리다이렉트해 쓸 예정
    print(json.dumps(feed, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
