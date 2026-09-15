#!/usr/bin/env python3
import csv, json, re, sys, time, html
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'products.json'
EXTERNAL=ROOT/'data'/'external_sources.csv'
EXTERNAL_PRODUCTS=ROOT/'data'/'external_products.csv'
BASE='https://inhousewellness.com'
UA='SaunasFactoryDirectPriceBot/1.1 (+https://saunasfactorydirect.com/methodology/)'

STATIC_URLS=[
    'https://saunasfactorydirect.com/',
    'https://saunasfactorydirect.com/about/',
    'https://saunasfactorydirect.com/editorial-policy/',
    'https://saunasfactorydirect.com/disclosure/',
    'https://saunasfactorydirect.com/disclaimer/',
    'https://saunasfactorydirect.com/privacy/',
    'https://saunasfactorydirect.com/terms/',
    'https://saunasfactorydirect.com/methodology/',
    'https://saunasfactorydirect.com/suppliers/',
]

SUPPLIER_LANDING={
    'InHouse Wellness':'https://inhousewellness.com/collections/saunas',
    'Plunge':'https://plunge.com/pages/product-lineup-hot',
    'Heavenly Heat Saunas':'https://heavenlyheatsaunas.com/',
}

SUPPLIER_SUMMARIES={
    'Almost Heaven':'Manufacturer-direct listings for traditional barrel, canopy and cabin saunas.',
    'Golden Design Saunas':'Retail listings for selected Golden Designs and Dynamic sauna models.',
    'Golden Designs Inc':'Manufacturer listings for selected Golden Designs and Dynamic sauna models.',
    'Green Vista Living':'Retail listings for selected home sauna models in the price index.',
    'Health Mate':'Manufacturer-direct listings for indoor infrared sauna cabins.',
    'Heavenly Heat Saunas':'Manufacturer-direct listings for infrared, red-light, traditional and combination sauna cabins.',
    'Northern Saunas':'Retail listings for premium indoor and outdoor sauna cabins from several manufacturers.',
    'Peak Saunas':'Manufacturer-direct listings for indoor and outdoor full-spectrum infrared saunas.',
    'Plunge':'Manufacturer-direct listings for traditional and infrared home saunas.',
    'Redwood Outdoors':'Manufacturer-direct listings for indoor, outdoor, barrel and cabin saunas.',
    'Sun Home':'Manufacturer-direct listings for indoor and outdoor infrared sauna cabins.',
}

try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    requests=None; BeautifulSoup=None

def slug(s):
    s=(s or '').lower().replace('‑','-').replace('–','-').replace('—','-')
    s=re.sub(r'[^a-z0-9]+','-',s).strip('-')
    return s[:90] or 'sauna'

def supplier_key(source):
    return slug(source or 'supplier')

def display_offers(p):
    """Return only offers that may be presented as places to buy.

    InHouse Wellness is the exclusive displayed seller whenever it carries an
    exact model. Other observed offers may remain in the source data for the
    updater, but they are not rendered as alternate purchase paths.
    """
    offers=[o for o in p.get('offers',[]) if fnum(o.get('price'))>0]
    inhouse=next((o for o in offers if o.get('source')=='InHouse Wellness'),None)
    if inhouse:return [inhouse]
    by_source={}
    for offer in offers:
        source=offer.get('source') or 'Supplier'
        if source not in by_source or fnum(offer.get('price'))<fnum(by_source[source].get('price')):
            by_source[source]=offer
    return sorted(by_source.values(),key=lambda o:fnum(o.get('price')) or 10**12)

def supplier_path(source):
    return f'/suppliers/{supplier_key(source)}/'

def supplier_landing(source,offers):
    if source in SUPPLIER_LANDING:return SUPPLIER_LANDING[source]
    for offer in offers:
        parts=urlsplit(str(offer.get('url') or ''))
        if parts.scheme in ('http','https') and parts.netloc:
            return f'{parts.scheme}://{parts.netloc}/'
    return '#'

def site_header():
    return '''<header class="site-header"><div class="wrap nav"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true">$</span><span>Saunas Factory Direct</span></a><nav class="nav-links" aria-label="Primary navigation"><a href="/#price-index">Price index</a><a href="/#deal-checker">Deal checker</a><a href="/suppliers/">Suppliers</a><a href="/methodology/">Methodology</a></nav></div></header>'''

def site_footer():
    return '''<footer><div class="wrap footer-grid"><div class="footer-intro"><a class="brand footer-brand" href="/"><span class="brand-mark" aria-hidden="true">$</span><span>Saunas Factory Direct</span></a><p class="tiny">A home sauna pricing reference. Prices and availability change; verify final specifications, delivery costs and seller terms before purchasing.</p></div><div class="footer-links"><div><strong>Research</strong><a href="/#price-index">Price index</a><a href="/#deal-checker">Deal checker</a><a href="/suppliers/">Supplier directory</a><a href="/methodology/">Methodology</a></div><div><strong>About</strong><a href="/about/">About us</a><a href="/editorial-policy/">Editorial policy</a><a href="/disclosure/">Retailer disclosure</a></div><div><strong>Legal</strong><a href="/disclaimer/">Disclaimer</a><a href="/privacy/">Privacy</a><a href="/terms/">Terms</a></div></div></div><div class="wrap footer-bottom"><span>© 2026 Saunas Factory Direct</span><span>Prices are informational, not guaranteed quotes.</span></div></footer>'''

def model_key(title='', sku=''):
    sku=(sku or '').strip()
    if sku and re.match(r'^(?:DYN-|MX-|GDI-|FD-)',sku,re.I):
        return slug(sku)
    text=f'{sku} {title}'.upper().replace('‑','-').replace('–','-')
    patterns=[
        r'\bDYN-\d{4}-\d{2}(?:[-\s]+(?:ELITE|FS))?\b',
        r'\bMX-[A-Z0-9-]+\b', r'\bGDI-[A-Z0-9-]+\b', r'\bFD-?[1-9]\b',
        r'\bE8G\b', r'\bG11\b', r'\bG6\b', r'\bG4\b', r'\bG3\b',
        r'\bMW20\b', r'\bMW16\b', r'\bMW12\b'
    ]
    for p in patterns:
        m=re.search(p,text)
        if m:return slug(m.group(0))
    for name in ['AROSA','AVILA','CARDOBA','CORDOBA','MADRID','VENICE','SEATTLE','MINIPOD']:
        if name in text:return slug(name)
    return slug(title)

def infer_category(title,tags=''):
    t=(title+' '+str(tags)).lower()
    if 'hybrid' in t or ('infrared' in t and ('steam' in t or 'traditional' in t)): return 'Hybrid'
    if 'infrared' in t or 'far ir' in t or 'full spectrum' in t or 'emf' in t: return 'Infrared'
    return 'Traditional'

def normalize_category(value,title=''):
    v=(value or '').lower()
    if 'hybrid' in v:return 'Hybrid'
    if 'infrared' in v:return 'Infrared'
    if 'traditional' in v:return 'Traditional'
    return infer_category(title)

def infer_placement(title,tags=''):
    t=(title+' '+str(tags)).lower()
    return 'Outdoor' if 'outdoor' in t or 'barrel' in t else 'Indoor'

def parse_capacity(value,title=''):
    nums=re.findall(r'\d+',str(value or ''))
    if nums:return max(int(x) for x in nums)
    t=(title or '').lower().replace('–','-')
    m=re.search(r'(\d+)\s*(?:-|to\s*)?(\d+)?\s*person',t)
    if m:return int(m.group(2) or m.group(1))
    m=re.search(r'up to\s*(\d+)\s*people',t)
    return int(m.group(1)) if m else None

def fnum(v):
    try:return float(str(v).replace(',','').replace('$','').strip())
    except:return 0.0

def is_active(row):
    if str(row.get('active','1')).strip().lower() in ('0','false','no'):return False
    availability=str(row.get('availability','')).strip().lower()
    return availability not in ('sold_out','out_of_stock','unavailable')

def load_existing():
    if DATA.exists():
        try:return json.loads(DATA.read_text())
        except Exception:return {'products':[]}
    return {'products':[]}

def sess():
    s=requests.Session()
    s.headers.update({'User-Agent':UA,'Accept':'text/html,application/json'})
    return s

def fetch_shopify():
    s=sess(); out=[]
    for handle in ['saunas','sauna']:
        try:
            seen=set()
            for page in range(1,6):
                u=f'{BASE}/collections/{handle}/products.json?limit=250&page={page}'
                r=s.get(u,timeout=30); r.raise_for_status()
                items=r.json().get('products',[])
                if not items:break
                for p in items:
                    if p.get('id') in seen:continue
                    seen.add(p.get('id'))
                    variants=p.get('variants') or []
                    available=[v for v in variants if v.get('available',True)] or variants
                    prices=[fnum(v.get('price')) for v in available if fnum(v.get('price'))>0]
                    if not prices:continue
                    price=min(prices)
                    chosen=min(available,key=lambda v:fnum(v.get('price')) or 10**9) if available else {}
                    compares=[fnum(v.get('compare_at_price')) for v in variants if fnum(v.get('compare_at_price'))>0]
                    msrp=max(compares) if compares else None
                    skuval=(chosen.get('sku') or '').strip()
                    title=p.get('title','').strip()
                    images=p.get('images') or []
                    out.append({
                        'model_key':model_key(title,skuval),
                        'brand':(p.get('vendor') or '').strip() or 'Unknown',
                        'model':skuval or model_key(title).upper(),
                        'title':title,
                        'category':infer_category(title,p.get('tags','')),
                        'placement':infer_placement(title,p.get('tags','')),
                        'capacity':parse_capacity('',title),
                        'msrp':msrp,
                        'image':(images[0].get('src') if images else None),
                        'offers':[{
                            'source':'InHouse Wellness','price':price,
                            'url':f"{BASE}/products/{p.get('handle')}",
                            'featured':True,
                            'observed':datetime.now(timezone.utc).date().isoformat()
                        }]
                    })
                if len(items)<250:break
            if out:return out
        except Exception as e:
            print(f'Shopify JSON failed for {handle}: {e}',file=sys.stderr)
    return []

def product_from_jsonld(url, source='External source'):
    s=sess(); r=s.get(url,timeout=30); r.raise_for_status()
    soup=BeautifulSoup(r.text,'html.parser')
    candidates=[]
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            obj=json.loads(tag.get_text(strip=True) or '{}')
            candidates += obj if isinstance(obj,list) else [obj]
        except Exception:
            pass
    def flatten(objs):
        for o in objs:
            if isinstance(o,dict) and '@graph' in o and isinstance(o['@graph'],list):
                yield from flatten(o['@graph'])
            else:yield o
    for obj in flatten(candidates):
        if not isinstance(obj,dict):continue
        typ=obj.get('@type'); types=typ if isinstance(typ,list) else [typ]
        if 'Product' not in types:continue
        offers=obj.get('offers') or {}
        if isinstance(offers,list):
            offers=offers[0] if offers else {}
        if not isinstance(offers,dict):offers={}
        price=fnum(offers.get('price') or offers.get('lowPrice'))
        if not price:continue
        title=obj.get('name') or (soup.title.string if soup.title else 'Sauna')
        brand=obj.get('brand'); brand=brand.get('name') if isinstance(brand,dict) else brand
        skuval=str(obj.get('sku') or obj.get('mpn') or '')
        image=obj.get('image')
        if isinstance(image,list):image=image[0] if image else None
        if isinstance(image,dict):image=image.get('url')
        return {'title':str(title).strip(),'brand':str(brand or 'Unknown'),'model':skuval or model_key(str(title)),'model_key':model_key(str(title),skuval),'price':price,'url':url,'source':source,'image':image}
    meta=soup.select_one('meta[property="product:price:amount"]') or soup.select_one('meta[property="og:price:amount"]')
    if meta and meta.get('content'):
        price=fnum(meta['content'])
        if price:
            og=soup.select_one('meta[property="og:title"]')
            title=og.get('content') if og else (soup.title.string if soup.title else 'Sauna')
            return {'title':title,'brand':'Unknown','model':model_key(title),'model_key':model_key(title),'price':price,'url':url,'source':source}
    return None

def fetch_inhouse_fallback():
    s=sess(); links=[]
    for page in range(1,8):
        try:
            r=s.get(f'{BASE}/collections/saunas?page={page}',timeout=30); r.raise_for_status()
            soup=BeautifulSoup(r.text,'html.parser'); found=[]
            for a in soup.select('a[href*="/products/"]'):
                href=(a.get('href') or '').split('?')[0]
                if href and '/products/' in href:found.append(urljoin(BASE,href))
            new=[u for u in dict.fromkeys(found) if u not in links]; links+=new
            if not new:break
        except Exception as e:
            print(f'Collection fallback page {page} failed: {e}',file=sys.stderr); break
    out=[]
    for u in links[:160]:
        try:
            p=product_from_jsonld(u,'InHouse Wellness')
            if not p:continue
            title=p['title']
            out.append({'model_key':p['model_key'],'brand':p['brand'],'model':p['model'],'title':title,'category':infer_category(title),'placement':infer_placement(title),'capacity':parse_capacity('',title),'msrp':None,'image':p.get('image'),'offers':[{'source':'InHouse Wellness','price':p['price'],'url':u,'featured':True,'observed':datetime.now(timezone.utc).date().isoformat()}]})
        except Exception as e:
            print(f'Product fallback failed {u}: {e}',file=sys.stderr)
        time.sleep(.15)
    return out

def read_csv(path):
    if not path.exists():return []
    with path.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))

def merge_with_existing(live,old):
    oldmap={p.get('model_key'):p for p in old.get('products',[])}
    for p in live:
        prior=oldmap.get(p['model_key'])
        if prior:
            for k in ['capacity','msrp','image','category','placement','brand','model']:
                if not p.get(k) and prior.get(k):p[k]=prior[k]
            p['offers'] += [o for o in prior.get('offers',[]) if o.get('source')!='InHouse Wellness']
    return live

def merge_external_catalog(products,refresh=True):
    rows=[r for r in read_csv(EXTERNAL_PRODUCTS) if is_active(r)]
    bykey={p['model_key']:p for p in products}
    today=datetime.now(timezone.utc).date().isoformat()
    for row in rows:
        key=slug(row.get('model_key',''))
        if not key:continue
        source=(row.get('retailer') or row.get('brand') or 'External retailer').strip()
        url=(row.get('url') or '').strip()
        fallback=fnum(row.get('observed_price')); observed=row.get('verified_date') or today
        ext=None
        if refresh and url:
            try:ext=product_from_jsonld(url,source)
            except Exception as e:print(f'Catalog refresh fallback {source}: {key}: {e}',file=sys.stderr)
        price=(ext or {}).get('price') or fallback
        if not price:
            print(f'External catalog skipped {source}: {key}: no usable price',file=sys.stderr); continue
        if ext:observed=today
        title=(row.get('product_name') or (ext or {}).get('title') or key).strip()
        brand=(row.get('brand') or (ext or {}).get('brand') or 'Unknown').strip()
        model=(row.get('model') or title).strip()
        msrp=fnum(row.get('reference_price')) or None
        category=normalize_category(row.get('category'),title)
        placement=(row.get('location') or infer_placement(title)).strip().title()
        capacity=parse_capacity(row.get('capacity'),title)
        image=(ext or {}).get('image')
        offer={'source':source,'price':float(price),'url':url,'featured':False,'observed':observed}
        if key in bykey:
            p=bykey[key]
            p['offers']=[o for o in p.get('offers',[]) if not (o.get('source')==source and o.get('url')==url)]+[offer]
            if not p.get('msrp') and msrp:p['msrp']=msrp
            if not p.get('image') and image:p['image']=image
        else:
            p={'model_key':key,'brand':brand,'model':model,'title':title,'category':category,'placement':placement,'capacity':capacity,'msrp':msrp,'image':image,'offers':[offer]}
            products.append(p); bykey[key]=p
        print(f'Catalog {source}: {key} ${float(price):,.2f}')
        time.sleep(.15)
    return products

def update_external(products,refresh=True):
    bykey={p['model_key']:p for p in products}; today=datetime.now(timezone.utc).date().isoformat()
    for row in [r for r in read_csv(EXTERNAL) if is_active(r)]:
        key=slug(row.get('match_key','')); url=(row.get('url') or '').strip(); source=(row.get('source_name') or 'External source').strip()
        if not key or not url or key not in bykey:continue
        fallback=fnum(row.get('fallback_price')); observed=row.get('verified_date') or today
        ext=None
        if refresh:
            try:ext=product_from_jsonld(url,source)
            except Exception as e:print(f'External source live fetch failed {source}: {e}',file=sys.stderr)
        price=(ext or {}).get('price') or fallback
        if not price:
            print(f'External source skipped {source}: no structured/fallback price',file=sys.stderr); continue
        if ext:observed=today
        offers=[o for o in bykey[key].get('offers',[]) if o.get('source')!=source]
        offers.append({'source':source,'price':float(price),'url':url,'featured':False,'observed':observed})
        offers.sort(key=lambda o:(not o.get('featured',False),o.get('price',10**12)))
        bykey[key]['offers']=offers
        print(f'External {source}: {key} ${float(price):,.2f}')
        time.sleep(.25)
    return products

def dedupe_products(products):
    out={}
    for p in products:
        key=p.get('model_key')
        if not key:continue
        if key not in out:out[key]=p; continue
        keep=out[key]
        for k in ['brand','model','title','category','placement','capacity','msrp','image']:
            if not keep.get(k) and p.get(k):keep[k]=p[k]
        merged={}
        for o in keep.get('offers',[])+p.get('offers',[]):
            oid=(o.get('source'),o.get('url'))
            if oid not in merged or o.get('observed','')>=merged[oid].get('observed',''):merged[oid]=o
        keep['offers']=list(merged.values())
    return list(out.values())

def write_csv(products):
    with (ROOT/'data'/'prices.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['model_key','brand','model','title','category','placement','capacity','msrp','source','price','url','featured','observed'])
        for p in products:
            for o in p.get('offers',[]):w.writerow([p.get('model_key'),p.get('brand'),p.get('model'),p.get('title'),p.get('category'),p.get('placement'),p.get('capacity'),p.get('msrp'),o.get('source'),o.get('price'),o.get('url'),o.get('featured'),o.get('observed')])

def primary_offer(p):
    offers=display_offers(p)
    if not offers:return {}
    return next((o for o in offers if o.get('featured')),None) or min(offers,key=lambda o:fnum(o.get('price')))

def page_html(p):
    offers=display_offers(p)
    primary=primary_offer(p); prices=[fnum(o.get('price')) for o in offers if fnum(o.get('price'))>0]
    lowest=min(prices) if prices else 0; highest=max(prices) if prices else 0; e=html.escape
    model_anchor=f'#model-{p.get("model_key","")}'
    offer_html=''.join(
        f'<div class="offer {"featured" if o.get("featured") else ""}"><div><strong>{e(str(o.get("source","")))}</strong>'
        f'{"<span class=\"feature-label\">Featured retailer</span>" if o.get("featured") else ""}'
        f'<div class="tiny">Observed {e(str(o.get("observed","recently")))}</div></div>'
        f'<div><strong>${fnum(o.get("price")):,.0f}</strong> · <a href="{supplier_path(o.get("source"))}{model_anchor}">Buy Here</a></div></div>'
        for o in offers
    )
    seller=primary.get('source','Observed supplier'); seller_label='Featured retailer' if primary.get('featured') else 'Observed supplier'
    desc=f'Current price comparison for {p.get("brand")} {p.get("model")}. Compare observed seller prices, reference price and deal context.'
    schema={'@context':'https://schema.org','@type':'Product','name':p.get('title'),'brand':{'@type':'Brand','name':p.get('brand')},'model':p.get('model'),'offers':{'@type':'AggregateOffer','priceCurrency':'USD','lowPrice':lowest,'highPrice':highest,'offerCount':len(offers)}}
    msrp=f'<s>${fnum(p.get("msrp")):,.0f}</s>' if fnum(p.get('msrp')) else ''
    ref=f'<p><strong>Reference price:</strong> ${fnum(p.get("msrp")):,.0f}</p>' if fnum(p.get('msrp')) else ''
    cap=f'{p.get("capacity")} person' if p.get('capacity') else 'Not verified'
    buy_path=f'{supplier_path(primary.get("source"))}{model_anchor}'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(str(p.get('brand','')))} {e(str(p.get('model','')))} Price | Saunas Factory Direct</title><meta name="description" content="{e(desc,quote=True)}"><link rel="canonical" href="https://saunasfactorydirect.com/models/{e(str(p.get('model_key','')),quote=True)}/"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/style.css"><script type="application/ld+json">{json.dumps(schema)}</script></head><body>{site_header()}<main><section class="page-hero"><div class="wrap"><span class="eyebrow">Price comparison</span><h1>{e(str(p.get('brand','')))} {e(str(p.get('model','')))}</h1><p>{e(str(p.get('title','')))}</p><div class="model-wrap"><article class="model-card"><span class="badge">{e(str(p.get('category','')))} · {e(str(p.get('placement','')))}</span><h2>Current observed pricing</h2><div class="price-line"><span class="price">${fnum(primary.get('price')):,.0f}</span>{msrp}</div><p>{seller_label}: <strong>{e(str(seller))}</strong>. Lowest displayed offer: <strong>${lowest:,.0f}</strong>.</p><div class="offer-list">{offer_html}</div></article><aside class="model-card"><h2>Model snapshot</h2><p><strong>Brand:</strong> {e(str(p.get('brand','')))}</p><p><strong>Model:</strong> {e(str(p.get('model','')))}</p><p><strong>Type:</strong> {e(str(p.get('category','')))}</p><p><strong>Placement:</strong> {e(str(p.get('placement','')))}</p><p><strong>Capacity:</strong> {e(str(cap))}</p>{ref}<a class="btn btn-primary" href="{buy_path}">Buy Here</a><p class="tiny">The button opens our supplier profile first. Verify configuration, shipping, electrical requirements, warranty and dealer authorization before purchase.</p></aside></div></div></section></main>{site_footer()}</body></html>'''

def supplier_groups(products):
    groups={}
    for p in products:
        for offer in display_offers(p):
            source=offer.get('source') or 'Supplier'
            groups.setdefault(source,[]).append((p,offer))
    return groups

def supplier_model_rows(items):
    e=html.escape
    rows=[]
    for p,offer in sorted(items,key=lambda item:(item[0].get('brand',''),item[0].get('model',''))):
        cap=f'{p.get("capacity")} person' if p.get('capacity') else 'Size not verified'
        rows.append(f'''<tr id="model-{e(str(p.get('model_key','')),quote=True)}"><td class="product-cell"><strong><a href="/models/{e(str(p.get('model_key','')),quote=True)}/">{e(str(p.get('title','')))}</a></strong><span>{e(str(p.get('brand','')))} · {e(str(p.get('model','')))}</span></td><td>{e(str(p.get('category','')))}</td><td>{e(str(p.get('placement','')))} · {e(cap)}</td><td class="price-main">${fnum(offer.get('price')):,.0f}</td><td><a class="text-link" href="/models/{e(str(p.get('model_key','')),quote=True)}/">Price details →</a></td></tr>''')
    return ''.join(rows)

def inhouse_supplier_page(items,landing):
    e=html.escape
    products=[p for p,_ in items]
    offers=[o for _,o in items]
    brands=sorted({p.get('brand') for p in products if p.get('brand')})
    categories=sorted({p.get('category') for p in products if p.get('category')})
    placements=sorted({p.get('placement') for p in products if p.get('placement')})
    prices=[fnum(o.get('price')) for o in offers if fnum(o.get('price'))]
    brand_text=', '.join(brands)
    stats=f'''<div class="profile-stats"><div><strong>{len(products)}</strong><span>models tracked</span></div><div><strong>{len(brands)}</strong><span>brands in index</span></div><div><strong>${min(prices):,.0f}–${max(prices):,.0f}</strong><span>observed range</span></div><div><strong>{' / '.join(placements)}</strong><span>placements</span></div></div>'''
    schema={'@context':'https://schema.org','@type':'Organization','name':'InHouse Wellness','description':'Featured home sauna retailer profile on Saunas Factory Direct.'}
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>InHouse Wellness Sauna Retailer Review, Brands & Prices</title><meta name="description" content="Review InHouse Wellness sauna brands, current tracked prices, delivery considerations and buying guidance for infrared, traditional, hybrid, indoor and outdoor saunas."><link rel="canonical" href="https://saunasfactorydirect.com/suppliers/inhouse-wellness/"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/style.css"><script type="application/ld+json">{json.dumps(schema)}</script></head><body>{site_header()}<main><section class="supplier-hero supplier-hero-featured"><div class="wrap supplier-hero-grid"><div><span class="eyebrow">Featured sauna retailer</span><h1>InHouse Wellness sauna brands, prices and buying guide</h1><p class="lede">InHouse Wellness is an Austin, Texas home-wellness retailer with a broad catalog of infrared saunas, traditional saunas, hybrid saunas, barrel saunas and outdoor sauna kits. This profile brings its tracked models, current advertised prices and practical purchase considerations together in one place.</p><div class="hero-actions"><a class="btn btn-primary" href="{e(landing,quote=True)}" target="_blank" rel="sponsored noopener">Shop home saunas at InHouse Wellness</a><a class="btn btn-secondary" href="#models">See {len(products)} tracked models</a></div><p class="link-note">External retailer link · Prices and terms should be verified on the retailer’s site.</p></div><aside class="supplier-summary"><span class="feature-label">Most complete supplier profile</span><h2>Catalog snapshot</h2><p><strong>Sauna types:</strong> {e(', '.join(categories))}</p><p><strong>Installation:</strong> {e(', '.join(placements))}</p><p><strong>Brands currently represented:</strong> {e(brand_text)}</p></aside></div></section><section class="section"><div class="wrap">{stats}<div class="content-grid"><article class="prose"><h2>A broad home sauna retailer</h2><p>InHouse Wellness covers more of the home sauna market than a single-brand store. The tracked selection ranges from compact one- and two-person infrared sauna cabins to multi-person traditional and hybrid rooms, outdoor sauna cabins, barrel saunas and heater packages. That range makes the retailer useful when a buyer is still comparing heat type, room size, placement and electrical requirements rather than choosing between two versions of the same cabin.</p><p>Brands associated with its sauna catalog include Finnmark Designs, Golden Designs, Dynamic Saunas, Maxxus, Dundalk LeisureCraft, SaunaLife, Scandia and Ripavi. The live Saunas Factory Direct dataset may show a slightly different list because models are included only when a usable current price and model identity can be recorded.</p><h2>Why InHouse Wellness is featured</h2><p>InHouse Wellness receives featured placement on Saunas Factory Direct. It is also the only displayed place to buy when the same exact model appears at multiple tracked sellers. That commercial presentation rule is separate from the mechanics used to record prices and reference values, and it is disclosed throughout this site.</p><p>The retailer advertises free curbside shipping in the continental United States, a price-match review, pre-purchase guidance and optional upgraded delivery or assembly services on eligible orders. Large saunas have site-access, unloading and electrical requirements that vary by model, so buyers should confirm the complete delivered and installed cost instead of comparing cabinet price alone.</p><h2>How to choose from the InHouse sauna catalog</h2><h3>Infrared saunas</h3><p>Infrared sauna buyers should compare heater spectrum, published EMF measurements, cabin material, maximum operating temperature, electrical circuit and warranty terms. Product labels such as low EMF, ultra-low EMF, near-zero EMF, far infrared and full spectrum are not interchangeable; compare the manufacturer’s measurement distance and test conditions before treating two claims as equivalent.</p><h3>Traditional and hybrid saunas</h3><p>Traditional electric or wood-fired saunas operate differently from infrared cabins and usually require more planning. Check heater output, room volume, ventilation, clearances and the electrical circuit or chimney requirements. A hybrid sauna combines more than one heating mode, but the buyer still needs to verify whether those modes can run together and which circuits are required.</p><h3>Indoor, outdoor and barrel saunas</h3><p>Indoor sauna shopping starts with finished room dimensions, door clearance, floor protection and power. Outdoor sauna shopping adds foundation, weather exposure, roof treatment and local permitting questions. Barrel and pod shapes can heat efficiently, while rectangular cabins may provide more flexible bench heights and interior layouts. The best choice depends on climate, intended bathers and whether the structure will be assembled by the owner or a professional.</p><h2>Price, delivery and installation checklist</h2><ul><li>Match the exact model or SKU, not only the marketing name.</li><li>Confirm whether the advertised price includes the heater, controls, stones, roof kit or accessories shown in photography.</li><li>Ask whether delivery is curbside, threshold, room-of-choice or full assembly.</li><li>Measure the crate path as well as the final sauna location.</li><li>Have a licensed electrician verify voltage, amperage and hardwiring requirements.</li><li>Read the manufacturer warranty, retailer return window, cancellation terms and any re-boxing or restocking fees.</li><li>Confirm current lead time and inventory before scheduling contractors.</li></ul><div class="disclosure"><strong>Retailer disclosure:</strong> InHouse Wellness is intentionally featured. Saunas Factory Direct is a pricing reference and does not process the retailer’s orders, returns, warranties or installations.</div></article><aside class="toc-card"><strong>On this page</strong><a href="#models">Tracked InHouse models</a><a href="/methodology/">Price methodology</a><a href="/disclosure/">Retailer disclosure</a><a href="/disclaimer/">Buyer disclaimer</a></aside></div></div></section><section class="section section-white" id="models"><div class="wrap"><div class="section-title"><div><span class="eyebrow">Current catalog data</span><h2>InHouse Wellness sauna models</h2></div><p>{len(products)} models currently have a usable InHouse Wellness offer in the index. Follow any model for its specification and price context.</p></div><div class="table-shell"><table class="supplier-table"><thead><tr><th>Sauna model</th><th>Type</th><th>Placement & size</th><th>Observed price</th><th>Research</th></tr></thead><tbody>{supplier_model_rows(items)}</tbody></table></div></div></section></main>{site_footer()}</body></html>'''

def standard_supplier_page(source,items,landing):
    e=html.escape
    products=[p for p,_ in items]
    brands=sorted({p.get('brand') for p in products if p.get('brand')})
    categories=sorted({p.get('category') for p in products if p.get('category')})
    summary=SUPPLIER_SUMMARIES.get(source,'Retailer or manufacturer listings represented in the Saunas Factory Direct price index.')
    desc=f'{source} supplier profile with {len(products)} tracked sauna models, observed prices and links to individual model research.'
    schema={'@context':'https://schema.org','@type':'Organization','name':source,'description':summary}
    canonical=f'https://saunasfactorydirect.com{supplier_path(source)}'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(source)} Sauna Models & Prices | Supplier Profile</title><meta name="description" content="{e(desc,quote=True)}"><link rel="canonical" href="{e(canonical,quote=True)}"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/style.css"><script type="application/ld+json">{json.dumps(schema)}</script></head><body>{site_header()}<main><section class="supplier-hero"><div class="wrap supplier-hero-grid"><div><span class="eyebrow">Supplier profile</span><h1>{e(source)}</h1><p class="lede">{e(summary)}</p><div class="hero-actions"><a class="btn btn-primary" href="{e(landing,quote=True)}" target="_blank" rel="sponsored noopener">Visit {e(source)}</a><a class="btn btn-secondary" href="#models">View tracked models</a></div><p class="link-note">One external retailer link is provided on this profile. Verify price, availability, shipping and warranty terms before purchase.</p></div><aside class="supplier-summary"><h2>Index snapshot</h2><p><strong>Tracked models:</strong> {len(products)}</p><p><strong>Brands:</strong> {e(', '.join(brands))}</p><p><strong>Sauna types:</strong> {e(', '.join(categories))}</p><p><strong>Last dataset update:</strong> generated with the current price index</p></aside></div></section><section class="section section-white" id="models"><div class="wrap"><div class="section-title"><div><span class="eyebrow">Current catalog data</span><h2>Models attributed to {e(source)}</h2></div><p>These are exact-model listings currently represented in our dataset. Product availability can change between observations.</p></div><div class="table-shell"><table class="supplier-table"><thead><tr><th>Sauna model</th><th>Type</th><th>Placement & size</th><th>Observed price</th><th>Research</th></tr></thead><tbody>{supplier_model_rows(items)}</tbody></table></div><div class="compact-prose"><h2>Before buying</h2><p>Confirm the exact model number, included heater and controls, electrical requirements, freight method, lead time, return terms and manufacturer warranty. Our recorded price is a research snapshot rather than a guaranteed quote.</p></div></div></section></main>{site_footer()}</body></html>'''

def supplier_index_page(groups):
    e=html.escape
    cards=[]
    ordered=sorted(groups.items(),key=lambda item:(item[0]!='InHouse Wellness',item[0].lower()))
    for source,items in ordered:
        brands=sorted({p.get('brand') for p,_ in items if p.get('brand')})
        cards.append(f'''<article class="supplier-card {"featured-supplier-card" if source=='InHouse Wellness' else ''}"><span class="badge">{"Featured retailer" if source=='InHouse Wellness' else "Supplier profile"}</span><h2><a href="{supplier_path(source)}">{e(source)}</a></h2><p>{len(items)} tracked model{"s" if len(items)!=1 else ""} · {e(', '.join(brands[:4]))}{' and more' if len(brands)>4 else ''}</p><a class="text-link" href="{supplier_path(source)}">View supplier profile →</a></article>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sauna Supplier Directory | Saunas Factory Direct</title><meta name="description" content="Browse the sauna retailers and manufacturers represented in our price index. Each profile groups tracked models and provides one clearly disclosed retailer link."><link rel="canonical" href="https://saunasfactorydirect.com/suppliers/"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/style.css"></head><body>{site_header()}<main><section class="page-hero"><div class="wrap"><span class="eyebrow">Supplier directory</span><h1>Where the sauna prices come from</h1><p class="lede">Each profile groups the models attributed to that retailer or manufacturer. Product and deal buttons stay inside Saunas Factory Direct until you reach a supplier profile, where one clearly labeled external link is provided.</p></div></section><section class="section section-white"><div class="wrap"><div class="supplier-grid">{''.join(cards)}</div></div></section></main>{site_footer()}</body></html>'''

def generate_supplier_pages(products):
    groups=supplier_groups(products)
    sdir=ROOT/'suppliers'; sdir.mkdir(exist_ok=True)
    keys={supplier_key(source) for source in groups}
    for d in sdir.iterdir():
        if d.is_dir() and d.name not in keys:
            for x in d.iterdir():
                if x.is_file():x.unlink()
            try:d.rmdir()
            except OSError:pass
    (sdir/'index.html').write_text(supplier_index_page(groups),encoding='utf-8')
    urls=[]
    for source,items in groups.items():
        key=supplier_key(source); d=sdir/key; d.mkdir(parents=True,exist_ok=True)
        offers=[o for _,o in items]; landing=supplier_landing(source,offers)
        page=inhouse_supplier_page(items,landing) if source=='InHouse Wellness' else standard_supplier_page(source,items,landing)
        (d/'index.html').write_text(page,encoding='utf-8')
        urls.append(f'https://saunasfactorydirect.com/suppliers/{key}/')
    return urls

def generate_pages(products):
    mdir=ROOT/'models'; mdir.mkdir(exist_ok=True); keys={p['model_key'] for p in products}
    for d in mdir.iterdir():
        if d.is_dir() and d.name not in keys:
            for x in d.iterdir():
                if x.is_file():x.unlink()
            try:d.rmdir()
            except OSError:pass
    for p in products:
        d=mdir/p['model_key']; d.mkdir(parents=True,exist_ok=True); (d/'index.html').write_text(page_html(p),encoding='utf-8')
    supplier_urls=generate_supplier_pages(products)
    urls=STATIC_URLS+supplier_urls+[f"https://saunasfactorydirect.com/models/{p['model_key']}/" for p in products]
    today=datetime.now(timezone.utc).date().isoformat()
    xml='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+''.join(f'<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n' for u in urls)+'</urlset>\n'
    (ROOT/'sitemap.xml').write_text(xml,encoding='utf-8')

def main():
    old=load_existing(); seed_only='--seed-only' in sys.argv
    if seed_only:
        products=merge_external_catalog(old.get('products',[]),refresh=False)
        products=update_external(products,refresh=False)
    else:
        if not requests or not BeautifulSoup:raise SystemExit('Install requirements: requests beautifulsoup4')
        live=fetch_shopify()
        if not live:
            print('Trying HTML/JSON-LD fallback...',file=sys.stderr); live=fetch_inhouse_fallback()
        products=merge_with_existing(live,old) if live else old.get('products',[])
        if not live:print('No live InHouse catalog retrieved; preserving existing dataset.',file=sys.stderr)
        products=merge_external_catalog(products,refresh=True)
        products=update_external(products,refresh=True)
    products=dedupe_products(products); products.sort(key=lambda p:(p.get('brand',''),p.get('model','')))
    for p in products:
        for offer in p.get('offers',[]):offer['supplier_key']=supplier_key(offer.get('source'))
    DATA.write_text(json.dumps({'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'currency':'USD','products':products},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    write_csv(products); generate_pages(products)
    print(f'Wrote {len(products)} models and {sum(len(p.get("offers",[])) for p in products)} offers.')

if __name__=='__main__':main()
