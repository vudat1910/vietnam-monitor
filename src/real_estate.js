/* ── Real Estate Section — modal chi tiết trên dashboard (không redirect ngoài) ─ */

const RE_API = 'http://localhost:5000';

const RE_GRID_GAP_PX = 12;
const RE_GRID_MIN_COL_PX = 220;
const RE_GRID_ROWS = 4;

function reColsFromGridWidth(widthPx) {
    if (widthPx <= 0) return 4;
    return Math.max(1, Math.floor((widthPx + RE_GRID_GAP_PX) / (RE_GRID_MIN_COL_PX + RE_GRID_GAP_PX)));
}

function reCardsPerPage() {
    const grid = document.getElementById('re-grid');
    const w = grid ? grid.clientWidth : 0;
    return RE_GRID_ROWS * reColsFromGridWidth(w);
}

let reState = {
    city:     '',
    type:     '',
    category: '',
    q:        '',
    page:     1,
    total:    0,
    perPage:  16,
    loading:  false,
};

function escapeHtml(s) {
    if (s == null || s === '') return '';
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}

function ensureRealEstateUI() {
    if (document.getElementById('re-wrapper')) return;

    const wrapper = document.createElement('div');
    wrapper.id    = 're-wrapper';
    wrapper.innerHTML = `
        <div class="re-header-row">
            <span class="re-section-title">BẤT ĐỘNG SẢN</span>
            <span class="live-badge">Live</span>
            <span class="re-stats-text" id="re-stats-text"></span>
            <span style="margin-left:auto;font-size:11px;color:var(--glass-text-muted)" id="re-update-time"></span>
        </div>

        <div class="re-filter-row">
            <select id="re-city" class="re-select">
                <option value="">Tất cả thành phố</option>
                <option value="HCM">Hồ Chí Minh</option>
                <option value="HN">Hà Nội</option>
            </select>
            <select id="re-type" class="re-select">
                <option value="">Mua & Thuê</option>
                <option value="ban">Mua bán</option>
                <option value="thue">Cho thuê</option>
            </select>
            <select id="re-category" class="re-select">
                <option value="">Tất cả loại</option>
                <option value="canho">Căn hộ</option>
                <option value="nha">Nhà đất</option>
                <option value="dat">Đất nền</option>
            </select>
            <input id="re-search" class="re-search" placeholder="🔍  Tìm dự án, địa chỉ..." type="text">
        </div>

        <div id="re-grid" class="re-grid"></div>

        <div class="re-pagination" id="re-pagination"></div>

        <!-- Modal chi tiết -->
        <div id="re-modal" class="re-modal" aria-hidden="true" role="dialog" aria-labelledby="re-modal-title">
            <div class="re-modal-backdrop" id="re-modal-backdrop"></div>
            <div class="re-modal-panel glass-3d">
                <button type="button" class="re-modal-close" id="re-modal-close" aria-label="Đóng">×</button>
                <div id="re-modal-inner" class="re-modal-inner"></div>
            </div>
        </div>
    `;
    document.getElementById('scroll-body').appendChild(wrapper);

    const modal = document.getElementById('re-modal');
    document.getElementById('re-modal-backdrop').addEventListener('click', closeREModal);
    document.getElementById('re-modal-close').addEventListener('click', closeREModal);
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && modal.classList.contains('is-open')) closeREModal();
    });

    ['re-city','re-type','re-category'].forEach(id => {
        document.getElementById(id).addEventListener('change', () => {
            reState[id.replace('re-','')] = document.getElementById(id).value;
            reState.page = 1;
            loadRE();
        });
    });

    let searchTimer;
    document.getElementById('re-search').addEventListener('input', e => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            reState.q    = e.target.value.trim();
            reState.page = 1;
            loadRE();
        }, 400);
    });
}

function closeREModal() {
    const modal = document.getElementById('re-modal');
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
}

function openREModal(listingId) {
    const modal = document.getElementById('re-modal');
    const inner = document.getElementById('re-modal-inner');
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    inner.innerHTML = `<div class="re-modal-loading">Đang tải chi tiết…</div>`;

    fetch(`${RE_API}/re/listing/${listingId}`)
        .then(r => {
            if (!r.ok) throw new Error('Không tìm thấy');
            return r.json();
        })
        .then(data => {
            inner.innerHTML = renderREModalContent(data);
            bindModalGallery(inner);
        })
        .catch(() => {
            inner.innerHTML = `<div class="re-modal-error">Không tải được chi tiết. Thử lại sau.</div>`;
        });
}

function renderREModalContent(d) {
    const imgs = Array.isArray(d.images) ? d.images.filter(Boolean) : [];
    const mainSrc = imgs[0] || '';
    const thumbs = imgs.slice(0, 8).map((src, i) =>
        `<button type="button" class="re-modal-thumb${i === 0 ? ' active' : ''}" data-src="${escapeHtml(src)}" aria-label="Ảnh ${i + 1}">
            <img src="${escapeHtml(src)}" alt="" loading="lazy">
        </button>`).join('');

    const typeLabel = d.listing_type === 'thue' ? 'Cho thuê' : 'Mua bán';
    const catLabel  = { canho: 'Căn hộ', nha: 'Nhà đất', dat: 'Đất nền' }[d.category] || d.category || '—';

    const pm2 = d.price_per_m2
        ? `${(d.price_per_m2 / 1_000_000).toFixed(2)} triệu/m²`
        : '—';

    const specRows = [
        ['Diện tích', d.area != null ? `${d.area} m²` : '—'],
        ['Giá', d.price_text || '—'],
        ['Giá/m²', pm2],
        ['Phòng ngủ', d.bedrooms != null ? String(d.bedrooms) : '—'],
        ['WC', d.bathrooms != null ? String(d.bathrooms) : '—'],
        ['Tầng', d.floor != null ? String(d.floor) : '—'],
        ['Hướng nhà', d.direction || '—'],
        ['Hướng ban công', d.balcony_dir || '—'],
        ['Pháp lý', d.legal || '—'],
        ['Nội thất', d.furniture || '—'],
        ['Dự án', d.project_name || '—'],
        ['Chủ đầu tư', d.developer || '—'],
        ['Loại tin', d.listing_tier || '—'],
        ['Mã tin', d.external_id || '—'],
        ['Ngày đăng', d.posted_at || '—'],
    ];

    const specHtml = specRows
        .filter(([, v]) => v && v !== '—')
        .map(([k, v]) => `<div class="re-spec-row"><span class="re-spec-k">${escapeHtml(k)}</span><span class="re-spec-v">${escapeHtml(v)}</span></div>`)
        .join('');

    const desc = d.description
        ? `<div class="re-modal-desc"><h4>Mô tả</h4><p>${escapeHtml(d.description).replace(/\n/g, '<br>')}</p></div>`
        : '';

    const phoneMasked = (d.contact_phone || '').includes('***');
    const contact = (d.contact_name || d.contact_phone)
        ? `<div class="re-modal-contact">
            <h4>Liên hệ</h4>
            <p>${escapeHtml(d.contact_name || '')}${d.contact_name && d.contact_phone ? ' · ' : ''}${escapeHtml(d.contact_phone || '')}</p>
            ${phoneMasked ? `<p class="re-phone-note">Batdongsan thường che 3 số cuối (***). Crawler đã thử bấm &quot;Hiện số&quot; và tìm trong mô tả; nếu vẫn thiếu là do trang nguồn không trả số đầy đủ.</p>` : ''}
           </div>`
        : '';

    const mainImg = mainSrc
        ? `<img id="re-modal-main-img" class="re-modal-main-img" src="${escapeHtml(mainSrc)}" alt="">`
        : `<div class="re-modal-main-img re-no-img">🏠</div>`;

    return `
        <div class="re-modal-layout">
            <div class="re-modal-gallery">
                ${mainImg}
                ${thumbs ? `<div class="re-modal-thumbs">${thumbs}</div>` : ''}
            </div>
            <div class="re-modal-info">
                <span class="re-modal-badges">
                    <span class="re-badge re-badge-type">${escapeHtml(typeLabel)}</span>
                    <span class="re-badge re-badge-cat">${escapeHtml(catLabel)}</span>
                    <span class="re-badge re-badge-src">${escapeHtml(d.source || '')}</span>
                </span>
                <h2 id="re-modal-title" class="re-modal-title">${escapeHtml(d.title || 'Chi tiết bất động sản')}</h2>
                <p class="re-modal-price-line">${escapeHtml(d.price_text || '')}${d.area ? ` <span class="re-muted">· ${escapeHtml(String(d.area))} m²</span>` : ''}</p>
                <p class="re-modal-addr">📍 ${escapeHtml(d.address || [d.ward, d.district, d.city].filter(Boolean).join(', ') || '—')}</p>
                <div class="re-modal-specs">${specHtml}</div>
                ${desc}
                ${contact}
                <p class="re-modal-footnote">Dữ liệu lưu trên Vietnam Monitor — không mở trang ngoài.</p>
            </div>
        </div>
    `;
}

function bindModalGallery(container) {
    const main = container.querySelector('#re-modal-main-img');
    container.querySelectorAll('.re-modal-thumb').forEach(btn => {
        btn.addEventListener('click', () => {
            const src = btn.getAttribute('data-src');
            if (main && src) {
                main.src = src;
                container.querySelectorAll('.re-modal-thumb').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            }
        });
    });
}

async function loadREStats() {
    try {
        const r = await fetch(`${RE_API}/re/stats`);
        const d = await r.json();
        if (d.error) return;
        const el = document.getElementById('re-stats-text');
        if (el) {
            el.textContent =
                `${d.total} tin  ·  HCM: ${d.hcm}  ·  HN: ${d.hn}` +
                (d.avg_price_m2_trieu ? `  ·  TB: ${d.avg_price_m2_trieu}tr/m²` : '');
        }
    } catch (_) {}
}

async function loadRE() {
    if (reState.loading) return;
    reState.loading = true;

    const grid = document.getElementById('re-grid');
    grid.innerHTML = `<div class="re-loading">⏳ Đang tải...</div>`;

    const perPage = reCardsPerPage();
    reState.perPage = perPage;

    const params = new URLSearchParams({
        city:     reState.city,
        type:     reState.type,
        category: reState.category,
        q:        reState.q,
        page:     reState.page,
        per_page: String(perPage),
    });

    try {
        const r = await fetch(`${RE_API}/re/listings?${params}`);
        let d;
        try {
            d = await r.json();
        } catch (_) {
            d = {};
        }

        reState.loading = false;

        if (!r.ok || d.error) {
            const msg = d.error || `Lỗi HTTP ${r.status}`;
            grid.innerHTML = `<div class="re-error"><strong>Không tải được dữ liệu BĐS</strong><br><span style="font-size:12px;opacity:.9">${escapeHtml(msg)}</span><br><span style="font-size:11px;margin-top:8px;display:inline-block">Kiểm tra Flask đang chạy (port 5000) và PostgreSQL trong <code>db.py</code>.</span></div>`;
            return;
        }

        reState.total = d.total || 0;

        const items = d.items || [];
        if (!items.length) {
            grid.innerHTML = `<div class="re-empty">
                Chưa có tin đăng trong database.<br>
                <span style="font-size:12px;opacity:.85">Chạy: <code>cd src/real_estate && python3 scrapers.py</code> rồi tải lại trang.</span>
            </div>`;
            renderREPagination();
            const now = new Date().toLocaleTimeString('vi-VN');
            const upd = document.getElementById('re-update-time');
            if (upd) upd.textContent = `Cập nhật ${now}`;
            return;
        }

        renderREGrid(items);
        bindRECardClicks();
        renderREPagination();

        const now = new Date().toLocaleTimeString('vi-VN');
        const upd = document.getElementById('re-update-time');
        if (upd) upd.textContent = `Cập nhật ${now}`;
    } catch (err) {
        reState.loading = false;
        grid.innerHTML = `<div class="re-error">Lỗi kết nối server — ${escapeHtml(err.message || String(err))}</div>`;
    }
}

function bindRECardClicks() {
    document.querySelectorAll('.re-card[data-re-id]').forEach(card => {
        card.addEventListener('click', e => {
            e.preventDefault();
            const id = card.getAttribute('data-re-id');
            if (id) openREModal(parseInt(id, 10));
        });
        card.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                const id = card.getAttribute('data-re-id');
                if (id) openREModal(parseInt(id, 10));
            }
        });
    });
}

function renderREGrid(items) {
    const grid = document.getElementById('re-grid');
    if (!items.length) {
        grid.innerHTML = `<div class="re-empty">Không tìm thấy bất động sản nào</div>`;
        return;
    }
    grid.innerHTML = items.map(item => reCard(item)).join('');
}

function reCard(item) {
    const id = item.id;
    const img     = (item.images && item.images[0]) ? item.images[0] : null;
    const imgHtml = img
        ? `<img src="${escapeHtml(img)}" class="re-card-img" loading="lazy" alt="" onerror="this.style.display='none'">`
        : `<div class="re-card-img re-no-img">🏠</div>`;

    const price   = escapeHtml(item.price_text || '—');
    const area    = item.area       ? `${item.area} m²`   : '';
    const pm2     = item.price_per_m2
        ? `${(item.price_per_m2/1_000_000).toFixed(1)} tr/m²`
        : '';
    const beds    = item.bedrooms   ? `🛏 ${item.bedrooms}` : '';
    const baths   = item.bathrooms  ? `🚿 ${item.bathrooms}` : '';
    const dir     = item.direction  ? `↗ ${escapeHtml(item.direction)}` : '';
    const legal   = item.legal      ? `📋 ${escapeHtml(item.legal)}`     : '';

    const typeTag = item.listing_type === 'thue' ? 'CHO THUÊ' : 'MUA BÁN';
    const catTag  = {canho:'Căn hộ', nha:'Nhà đất', dat:'Đất nền'}[item.category] || item.category;
    const sourceColor = {batdongsan:'#e74c3c', mogi:'#2ecc71', nha:'#3498db', homedy:'#9b59b6'}[item.source] || '#888';

    return `
    <article class="re-card" data-re-id="${id}" role="button" tabindex="0" aria-label="Xem chi tiết">
        <div class="re-card-img-wrap">
            ${imgHtml}
            <span class="re-tag re-tag-type">${typeTag}</span>
            <span class="re-tag re-tag-cat">${escapeHtml(String(catTag))}</span>
        </div>
        <div class="re-card-body">
            <div class="re-card-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title) || '—'}</div>
            <div class="re-card-price">${price}${pm2 ? `<span class="re-pm2"> · ${escapeHtml(pm2)}</span>` : ''}</div>
            <div class="re-card-meta">
                ${area ? `<span>${escapeHtml(area)}</span>` : ''}
                ${beds}  ${baths}
            </div>
            ${dir || legal ? `<div class="re-card-specs">${[dir,legal].filter(Boolean).join('  ·  ')}</div>` : ''}
            ${item.project_name ? `<div class="re-card-project">🏢 ${escapeHtml(item.project_name)}</div>` : ''}
            <div class="re-card-addr">📍 ${escapeHtml(item.address || item.district || item.city || '—')}</div>
            <div class="re-card-footer">
                <span class="re-source" style="color:${sourceColor}">${escapeHtml(item.source || '')}</span>
                ${item.posted_at ? `<span class="re-date">${escapeHtml(item.posted_at)}</span>` : ''}
            </div>
        </div>
    </article>`;
}

function renderREPagination() {
    const el        = document.getElementById('re-pagination');
    const pp = reState.perPage || reCardsPerPage();
    const totalPages = Math.ceil(reState.total / pp);
    if (totalPages <= 1) { el.innerHTML = ''; return; }

    const p = reState.page;
    let html = '';

    if (p > 1)          html += `<button class="re-page-btn" onclick="reGoPage(${p-1})">‹</button>`;
    if (p > 2)          html += `<button class="re-page-btn" onclick="reGoPage(1)">1</button>`;
    if (p > 3)          html += `<span class="re-page-dots">…</span>`;

    for (let i = Math.max(1,p-1); i <= Math.min(totalPages,p+1); i++) {
        html += `<button class="re-page-btn${i===p?' active':''}" onclick="reGoPage(${i})">${i}</button>`;
    }

    if (p < totalPages-2) html += `<span class="re-page-dots">…</span>`;
    if (p < totalPages-1) html += `<button class="re-page-btn" onclick="reGoPage(${totalPages})">${totalPages}</button>`;
    if (p < totalPages)   html += `<button class="re-page-btn" onclick="reGoPage(${p+1})">›</button>`;

    html += `<span class="re-page-info">${reState.total} tin</span>`;
    el.innerHTML = html;
}

function reGoPage(p) {
    reState.page = p;
    loadRE();
    document.getElementById('re-wrapper').scrollIntoView({behavior:'smooth'});
}

function initRealEstate() {
    ensureRealEstateUI();
    loadREStats();
    loadRE();
    setInterval(() => { loadREStats(); loadRE(); }, 5 * 60 * 1000);

    let resizeTimer;
    let lastCols = reColsFromGridWidth(document.getElementById('re-grid')?.clientWidth || 0);
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            const g = document.getElementById('re-grid');
            const c = reColsFromGridWidth(g ? g.clientWidth : 0);
            if (c !== lastCols) {
                lastCols = c;
                reState.page = 1;
                loadRE();
            }
        }, 200);
    });
}

document.addEventListener('DOMContentLoaded', initRealEstate);
