#!/usr/bin/env python3
"""
search_worker.py — Selenium multi-engine web search
Accepts any list of search queries and returns search results.
Anti-block strategies:
  • undetected-chromedriver
  • Randomised human delays
  • Random User-Agent / window size
  • Engine rotation with cooldown tracking
  • CAPTCHA/block detection → switches engine
"""

import re
import time
import random
import logging
from datetime import datetime
from urllib.parse import quote_plus

from PyQt5.QtCore import QThread, pyqtSignal

try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException
)

logger = logging.getLogger(__name__)

# ── User-Agent pool ──────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

WINDOW_SIZES = [(1366, 768), (1440, 900), (1920, 1080), (1280, 800), (1600, 900)]

# ── Engine definitions ───────────────────────────────────────────────────────
ENGINES = {
    "google": {
        "search_url": "https://www.google.com/search?q={query}&num=20",
        "result_selector": "div.g",
        "title_selector": "h3",
        "link_selector": "a",
        "snippet_selector": "div.VwiC3b, span.aCOpRe",
        "block_signals": ["captcha", "unusual traffic", "robot", "recaptcha"],
        "next_page_selector": "#pnnext",
    },
    "bing": {
        "search_url": "https://www.bing.com/search?q={query}&count=30",
        "result_selector": "li.b_algo",
        "title_selector": "h2",
        "link_selector": "a",
        "snippet_selector": "p, .b_caption p",
        "block_signals": ["captcha", "blocked", "automated"],
        "next_page_selector": "a.sb_pagN",
    },
    "yahoo": {
        "search_url": "https://search.yahoo.com/search?p={query}&n=30",
        "result_selector": "div.algo-sr, div[data-component-type='web-organic']",
        "title_selector": "h3, h3.title",
        "link_selector": "a",
        "snippet_selector": "div.compText p, span.fc-2nd",
        "block_signals": ["captcha", "blocked"],
        "next_page_selector": "a.next",
    },
}

# Domínios comuns a serem ignorados (opcional)
SKIP_DOMAINS = {
    "google.com", "bing.com", "yahoo.com", "facebook.com", "wikipedia.org",
    "instagram.com", "twitter.com", "youtube.com", "linkedin.com", "reddit.com",
}


def _human_delay(min_s=0.6, max_s=1.8):
    time.sleep(random.uniform(min_s, max_s))

def _normalise_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        domain = re.sub(r'^www\.', '', domain)
        return domain
    except Exception:
        return url

def _detect_chrome_version() -> int | None:
    import subprocess, shutil
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "google-chrome", "google-chrome-stable", "chromium-browser"
    ]
    for candidate in candidates:
        try:
            if not candidate.startswith("/") and not candidate.startswith("C:"):
                if not shutil.which(candidate):
                    continue
                path = candidate
            else:
                path = candidate
            result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
            output = result.stdout.strip() or result.stderr.strip()
            m = re.search(r'(\d+)\.\d+\.\d+', output)
            if m:
                return int(m.group(1))
        except Exception:
            continue
    return None


class WebSearchWorker(QThread):
    """
    Generic web search worker.
    Accepts a list of query strings.
    Returns each result as a dict with keys:
        query, engine, title, url, snippet
    """
    result = pyqtSignal(dict)      # per result
    progress = pyqtSignal(str)     # log messages
    finished = pyqtSignal(int)     # total results found

    def __init__(self, queries, engines=None, headless=True, max_pages=1, parent=None):
        """
        queries   : list of strings (search terms)
        engines   : list of engine names (default all)
        headless  : run browser without GUI
        max_pages : number of SERP pages per query per engine
        """
        super().__init__(parent)
        self.queries = queries
        self.engines = engines or list(ENGINES.keys())
        self.headless = headless
        self.max_pages = max_pages
        self._running = True
        self._driver = None
        self._seen_urls = set()
        self._engine_cooldowns = {e: 0 for e in ENGINES}

    def stop(self):
        self._running = False

    def run(self):
        total = 0
        try:
            self._driver = self._build_driver()
            self.progress.emit("🌐 Navegador iniciado.")

            for query in self.queries:
                if not self._running:
                    break
                for engine in self.engines:
                    if not self._running:
                        break
                    # Check cooldown
                    if time.time() - self._engine_cooldowns[engine] < 60:
                        self.progress.emit(f"⏳ {engine} em cooldown, pulando...")
                        continue
                    try:
                        self.progress.emit(f"🔍 [{engine.upper()}] {query}")
                        found = self._search_engine(engine, query)
                        total += found
                        self._engine_cooldowns[engine] = time.time()
                        _human_delay(1.0, 2.5)
                    except BlockedError:
                        self.progress.emit(f"⚠️ {engine} bloqueado, cooldown de 2 min")
                        self._engine_cooldowns[engine] = time.time() + 120
                    except Exception as e:
                        self.progress.emit(f"❌ Erro em {engine}: {e}")
        except Exception as e:
            self.progress.emit(f"❌ Erro fatal: {e}")
        finally:
            if self._driver:
                try:
                    self._driver.quit()
                except:
                    pass
            self.finished.emit(total)

    def _build_driver(self):
        ua = random.choice(USER_AGENTS)
        w, h = random.choice(WINDOW_SIZES)

        if HAS_UC:
            options = uc.ChromeOptions()
            if self.headless:
                options.add_argument("--headless=new")
            options.add_argument(f"--window-size={w},{h}")
            options.add_argument(f"--user-agent={ua}")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--lang=pt-BR,pt;q=0.9")
            prefs = {"profile.managed_default_content_settings.images": 2}
            options.add_experimental_option("prefs", prefs)
            chrome_version = _detect_chrome_version()
            driver = uc.Chrome(options=options, version_main=chrome_version)
        else:
            from selenium.webdriver.chrome.options import Options
            options = Options()
            if self.headless:
                options.add_argument("--headless=new")
            options.add_argument(f"--window-size={w},{h}")
            options.add_argument(f"--user-agent={ua}")
            options.add_argument("--disable-blink-features=AutomationControlled")
            driver = webdriver.Chrome(options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.set_page_load_timeout(30)
        return driver

    def _search_engine(self, engine, query):
        cfg = ENGINES[engine]
        url = cfg["search_url"].format(query=quote_plus(query))

        self._driver.get(url)
        _human_delay(0.8, 1.6)

        # Check block
        page_text = self._driver.execute_script("return document.body.innerText.toLowerCase();") or ""
        for sig in cfg["block_signals"]:
            if sig in page_text:
                raise BlockedError(f"{engine} bloqueado: {sig}")

        results = []
        for page in range(self.max_pages):
            if not self._running:
                break
            results += self._extract_results(engine, cfg, query)
            if page + 1 < self.max_pages and self._go_next_page(cfg):
                _human_delay(1.0, 2.0)
                # Re-check block after navigation
                page_text = self._driver.execute_script("return document.body.innerText.toLowerCase();") or ""
                for sig in cfg["block_signals"]:
                    if sig in page_text:
                        raise BlockedError(f"{engine} bloqueado na página {page+2}")
            else:
                break
        return len(results)

    def _extract_results(self, engine, cfg, query):
        results = []
        try:
            containers = self._driver.find_elements(By.CSS_SELECTOR, cfg["result_selector"])
        except:
            return results

        for container in containers:
            try:
                # Title
                title_el = container.find_element(By.CSS_SELECTOR, cfg["title_selector"])
                title = title_el.text.strip()
                # Link
                link_el = container.find_element(By.CSS_SELECTOR, cfg["link_selector"])
                href = link_el.get_attribute("href") or ""
                # Google wrapped URL
                if "google.com/url?q=" in href:
                    match = re.search(r'q=([^&]+)', href)
                    href = match.group(1) if match else ""
                # Snippet
                try:
                    snip_el = container.find_element(By.CSS_SELECTOR, cfg["snippet_selector"])
                    snippet = snip_el.text.strip()
                except:
                    snippet = ""

                if not title or not href:
                    continue

                domain = _normalise_domain(href)
                if domain in SKIP_DOMAINS:
                    continue
                if href in self._seen_urls:
                    continue
                self._seen_urls.add(href)

                result = {
                    "query": query,
                    "engine": engine,
                    "title": title,
                    "url": href,
                    "snippet": snippet,
                    "collected_at": datetime.now().isoformat()
                }
                results.append(result)
                self.result.emit(result)
                self.progress.emit(f"  ➕ {title[:60]} — {domain}")
            except Exception:
                continue
        return results

    def _go_next_page(self, cfg):
        try:
            next_btn = self._driver.find_element(By.CSS_SELECTOR, cfg["next_page_selector"])
            self._driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
            _human_delay(0.5, 1.0)
            next_btn.click()
            return True
        except:
            return False


class BlockedError(Exception):
    pass