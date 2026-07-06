"""
Energetica Natura — gedeelde scraper-kern
=========================================
Bron: de OPENBARE consumentenwinkel op energeticanatura.com (custom Drupal,
geen products.json). Prijzen zijn publiek zichtbaar zonder login.

Afgesproken prijslogica: de publieke consumentenprijs (incl. BTW) wordt 1-op-1
onze verkoopprijs. Geen login, geen BTW-berekening, geen marge — de winkel toont
de eindprijs al.

Enumeratie: de categorielijst /nl-nl/producten pagineert (?page=0,1,2,…). We
verzamelen alle /nl-nl/producten/<slug> links tot een pagina niets nieuws geeft.
De echte productcheck gebeurt bij het scrapen (heeft de pagina een prijs-meta?).

Per productpagina plukken we uit stabiele ankers:
  - <meta property="product:price:amount">      → prijs (incl. BTW)
  - <meta property="product:availability">      → in stock / out of stock
  - insider-product-data="{…}"                  → SKU + unit_price + unit_sale_price
  - #product-additional-info                    → SKU / EAN / CNK / ZINDEX
  - og:title / og:image / product-detail__brand → titel / afbeelding / merk
  - .stock-availability is-high|is-medium|is-low → voorraadniveau (heuristiek)
  - product-detail__section blokken (<h2> + body) → samenstelling/dosering/…

Lokaal achter een SSL-onderscheppende proxy: zet INSECURE_SSL=1.
Eén product testen: TEST_SLUG=<slug>.
"""

import os
import re
import time
import json
from html import unescape

import requests

BASE = "https://www.energeticanatura.com"
LOCALE = "/nl-nl"
LISTING = f"{BASE}{LOCALE}/producten"
PRODUCT_PREFIX = f"{LOCALE}/producten/"
REQUEST_DELAY = 0.6

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GoodForYouFeedBot/1.0; +https://goodforyouonline.nl)",
    "Accept-Language": "nl-NL,nl;q=0.9",
}

VERIFY_SSL = os.environ.get("INSECURE_SSL") != "1"
if not VERIFY_SSL:
    import urllib3
    urllib3.disable_warnings()

# Voorraadniveau (class op de pagina) → indicatieve hoeveelheid voor Stock Sync.
# Energetica toont géén exact aantal, alleen een niveau; dit is bewust grof.
STOCK_LEVELS = {
    "is-high": 100,
    "is-medium": 25,
    "is-low": 5,
    "is-out": 0,
    "is-none": 0,
}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = VERIFY_SSL
    return s


def fetch(session, url, retries=3, allow_404=False):
    """GET met retry. Bij 404 (en allow_404) → None zonder herhalen."""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 404 and allow_404:
                return None
            r.raise_for_status()
            return r
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 404 and allow_404:
                return None
            if attempt < retries - 1:
                wait = (attempt + 1) * 20
                print(f"    ⚠️  Fout ({e}) bij {url} — opnieuw in {wait}s...")
                time.sleep(wait)
            else:
                print(f"    ❌ Mislukt na {retries} pogingen: {url} ({e})")
                return None


# --------------------------------------------------------------------------- #
# Enumeratie via de categorielijst
# --------------------------------------------------------------------------- #
def iter_product_slugs(session=None, max_pages=25):
    """
    Alle product-slugs uit /nl-nl/producten?page=0,1,2,… Stopt zodra een pagina
    geen nieuwe slugs oplevert. Dedupe met behoud van volgorde. (Content-pagina's
    komen hier niet voor; de prijs-check bij het scrapen filtert eventuele rest.)
    """
    session = session or make_session()
    slugs = []
    seen = set()
    for page in range(max_pages):
        r = fetch(session, f"{LISTING}?page={page}")
        if not r:
            break
        found = re.findall(r'/nl-nl/producten/([a-z0-9][a-z0-9\-]*)"', r.text)
        new = [s for s in found if s not in seen]
        if not new:
            break
        for s in new:
            seen.add(s)
            slugs.append(s)
        print(f"  pagina {page}: +{len(new)} (totaal {len(slugs)})")
        time.sleep(REQUEST_DELAY)
    return slugs


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _meta(html, prop):
    m = re.search(
        rf'<meta property="{re.escape(prop)}"[^>]*content="([^"]*)"', html
    )
    if not m:
        m = re.search(
            rf'<meta content="([^"]*)"[^>]*property="{re.escape(prop)}"', html
        )
    return unescape(m.group(1)).strip() if m else None


def clean_text(fragment):
    if not fragment:
        return ""
    t = re.sub(r"<[^>]+>", " ", fragment)
    t = unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _insider(html):
    """De insider-product-data JSON (SKU + unit_price + unit_sale_price)."""
    m = re.search(r'insider-product-data="([^"]+)"', html)
    if not m:
        return {}
    try:
        return json.loads(unescape(m.group(1)))
    except Exception:
        return {}


def _codes(html):
    """SKU / EAN / CNK / ZINDEX uit het #product-additional-info blok."""
    block = re.search(
        r'id="product-additional-info">(.*?)</div>', html, re.DOTALL
    )
    text = clean_text(block.group(1)) if block else ""
    def grab(label):
        m = re.search(rf'{label}\s+([A-Za-z0-9]+)', text)
        return m.group(1) if m else ""
    return {
        "sku": grab("SKU"),
        "ean": grab("EAN"),
        "cnk": grab("CNK"),
        "zindex": grab("ZINDEX"),
    }


def _brand(html):
    """Merk uit .product-detail__brand, met de <title> als terugval."""
    m = re.search(r'product-detail__brand"[^>]*>\s*<a[^>]*>([^<]+)</a>', html)
    if m:
        return unescape(m.group(1)).strip()
    # <title>Naam | Merk | Energetica Natura</title>
    t = re.search(r"<title>([^<]+)</title>", html)
    if t:
        parts = [p.strip() for p in t.group(1).split("|")]
        if len(parts) >= 3:
            return parts[1]
    return "Energetica Natura"


def _stock(html):
    """Voorraad-heuristiek uit de .stock-availability class + availability-meta."""
    level = ""
    m = re.search(r'stock-availability\s+(is-[a-z]+)', html)
    if m:
        level = m.group(1)
    avail_meta = (_meta(html, "product:availability") or "").lower()
    available = "in stock" in avail_meta or level in ("is-high", "is-medium", "is-low")
    quantity = STOCK_LEVELS.get(level, 100 if available else 0)
    return {"available": available, "quantity": quantity, "stock_level": level}


def _images(html, insider):
    """Productafbeeldingen (product-attachments), gededupliceerd op UUID."""
    urls = []
    seen = set()
    main = insider.get("product_image_url")
    if main:
        urls.append(main)
        seen.add(_img_key(main))
    for u in re.findall(
        r'https://www\.energeticanatura\.com/sites/default/files/[^"\']*?product-attachments/[^"\']+?\.(?:jpg|jpeg|png|webp)',
        html,
    ):
        # Voorkeur voor het volledige formaat; sla thumbnails over
        if "product_thumb" in u:
            continue
        key = _img_key(u)
        if key in seen:
            continue
        seen.add(key)
        urls.append(u)
    return urls


def _img_key(url):
    """Basis-UUID van een afbeelding (zonder style-map) om dubbels te vinden."""
    m = re.search(r'product-attachments/([0-9a-f\-]+~\d+)', url)
    return m.group(1) if m else url


# Named secties (h2-kop → body) die we als losse velden willen.
SECTION_IDS = {
    "product-composition": "samenstelling",
    "product-instructions": "dosering",
    "product-usage": "dosering",
}


def _sections(html):
    """
    Rijke secties. Combineert:
      - dosering    : .field-name-instructions (Standaarddosering)
      - vrij_van    : .field--name-field-info-free-of (allergenen/vrij van)
      - samenstelling / overige named product-detail__section blokken
    """
    out = {}

    m = re.search(
        r'field-name-instructions.*?<div class="product-detail__instructions__text">(.*?)</div>\s*</div>',
        html, re.DOTALL,
    )
    if m:
        out["dosering"] = clean_text(m.group(1))

    m = re.search(
        r'field--name-field-info-free-of[^>]*>(.*?)</div>', html, re.DOTALL
    )
    if m:
        out["vrij_van"] = clean_text(m.group(1))

    # Named secties met een <h2>-kop en body
    for sec in re.finditer(
        r'<div id="(product-[a-z\-]+)"[^>]*class="[^"]*product-detail__section[^"]*">(.*?)(?=<div id="product-|<div id="product-additional-info)',
        html, re.DOTALL,
    ):
        sec_id, body = sec.group(1), sec.group(2)
        key = SECTION_IDS.get(sec_id)
        if not key or key in out:
            continue
        # kop weghalen, rest als tekst
        body_wo_head = re.sub(r'<h2[^>]*>.*?</h2>', ' ', body, flags=re.DOTALL)
        txt = clean_text(body_wo_head)
        # De samenstelling-sectie bevat ook de 'vrij van'- en downloads-blokken;
        # knip die af zodat 'samenstelling' alleen de ingrediënten bevat.
        for marker in ("Dit product is vrij van", "Downloads"):
            idx = txt.find(marker)
            if idx > 0:
                txt = txt[:idx].strip()
        if txt and len(txt) > 2:
            out[key] = txt

    return out


def _description_html(html):
    """
    De volledige rijke beschrijving uit de 'product-description'-sectie (kopjes,
    alinea's, opsommingen, vet) — veel completer dan de korte og:description-meta.
    Behoudt een whitelist van basis-tags en strip de rest.
    """
    m = re.search(
        r'<div id="product-description"[^>]*class="[^"]*product-detail__section[^"]*">(.*?)'
        r'(?=<div id="product-usage"|<div id="product-composition"|<div id="product-info")',
        html, re.DOTALL,
    )
    if not m:
        return ""
    b = m.group(1)
    b = re.sub(r"<h2[^>]*>.*?</h2>", "", b, flags=re.DOTALL)            # sectiekop weg
    b = re.sub(r"<(script|style|figure|svg|button|a)[^>]*>.*?</\1>", "", b, flags=re.DOTALL | re.I)
    b = re.sub(r"<img[^>]*>", "", b, flags=re.I)
    keep = {"p", "ul", "ol", "li", "strong", "b", "em", "h3", "h4", "br"}

    def _tag(mo):
        slash = "/" if mo.group(1) else ""
        tag = mo.group(2).lower()
        return f"<{slash}{tag}>" if tag in keep else ""

    b = re.sub(r"<(/?)(\w+)[^>]*>", _tag, b)
    b = b.replace("&nbsp;", " ")
    b = re.sub(r"[ \t]+", " ", b)
    b = re.sub(r"\s*\n\s*", "", b)
    b = re.sub(r"<p>\s*</p>", "", b)
    b = re.sub(r"(<br>\s*){2,}", "<br>", b)
    return b.strip()


def _content(name):
    """Inhoud/verpakking uit de insider-naam: 'Titel - 90 capsules' → '90 capsules'."""
    if name and " - " in name:
        return name.rsplit(" - ", 1)[-1].strip()
    return ""


def parse_product(html, slug):
    """
    Zet een productpagina om naar een dict. Geeft None terug als het geen
    (koopbaar) product is: geen prijs-meta én geen insider-prijs.
    """
    price_meta = _meta(html, "product:price:amount")
    insider = _insider(html)

    price = None
    if price_meta:
        try:
            price = round(float(price_meta), 2)
        except ValueError:
            price = None
    if price is None and insider.get("unit_price") is not None:
        price = round(float(insider["unit_price"]), 2)

    if price is None:
        return None  # geen product

    # Actieprijs: als unit_sale_price lager is dan unit_price → korting actief.
    compare_at = None
    up, usp = insider.get("unit_price"), insider.get("unit_sale_price")
    if up is not None and usp is not None and float(usp) < float(up):
        price = round(float(usp), 2)
        compare_at = round(float(up), 2)

    codes = _codes(html)
    sku = codes["sku"] or insider.get("id") or ""
    stock = _stock(html)

    return {
        "slug": slug,
        "url": f"{BASE}{PRODUCT_PREFIX}{slug}",
        "title": _meta(html, "og:title") or (insider.get("name") or "").split(" - ")[0],
        "brand": _brand(html),
        "sku": sku,
        "ean": codes["ean"],
        "cnk": codes["cnk"],
        "zindex": codes["zindex"],
        "content": _content(insider.get("name")),
        "price": price,
        "compare_at_price": compare_at,
        "available": stock["available"],
        "quantity": stock["quantity"],
        "stock_level": stock["stock_level"],
        "image": _meta(html, "og:image") or insider.get("product_image_url") or "",
        "images": _images(html, insider),
        "description": _description_html(html) or _meta(html, "og:description") or "",
        "sections": _sections(html),
    }


def scrape_products(session, slugs, full=True):
    """
    Scrape elke slug. `full=False` (update-feed) doet niets anders qua ophalen,
    maar de aanroeper gebruikt dan alleen prijs/voorraad-velden.
    Slaat pagina's over die geen product blijken (geen prijs).
    """
    total = len(slugs)
    skipped = 0
    for i, slug in enumerate(slugs, 1):
        r = fetch(session, f"{BASE}{PRODUCT_PREFIX}{slug}", allow_404=True)
        if not r:
            skipped += 1
            continue
        prod = parse_product(r.text, slug)
        if not prod:
            skipped += 1
            time.sleep(REQUEST_DELAY)
            continue
        sale = f" (was €{prod['compare_at_price']})" if prod["compare_at_price"] else ""
        print(f"  [{i}/{total}] {prod['title'][:44]:44} €{prod['price']}{sale} "
              f"[{prod['stock_level'] or 'n/a'}] {prod['sku']}")
        yield prod
        time.sleep(REQUEST_DELAY)
    print(f"\nℹ️  {total - skipped} producten in de feed | {skipped} overgeslagen (geen product/404).")
