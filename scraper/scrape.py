import json, re, time, hashlib, sys, pathlib  
from urllib.parse import urljoin  
import requests  
from bs4 import BeautifulSoup  
from playwright.sync_api import sync_playwright  

TARGET_URLS = [  
    # 검색어 없이 '시행 예정' 전체 목록  
    "https://www.law.go.kr/LSW/lsSc.do?menuId=1&subMenuId=15&tabMenuId=81&eventGubun=060101"  
]  

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"  
HEADERS =
