#!/usr/bin/env python3
"""
DataSift v1.2
- Scrape pages with CSS selectors
- Search Google/Bing/Yahoo for URLs
- Enrich URLs with email/phone using regex + Groq AI
"""

import sys
import json
import time
import csv
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QLineEdit, QTextEdit, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QGroupBox, QFormLayout, QSpinBox, QMessageBox, QFileDialog,
    QSplitter, QStatusBar, QPlainTextEdit, QStyle
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPalette, QIcon

# Import workers
from search_worker import WebSearchWorker
from contact_enricher import ContactEnricherWorker

# Optional Selenium for ScrapeWorker
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
APP_NAME = 'DataSift'
APP_VERSION = '1.2'
CONFIG_FILE = Path.home() / 'DataSift' / 'config.json'
PROJECTS_DIR = Path.home() / 'DataSift' / 'projects'

def ensure_dirs():
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

def load_config():
    ensure_dirs()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_config(cfg):
    ensure_dirs()
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ----------------------------------------------------------------------
# Scraping Worker (static + Selenium)
# ----------------------------------------------------------------------
class ScrapeWorker(QThread):
    progress = pyqtSignal(str)
    result   = pyqtSignal(dict)
    finished = pyqtSignal(int)
    status   = pyqtSignal(int, int)

    def __init__(self, urls, fields, use_selenium=False, headless=True,
                 delay=1, user_agent=None):
        super().__init__()
        self.urls = urls
        self.fields = fields
        self.use_selenium = use_selenium
        self.headless = headless
        self.delay = delay
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        self._running = True
        self.driver = None

    def stop(self):
        self._running = False

    def _init_selenium(self):
        if not HAS_SELENIUM:
            raise RuntimeError("Selenium not installed")
        opts = Options()
        if self.headless:
            opts.add_argument("--headless")
        opts.add_argument(f"--user-agent={self.user_agent}")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        self.driver = webdriver.Chrome(options=opts)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def _scrape_with_requests(self, url):
        headers = {'User-Agent': self.user_agent}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        item = {'url': url}
        for field in self.fields:
            name = field['name']
            selector = field['selector']
            elements = soup.select(selector)
            item[name] = elements[0].get_text(strip=True) if elements else ''
        return item

    def _scrape_with_selenium(self, url):
        if self.driver is None:
            self._init_selenium()
        self.driver.get(url)
        WebDriverWait(self.driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        item = {'url': url}
        for field in self.fields:
            name = field['name']
            selector = field['selector']
            try:
                elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                item[name] = elem.text.strip()
            except:
                item[name] = ''
        return item

    def run(self):
        total = len(self.urls)
        scraped = 0
        for idx, url in enumerate(self.urls):
            if not self._running:
                break
            self.status.emit(idx+1, total)
            self.progress.emit(f"Scraping: {url}")
            try:
                if self.use_selenium:
                    data = self._scrape_with_selenium(url)
                else:
                    data = self._scrape_with_requests(url)
                self.result.emit(data)
                scraped += 1
            except Exception as e:
                self.progress.emit(f"Error on {url}: {str(e)}")
            time.sleep(self.delay)
        if self.driver:
            self.driver.quit()
        self.finished.emit(scraped)

# ----------------------------------------------------------------------
# Main Window
# ----------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.scraped_data = []
        self.search_results = []
        self.enriched_leads = []
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1200, 750)
        self.setStyleSheet(self._get_stylesheet())
        self._build_ui()
        self._load_config_to_ui()
        self._update_status()

    def _get_stylesheet(self):
        # Visual profissional, sem emojis, cores elegantes
        return """
        QMainWindow, QWidget {
            background-color: #1e1e2e;
            color: #cdd6f4;
            font-family: 'Segoe UI', 'Roboto', sans-serif;
            font-size: 13px;
        }
        QTabWidget::pane {
            border: 1px solid #313244;
            background: #181825;
            border-radius: 6px;
        }
        QTabBar::tab {
            background: #313244;
            color: #a6adc8;
            padding: 8px 16px;
            border: none;
            margin-right: 2px;
            border-radius: 4px 4px 0 0;
            font-weight: 500;
        }
        QTabBar::tab:selected {
            background: #89b4fa;
            color: #1e1e2e;
        }
        QTabBar::tab:hover:!selected {
            background: #45475a;
            color: #cdd6f4;
        }
        QPushButton {
            background: #89b4fa;
            color: #1e1e2e;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-weight: 600;
        }
        QPushButton:hover {
            background: #b4befe;
        }
        QPushButton:disabled {
            background: #45475a;
            color: #6c7086;
        }
        QPushButton#danger {
            background: #f38ba8;
            color: #1e1e2e;
        }
        QPushButton#danger:hover {
            background: #fab387;
        }
        QPushButton#secondary {
            background: #313244;
            color: #cdd6f4;
            border: 1px solid #45475a;
        }
        QPushButton#secondary:hover {
            background: #45475a;
        }
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
            background: #181825;
            border: 1px solid #313244;
            border-radius: 6px;
            padding: 6px;
            color: #cdd6f4;
            selection-background-color: #89b4fa;
        }
        QGroupBox {
            border: 1px solid #313244;
            border-radius: 8px;
            margin-top: 12px;
            font-weight: 600;
            padding-top: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
        }
        QTableWidget {
            background: #181825;
            gridline-color: #313244;
            selection-background-color: #45475a;
            border: 1px solid #313244;
            border-radius: 6px;
        }
        QProgressBar {
            background: #313244;
            border: none;
            border-radius: 4px;
            height: 8px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: #89b4fa;
            border-radius: 4px;
        }
        QStatusBar {
            background: #11111b;
            color: #6c7086;
            border-top: 1px solid #181825;
        }
        QHeaderView::section {
            background-color: #313244;
            padding: 4px;
            border: none;
        }
        """

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QWidget()
        header.setFixedHeight(60)
        header.setStyleSheet("background: #11111b; border-bottom: 1px solid #313244;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(20, 0, 20, 0)
        title = QLabel("DataSift")
        title.setStyleSheet("font-size: 22px; font-weight: 800; color: #89b4fa;")
        hlay.addWidget(title)
        hlay.addStretch()
        ver = QLabel(APP_VERSION)
        ver.setStyleSheet("background: #313244; color: #a6adc8; padding: 4px 12px; border-radius: 16px;")
        hlay.addWidget(ver)
        root.addWidget(header)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.tabs.addTab(self._tab_scraper(), "Extractor")
        self.tabs.addTab(self._tab_web_search(), "Web Search")
        self.tabs.addTab(self._tab_enrich(), "Contact Enrichment")
        self.tabs.addTab(self._tab_results(), "Results")
        self.tabs.addTab(self._tab_settings(), "Settings")

        self.status_bar = QStatusBar()
        self.status_label = QLabel("Ready")
        self.items_label = QLabel("0 items")
        self.status_bar.addWidget(self.items_label)
        self.status_bar.addPermanentWidget(self.status_label)
        self.setStatusBar(self.status_bar)

    # ---------------------- Scraper Tab -------------------------------
    def _tab_scraper(self):
        w = QWidget()
        layout = QHBoxLayout(w)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        g_urls = QGroupBox("Target URLs (one per line)")
        url_layout = QVBoxLayout(g_urls)
        self.urls_text = QPlainTextEdit()
        self.urls_text.setPlaceholderText("https://example.com/page1\nhttps://example.com/page2")
        url_layout.addWidget(self.urls_text)
        left_layout.addWidget(g_urls)

        g_fields = QGroupBox("Fields to extract (CSS selectors)")
        fields_layout = QVBoxLayout(g_fields)
        self.fields_table = QTableWidget()
        self.fields_table.setColumnCount(2)
        self.fields_table.setHorizontalHeaderLabels(["Field Name", "CSS Selector"])
        self.fields_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.fields_table.setAlternatingRowColors(True)
        fields_layout.addWidget(self.fields_table)

        btn_row = QHBoxLayout()
        btn_add_field = QPushButton("+ Add field")
        btn_add_field.setObjectName("secondary")
        btn_add_field.clicked.connect(self._add_field_row)
        btn_rem_field = QPushButton("- Remove last")
        btn_rem_field.setObjectName("secondary")
        btn_rem_field.clicked.connect(self._remove_last_field)
        btn_row.addWidget(btn_add_field)
        btn_row.addWidget(btn_rem_field)
        btn_row.addStretch()
        fields_layout.addLayout(btn_row)
        left_layout.addWidget(g_fields)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        g_opts = QGroupBox("Extraction Options")
        opts_form = QFormLayout(g_opts)
        self.use_selenium_cb = QCheckBox("Use Selenium (for JavaScript pages)")
        self.use_selenium_cb.setChecked(False)
        self.headless_cb = QCheckBox("Headless mode (Selenium only)")
        self.headless_cb.setChecked(True)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 30)
        self.delay_spin.setValue(1)
        self.delay_spin.setSuffix(" sec")
        opts_form.addRow(self.use_selenium_cb)
        opts_form.addRow(self.headless_cb)
        opts_form.addRow("Request delay", self.delay_spin)
        right_layout.addWidget(g_opts)

        btn_start = QPushButton("Start Extraction")
        btn_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        btn_start.clicked.connect(self._start_scraping)
        btn_stop = QPushButton("Stop")
        btn_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        btn_stop.setObjectName("danger")
        btn_stop.setEnabled(False)
        btn_stop.clicked.connect(self._stop_scraping)
        btn_load = QPushButton("Load Project")
        btn_load.setObjectName("secondary")
        btn_load.clicked.connect(self._load_project)
        btn_save = QPushButton("Save Project")
        btn_save.setObjectName("secondary")
        btn_save.clicked.connect(self._save_project)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        ctrl_layout = QVBoxLayout()
        ctrl_layout.addWidget(btn_start)
        ctrl_layout.addWidget(btn_stop)
        ctrl_layout.addWidget(btn_load)
        ctrl_layout.addWidget(btn_save)
        ctrl_layout.addWidget(self.progress_bar)
        right_layout.addLayout(ctrl_layout)

        g_log = QGroupBox("Extraction Log")
        log_layout = QVBoxLayout(g_log)
        self.scraper_log = QTextEdit()
        self.scraper_log.setReadOnly(True)
        self.scraper_log.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self.scraper_log)
        right_layout.addWidget(g_log)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([500, 400])
        layout.addWidget(splitter)

        self.btn_start = btn_start
        self.btn_stop = btn_stop
        return w

    def _add_field_row(self):
        row = self.fields_table.rowCount()
        self.fields_table.insertRow(row)
        self.fields_table.setItem(row, 0, QTableWidgetItem("field_name"))
        self.fields_table.setItem(row, 1, QTableWidgetItem("h1"))

    def _remove_last_field(self):
        if self.fields_table.rowCount() > 0:
            self.fields_table.removeRow(self.fields_table.rowCount() - 1)

    def _get_fields_from_table(self):
        fields = []
        for row in range(self.fields_table.rowCount()):
            name_item = self.fields_table.item(row, 0)
            sel_item = self.fields_table.item(row, 1)
            if name_item and sel_item and name_item.text().strip():
                fields.append({
                    'name': name_item.text().strip(),
                    'selector': sel_item.text().strip()
                })
        return fields

    def _get_urls_from_text(self):
        urls = []
        for line in self.urls_text.toPlainText().splitlines():
            line = line.strip()
            if line and (line.startswith('http://') or line.startswith('https://')):
                urls.append(line)
        return urls

    def _start_scraping(self):
        urls = self._get_urls_from_text()
        fields = self._get_fields_from_table()
        if not urls:
            QMessageBox.warning(self, "No URLs", "Please enter at least one valid URL.")
            return
        if not fields:
            QMessageBox.warning(self, "No fields", "Please define at least one field to extract.")
            return

        self.scraped_data = []
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(urls))
        self.progress_bar.setValue(0)
        self.scraper_log.clear()

        use_sel = self.use_selenium_cb.isChecked()
        headless = self.headless_cb.isChecked()
        delay = self.delay_spin.value()
        ua = self.config.get("user_agent", "")

        self.scrape_worker = ScrapeWorker(
            urls, fields, use_selenium=use_sel,
            headless=headless, delay=delay, user_agent=ua
        )
        self.scrape_worker.progress.connect(self._log_scrape)
        self.scrape_worker.result.connect(self._on_scraped_item)
        self.scrape_worker.status.connect(self._update_progress)
        self.scrape_worker.finished.connect(self._scraping_finished)
        self.scrape_worker.start()

    def _stop_scraping(self):
        if hasattr(self, 'scrape_worker') and self.scrape_worker.isRunning():
            self.scrape_worker.stop()
            self._log_scrape("[STOP] Extraction stopped by user.")

    def _log_scrape(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.scraper_log.append(f"[{timestamp}] {msg}")

    def _update_progress(self, current, total):
        self.progress_bar.setValue(current)

    def _on_scraped_item(self, item):
        self.scraped_data.append(item)
        self._log_scrape(f"[OK] Extracted: {item.get('url', '')}")
        self._update_status()
        self._update_enrich_source_list()

    def _scraping_finished(self, total):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)
        self._log_scrape(f"[DONE] Extraction completed. {total} items.")
        self._refresh_results_table()
        self.tabs.setCurrentIndex(3)

    # ---------------------- Web Search Tab ---------------------------------
    def _tab_web_search(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        g_queries = QGroupBox("Search Queries (one per line)")
        q_layout = QVBoxLayout(g_queries)
        self.search_queries = QPlainTextEdit()
        self.search_queries.setPlaceholderText("example:\nevent equipment rental Sao Paulo\nprojector rental")
        q_layout.addWidget(self.search_queries)
        layout.addWidget(g_queries)

        g_engines = QGroupBox("Search Engines")
        eng_layout = QHBoxLayout(g_engines)
        self.chk_google = QCheckBox("Google")
        self.chk_google.setChecked(True)
        self.chk_bing = QCheckBox("Bing")
        self.chk_bing.setChecked(True)
        self.chk_yahoo = QCheckBox("Yahoo")
        self.chk_yahoo.setChecked(True)
        eng_layout.addWidget(self.chk_google)
        eng_layout.addWidget(self.chk_bing)
        eng_layout.addWidget(self.chk_yahoo)
        eng_layout.addStretch()
        layout.addWidget(g_engines)

        opts = QHBoxLayout()
        self.ws_headless = QCheckBox("Headless mode")
        self.ws_headless.setChecked(True)
        self.ws_pages = QSpinBox()
        self.ws_pages.setRange(1, 3)
        self.ws_pages.setValue(1)
        opts.addWidget(QLabel("Pages per query:"))
        opts.addWidget(self.ws_pages)
        opts.addWidget(self.ws_headless)
        opts.addStretch()
        layout.addLayout(opts)

        ctrl = QHBoxLayout()
        self.btn_ws_start = QPushButton("Start Search")
        self.btn_ws_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_ws_start.clicked.connect(self._start_web_search)
        self.btn_ws_stop = QPushButton("Stop")
        self.btn_ws_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_ws_stop.setObjectName("danger")
        self.btn_ws_stop.setEnabled(False)
        self.btn_ws_stop.clicked.connect(self._stop_web_search)
        ctrl.addWidget(self.btn_ws_start)
        ctrl.addWidget(self.btn_ws_stop)
        layout.addLayout(ctrl)

        self.ws_progress = QProgressBar()
        self.ws_progress.setVisible(False)
        layout.addWidget(self.ws_progress)

        self.ws_results_table = QTableWidget()
        self.ws_results_table.setColumnCount(4)
        self.ws_results_table.setHorizontalHeaderLabels(["Query", "Engine", "Title", "URL"])
        self.ws_results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.ws_results_table)

        g_log = QGroupBox("Search Log")
        log_layout = QVBoxLayout(g_log)
        self.ws_log = QTextEdit()
        self.ws_log.setReadOnly(True)
        self.ws_log.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self.ws_log)
        layout.addWidget(g_log)

        btn_export = QPushButton("Export Results (CSV)")
        btn_export.setObjectName("secondary")
        btn_export.clicked.connect(self._export_web_search_results)
        layout.addWidget(btn_export)

        return w

    def _start_web_search(self):
        queries_text = self.search_queries.toPlainText().strip()
        if not queries_text:
            QMessageBox.warning(self, "Empty", "Enter at least one search query.")
            return
        queries = [q.strip() for q in queries_text.splitlines() if q.strip()]

        engines = []
        if self.chk_google.isChecked(): engines.append("google")
        if self.chk_bing.isChecked():   engines.append("bing")
        if self.chk_yahoo.isChecked():  engines.append("yahoo")
        if not engines:
            QMessageBox.warning(self, "No engine", "Select at least one search engine.")
            return

        self.ws_results_table.setRowCount(0)
        self.search_results = []
        self.ws_log.clear()
        self.btn_ws_start.setEnabled(False)
        self.btn_ws_stop.setEnabled(True)
        self.ws_progress.setVisible(True)
        self.ws_progress.setMaximum(0)

        self.web_search_worker = WebSearchWorker(
            queries,
            engines=engines,
            headless=self.ws_headless.isChecked(),
            max_pages=self.ws_pages.value()
        )
        self.web_search_worker.progress.connect(self._ws_log)
        self.web_search_worker.result.connect(self._on_ws_result)
        self.web_search_worker.finished.connect(self._ws_finished)
        self.web_search_worker.start()

    def _stop_web_search(self):
        if hasattr(self, 'web_search_worker') and self.web_search_worker.isRunning():
            self.web_search_worker.stop()
            self._ws_log("[STOP] Web search stopped by user.")

    def _ws_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.ws_log.append(f"[{ts}] {msg}")

    def _on_ws_result(self, result):
        self.search_results.append(result)
        row = self.ws_results_table.rowCount()
        self.ws_results_table.insertRow(row)
        self.ws_results_table.setItem(row, 0, QTableWidgetItem(result.get("query", "")))
        self.ws_results_table.setItem(row, 1, QTableWidgetItem(result.get("engine", "")))
        self.ws_results_table.setItem(row, 2, QTableWidgetItem(result.get("title", "")))
        self.ws_results_table.setItem(row, 3, QTableWidgetItem(result.get("url", "")))
        self.ws_results_table.resizeColumnsToContents()
        self._update_enrich_source_list()

    def _ws_finished(self, total):
        self.btn_ws_start.setEnabled(True)
        self.btn_ws_stop.setEnabled(False)
        self.ws_progress.setVisible(False)
        self._ws_log(f"[DONE] Web search finished. Total results: {total}")

    def _export_web_search_results(self):
        if self.ws_results_table.rowCount() == 0:
            QMessageBox.information(self, "No data", "Nothing to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "web_search_results.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["Query", "Engine", "Title", "URL"])
            for row in range(self.ws_results_table.rowCount()):
                row_data = [self.ws_results_table.item(row, col).text() for col in range(4)]
                writer.writerow(row_data)
        QMessageBox.information(self, "Exported", f"Saved to {path}")

    # ---------------------- Enrich Contacts Tab ---------------------------
    def _tab_enrich(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        g_source = QGroupBox("Data Source for Enrichment")
        source_layout = QHBoxLayout(g_source)
        self.source_scraper = QCheckBox("Extractor results")
        self.source_websearch = QCheckBox("Web Search results")
        self.source_scraper.setChecked(True)
        self.source_websearch.setChecked(True)
        source_layout.addWidget(self.source_scraper)
        source_layout.addWidget(self.source_websearch)
        source_layout.addStretch()
        layout.addWidget(g_source)

        g_opts = QGroupBox("Enrichment Options")
        opts_layout = QFormLayout(g_opts)
        self.enrich_use_ai = QCheckBox("Use Groq AI (free) as fallback - requires API key in Settings")
        self.enrich_use_ai.setChecked(False)
        self.enrich_overwrite = QCheckBox("Overwrite existing contacts (if any)")
        self.enrich_overwrite.setChecked(False)
        opts_layout.addRow(self.enrich_use_ai)
        opts_layout.addRow(self.enrich_overwrite)
        layout.addWidget(g_opts)

        ctrl = QHBoxLayout()
        self.btn_enrich_start = QPushButton("Start Enrichment")
        self.btn_enrich_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_enrich_start.clicked.connect(self._start_enrichment)
        self.btn_enrich_stop = QPushButton("Stop")
        self.btn_enrich_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_enrich_stop.setObjectName("danger")
        self.btn_enrich_stop.setEnabled(False)
        self.btn_enrich_stop.clicked.connect(self._stop_enrichment)
        ctrl.addWidget(self.btn_enrich_start)
        ctrl.addWidget(self.btn_enrich_stop)
        layout.addLayout(ctrl)

        self.enrich_progress = QProgressBar()
        self.enrich_progress.setVisible(False)
        layout.addWidget(self.enrich_progress)

        self.enrich_table = QTableWidget()
        self.enrich_table.setColumnCount(5)
        self.enrich_table.setHorizontalHeaderLabels(["URL", "Title", "Email", "Phone", "Source"])
        self.enrich_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.enrich_table)

        g_log = QGroupBox("Enrichment Log")
        log_layout = QVBoxLayout(g_log)
        self.enrich_log = QTextEdit()
        self.enrich_log.setReadOnly(True)
        self.enrich_log.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self.enrich_log)
        layout.addWidget(g_log)

        btn_export = QPushButton("Export Enriched Data (CSV)")
        btn_export.setObjectName("secondary")
        btn_export.clicked.connect(self._export_enriched)
        layout.addWidget(btn_export)

        return w

    def _update_enrich_source_list(self):
        leads = []
        if self.source_scraper.isChecked():
            for item in self.scraped_data:
                url = item.get("url", "")
                if url:
                    leads.append({
                        "website": url,
                        "title": item.get("title", ""),
                        "source": "Extractor",
                        "email": "",
                        "phone": ""
                    })
        if self.source_websearch.isChecked():
            for res in self.search_results:
                url = res.get("url", "")
                if url:
                    leads.append({
                        "website": url,
                        "title": res.get("title", ""),
                        "source": "Web Search",
                        "email": "",
                        "phone": ""
                    })
        seen = set()
        unique = []
        for lead in leads:
            if lead["website"] not in seen:
                seen.add(lead["website"])
                unique.append(lead)
        self.enriched_leads = unique
        self._refresh_enrich_table()

    def _refresh_enrich_table(self):
        self.enrich_table.setRowCount(0)
        for lead in self.enriched_leads:
            row = self.enrich_table.rowCount()
            self.enrich_table.insertRow(row)
            self.enrich_table.setItem(row, 0, QTableWidgetItem(lead.get("website", "")))
            self.enrich_table.setItem(row, 1, QTableWidgetItem(lead.get("title", "")))
            self.enrich_table.setItem(row, 2, QTableWidgetItem(lead.get("email", "")))
            self.enrich_table.setItem(row, 3, QTableWidgetItem(lead.get("phone", "")))
            self.enrich_table.setItem(row, 4, QTableWidgetItem(lead.get("source", "")))
        self.enrich_table.resizeColumnsToContents()

    def _start_enrichment(self):
        self._update_enrich_source_list()
        if not self.enriched_leads:
            QMessageBox.information(self, "No leads", "No URLs to enrich. Run Extractor or Web Search first.")
            return

        use_ai = self.enrich_use_ai.isChecked()
        groq_key = self.config.get("groq_key", "") if use_ai else ""
        if use_ai and not groq_key:
            QMessageBox.warning(self, "Groq key missing", "Please configure Groq API key in Settings tab.")
            return

        for lead in self.enriched_leads:
            lead["email"] = ""
            lead["phone"] = ""

        self.btn_enrich_start.setEnabled(False)
        self.btn_enrich_stop.setEnabled(True)
        self.enrich_progress.setVisible(True)
        self.enrich_progress.setMaximum(len(self.enriched_leads))
        self.enrich_progress.setValue(0)
        self.enrich_log.clear()

        leads_for_worker = []
        for lead in self.enriched_leads:
            leads_for_worker.append({
                "website": lead["website"],
                "email": lead.get("email", ""),
                "phone": lead.get("phone", ""),
                "name": lead.get("title", "")
            })

        self.enrich_worker = ContactEnricherWorker(leads_for_worker, groq_key=groq_key)
        self.enrich_worker.progress.connect(self._enrich_log)
        self.enrich_worker.enriched.connect(self._on_lead_enriched)
        self.enrich_worker.finished.connect(self._enrich_finished)
        self.enrich_worker.start()

    def _enrich_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.enrich_log.append(f"[{ts}] {msg}")

    def _on_lead_enriched(self, idx, updates):
        if idx < len(self.enriched_leads):
            overwrite = self.enrich_overwrite.isChecked()
            if "email" in updates and (overwrite or not self.enriched_leads[idx].get("email")):
                self.enriched_leads[idx]["email"] = updates["email"]
            if "phone" in updates and (overwrite or not self.enriched_leads[idx].get("phone")):
                self.enriched_leads[idx]["phone"] = updates["phone"]
            self._refresh_enrich_table()
        self.enrich_progress.setValue(self.enrich_progress.value() + 1)

    def _enrich_finished(self, total):
        self.btn_enrich_start.setEnabled(True)
        self.btn_enrich_stop.setEnabled(False)
        self.enrich_progress.setVisible(False)
        self._enrich_log(f"[DONE] Enrichment finished. Updated {total} leads.")

    def _stop_enrichment(self):
        if hasattr(self, 'enrich_worker') and self.enrich_worker.isRunning():
            self.enrich_worker.stop()
            self._enrich_log("[STOP] Enrichment stopped by user.")

    def _export_enriched(self):
        if not self.enriched_leads:
            QMessageBox.information(self, "No data", "No enriched leads to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "enriched_leads.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=["website", "title", "email", "phone", "source"])
            writer.writeheader()
            for lead in self.enriched_leads:
                writer.writerow({
                    "website": lead.get("website", ""),
                    "title": lead.get("title", ""),
                    "email": lead.get("email", ""),
                    "phone": lead.get("phone", ""),
                    "source": lead.get("source", "")
                })
        QMessageBox.information(self, "Exported", f"Saved to {path}")

    # ---------------------- Results Tab ------------------------------------
    def _tab_results(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        toolbar = QHBoxLayout()
        self.results_count = QLabel("0 rows")
        toolbar.addWidget(self.results_count)
        toolbar.addStretch()
        btn_export_csv = QPushButton("Export as CSV")
        btn_export_csv.setObjectName("secondary")
        btn_export_csv.clicked.connect(self._export_csv)
        btn_export_json = QPushButton("Export as JSON")
        btn_export_json.setObjectName("secondary")
        btn_export_json.clicked.connect(self._export_json)
        toolbar.addWidget(btn_export_csv)
        toolbar.addWidget(btn_export_json)
        layout.addLayout(toolbar)

        self.results_table = QTableWidget()
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.results_table)
        return w

    def _refresh_results_table(self):
        if not self.scraped_data:
            self.results_table.setRowCount(0)
            self.results_table.setColumnCount(0)
            self.results_count.setText("0 rows")
            return
        all_keys = set()
        for item in self.scraped_data:
            all_keys.update(item.keys())
        columns = sorted(all_keys)
        if 'url' in columns:
            columns.remove('url')
            columns = ['url'] + columns
        self.results_table.setColumnCount(len(columns))
        self.results_table.setHorizontalHeaderLabels(columns)
        self.results_table.setRowCount(len(self.scraped_data))
        for row, item in enumerate(self.scraped_data):
            for col, key in enumerate(columns):
                value = item.get(key, '')
                self.results_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.results_table.resizeColumnsToContents()
        self.results_count.setText(f"{len(self.scraped_data)} rows")

    def _export_csv(self):
        if not self.scraped_data:
            QMessageBox.information(self, "No data", "Nothing to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "scraped_data.csv", "CSV (*.csv)")
        if not path:
            return
        keys = set()
        for item in self.scraped_data:
            keys.update(item.keys())
        keys = sorted(keys)
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.scraped_data)
        QMessageBox.information(self, "Export complete", f"Saved to {path}")

    def _export_json(self):
        if not self.scraped_data:
            QMessageBox.information(self, "No data", "Nothing to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save JSON", "scraped_data.json", "JSON (*.json)")
        if not path:
            return
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.scraped_data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "Export complete", f"Saved to {path}")

    # ---------------------- Settings Tab -----------------------------------
    def _tab_settings(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        g_general = QGroupBox("General Settings")
        form = QFormLayout(g_general)
        self.user_agent_edit = QLineEdit()
        self.user_agent_edit.setPlaceholderText("Custom User-Agent")
        form.addRow("User-Agent", self.user_agent_edit)
        layout.addWidget(g_general)

        g_groq = QGroupBox("Groq AI (free) - for email/phone extraction")
        groq_layout = QFormLayout(g_groq)
        self.groq_key_edit = QLineEdit()
        self.groq_key_edit.setEchoMode(QLineEdit.Password)
        self.groq_key_edit.setPlaceholderText("gsk_... from console.groq.com")
        groq_layout.addRow("API Key", self.groq_key_edit)
        expl = QLabel("Used only when 'Use Groq AI' is checked in Enrich tab. 100% free.")
        expl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        groq_layout.addRow(expl)
        layout.addWidget(g_groq)

        info = QLabel(
            "Notes:\n"
            "- Extractor: use 'requests' for static pages, Selenium for JS-heavy.\n"
            "- Web Search: uses Selenium to search Google/Bing/Yahoo.\n"
            "- Enrich Contacts: extracts emails/phones from websites using regex + Groq AI.\n"
            "- Groq API is free: sign up at console.groq.com, create an API key."
        )
        info.setStyleSheet("background: #181825; padding: 12px; border-radius: 6px; color: #a6adc8;")
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_save = QPushButton("Save Settings")
        btn_save.clicked.connect(self._save_settings)
        layout.addWidget(btn_save)
        layout.addStretch()
        return w

    def _load_config_to_ui(self):
        cfg = self.config
        self.user_agent_edit.setText(cfg.get("user_agent", ""))
        self.groq_key_edit.setText(cfg.get("groq_key", ""))

    def _save_settings(self):
        self.config["user_agent"] = self.user_agent_edit.text().strip()
        self.config["groq_key"] = self.groq_key_edit.text().strip()
        save_config(self.config)
        QMessageBox.information(self, "Settings", "Configuration saved.")

    # ---------------------- Project Load/Save -----------------------------
    def _save_project(self):
        urls = self._get_urls_from_text()
        fields = self._get_fields_from_table()
        if not urls and not fields:
            QMessageBox.warning(self, "Empty project", "No URLs or fields to save.")
            return
        project = {
            "urls": urls,
            "fields": fields,
            "use_selenium": self.use_selenium_cb.isChecked(),
            "headless": self.headless_cb.isChecked(),
            "delay": self.delay_spin.value()
        }
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", str(PROJECTS_DIR), "JSON (*.json)")
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(project, f, indent=2)
            QMessageBox.information(self, "Saved", f"Project saved to {path}")

    def _load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Project", str(PROJECTS_DIR), "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                proj = json.load(f)
            self.urls_text.setPlainText("\n".join(proj.get("urls", [])))
            fields = proj.get("fields", [])
            self.fields_table.setRowCount(0)
            for fld in fields:
                row = self.fields_table.rowCount()
                self.fields_table.insertRow(row)
                self.fields_table.setItem(row, 0, QTableWidgetItem(fld.get("name", "")))
                self.fields_table.setItem(row, 1, QTableWidgetItem(fld.get("selector", "")))
            self.use_selenium_cb.setChecked(proj.get("use_selenium", False))
            self.headless_cb.setChecked(proj.get("headless", True))
            self.delay_spin.setValue(proj.get("delay", 1))
            QMessageBox.information(self, "Loaded", f"Project loaded from {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load project: {e}")

    # ---------------------- Utility ---------------------------------------
    def _update_status(self):
        self.items_label.setText(f"Data: {len(self.scraped_data)} extracted + {len(self.search_results)} search results")

    def closeEvent(self, event):
        for worker in ['scrape_worker', 'web_search_worker', 'enrich_worker']:
            if hasattr(self, worker) and getattr(self, worker).isRunning():
                getattr(self, worker).stop()
                getattr(self, worker).wait()
        save_config(self.config)
        event.accept()

# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main():
    ensure_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#1e1e2e"))
    palette.setColor(QPalette.WindowText, QColor("#cdd6f4"))
    palette.setColor(QPalette.Base, QColor("#181825"))
    palette.setColor(QPalette.AlternateBase, QColor("#313244"))
    palette.setColor(QPalette.Text, QColor("#cdd6f4"))
    palette.setColor(QPalette.Button, QColor("#313244"))
    palette.setColor(QPalette.ButtonText, QColor("#cdd6f4"))
    palette.setColor(QPalette.Highlight, QColor("#89b4fa"))
    app.setPalette(palette)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()