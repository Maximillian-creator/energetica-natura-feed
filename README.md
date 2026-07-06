# Energetica Natura feeds → Stock Sync

Scrapt de **openbare consumentenwinkel** van [Energetica Natura](https://www.energeticanatura.com/nl-nl)
(custom Drupal, géén `products.json`) en genereert twee XML-feeds voor
[Stock Sync](https://stock-sync.com). Beide draaien automatisch via GitHub Actions.

| Feed | Script | Output | Doel | Schema |
|---|---|---|---|---|
| **Update-feed** | `scraper.py` | `energetica_natura_feed.xml` | Prijs + voorraad van **bestaande** producten | 2× per dag (06:00 + 18:00 UTC) |
| **Add-feed** | `add_scraper.py` | `energetica_natura_add_feed.xml` | **Nieuwe** producten aanmaken met álle info | 1× per week (ma 04:00 UTC) |

De scraper-kern zit in **`energetica_common.py`** (enumeratie + parsing); beide
scripts bouwen daar hun XML omheen.

## Feed-URL's (Stock Sync)

```
Update:  https://raw.githubusercontent.com/Maximillian-creator/energetica-natura-feed/main/energetica_natura_feed.xml
Add:     https://raw.githubusercontent.com/Maximillian-creator/energetica-natura-feed/main/energetica_natura_add_feed.xml
```

## Prijslogica

De publieke **consumentenprijs (incl. BTW)** wordt **1-op-1** onze verkoopprijs.
Geen login, geen BTW-berekening, geen marge — de winkel toont de eindprijs al.

> Stel in Stock Sync dus **géén** extra BTW-opslag of marge in: `price` is de
> definitieve verkoopprijs. Is er een actie actief, dan staat de oude prijs in
> `compare_at_price` en de actieprijs in `price`.

## Waar de data vandaan komt

Enumeratie via de categorielijst `/nl-nl/producten?page=0,1,2,…` (stopt zodra een
pagina niets nieuws geeft; ~210 links, non-producten worden bij het scrapen
afgevangen). Per productpagina uit stabiele ankers:

- `<meta property="product:price:amount">` → prijs (incl. BTW)
- `<meta property="product:availability">` + `.stock-availability is-high|is-medium|is-low` → voorraad
- `insider-product-data="{…}"` → SKU + `unit_price` + `unit_sale_price` (actie)
- `#product-additional-info` → SKU / EAN / CNK / ZINDEX
- `og:title` / `og:image` / `.product-detail__brand` → titel / afbeelding / merk
- `.product-detail__section` blokken → samenstelling, dosering, "vrij van"

## Voorraad (belangrijk)

Energetica toont **geen exact aantal**, alleen een niveau. De update-feed vertaalt
dat grof naar een hoeveelheid: `is-high → 100`, `is-medium → 25`, `is-low → 5`,
anders `0`. `available` is `true` zolang het product op voorraad is. Map in Stock
Sync bij voorkeur op **`available`**; gebruik `quantity` alleen als indicatie.

## Velden in de add-feed

Per `<product>`: `handle, title, vendor, sku, barcode, cnk, zindex, content,
price, compare_at_price, available, product_type, description`, losse secties
(`samenstelling`, `dosering`, `vrij_van`), een `<images>`-blok en `image_links`
(komma-gescheiden).

## Stock Sync mapping

- **Add products** → feed-URL: `…/energetica_natura_add_feed.xml`. Record-pad
  `/products/product`. Map o.a. `sku` (identifier), `title`, `description`,
  `vendor`, `barcode`, `price`, `image_links` (scheidingsteken = komma).
  Zet de koppeling op **alleen nieuwe producten aanmaken**; map géén voorraad.
- **Update** → feed-URL: `…/energetica_natura_feed.xml`. Match op `sku` (of `barcode`);
  map `price`, `compare_at_price`, `available`/`quantity`.

## Lokaal draaien / testen

```bash
pip install -r requirements.txt
python scraper.py                          # volledige update-feed
python add_scraper.py                      # volledige add-feed
TEST_SLUG=acetyl-l-carnitine python add_scraper.py   # één product testen
INSECURE_SSL=1 python add_scraper.py       # achter een SSL-onderscheppende proxy
```

`INSECURE_SSL` is alleen voor lokaal testen achter een bedrijfsproxy; in GitHub
Actions staat dit uit en wordt het certificaat netjes geverifieerd.
