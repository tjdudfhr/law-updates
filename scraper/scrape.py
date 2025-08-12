import json, time, hashlib, re, sys
import xml.etree.ElementTree as ET
import requests

RSS_FEEDS = [
    "https://opinion.lawmaking.go.kr/rss/announce.rss",  # 입법예고 RSS (실제 데이터 많음)
    "https://www.law.go.kr/rss/lsRss.do?section=LS"      # 제정·개정법령 RSS (법제처 공식)
]

def norm_date(s):
    if not s: return None
    # RSS pubDate 형식 처리 (e.g., "Fri, 10 Jan 2025 09:00:00 GMT")
    import datetime
    try:
        # 간단한 파싱 (RFC 822 형식 지원)
        dt = datetime.datetime.strptime(s.split('+')[0].strip(), "%a, %d %b %Y %H:%M:%S")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        try:
            # 다른 형식 (e.g., "2025-08-12T12:00:00")
            dt = datetime.datetime.fromisoformat(s.split('.')[0].replace('Z', ''))
            return dt.strftime("%Y-%m-%d")
        except:
            # 숫자 추출 대안
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
        print(f"RSS parse error for {url}: {e}", file=sys.stderr)
    return items

def main():
    all_items = []
    for feed_url in RSS_FEEDS:
        parsed = parse_rss(feed_url)
        all_items.extend(parsed)
        print(f"[INFO] Parsed {len(parsed)} items from {feed_url}", file=sys.stderr)
    
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
