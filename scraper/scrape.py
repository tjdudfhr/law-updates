import sys, json, time, hashlib, re, os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) law-updates-bot/1.4"
LAW_RSS = "https://www.law.go.kr/rss/lsRss.do?section=LS"
ALT_RSS = "https://opinion.lawmaking.go.kr/rss/announce.rss"

TODAY = date.today()
RANGE_DAYS = 365
FUTURE_LIMIT = TODAY + timedelta(days=RANGE_DAYS)

DATE_RE = re.compile(r"(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]?\s*(\d{1,2})[.\-/일]?")
AMEND_RE = re.compile(r"(전부개정|일부개정|타법개정|개정(령|법률|규칙)?)")

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml,application/xml,text/html"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    for enc in ("utf-8", "euc-kr"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "ignore")

def read_local(path):
    try:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except Exception:
        pass
    return None

def load_xml(url, debug_name):
    # 1순위: curl이 저장해 둔 파일 사용 → 네트워크 막혀도 파싱 가능
    local_path = f"docs/_debug/{debug_name}.xml"
    xml = read_local(local_path)
    if xml:
        print(f"[INFO] use local {local_path}", file=sys.stderr)
        return xml
    # 2순위: 파이썬으로 직접 다운로드(성공 시 디버그로 저장)
    try:
        xml = fetch(url)
        os.makedirs("docs/_debug", exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(xml)
        return xml
    except Exception as e:
        print(f"[ERR] fetch failed {url}: {e}", file=sys.stderr)
        return ""

def parse_rss(url, debug_name):
    xml = load_xml(url, debug_name)
    items = []
    if not xml:
        return items
    try:
        root = ET.fromstring(xml)
        for it in root.findall(".//item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = (it.findtext("description") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            if title and link:
                items.append({"title": title, "url": link, "summary": desc, "pubDate": pub})
        print(f"[INFO] parsed {debug_name}: {len(items)} items", file=sys.stderr)
    except Exception as e:
        print(f"[ERR] XML parse failed for {debug_name}: {e}", file=sys.stderr)
    return items

def is_amendment(title, desc):
    return AMEND_RE.search(f"{title} {desc}") is not None

def extract_effective_date(text):
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\s+", " ", t)
    cand = set()
    for m in re.finditer("시행", t):
        s = max(0, m.start()-100); e = min(len(t), m.end()+150)
        w = t[s:e]
        for y, mm, dd in DATE_RE.findall(w):
            try:
                d = date(int(y), int(mm), int(dd))
                if 2000 <= d.year <= 2035: cand.add(d)
            except: pass
    if not cand:
        for y, mm, dd in DATE_RE.findall(t):
            try:
                d = date(int(y), int(mm), int(dd))
                if 2000 <= d.year <= 2035: cand.add(d)
            except: pass
    if not cand: return None
    future = [d for d in cand if d >= TODAY]
    d = min(future) if future else min(cand)
    return d.strftime("%Y-%m-%d")

def parse_pubdate(s):
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None

def map_law(items):
    out=[]
    for it in items:
        title, desc = it["title"], it.get("summary","")
        typ = "개정" if is_amendment(title, desc) else ""
        eff = extract_effective_date(desc) if desc else None
        out.append({
            "title": title, "url": it["url"], "summary": desc,
            "effectiveDate": eff, "pubDate": it.get("pubDate"), "lawType": typ,
            "source": {"name":"국가법령정보센터", "url": it["url"]},
        })
    return out

def map_alt(items):
    out=[]
    for it in items:
        title, desc = it["title"], it.get("summary","")
        typ = "입법예고-개정" if is_amendment(title, desc) else "입법예고"
        eff = extract_effective_date(desc)
        out.append({
            "title": title, "url": it["url"], "summary": desc,
            "effectiveDate": eff, "pubDate": it.get("pubDate"), "lawType": typ,
            "source": {"name":"입법예고", "url": it["url"]},
        })
    return out

def main():
    law_raw = parse_rss(LAW_RSS, "law_rss")
    alt_raw = parse_rss(ALT_RSS, "announce_rss")

    law = map_law(law_raw)
    alt = map_alt(alt_raw)

    # 우선순위로 집계
    primary = []
    for x in law:
        if x["lawType"]!="개정" or not x["effectiveDate"]: continue
        try:
            d=datetime.strptime(x["effectiveDate"], "%Y-%m-%d").date()
            if TODAY<=d<=FUTURE_LIMIT: primary.append(x)
        except: pass
    secondary = [x for x in law if x["lawType"]=="개정" and x["effectiveDate"]]
    tertiary  = law[:20]
    fallback  = alt[:20]

    picked = primary or secondary or tertiary or fallback

    # 결과 구성
    results, seen = [], set()
    for it in picked[:30]:
        key = (it["title"] or "") + (it["url"] or "")
        _id = hashlib.md5(key.encode("utf-8")).hexdigest()
        if _id in seen: continue
        seen.add(_id)
        results.append({
            "id": _id, "title": it["title"], "summary": it.get("summary",""),
            "effectiveDate": it.get("effectiveDate"), "announcedDate": None,
            "lawType": it.get("lawType") or "", "source": it.get("source") or {"name":"","url":it.get("url")}
        })

    # 정렬
    def sort_key(x):
        return (1, x.get("effectiveDate") or "") if x.get("effectiveDate") else (2, x.get("title") or "")
    results.sort(key=sort_key, reverse=True)

    print(json.dumps({"generatedAt": int(time.time()), "items": results}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
