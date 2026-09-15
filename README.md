# SaunasFactoryDirect.com

Static GitHub Pages site for a sauna price index and deal checker.

## Purchase-link structure
- Homepage, Deal Checker, featured picks and model pages link to internal pages under `/suppliers/`.
- Each supplier profile contains one external link to that supplier.
- When InHouse Wellness carries an exact model, it is the only displayed place-to-buy option for that model.
- Supplier pages are regenerated with model pages during every scheduled price update.

## Data sources
- InHouse Wellness is the featured retailer where it carries a model.
- `data/external_sources.csv` adds exact-model competing seller offers to existing models.
- `data/external_products.csv` seeds researched models from additional sauna brands.
- `scripts/update_prices.py` refreshes data, model pages, `data/prices.csv`, `data/products.json`, and `sitemap.xml`.
- Plunge and Heavenly Heat are included as complementary manufacturer-direct catalogs that do not overlap the current InHouse Wellness sauna brands.

## External exact-model source format
```csv
match_key,source_name,url,active,notes,fallback_price,verified_date,availability
fd-4,Example Dealer,https://example.com/product,1,Exact model only,6999,2026-08-12,listed
```

## Deploy / refresh
1. In Settings → Pages, Source should remain GitHub Actions.
2. After changing files, go to Actions → Update sauna prices and deploy.
3. Click Run workflow, choose `main`, then Run workflow.
4. A successful run refreshes generated data/model pages, commits them, and deploys the site.

No API key is required.
