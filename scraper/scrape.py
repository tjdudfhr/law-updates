import sys, json, time, hashlib, re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta

# 국가법령정보센터 최근 법령 RSS
LAW_RSS = "https://www.law.go.kr/rss/lsRss.do?section=LS"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) law-updates-bot/1.0"

TODAY = date.today()
RANGE_DAYS = 365  # 필터 완화: 앞으로 365일 이내 시행
FUTURE_LIMIT = TODAY + timedelta(days=RANGE_DAYS)
MAX_ITEMS = 40    # 상세 페이지 요청 상한
SLEEP_SEC = 0.6   # 예의상 지연

def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
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

def html_to_text(html):
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = text.replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()

def detect_law_type(text):
    if re.search(r"(전부개정|일부개정|타법개정|개정)", text):
        return "개정"
    if re.search(r"(전부개정법률|일부개정법률|일부개정령|일부개정)", text):
        return "개정"
    if re.search(r"(제정)", text):
        return "제정"
    if re.search(r"(폐지)", text):
        return "폐지"
    return None

DATE_PAT = re.compile(r"(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]?\s*(\d{1,2})[.\-/일]?", re.U)

def extract_candidate_dates(text):
    # '시행', '부터 시행', '부칙' 등 주변 100~150자에서 날짜 추출
    candidates = set()
    for kw in ("시행", "부터 시행", "부칙", "이 법은", "발효"):
        for m in re.finditer(re.escape(kw), text):
            s = max(0, m.start() - 100)
            e = min(len(text), m.end() + 150)
            window = text[s:e]
            for y, mm, dd in DATE_PAT.findall(window):
                try:
                    d = date(int(y), int(mm), int(dd))
                    # 2000~2035 범위 정도의 정상적인 날짜만
                    if 2000 <= d.year <= 2035:
                        candidates.add(d)
                except Exception:
                    pass
    # 전역 스캔도 한 번 더(혹시 키워드 근처에 없을 때)
    if not candidates:
        for y, mm, dd in DATE_PAT.findall(text):
            try:
                d = date(int(y), int(mm), int(dd))
                if 2000 <= d.year <= 2035:
                    candidates.add(d)
            except Exception:
                pass
    return sorted(candidates)

def enrich_from_detail(url):
    try:
        html = fetch(url)
        txt = html_to_text(html)
        law_type = detect_law_type(txt)
        cands = extract_candidate_dates(txt)

        # 시행일 후보들 중 가장 가까운 '미래' 날짜 우선
        future = [d for d in cands if d >= TODAY]
        eff = min(future) if future else (min(cands) if cands else None)
        eff_str = eff.strftime("%Y-%m-%d") if eff else None
        return eff_str, law_type
    except Exception as e:
        print(f"[WARN] detail parse failed: {url} ({e})", file=sys.stderr)
        return None, None

def parse_pubdate(s):
    # 예: Tue, 07 Jan 2025 00:00:00 +0900
    try:
        return datetime.strptime(s, "%a, %d %b %Y %H:%M:%S %z").date()
    except Exception:
        return None

def main():
    rss_items = parse_rss(LAW_RSS)
    if not rss_items:
        print(json.dumps({"generatedAt": int(time.time()), "items": []}, ensure_ascii=False))
        return

    enriched = []
    for it in rss_items[:MAX_ITEMS]:
        url = it["url"]
        if "law.go.kr" not in url:
            continue
        time.sleep(SLEEP_SEC)  # 서버 과부하 방지
        eff, law_type = enrich_from_detail(url)

        item = {
            "title": it["title"],
            "url": url,
            "summary": it.get("summary", ""),
            "pubDate": it.get("pubDate"),
            "effectiveDate": eff,
            "lawType": law_type,
        }
        enriched.append(item)

    # 1차: '개정' + 오늘~365일 내 시행
    filtered = []
    for it in enriched:
        if it["lawType"] != "개정" or not it["effectiveDate"]:
            continue
        try:
            eff_d = datetime.strptime(it["effectiveDate"], "%Y-%m-%d").date()
        except Exception:
            continue
        if TODAY <= eff_d <= FUTURE_LIMIT:
            filtered.append(it)

    # 2차(백업): 결과가 없으면 '개정' 중에서 시행일 있는 것 우선, 없으면 개정 전체 중 최근 20건
    if not filtered:
        with_date = [it for it in enriched if it["lawType"] == "개정" and it["effectiveDate"]]
        if with_date:
            filtered = sorted(with_date, key=lambda x: x["effectiveDate"])[:20]
        else:
            only_amended = [it for it in enriched if it["lawType"] == "개정"]
            if only_amended:
                # pubDate가 있는 경우 최신순
                def sort_key(x):
                    pd = parse_pubdate(x.get("pubDate") or "")
                    return pd or TODAY
                filtered = sorted(only_amended, key=sort_key, reverse=True)[:20]

    # 최종 결과 구성
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

    # 보기 좋게 정렬: 시행일 최신순(없으면 뒤로)
    results.sort(key=lambda x: x.get("effectiveDate") or "", reverse=True)

    feed = {"generatedAt": int(time.time()), "items": results}
    print(json.dumps(feed, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
