import sys, json, time, hashlib, re, os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta

LAW_RSS = "https://www.law.go.kr/rss/lsRss.do?section=LS"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) law-updates-bot/1.1"

TODAY = date.today()
RANGE_DAYS = 365
FUTURE_LIMIT = TODAY + timedelta(days=RANGE_DAYS)

def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml,application/xml,text/html;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    for enc in ("utf-8", "euc-kr"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "ignore")

def parse_rss(url):
    items = []
    try:
        xml = fetch(url)
        root = ET.fromstring(xml)
        for it in root.findall(".//item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = (it.findtext("description") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            if title and link:
                items.append({"title": title, "url": link, "summary": desc, "pubDate": pub})
        print(f"[INFO] RSS {url} -> {len(items)} items", file=sys.stderr)
    except Exception as e:
        print(f"[ERR] RSS {url}: {e}", file=sys.stderr)
    return items

# 개정 여부: 제목/요약만으로 판별(상세 페이지 방문 X)
AMEND_RE = re.compile(r"(전부개정|일부개정|타법개정|개정(령|법률|규칙)?)")

# 날짜 형식: 2025. 8. 13. / 2025-08-13 / 2025년 8월 13일
DATE_RE = re.compile(r"(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]?\s*(\d{1,2})[.\-/일]?")

def is_amendment(title, desc):
    text = f"{title} {desc}"
    return AMEND_RE.search(text) is not None

def extract_effective_date_from_desc(desc):
    # '시행' 주변을 우선 탐지
    text = re.sub(r"<[^>]+>", " ", desc)
    text = re.sub(r"\s+", " ", text)
    candidates = set()

    for m in re.finditer(r"시행", text):
        s = max(0, m.start() - 80)
        e = min(len(text), m.end() + 120)
        window = text[s:e]
        for y, mm, dd in DATE_RE.findall(window):
            try:
                d = date(int(y), int(mm), int(dd))
                if 2000 <= d.year <= 2035:
                    candidates.add(d)
            except:
                pass

    # 그래도 없으면 본문 전체에서 날짜 추출(안전망)
    if not candidates:
        for y, mm, dd in DATE_RE.findall(text):
            try:
                d = date(int(y), int(mm), int(dd))
                if 2000 <= d.year <= 2035:
                    candidates.add(d)
            except:
                pass

    if not candidates:
        return None

    future = sorted([d for d in candidates if d >= TODAY])
    if future:
        return future[0].strftime("%Y-%m-%d")
    return min(candidates).strftime("%Y-%m-%d")

def parse_pubdate(s):
    try:
        return datetime.strptime(s, "%a, %d %b %Y %H:%M:%S %z").date()
    except Exception:
        return None

def main():
    rss = parse_rss(LAW_RSS)

    # 디버그: 원본 RSS 일부 저장(페이지에서 /_debug/rss.json로 확인 가능)
    os.makedirs("docs/_debug", exist_ok=True)
    try:
        with open("docs/_debug/rss.json", "w", encoding="utf-8") as f:
            json.dump({"count": len(rss), "sample": rss[:10]}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] debug write failed: {e}", file=sys.stderr)

    enriched = []
    for it in rss[:60]:  # 최대 60개만 처리
        title = it["title"]
        desc = it.get("summary", "")
        amend = is_amendment(title, desc)
        eff = extract_effective_date_from_desc(desc) if amend else None
        enriched.append({
            "title": title,
            "url": it["url"],
            "summary": desc,
            "pubDate": it.get("pubDate"),
            "effectiveDate": eff,
            "lawType": "개정" if amend else None,
        })

    # 1차 필터: '개정' + 앞으로 365일 이내 시행
    filtered = []
    for it in enriched:
        if it["lawType"] != "개정" or not it["effectiveDate"]:
            continue
        try:
            eff_d = datetime.strptime(it["effectiveDate"], "%Y-%m-%d").date()
        except:
            continue
        if TODAY <= eff_d <= FUTURE_LIMIT:
            filtered.append(it)

    # 2차(안전망): 결과 없으면 '개정' 중 시행일이 있는 것(최신순) 또는 '개정' 최근 20건
    if not filtered:
        with_date = [x for x in enriched if x["lawType"] == "개정" and x["effectiveDate"]]
        if with_date:
            filtered = sorted(with_date, key=lambda x: x["effectiveDate"], reverse=True)[:20]
        else:
            only_amend = [x for x in enriched if x["lawType"] == "개정"]
            if only_amend:
                def sort_key(x):
                    pd = parse_pubdate(x.get("pubDate") or "")
                    return pd or TODAY
                filtered = sorted(only_amend, key=sort_key, reverse=True)[:20]

    # 최종 JSON
    results, seen = [], set()
    for it in filtered:
        key = (it["title"] or "") + (it["url"] or "")
        _id = hashlib.md5(key.encode("utf-8")).hexdigest()
        if _id in seen: 
            continue
        seen.add(_id)
        results.append({
            "id": _id,
            "title": it["title"],
            "summary": it.get("summary", ""),
            "effectiveDate": it.get("effectiveDate"),
            "announcedDate": None,
            "lawType": it.get("lawType") or "",
            "source": {"name": "국가법령정보센터", "url": it["url"]},
        })

    results.sort(key=lambda x: x.get("effectiveDate") or "", reverse=True)
    feed = {"generatedAt": int(time.time()), "items": results}
    print(json.dumps(feed, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
