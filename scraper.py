import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import re
import time
from datetime import datetime, timezone

# ── Configuratie ─────────────────────────────────────────────────────────────
BASE_URL   = "https://www.energeticanatura.com"
DELAY      = 0.75   # seconden tussen requests (vriendelijk voor de server)
OUTPUT     = "energetica_natura_feed.xml"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Stap 1: URL-ontdekking via sitemap ───────────────────────────────────────

def get_urls_from_sitemap():
    """Haal alle URLs op uit sitemap.xml (ondersteunt sitemap index én directe sitemap)."""
    sitemap_url = f"{BASE_URL}/sitemap.xml"
    print(f"Sitemap ophalen: {sitemap_url}")
    urls = []

    try:
        r = requests.get(sitemap_url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"Sitemap niet bereikbaar: {e}")
        return []

    soup = BeautifulSoup(r.content, "xml")

    # Sitemap-index? → loop sub-sitemaps
    sub_sitemaps = soup.find_all("sitemap")
    if sub_sitemaps:
        print(f"Sitemap-index gevonden met {len(sub_sitemaps)} sub-sitemaps")
        for sm in sub_sitemaps:
            loc = sm.find("loc")
            if not loc:
                continue
            sm_url = loc.text.strip()
            print(f"  → Sub-sitemap: {sm_url}")
            try:
                sr = requests.get(sm_url, headers=HEADERS, timeout=30)
                sr.raise_for_status()
                sub = BeautifulSoup(sr.content, "xml")
                for tag in sub.find_all("url"):
                    loc_tag = tag.find("loc")
                    if loc_tag:
                        urls.append(loc_tag.text.strip())
            except Exception as e:
                print(f"  Sub-sitemap mislukt {sm_url}: {e}")
            time.sleep(0.5)
    else:
        # Directe sitemap
        for tag in soup.find_all("url"):
            loc_tag = tag.find("loc")
            if loc_tag:
                urls.append(loc_tag.text.strip())

    print(f"Sitemap: {len(urls)} URLs gevonden")
    return urls


def get_urls_from_categories():
    """
    Fallback als sitemap leeg is: crawl categoriepagina's.
    Drupal Commerce gebruikt doorgaans paginering via ?page=N.
    """
    print("Fallback: categoriepagina's crawlen…")
    found = set()

    # Probeer gangbare Drupal Commerce shop-paden
    start_paths = [
        "/nl-nl/shop",
        "/nl-nl/producten",
        "/nl-nl/products",
        "/nl-nl",
    ]

    for path in start_paths:
        base = BASE_URL + path
        page_num = 0
        consecutive_empty = 0

        while consecutive_empty < 2:
            url = f"{base}?page={page_num}" if page_num > 0 else base
            try:
                r = requests.get(url, headers=HEADERS, timeout=30)
                if r.status_code != 200:
                    break
                soup = BeautifulSoup(r.content, "html.parser")
                new_on_page = 0
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    # Alleen /nl-nl/ links, geen paginering zelf
                    if "/nl-nl/" in href and "?page=" not in href:
                        full = href if href.startswith("http") else BASE_URL + href
                        if full not in found:
                            found.add(full)
                            new_on_page += 1
                if new_on_page == 0:
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0
                page_num += 1
                time.sleep(DELAY)
            except Exception as e:
                print(f"  Crawl-fout {url}: {e}")
                break

    print(f"Categorie-crawl: {len(found)} URLs gevonden")
    return list(found)


# ── Stap 2: Productpagina scrapen ─────────────────────────────────────────────

def scrape_product(url):
    """
    Scrapt één URL. Retourneert dict bij succes, anders None.
    Filtert automatisch niet-productpagina's (geen price meta → None).
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.content, "html.parser")
    except Exception as e:
        print(f"  Request-fout: {e}")
        return None

    # ── Prijs (incl. BTW, geen BTW-berekening nodig) ──────────────────────
    price_tag = soup.find("meta", property="product:price:amount")
    if not price_tag:
        return None  # Geen productpagina
    price = price_tag.get("content", "").strip()

    # ── Beschikbaarheid ────────────────────────────────────────────────────
    avail_tag = soup.find("meta", property="product:availability")
    availability = avail_tag.get("content", "").strip().lower() if avail_tag else "out of stock"
    available = "true" if "in stock" in availability else "false"
    quantity  = "100"  if available == "true" else "0"

    # ── Titel ──────────────────────────────────────────────────────────────
    title_tag = soup.find("meta", property="og:title")
    title = title_tag.get("content", "").strip() if title_tag else ""

    # ── Beschrijving ───────────────────────────────────────────────────────
    desc_tag = soup.find("meta", property="og:description")
    description = desc_tag.get("content", "").strip() if desc_tag else ""

    # ── Afbeelding ─────────────────────────────────────────────────────────
    img_tag = soup.find("meta", property="og:image")
    image = img_tag.get("content", "").strip() if img_tag else ""

    # ── SKU en EAN uit "Productcodes" sectie ──────────────────────────────
    # Formaat: "SKU MG2460 / EAN 0780053009181 / CNK … / ZINDEX …"
    sku, ean = "", ""

    # Probeer eerst op samengevoegde paginatekst
    page_text = soup.get_text(" ", strip=True)
    m = re.search(r'SKU\s+([A-Z0-9]+)\s*/\s*EAN\s+(\d+)', page_text, re.IGNORECASE)
    if m:
        sku = m.group(1).upper()
        ean = m.group(2)
    else:
        # Fallback: zoek direct in raw HTML (tekst kan over tags verdeeld zijn)
        m2 = re.search(r'SKU\s+([A-Z0-9]+)\s*/\s*EAN\s+(\d+)', r.text, re.IGNORECASE)
        if m2:
            sku = m2.group(1).upper()
            ean = m2.group(2)

    if not sku:
        print(f"  ✗ Geen SKU gevonden — overgeslagen")
        return None

    return {
        "sku":         sku,
        "ean":         ean,
        "title":       title,
        "description": description,
        "price":       price,
        "available":   available,
        "quantity":    quantity,
        "image":       image,
        "url":         url,
    }


# ── Stap 3: XML genereren ─────────────────────────────────────────────────────

def build_xml(products):
    root = ET.Element("products")
    root.set("generated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    root.set("count", str(len(products)))

    for p in products:
        prod = ET.SubElement(root, "product")
        for field in ["sku", "ean", "title", "description",
                      "price", "available", "quantity", "image", "url"]:
            el = ET.SubElement(prod, field)
            el.text = p.get(field, "")

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"=== Energetica Natura Scraper — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===\n")

    # Stap 1: URLs ontdekken
    urls = get_urls_from_sitemap()
    if not urls:
        urls = get_urls_from_categories()

    if not urls:
        print("FOUT: Geen URLs gevonden. Script afgebroken.")
        raise SystemExit(1)

    print(f"\n{len(urls)} URLs te verwerken…\n")

    # Stap 2: Productpagina's scrapen
    products = []
    skipped  = 0

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        product = scrape_product(url)
        if product:
            products.append(product)
            status = "✅" if product["available"] == "true" else "❌"
            print(f"  ✓ {product['sku']} | {product['title']} | €{product['price']} {status}")
        else:
            skipped += 1
        time.sleep(DELAY)

    print(f"\n=== Resultaat: {len(products)} producten gescrapt, {skipped} overgeslagen ===\n")

    if not products:
        print("FOUT: Geen producten gevonden. Feed niet overschreven.")
        raise SystemExit(1)

    # Stap 3: XML wegschrijven
    xml_content = f'<?xml version="1.0" encoding="UTF-8"?>\n{build_xml(products)}\n'
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(xml_content)

    print(f"Feed weggeschreven: {OUTPUT} ({len(products)} producten)")


if __name__ == "__main__":
    main()
