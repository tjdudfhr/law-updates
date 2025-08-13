import sys, json, time, hashlib, re, os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta

LAW_RSS = "https://www.law.go.kr/rss/lsRss.do?section=LS"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) law-updates-bot/1.2"

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

AMEND_RE = re.compile(r"(전부개정|일부개정|타법개정|개정(령|법률|규칙)?|일부개정령|일부개정법률)")
DATE_RE = re.compile(r"(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]?\s*(\d{1,2})[.\-/일]?")

def is_amendment(title, desc):
    txt = f"{title} {desc}"
    return AMEND_RE.search(txt) is not None

def extract_effective_date_from_desc(desc):
    # RSS description에서 '시행' 근처 날짜 우선 추출, 없으면 전체에서 추출
    text = re.sub(r"<[^>]+>", " ", desc or "")
    text = re.sub(r"\s+", " ", text)
    cands = set()

    for m in re.finditer(r"시행", text):
        s = max(0, m.start() - 100)
        e = min(len(text), m.end() + 150)
        window = text[s:e]
        for y, mm, dd in DATE_RE.findall(window):
            try:
                d = date(int(y), int(mm), int(dd))
                if 2000 <= d.year <= 2035:
                    cands.add(d)
            except:
                pass

    if not cands:
        for y, mm, dd in DATE_RE.findall(text):
            try:
                d = date(int(y), int(mm), int(dd))
                if 2000 <= d.year <= 2035:
                    cands.add(d)
            except:
                pass

    if not cands:
        return None
    future = sorted([d for d in cands if d >= TODAY])
    if future:
        return future[0].strftime("%Y-%m-%d")
    return min(cands).strftime("%Y-%m-%d")

def parse_pubdate(s):
    try:
        return datetime.strptime(s, "%a, %d %b %Y %H:%M:%S %z").date()
    except Exception:
        return None

def main():
    rss = parse_rss(LAW_RSS)

    # 디버그 저장
    os.makedirs("docs/_debug", exist_ok=True)
    try:
        with open("docs/_debug/rss.json", "w", encoding="utf-8") as f:
            json.dump({"count": len(rss), "sample": rss[:10]}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] debug write failed: {e}", file=sys.stderr)

    enriched = []
    for it in rss[:80]:
        title = it["title"]
        desc = it.get("summary", "")
        amend = is_amendment(title, desc)
        eff = extract_effective_date_from_desc(desc) if desc else None
        enriched.append({
            "title": title, "url": it["url"], "summary": desc,
            "pubDate": it.get("pubDate"), "effectiveDate": eff,
            "lawType": "개정" if amend else "",
        })

    # 1) 개정 + 앞으로 365일 이내 시행
    primary = []
    for x in enriched:
        if x["lawType"] != "개정" or not x["effectiveDate"]:
            continue
        try:
            d = datetime.strptime(x["effectiveDate"], "%Y-%m-%d").date()
        except:
            continue
        if TODAY <= d <= FUTURE_LIMIT:
            primary.append(x)

    # 2) 개정 + 시행일 있는 모든 것(최신순)
    secondary = [x for x in enriched if x["lawType"] == "개정" and x["effectiveDate"]]

    # 3) 개정 전체(최신순)
    def pd(x):
        p = parse_pubdate(x.get("pubDate") or "")
        return p or TODAY
    tertiary = sorted([x for x in enriched if x["lawType"] == "개정"], key=pd, reverse=True)

    # 4) 최후 안전망: 최근 항목 아무거나 20건
    fallback_any = sorted(enriched, key=pd, reverse=True)[:20]

    pick = primary or secondary or tertiary or fallback_any

    # 결과 구성
    results, seen = [], set()
    for it in pick[:30]:
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

    # 시행일이 있으면 그걸로, 없으면 pubDate로 정렬
    def sort_key(x):
        if x.get("effectiveDate"):
            return ("1", x["effectiveDate"])
        return ("2", "")
    results.sort(key=sort_key, reverse=True)

    print(json.dumps({"generatedAt": int(time.time()), "items": results}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
