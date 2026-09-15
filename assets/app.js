const $ = (selector) => document.querySelector(selector);

const money = (value) => new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
}).format(Number(value) || 0);

const esc = (value) => (value ?? '').toString().replace(/[&<>"']/g, (character) => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#039;',
}[character]));

const sourceSlug = (value) => (value || 'supplier')
  .toLowerCase()
  .normalize('NFKD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-|-$/g, '');

let DATA = [];

function inhouseOffer(product) {
  return (product.offers || []).find((offer) => offer.source === 'InHouse Wellness' && Number(offer.price) > 0);
}

function displayOffers(product) {
  const offers = (product.offers || []).filter((offer) => Number(offer.price) > 0);
  const inhouse = inhouseOffer(product);
  if (inhouse) return [inhouse];

  const bySource = new Map();
  offers.forEach((offer) => {
    const current = bySource.get(offer.source);
    if (!current || Number(offer.price) < Number(current.price)) bySource.set(offer.source, offer);
  });
  return [...bySource.values()].sort((a, b) => Number(a.price) - Number(b.price));
}

function supplierUrl(offer, product) {
  const key = offer.supplier_key || sourceSlug(offer.source);
  const modelAnchor = product?.model_key ? `#model-${encodeURIComponent(product.model_key)}` : '#models';
  return `/suppliers/${encodeURIComponent(key)}/${modelAnchor}`;
}

function primaryOffer(product) {
  const offers = displayOffers(product);
  return offers.find((offer) => offer.featured) || offers[0];
}

function bestObserved(product) {
  const prices = displayOffers(product).map((offer) => Number(offer.price)).filter(Boolean);
  return prices.length ? Math.min(...prices) : 0;
}

function savings(product) {
  const offer = primaryOffer(product);
  return product.msrp && offer ? Math.max(0, product.msrp - offer.price) : 0;
}

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return 0;
  const midpoint = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[midpoint] : (sorted[midpoint - 1] + sorted[midpoint]) / 2;
}

function updateStats(meta) {
  $('#model-count').textContent = DATA.length;
  const prices = DATA.map((product) => Number(primaryOffer(product)?.price)).filter(Boolean);
  $('#median-price').textContent = money(median(prices));
  $('#low-price').textContent = prices.length ? money(Math.min(...prices)) : '—';
  $('#high-price').textContent = prices.length ? money(Math.max(...prices)) : '—';
  $('#updated-date').textContent = (meta.generated_at || '').slice(0, 10) || '—';

  const categoryMedian = (category) => median(DATA
    .filter((product) => product.category === category)
    .map((product) => Number(primaryOffer(product)?.price)));

  $('#idx-infrared').textContent = money(categoryMedian('Infrared'));
  $('#idx-traditional').textContent = money(categoryMedian('Traditional'));
  $('#idx-hybrid').textContent = money(categoryMedian('Hybrid'));
  $('#idx-outdoor').textContent = money(median(DATA
    .filter((product) => product.placement === 'Outdoor')
    .map((product) => Number(primaryOffer(product)?.price))));
}

function resetChecker(message = 'Choose a brand, select a model and enter your quoted price.') {
  const result = $('#checker-result');
  result.className = 'checker-result empty';
  result.innerHTML = `<div><strong>${esc(message)}</strong><br>We’ll compare it with the current displayed offer and available reference price.</div>`;
}

function populateCheckerModels() {
  const brand = $('#checker-brand').value;
  const modelSelect = $('#checker-model');
  const products = DATA.filter((product) => product.brand === brand);

  modelSelect.disabled = !brand;
  modelSelect.innerHTML = brand
    ? `<option value="">Select a ${esc(brand)} model…</option>${products.map((product) => (
      `<option value="${esc(product.model_key)}">${esc(product.model)} — ${esc(product.title)}</option>`
    )).join('')}`
    : '<option value="">Choose a brand first…</option>';
  resetChecker(brand ? 'Now select a model and enter your quoted price.' : undefined);
}

function populateSelectors() {
  const brands = [...new Set(DATA.map((product) => product.brand))].sort((a, b) => a.localeCompare(b));
  const options = brands.map((brand) => `<option value="${esc(brand)}">${esc(brand)}</option>`).join('');
  $('#checker-brand').innerHTML = `<option value="">Choose a brand…</option>${options}`;
  $('#brand-filter').innerHTML = `<option value="">All brands</option>${options}`;
  populateCheckerModels();
}

function renderTable() {
  const query = $('#search').value.toLowerCase();
  const brand = $('#brand-filter').value;
  const category = $('#category-filter').value;
  const capacity = $('#capacity-filter').value;
  const rows = DATA.filter((product) => {
    const haystack = `${product.title} ${product.brand} ${product.model}`.toLowerCase();
    return (!query || haystack.includes(query))
      && (!brand || product.brand === brand)
      && (!category || product.category === category)
      && (!capacity || String(product.capacity) === capacity);
  });

  $('#result-count').textContent = `${rows.length} model${rows.length === 1 ? '' : 's'} shown`;
  $('#price-table-body').innerHTML = rows.map((product) => {
    const offer = primaryOffer(product);
    const best = bestObserved(product);
    const save = savings(product);
    const modelUrl = `/models/${encodeURIComponent(product.model_key)}/`;
    return `<tr>
      <td class="product-cell"><strong><a href="${modelUrl}">${esc(product.title)}</a></strong><span>${esc(product.category)} · ${esc(product.placement)} · ${product.capacity || '—'} person</span></td>
      <td>${esc(product.brand)}</td>
      <td>${esc(product.model)}</td>
      <td><span class="price-main">${money(offer?.price)}</span>${save ? `<div class="deal-save">${money(save)} below reference</div>` : ''}</td>
      <td>${money(best)}</td>
      <td>${product.msrp ? money(product.msrp) : '—'}</td>
      <td><span class="seller-name">${esc(offer?.source || 'Supplier')}</span><a class="shop-link" href="${supplierUrl(offer || {}, product)}">Buy Here →</a></td>
    </tr>`;
  }).join('') || '<tr><td colspan="7">No matching models.</td></tr>';
}

function renderPicks() {
  const featured = DATA.filter((product) => inhouseOffer(product));
  const under3 = featured
    .filter((product) => Number(inhouseOffer(product).price) < 3000)
    .sort((a, b) => Number(inhouseOffer(a).price) - Number(inhouseOffer(b).price))[0];
  const hybrid = featured
    .filter((product) => product.category === 'Hybrid')
    .sort((a, b) => Number(inhouseOffer(a).price) - Number(inhouseOffer(b).price))[0];
  const outdoor = featured
    .filter((product) => product.placement === 'Outdoor')
    .sort((a, b) => Number(inhouseOffer(a).price) - Number(inhouseOffer(b).price))[0];
  const picks = [
    ['Featured value under $3k', under3],
    ['Featured hybrid', hybrid],
    ['Featured outdoor value', outdoor],
  ];

  $('#featured-picks').innerHTML = picks.filter(([, product]) => product).map(([label, product]) => {
    const offer = inhouseOffer(product);
    return `<article class="pick-card">
      <div class="pick-kicker">${esc(label)}</div>
      <h3>${esc(product.title)}</h3>
      <p>${esc(product.brand)} · ${product.capacity || '—'} person · ${esc(product.placement)}</p>
      <div class="pick-price">${money(offer.price)}</div>
      <a class="btn btn-primary" href="${supplierUrl(offer, product)}">Buy Here</a>
    </article>`;
  }).join('');
}

function selectedCheckerProduct() {
  const key = $('#checker-model').value;
  return DATA.find((product) => product.model_key === key);
}

function runChecker() {
  const product = selectedCheckerProduct();
  const quote = Number($('#quote-price').value);
  if (!product || !Number.isFinite(quote) || quote <= 0) {
    resetChecker('Select a brand and model, then enter a valid quoted price.');
    return;
  }

  const best = bestObserved(product);
  const offers = displayOffers(product);
  let label = 'High';
  let className = 'high';
  let message = 'The quote is materially above the current displayed offer.';

  if (quote <= best * 0.98) {
    label = 'Excellent';
    className = 'good';
    message = 'This quote is below the current displayed offer in our dataset.';
  } else if (quote <= best * 1.05) {
    label = 'Competitive';
    className = 'good';
    message = 'This quote is within 5% of the current displayed offer.';
  } else if (!product.msrp || quote <= product.msrp) {
    label = 'Fair';
    className = 'fair';
    message = 'The quote is above the current displayed offer, but remains below the reference price when one is available.';
  }

  const result = $('#checker-result');
  result.className = 'checker-result';
  result.innerHTML = `<span class="rating ${className}">${label} deal</span>
    <h3>${esc(product.brand)} ${esc(product.model)}</h3>
    <div class="price-line"><span class="price">${money(quote)}</span>${product.msrp ? `<s>${money(product.msrp)}</s>` : ''}</div>
    <p>${esc(message)}</p>
    <div class="offer-list">${offers.map((offer) => `<div class="offer ${offer.featured ? 'featured' : ''}">
      <div><strong>${esc(offer.source)}</strong>${offer.featured ? '<span class="feature-label">Featured retailer</span>' : ''}<div class="tiny">Observed ${esc(offer.observed || 'recently')}</div></div>
      <div><strong>${money(offer.price)}</strong> · <a href="${supplierUrl(offer, product)}">Buy Here</a></div>
    </div>`).join('')}</div>
    <p class="tiny">Purchase links open an internal supplier profile first. Shipping, installation and included accessories can change the total value.</p>`;
}

async function init() {
  try {
    const response = await fetch('/data/products.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Price data request failed: ${response.status}`);
    const meta = await response.json();
    DATA = meta.products || [];
    updateStats(meta);
    populateSelectors();
    renderTable();
    renderPicks();

    ['#search', '#brand-filter', '#category-filter', '#capacity-filter'].forEach((selector) => {
      $(selector)?.addEventListener('input', renderTable);
    });
    $('#checker-brand')?.addEventListener('change', populateCheckerModels);
    $('#checker-model')?.addEventListener('change', () => {
      if (Number($('#quote-price').value) > 0) runChecker();
    });
    $('#checker-btn')?.addEventListener('click', runChecker);
    $('#quote-price')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') runChecker();
    });
  } catch (error) {
    console.error(error);
    $('#price-table-body').innerHTML = '<tr><td colspan="7">Price data could not be loaded.</td></tr>';
    resetChecker('Price data could not be loaded. Please try again later.');
  }
}

init();
