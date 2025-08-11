import json, time, hashlib, re
import xml.etree.ElementTree as ET
import requests

RSS_FEEDS = [
    "https://www.law.go.kr/LSW/rss/rssList.do?rssSeq=1",  # 제정·개정법령
    "https://www.law.go.kr/LSW/rss/rssList.do?rssSeq=2"   # 입법예고
]

def norm_date(s):
    if not s: return None
    # RSS pubDate 형식 처리 (e.g., "Fri, 10 Jan 2025 09:00:00 GMT")
    import datetime
    try:
        # 간단한 파싱
        dt = datetime.datetime.strptime(s[:25], "%a, %d %b %Y %H:%M:%S")
        return dt.strftime("%Y-%m-%d")
    except:
        # 대안으로 숫자 추출
        m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
        if m:
            y, mm, d = map(int, m.groups())
            return f"{y:04d}-{mm:02d}-{d:02d}"
    return None

def parse_rss(url):
    items = []
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        r.encoding = 'utf-8'
        root = ET.fromstring(r.text)
        
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            
            if title and link:
                items.append({
                    "title": title,
                    "url": link,
                    "summary": desc,
                    "date": norm_date(pub_date)
                })
    except Exception as e:
        print(f"RSS parse error: {e}", file=sys.stderr)
    return items

def main():
    all_items = []
    for feed_url in RSS_FEEDS:
        all_items.extend(parse_rss(feed_url))
    
    # 중복 제거 및 JSON 변환
    results = []
    seen = set()
    for item in all_items[:30]:  # 최대 30건
        _id = hashlib.md5((item["title"] + item["url"]).encode()).hexdigest()
        if _id in seen: continue
        seen.add(_id)
        
        results.append({
            "id": _id,
            "title": item["title"],
            "summary": item.get("summary", ""),
            "effectiveDate": item.get("date"),
            "announcedDate": item.get("date"),
            "lawType": None,
            "source": {
                "name": "국가법령정보센터",
                "url": item["url"]
            }
        })
    
    results.sort(key=lambda x: x.get("effectiveDate") or "", reverse=True)
    feed = {"generatedAt": int(time.time()), "items": results}
    print(json.dumps(feed, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
