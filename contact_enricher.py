#!/usr/bin/env python3
"""
contact_enricher.py — Extrai e-mails e telefones dos sites dos leads.

Estratégia em 3 camadas:
  1. Regex direto no HTML (rápido, sem custo)
  2. Visita páginas internas: /contato, /contact, /sobre, /fale-conosco
  3. Groq AI analisa o texto da página quando regex não acha nada
     (usa apenas texto visível, sem enviar HTML bruto — economiza tokens)
     API gratuita: console.groq.com → API Keys
"""

import re
import time
import json
import random
import logging
import requests
from datetime import datetime
from urllib.parse import urljoin, urlparse

from PyQt5.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────────────────────

# Email — evita falsos positivos como "example@domain" em código
_EMAIL_RE = re.compile(
    r'\b[a-zA-Z0-9._%+\-]{2,}@[a-zA-Z0-9.\-]{2,}\.[a-zA-Z]{2,}\b'
)

# Telefones brasileiros: (11) 99999-9999 / 11 9 9999-9999 / +55 11 99999999 / etc.
_PHONE_RE = re.compile(
    r'(?:\+55\s?)?'                        # opcional +55
    r'(?:\(?\d{2}\)?\s?)'                  # DDD
    r'(?:9\s?)?'                           # opcional 9 de celular
    r'\d{4}[\s.\-]?\d{4}'                 # número
)

# Domínios a ignorar nos emails (falsos positivos comuns)
_SKIP_EMAIL_DOMAINS = {
    'example.com', 'seusite.com', 'empresa.com', 'dominio.com',
    'email.com', 'seuemail.com', 'suaempresa.com',
    'wixpress.com', 'squarespace.com', 'wordpress.com',
    'sentry.io', 'cloudflare.com', 'google.com',
}

# Páginas de contato comuns para visitar
_CONTACT_PATHS = [
    '/contato', '/contact', '/fale-conosco', '/fale-com-a-gente',
    '/sobre', '/about', '/quem-somos', '/nos', '/onde-estamos',
    '/atendimento', '/suporte', '/ajuda',
]


def _clean_emails(raw: list[str]) -> list[str]:
    """Filter out obvious false positives."""
    out = []
    seen = set()
    for e in raw:
        e = e.lower().strip()
        domain = e.split('@')[-1] if '@' in e else ''
        if domain in _SKIP_EMAIL_DOMAINS:
            continue
        if e in seen:
            continue
        # Skip image/file extensions mistaken as emails
        if re.search(r'\.(png|jpg|jpeg|gif|svg|webp|js|css|woff)$', e):
            continue
        seen.add(e)
        out.append(e)
    return out


def _clean_phones(raw: list[str]) -> list[str]:
    """Deduplicate and normalise phone numbers."""
    seen = set()
    out = []
    for p in raw:
        # Keep only digits for dedup key
        digits = re.sub(r'\D', '', p)
        if len(digits) < 8 or digits in seen:
            continue
        seen.add(digits)
        out.append(p.strip())
    return out


def _extract_from_html(html: str) -> tuple[list[str], list[str]]:
    """Run regex directly on raw HTML."""
    emails = _clean_emails(_EMAIL_RE.findall(html))
    phones = _clean_phones(_PHONE_RE.findall(html))
    return emails, phones


def _visible_text(html: str, max_chars: int = 4000) -> str:
    """Strip HTML tags and return visible text (no BeautifulSoup needed)."""
    # Remove scripts and styles
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


# ── Groq AI extractor ─────────────────────────────────────────────────────────

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"   # gratuito, rápido e muito capaz

_AI_SYSTEM = (
    "Você é um extrator de dados. Analise o texto de uma página web de empresa "
    "e extraia APENAS e-mails e telefones reais de contato. "
    "Responda SOMENTE em JSON, sem texto extra, no formato: "
    '{"emails": ["..."], "phones": ["..."]}'
    "\nSe não encontrar nada, retorne {\"emails\": [], \"phones\": []}."
    "\nNão invente dados. Ignore e-mails de exemplo ou placeholder."
)


def _ask_groq(page_text: str, groq_key: str) -> tuple[list[str], list[str]]:
    """Send visible page text to Groq (Llama) and get structured contacts back.
    
    API gratuita em: console.groq.com → API Keys
    Limites generosos: ~14.400 req/dia no plano free.
    """
    if not groq_key or not page_text.strip():
        return [], []

    prompt = (
        f"Extraia e-mails e telefones de contato desta página:\n\n{page_text[:3500]}"
    )
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": 300,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _AI_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type":  "application/json",
    }
    try:
        resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if present
        raw = re.sub(r'^```json\s*|```$', '', raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
        emails = _clean_emails(data.get("emails", []))
        phones = _clean_phones(data.get("phones", []))
        return emails, phones
    except Exception as e:
        logger.debug(f"Groq API erro: {e}")
        return [], []


# ── HTTP-only fetcher (fast, no Selenium overhead) ────────────────────────────

_SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _fetch_url(session: requests.Session, url: str, timeout: int = 12) -> str | None:
    """GET a URL and return HTML text, or None on failure."""
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and 'text/html' in resp.headers.get('Content-Type', ''):
            return resp.text
    except Exception:
        pass
    return None


# ── Main Worker ───────────────────────────────────────────────────────────────

class ContactEnricherWorker(QThread):
    """
    For each lead that has a website but is missing email/phone,
    visits the site and tries to extract contacts.

    Signals:
        enriched(int, dict)  — lead index + updated fields {"email": ..., "phone": ...}
        progress(str)        — log messages
        finished(int)        — number of leads enriched
    """
    enriched = pyqtSignal(int, dict)
    progress = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, leads: list, groq_key: str = "", parent=None):
        """
        leads     — full leads list (will filter to those needing enrichment)
        groq_key  — optional Groq API key for AI fallback (gratuito: console.groq.com)
        """
        super().__init__(parent)
        self.leads    = leads
        self.groq_key = groq_key
        self._running = True
        self._session = requests.Session()
        self._session.headers.update(_SESSION_HEADERS)

    def stop(self):
        self._running = False

    # ── Thread ───────────────────────────────────────────────────────────────

    def run(self):
        total = 0
        targets = [
            (i, lead) for i, lead in enumerate(self.leads)
            if lead.get("website")
            and not (lead.get("email") and lead.get("phone"))
        ]
        self.progress.emit(
            f"🔎 Enriquecimento: {len(targets)} leads com site mas sem contato completo"
        )

        for i, (lead_idx, lead) in enumerate(targets):
            if not self._running:
                break

            name    = lead.get("name", "?")
            website = lead.get("website", "").strip()
            if not website.startswith("http"):
                website = "https://" + website

            self.progress.emit(
                f"[{i+1}/{len(targets)}] 🌐 {name} — {website}"
            )

            emails, phones = self._enrich_lead(website, lead)

            if emails or phones:
                updates = {}
                if emails and not lead.get("email"):
                    updates["email"] = emails[0]
                if phones and not lead.get("phone"):
                    updates["phone"] = phones[0]
                if updates:
                    self.enriched.emit(lead_idx, updates)
                    total += 1
                    found_str = " | ".join(
                        [f"✉️ {e}" for e in emails[:2]] +
                        [f"📞 {p}" for p in phones[:2]]
                    )
                    self.progress.emit(f"  ✅ Encontrado: {found_str}")
            else:
                self.progress.emit(f"  — Sem contatos encontrados")

            # Polite delay between sites
            time.sleep(random.uniform(1.5, 3.5))

        self.finished.emit(total)

    # ── Enrichment logic ──────────────────────────────────────────────────────

    def _enrich_lead(self, website: str, lead: dict) -> tuple[list, list]:
        """
        3-layer extraction:
          1. Regex on homepage HTML
          2. Regex on common contact sub-pages
          3. Groq AI (Llama) on visible text (if key provided and still no results)
        """
        all_emails: list[str] = []
        all_phones: list[str] = []

        # Already has what we need?
        if lead.get("email"):
            all_emails = [lead["email"]]
        if lead.get("phone"):
            all_phones = [lead["phone"]]

        # ── Layer 1: homepage ────────────────────────────────────────────────
        html = _fetch_url(self._session, website)
        if html:
            e, p = _extract_from_html(html)
            all_emails += [x for x in e if x not in all_emails]
            all_phones += [x for x in p if x not in all_phones]

        # ── Layer 2: contact sub-pages (only if still missing data) ──────────
        if not all_emails or not all_phones:
            base = f"{urlparse(website).scheme}://{urlparse(website).netloc}"
            for path in _CONTACT_PATHS:
                if not self._running:
                    break
                if all_emails and all_phones:
                    break  # got everything
                sub_html = _fetch_url(self._session, base + path)
                if sub_html:
                    e, p = _extract_from_html(sub_html)
                    all_emails += [x for x in e if x not in all_emails]
                    all_phones += [x for x in p if x not in all_phones]
                    if e or p:
                        self.progress.emit(f"    📄 Achado em {path}")
                    time.sleep(random.uniform(0.5, 1.2))

        # ── Layer 3: Groq AI fallback (gratuito) ─────────────────────────────
        if self.groq_key and (not all_emails or not all_phones) and html:
            self.progress.emit("    🤖 Sem resultado no regex — usando Groq AI (Llama)...")
            text = _visible_text(html)
            ai_emails, ai_phones = _ask_groq(text, self.groq_key)
            all_emails += [x for x in ai_emails if x not in all_emails]
            all_phones += [x for x in ai_phones if x not in all_phones]

            # Also try contact page text with AI if still missing
            if (not all_emails or not all_phones):
                base = f"{urlparse(website).scheme}://{urlparse(website).netloc}"
                for path in ['/contato', '/contact', '/fale-conosco']:
                    sub_html = _fetch_url(self._session, base + path)
                    if sub_html:
                        text = _visible_text(sub_html)
                        ai_e, ai_p = _ask_groq(text, self.groq_key)
                        all_emails += [x for x in ai_e if x not in all_emails]
                        all_phones += [x for x in ai_p if x not in all_phones]
                        if ai_e or ai_p:
                            break

        return _clean_emails(all_emails), _clean_phones(all_phones)