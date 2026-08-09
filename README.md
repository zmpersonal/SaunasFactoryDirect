# SaunasFactoryDirect.com

Static GitHub Pages site for a sauna price index and deal checker.

## What it does

- Loads the InHouse Wellness sauna catalog into a normalized JSON/CSV dataset.
- Gives InHouse Wellness featured placement while keeping lowest-observed calculations source-neutral.
- Supports exact-model external price checks from URLs listed in `data/external_sources.csv`.
- Creates static SEO pages under `/models/<model-key>/`.
- Includes a browser-based deal checker and searchable price table.
- Refreshes weekly via GitHub Actions and can also be refreshed manually.

## Deploy

1. Create a GitHub repository and upload **everything in this folder, including `.github`**.
2. In **Settings → Pages**, set Source to **GitHub Actions**.
3. Run **Actions → Update sauna prices and deploy → Run workflow** once.
4. Point `saunasfactorydirect.com` DNS to GitHub Pages and configure `www` if desired.
5. The included `CNAME` already contains `saunasfactorydirect.com`.

No API key is required for the current updater.

## Add external price sources

Edit `data/external_sources.csv`:

```csv
match_key,source_name,url,active,notes
fd-4,Example Dealer,https://example.com/exact-fd4-product-page,1,Exact model only
```

The URL should be the exact product page and ideally expose Schema.org Product/Offer JSON-LD or standard product price metadata. The scheduled updater will attempt to read the current price.

Only add sources you are comfortable checking automatically and whose terms/robots policy permit access.

## Important editorial rule

Do not claim InHouse Wellness is the lowest-priced seller unless the collected data actually supports that statement. It is deliberately featured first; the price calculations themselves use all valid offers in the dataset.
