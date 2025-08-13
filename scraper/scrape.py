import sys, json, time, hashlib, re
import urllib.request
import xml.etree.ElementTree as ET

FEEDS = [
    "https://opinion.lawmaking.go.kr/rss/announce.rss"  # 입법예고 RSS
]

def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("euc-kr", "ignore")

def norm_date(s):
    if not s: return None
    s = s.strip()
    m = re.match(r"\w{3},\s+(\d{1,2})\s+(\w{3})\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", s)
    months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    if m:
        d, mon, y = int(m.group(1)), months.get(m.group(2),1), int(m.group(3))
        return f"{y:04d}-{mon:02d}-{d:02d}"
    m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", s)
    if m:
        y, mm, d = map(int, m.groups())
        return f"{y:04d}-{mm:02d}-{d:02d}"
    return None

def parse_rss(xml_text):
    items = []
    root = ET.fromstring(xml_text)
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = (it.findtext("description") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        if title and link:
            items.append({
                "title": title,
                "url": link,
                "summary": desc,
                "date": norm_date(pub),
            })
    return items

def main():
    all_items = []
    for u in FEEDS:
        try:
            xml = fetch(u)
            parsed = parse_rss(xml)
            all_items.extend(parsed)
            print(f"[INFO] {u} -> {len(parsed)} items", file=sys.stderr)
        except Exception as e:
            print(f"[ERR] {u}: {e}", file=sys.stderr)

    results, seen = [], set()
    for it in all_items[:50]:
        _id = hashlib.md5((it["title"] + it["url"]).encode()).hexdigest()
        if _id in seen:
            continue
        seen.add(_id)
        results.append({
            "id": _id,
            "title": it["title"],
            "summary": it.get("summary",""),
            "effectiveDate": it.get("date"),
            "announcedDate": it.get("date"),
            "lawType": "입법예고",
            "source": {"name":"입법예고", "url": it["url"]},
        })

    results.sort(key=lambda x: x.get("effectiveDate") or "", reverse=True)

    if not results:
        results = [
            {
                "id": "sample1",
                "title": "샘플: 개인정보 보호법 시행령 일부개정령",
                "summary": "화면 확인용 샘플 데이터입니다.",
                "effectiveDate": "2025-02-01",
                "announcedDate": "2025-01-10",
                "lawType": "대통령령",
                "source": {"name": "샘플", "url": "https://www.law.go.kr"},
            },
            {
                "id": "sample2",
                "title": "샘플: 전자상거래 등에서의 소비자보호에 관한 법률 시행규칙",
                "summary": "화면 확인용 샘플 데이터입니다.",
                "effectiveDate": "2025-03-01",
                "announcedDate": "2025-01-08",
                "lawType": "부령",
                "source": {"name": "샘플", "url": "https://www.law.go.kr"},
            },
        ]

    feed = {"generatedAt": int(time.time()), "items": results}
    print(json.dumps(feed, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
