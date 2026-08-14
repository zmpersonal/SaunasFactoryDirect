#!/usr/bin/env python3
import csv, json, re, sys, time, html
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'products.json'
EXTERNAL=ROOT/'data'/'external_sources.csv'
EXTERNAL_PRODUCTS=ROOT/'data'/'external_products.csv'
BASE='https://inhousewellness.com'
UA='SaunasFactoryDirectPriceBot/1.1 (+https://saunasfactorydirect.com/methodology/)'

try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    requests=None; BeautifulSoup=None

def slug(s):
    s=(s or '').lower().replace('‑','-').replace('–','-').replace('—','-')
    s=re.sub(r'[^a-z0-9]+','-',s).strip('-')
    return s[:90] or 'sauna'

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
    offers=[o for o in p.get('offers',[]) if fnum(o.get('price'))>0]
    if not offers:return {}
    return next((o for o in offers if o.get('featured')),None) or min(offers,key=lambda o:fnum(o.get('price')))

def page_html(p):
    offers=sorted(p.get('offers',[]),key=lambda o:(not o.get('featured',False),fnum(o.get('price')) or 10**12))
    primary=primary_offer(p); prices=[fnum(o.get('price')) for o in offers if fnum(o.get('price'))>0]
    lowest=min(prices) if prices else 0; highest=max(prices) if prices else 0; e=html.escape
    offer_html=''.join(
        f'<div class="offer {"featured" if o.get("featured") else ""}"><div><strong>{e(str(o.get("source","")))}</strong>'
        f'{"<span class=\"feature-label\">Featured first</span>" if o.get("featured") else ""}'
        f'<div class="tiny">Observed {e(str(o.get("observed","recently")))}</div></div>'
        f'<div><strong>${fnum(o.get("price")):,.0f}</strong> · <a href="{e(str(o.get("url","")),quote=True)}" target="_blank" rel="sponsored noopener">visit</a></div></div>'
        for o in offers
    )
    seller=primary.get('source','Observed seller'); seller_label='Featured seller' if primary.get('featured') else 'Observed seller'
    button='View InHouse offer' if primary.get('featured') else f'View {seller}'
    desc=f'Current price comparison for {p.get("brand")} {p.get("model")}. Compare observed seller prices, reference price and deal context.'
    schema={'@context':'https://schema.org','@type':'Product','name':p.get('title'),'brand':{'@type':'Brand','name':p.get('brand')},'model':p.get('model'),'offers':{'@type':'AggregateOffer','priceCurrency':'USD','lowPrice':lowest,'highPrice':highest,'offerCount':len(offers)}}
    msrp=f'<s>${fnum(p.get("msrp")):,.0f}</s>' if fnum(p.get('msrp')) else ''
    ref=f'<p><strong>Reference price:</strong> ${fnum(p.get("msrp")):,.0f}</p>' if fnum(p.get('msrp')) else ''
    cap=f'{p.get("capacity")} person' if p.get('capacity') else 'Not verified'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(str(p.get('brand','')))} {e(str(p.get('model','')))} Price | Saunas Factory Direct</title><meta name="description" content="{e(desc,quote=True)}"><link rel="canonical" href="https://saunasfactorydirect.com/models/{e(str(p.get('model_key','')),quote=True)}/"><link rel="stylesheet" href="/assets/style.css"><script type="application/ld+json">{json.dumps(schema)}</script></head><body><header class="site-header"><div class="wrap nav"><a class="brand" href="/"><span class="brand-mark">$</span><span>Saunas Factory Direct</span></a><nav class="nav-links"><a href="/#price-index">Price index</a><a href="/#deal-checker">Deal checker</a><a href="/methodology/">Methodology</a></nav></div></header><main><section class="page-hero"><div class="wrap"><span class="eyebrow">Price comparison</span><h1>{e(str(p.get('brand','')))} {e(str(p.get('model','')))}</h1><p>{e(str(p.get('title','')))}</p><div class="model-wrap"><article class="model-card"><span class="badge">{e(str(p.get('category','')))} · {e(str(p.get('placement','')))}</span><h2>Current observed pricing</h2><div class="price-line"><span class="price">${fnum(primary.get('price')):,.0f}</span>{msrp}</div><p>{seller_label}: <strong>{e(str(seller))}</strong>. Lowest observed across active sources: <strong>${lowest:,.0f}</strong>.</p><div class="offer-list">{offer_html}</div></article><aside class="model-card"><h2>Model snapshot</h2><p><strong>Brand:</strong> {e(str(p.get('brand','')))}</p><p><strong>Model:</strong> {e(str(p.get('model','')))}</p><p><strong>Type:</strong> {e(str(p.get('category','')))}</p><p><strong>Placement:</strong> {e(str(p.get('placement','')))}</p><p><strong>Capacity:</strong> {e(str(cap))}</p>{ref}<a class="btn btn-primary" href="{e(str(primary.get('url','#')),quote=True)}" target="_blank" rel="sponsored noopener">{e(button)}</a><p class="tiny">Verify configuration, shipping, electrical requirements, warranty and dealer authorization before purchase.</p></aside></div></div></section></main><footer><div class="wrap"><a href="/">← Back to price index</a></div></footer></body></html>'''

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
    urls=['https://saunasfactorydirect.com/','https://saunasfactorydirect.com/methodology/']+[f"https://saunasfactorydirect.com/models/{p['model_key']}/" for p in products]
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
    DATA.write_text(json.dumps({'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'currency':'USD','products':products},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    write_csv(products); generate_pages(products)
    print(f'Wrote {len(products)} models and {sum(len(p.get("offers",[])) for p in products)} offers.')

if __name__=='__main__':main()
