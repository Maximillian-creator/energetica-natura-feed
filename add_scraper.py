"""
Energetica Natura ADD-feed
==========================
Volledige productinfo om met Stock Sync NIEUWE producten aan te maken. Bron: de
openbare consumentenwinkel (custom Drupal). Prijs = consumentenprijs (incl. BTW),
1-op-1 als verkoopprijs.

Voorraad zit bewust NIET als aantal in de add-feed (alleen `available`): de echte
voorraad loopt via de update-feed, zodat één bron de stand bepaalt.

Lokaal: INSECURE_SSL=1 (SSL-proxy), TEST_SLUG=<slug> om één product te draaien.
"""

import os
import time
import xml.etree.ElementTree as ET
from xml.dom import minidom
from html import escape

import energetica_common as ec

OUTPUT_FILE = "energetica_natura_add_feed.xml"

# Volgorde + labels van de losse secties in de rijke beschrijving.
SECTION_LABELS = [
    ("samenstelling", "Samenstelling"),
    ("dosering", "Dosering"),
    ("vrij_van", "Vrij van"),
]


def add(parent, tag, value):
    el = ET.SubElement(parent, tag)
    el.text = "" if value is None else str(value)
    return el


def build_description_html(p):
    """Rijke product-beschrijving (al HTML) + losse feitelijke secties."""
    parts = []
    if p.get("description"):
        parts.append(p["description"])          # is al opgemaakte HTML
    for key, label in SECTION_LABELS:
        val = p["sections"].get(key)
        if val:
            parts.append(f"<p><strong>{label}:</strong> {escape(val)}</p>")
    return "\n".join(parts)


def build_xml(products):
    root = ET.Element("products")
    for p in products:
        item = ET.SubElement(root, "product")
        add(item, "handle", p["slug"])
        add(item, "title", p["title"])
        add(item, "vendor", p["brand"])
        add(item, "sku", p["sku"])
        add(item, "barcode", p["ean"])
        add(item, "cnk", p["cnk"])
        add(item, "zindex", p["zindex"])
        add(item, "content", p["content"])          # bv. '90 capsules'
        add(item, "price", f"{p['price']:.2f}")      # incl. BTW, verkoopprijs
        add(item, "compare_at_price",
            f"{p['compare_at_price']:.2f}" if p["compare_at_price"] else "")
        add(item, "available", "true" if p["available"] else "false")
        add(item, "product_type", "Voedingssupplementen")
        add(item, "description", build_description_html(p))
        # losse secties (handig als aparte metafields)
        for key, _ in SECTION_LABELS:
            add(item, key, p["sections"].get(key, ""))
        # afbeeldingen
        images_el = ET.SubElement(item, "images")
        for src in p["images"]:
            img = ET.SubElement(images_el, "image")
            img.text = src
        add(item, "image_links", ",".join(p["images"]))
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
    print("🚀 Energetica Natura ADD-feed gestart\n")
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
    out = "energetica_natura_add_feed_TEST.xml" if test_slug else OUTPUT_FILE
    save_xml(build_xml(products), out)

    print(f"⏱️  Klaar in {time.time() - start:.0f}s — {len(products)} producten")
    print("\n📋 Feed-URL voor Stock Sync (Add products):")
    print("https://raw.githubusercontent.com/Maximillian-creator/energetica-natura-feed/main/energetica_natura_add_feed.xml")


if __name__ == "__main__":
    main()
