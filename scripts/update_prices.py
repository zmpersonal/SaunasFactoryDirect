#!/usr/bin/env python3
import csv, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'products.json'
EXTERNAL=ROOT/'data'/'external_sources.csv'
BASE='https://inhousewellness.com'
UA='SaunasFactoryDirectPriceBot/1.0 (+https://saunasfactorydirect.com/methodology/)'

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
    text=f'{sku} {title}'.upper().replace('‑','-').replace('–','-')
    patterns=[r'\bFD-?[1-9]\b',r'\bDYN-\d{4}-\d{2}(?:-[A-Z0-9]+)?\b',r'\bMX-[A-Z0-9-]+\b',r'\bGDI-[A-Z0-9-]+\b',r'\bE8G\b',r'\bG11\b',r'\bG6\b',r'\bG4\b',r'\bG3\b',r'\bMW20\b',r'\bMW16\b',r'\bMW12\b']
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

def infer_placement(title,tags=''):
    t=(title+' '+str(tags)).lower(); return 'Outdoor' if 'outdoor' in t or 'barrel' in t else 'Indoor'

def infer_capacity(title):
    t=title.lower().replace('–','-')
    m=re.search(r'(\d+)\s*(?:-|to\s*)?(\d+)?\s*person',t)
    if m:return int(m.group(2) or m.group(1))
    m=re.search(r'up to\s*(\d+)\s*people',t)
    return int(m.group(1)) if m else None

def load_existing():
    if DATA.exists():
        return json.loads(DATA.read_text())
    return {'products':[]}

def sess():
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept':'text/html,application/json'}); return s

def fetch_shopify():
    s=sess(); out=[]
    for handle in ['saunas','sauna']:
        try:
            seen=set()
            for page in range(1,6):
                u=f'{BASE}/collections/{handle}/products.json?limit=250&page={page}'
                r=s.get(u,timeout=30); r.raise_for_status(); payload=r.json(); items=payload.get('products',[])
                if not items:break
                for p in items:
                    if p.get('id') in seen:continue
                    seen.add(p.get('id'))
                    variants=p.get('variants') or []
                    available=[v for v in variants if v.get('available',True)] or variants
                    def fnum(v):
                        try:return float(v)
                        except:return 0.0
                    prices=[fnum(v.get('price')) for v in available if fnum(v.get('price'))>0]
                    if not prices:continue
                    price=min(prices)
                    chosen=min(available,key=lambda v:fnum(v.get('price')) or 10**9) if available else {}
                    compares=[fnum(v.get('compare_at_price')) for v in variants if fnum(v.get('compare_at_price'))>0]
                    msrp=max(compares) if compares else None
                    skuval=(chosen.get('sku') or '').strip()
                    title=p.get('title','').strip(); key=model_key(title,skuval)
                    images=p.get('images') or []
                    out.append({
                        'model_key':key,'brand':(p.get('vendor') or '').strip() or 'Unknown','model':skuval or key.upper(),
                        'title':title,'category':infer_category(title,p.get('tags','')),'placement':infer_placement(title,p.get('tags','')),
                        'capacity':infer_capacity(title),'msrp':msrp,'image':(images[0].get('src') if images else None),
                        'offers':[{'source':'InHouse Wellness','price':price,'url':f"{BASE}/products/{p.get('handle')}",'featured':True,'observed':datetime.now(timezone.utc).date().isoformat()}]
                    })
                if len(items)<250:break
            if out:return out
        except Exception as e:
            print(f'Shopify JSON failed for {handle}: {e}',file=sys.stderr)
    return []

def product_from_jsonld(url, source='InHouse Wellness'):
    s=sess(); r=s.get(url,timeout=30); r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser')
    candidates=[]
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            obj=json.loads(tag.get_text(strip=True) or '{}')
            candidates += obj if isinstance(obj,list) else [obj]
        except: pass
    def flatten(objs):
        for o in objs:
            if isinstance(o,dict) and '@graph' in o and isinstance(o['@graph'],list):
                yield from flatten(o['@graph'])
            else:yield o
    for obj in flatten(candidates):
        if not isinstance(obj,dict):continue
        typ=obj.get('@type'); types=typ if isinstance(typ,list) else [typ]
        if 'Product' not in types:continue
        offers=obj.get('offers') or {}; offers=offers[0] if isinstance(offers,list) and offers else offers
        if not isinstance(offers,dict):offers={}
        raw=offers.get('price') or offers.get('lowPrice')
        try:price=float(str(raw).replace(',',''))
        except:continue
        title=obj.get('name') or (soup.title.string if soup.title else 'Sauna')
        brand=obj.get('brand'); brand=brand.get('name') if isinstance(brand,dict) else brand
        skuval=str(obj.get('sku') or obj.get('mpn') or '')
        return {'title':str(title).strip(),'brand':str(brand or 'Unknown'),'model':skuval or model_key(str(title)), 'model_key':model_key(str(title),skuval), 'price':price,'url':url,'source':source,'image':obj.get('image')}
    meta=soup.select_one('meta[property="product:price:amount"]') or soup.select_one('meta[property="og:price:amount"]')
    if meta and meta.get('content'):
        try:price=float(meta['content'].replace(',',''))
        except:return None
        title=(soup.select_one('meta[property="og:title"]') or {}).get('content') if soup.select_one('meta[property="og:title"]') else (soup.title.string if soup.title else 'Sauna')
        return {'title':title,'brand':'Unknown','model':model_key(title),'model_key':model_key(title),'price':price,'url':url,'source':source}
    return None

def fetch_inhouse_fallback():
    s=sess(); links=[]
    for page in range(1,8):
        try:
            r=s.get(f'{BASE}/collections/saunas?page={page}',timeout=30); r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser')
            found=[]
            for a in soup.select('a[href*="/products/"]'):
                href=(a.get('href') or '').split('?')[0]
                if href and '/products/' in href:found.append(urljoin(BASE,href))
            new=[u for u in dict.fromkeys(found) if u not in links]; links+=new
            if not new:break
        except Exception as e:
            print(f'Collection fallback page {page} failed: {e}',file=sys.stderr); break
    out=[]
    for i,u in enumerate(links[:160]):
        try:
            p=product_from_jsonld(u)
            if not p:continue
            title=p['title']; out.append({'model_key':p['model_key'],'brand':p['brand'],'model':p['model'],'title':title,'category':infer_category(title),'placement':infer_placement(title),'capacity':infer_capacity(title),'msrp':None,'image':p.get('image'),'offers':[{'source':'InHouse Wellness','price':p['price'],'url':u,'featured':True,'observed':datetime.now(timezone.utc).date().isoformat()}]})
        except Exception as e: print(f'Product fallback failed {u}: {e}',file=sys.stderr)
        time.sleep(.15)
    return out

def external_rows():
    if not EXTERNAL.exists():return []
    with EXTERNAL.open(newline='') as f:return [r for r in csv.DictReader(f) if str(r.get('active','1')).strip().lower() not in ('0','false','no')]

def update_external(products):
    bykey={p['model_key']:p for p in products}; today=datetime.now(timezone.utc).date().isoformat()
    for row in external_rows():
        key=slug(row.get('match_key','')); url=row.get('url','').strip(); source=row.get('source_name','External source').strip()
        if not key or not url or key not in bykey:continue
        try:
            ext=product_from_jsonld(url,source)
            if not ext:raise ValueError('No structured product price found')
            offers=[o for o in bykey[key].get('offers',[]) if o.get('source')!=source]
            offers.append({'source':source,'price':ext['price'],'url':url,'featured':False,'observed':today})
            offers.sort(key=lambda o:(not o.get('featured',False),o.get('price',10**12)))
            bykey[key]['offers']=offers
            print(f'External {source}: {key} ${ext["price"]:,.2f}')
        except Exception as e: print(f'External source skipped {source}: {e}',file=sys.stderr)
        time.sleep(.5)
    return products

def merge_with_existing(live, old):
    oldmap={p.get('model_key'):p for p in old.get('products',[])}
    for p in live:
        prior=oldmap.get(p['model_key'])
        if prior:
            # keep known metadata if live feed omits it
            for k in ['capacity','msrp','image','category','placement','brand','model']:
                if not p.get(k) and prior.get(k):p[k]=prior[k]
            # keep non-InHouse offers until refreshed
            ext=[o for o in prior.get('offers',[]) if o.get('source')!='InHouse Wellness']
            p['offers']+=ext
    return live

def write_csv(products):
    path=ROOT/'data'/'prices.csv'
    with path.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['model_key','brand','model','title','category','placement','capacity','msrp','source','price','url','featured','observed'])
        for p in products:
            for o in p.get('offers',[]):w.writerow([p.get('model_key'),p.get('brand'),p.get('model'),p.get('title'),p.get('category'),p.get('placement'),p.get('capacity'),p.get('msrp'),o.get('source'),o.get('price'),o.get('url'),o.get('featured'),o.get('observed')])

def page_html(p):
    offers=sorted(p.get('offers',[]),key=lambda o:(not o.get('featured',False),o.get('price',10**12)))
    featured=next((o for o in offers if o.get('featured')),offers[0] if offers else {})
    lowest=min([o.get('price',10**12) for o in offers] or [0])
    offer_html=''.join(f'<div class="offer {"featured" if o.get("featured") else ""}"><div><strong>{o.get("source")}</strong>{"<span class=\"feature-label\">Featured first</span>" if o.get("featured") else ""}<div class="tiny">Observed {o.get("observed","recently")}</div></div><div><strong>${o.get("price",0):,.0f}</strong> · <a href="{o.get("url")}" target="_blank" rel="sponsored noopener">visit</a></div></div>' for o in offers)
    desc=f'Current price comparison for {p.get("brand")} {p.get("model")}. Compare observed seller prices, reference price and deal context.'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{p.get('brand')} {p.get('model')} Price | Saunas Factory Direct</title><meta name="description" content="{desc}"><link rel="canonical" href="https://saunasfactorydirect.com/models/{p.get('model_key')}/"><link rel="stylesheet" href="/assets/style.css"><script type="application/ld+json">{json.dumps({'@context':'https://schema.org','@type':'Product','name':p.get('title'),'brand':{'@type':'Brand','name':p.get('brand')},'model':p.get('model'),'offers':{'@type':'AggregateOffer','priceCurrency':'USD','lowPrice':lowest,'highPrice':max([o.get('price',0) for o in offers] or [0]),'offerCount':len(offers)}})}</script></head><body><header class="site-header"><div class="wrap nav"><a class="brand" href="/"><span class="brand-mark">$</span><span>Saunas Factory Direct</span></a><nav class="nav-links"><a href="/#price-index">Price index</a><a href="/#deal-checker">Deal checker</a><a href="/methodology/">Methodology</a></nav></div></header><main><section class="page-hero"><div class="wrap"><span class="eyebrow">Price comparison</span><h1>{p.get('brand')} {p.get('model')}</h1><p>{p.get('title')}</p><div class="model-wrap"><article class="model-card"><span class="badge">{p.get('category')} · {p.get('placement')}</span><h2>Current observed pricing</h2><div class="price-line"><span class="price">${featured.get('price',0):,.0f}</span>{f'<s>${p.get("msrp"):,.0f}</s>' if p.get('msrp') else ''}</div><p>Featured seller: <strong>InHouse Wellness</strong>. Lowest observed across sources: <strong>${lowest:,.0f}</strong>.</p><div class="offer-list">{offer_html}</div></article><aside class="model-card"><h2>Model snapshot</h2><p><strong>Brand:</strong> {p.get('brand')}</p><p><strong>Model:</strong> {p.get('model')}</p><p><strong>Type:</strong> {p.get('category')}</p><p><strong>Placement:</strong> {p.get('placement')}</p><p><strong>Capacity:</strong> {p.get('capacity') or 'Not verified'} person</p>{f'<p><strong>Reference price:</strong> ${p.get("msrp"):,.0f}</p>' if p.get('msrp') else ''}<a class="btn btn-primary" href="{featured.get('url','#')}" target="_blank" rel="sponsored noopener">View featured offer</a><p class="tiny">Verify configuration, shipping, electrical requirements, warranty and dealer authorization before purchase.</p></aside></div></div></section></main><footer><div class="wrap"><a href="/">← Back to price index</a></div></footer></body></html>'''

def generate_pages(products):
    mdir=ROOT/'models'; mdir.mkdir(exist_ok=True)
    # remove generated model dirs no longer present
    keys={p['model_key'] for p in products}
    for d in mdir.iterdir():
        if d.is_dir() and d.name not in keys:
            for x in d.iterdir():x.unlink()
            d.rmdir()
    for p in products:
        d=mdir/p['model_key'];d.mkdir(parents=True,exist_ok=True);(d/'index.html').write_text(page_html(p))
    urls=['https://saunasfactorydirect.com/','https://saunasfactorydirect.com/methodology/']+[f"https://saunasfactorydirect.com/models/{p['model_key']}/" for p in products]
    today=datetime.now(timezone.utc).date().isoformat()
    xml='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+''.join(f'<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n' for u in urls)+'</urlset>\n'
    (ROOT/'sitemap.xml').write_text(xml)

def main():
    old=load_existing()
    if '--seed-only' in sys.argv:
        products=old.get('products',[]);generate_pages(products);write_csv(products);return
    if not requests or not BeautifulSoup:
        raise SystemExit('Install requirements: requests beautifulsoup4')
    live=fetch_shopify()
    if not live:
        print('Trying HTML/JSON-LD fallback...',file=sys.stderr);live=fetch_inhouse_fallback()
    if live:
        products=merge_with_existing(live,old)
    else:
        print('No live catalog retrieved; preserving existing dataset.',file=sys.stderr);products=old.get('products',[])
    products=update_external(products)
    products.sort(key=lambda p:(p.get('brand',''),p.get('model','')))
    payload={'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'currency':'USD','products':products}
    DATA.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n')
    write_csv(products);generate_pages(products)
    print(f'Wrote {len(products)} models and {sum(len(p.get("offers",[])) for p in products)} offers.')

if __name__=='__main__':main()
