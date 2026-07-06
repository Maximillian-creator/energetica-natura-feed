"""
Energetica Natura UPDATE-feed
=============================
Prijs + voorraad van BESTAANDE producten bijwerken. Match in Stock Sync op SKU
(of EAN). Bron: de openbare consumentenwinkel (prijs = incl. BTW, 1-op-1).

Lokaal: INSECURE_SSL=1 (SSL-proxy), TEST_SLUG=<slug> om één product te draaien.
"""

import os
import time
import xml.etree.ElementTree as ET
from xml.dom import minidom

import energetica_common as ec

OUTPUT_FILE = "energetica_natura_feed.xml"


def add(parent, tag, value):
    el = ET.SubElement(parent, tag)
    el.text = "" if value is None else str(value)
    return el


def build_xml(products):
    root = ET.Element("products")
    for p in products:
        item = ET.SubElement(root, "product")
        add(item, "sku", p["sku"])
        add(item, "barcode", p["ean"])
        add(item, "title", p["title"])
        add(item, "price", f"{p['price']:.2f}")            # incl. BTW, verkoopprijs
        add(item, "compare_at_price",
            f"{p['compare_at_price']:.2f}" if p["compare_at_price"] else "")
        add(item, "available", "true" if p["available"] else "false")
        add(item, "quantity", p["quantity"])
        add(item, "handle", p["slug"])
        add(item, "image", p["image"])
    return root


def save_xml(root, filepath):
    xml_str = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(xml_str).toprettyxml(indent="  ")
    lines = pretty.split("\n")
    if lines[0].startswith("<?xml"):
        lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n💾 XML opgeslagen: {filepath}")


def main():
    print("🚀 Energetica Natura UPDATE-feed gestart\n")
    start = time.time()

    session = ec.make_session()
    test_slug = os.environ.get("TEST_SLUG")
    if test_slug:
        slugs = [test_slug]
    else:
        print("📦 Producten enumereren...")
        slugs = ec.iter_product_slugs(session)
    print(f"\n📦 {len(slugs)} slug(s) te verwerken\n")

    products = list(ec.scrape_products(session, slugs))
    out = "energetica_natura_feed_TEST.xml" if test_slug else OUTPUT_FILE
    save_xml(build_xml(products), out)

    print(f"⏱️  Klaar in {time.time() - start:.0f}s — {len(products)} producten")
    print("\n📋 Feed-URL voor Stock Sync (Update):")
    print("https://raw.githubusercontent.com/Maximillian-creator/energetica-natura-feed/main/energetica_natura_feed.xml")


if __name__ == "__main__":
    main()
