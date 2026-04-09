(function () {
  const API = "http://localhost:5000";

  const SEV_LABEL_VI = {
    critical: "Rất nghiêm trọng",
    warning: "Cảnh báo",
    watch: "Theo dõi",
    info: "Thông tin",
    ok: "Bình thường",
  };

  const LAYER_LABEL_VI = {
    weather: "Thời tiết",
    news: "Tin tức",
  };

  function escapeHtml(s) {
    if (s == null) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function formatShortDate(iso) {
    if (!iso) return "—";
    const raw = String(iso).trim();
    try {
      const d = new Date(raw.length === 10 ? `${raw}T12:00:00` : raw);
      if (Number.isNaN(d.getTime())) return escapeHtml(raw);
      return d.toLocaleDateString("vi-VN", {
        weekday: "short",
        day: "numeric",
        month: "numeric",
      });
    } catch (_) {
      return escapeHtml(raw);
    }
  }

  function safeNewsLink(url, label) {
    const u = String(url || "").trim();
    try {
      const parsed = new URL(u);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return escapeHtml(label);
      const href = parsed.href.replace(/"/g, "%22");
      return `<a class="am-news-link" href="${href}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
    } catch (_) {
      return escapeHtml(label);
    }
  }

  function renderAlertItem(a) {
    const sev = a.severity || "info";
    const sevVi = SEV_LABEL_VI[sev] || sev || "—";
    const layer = LAYER_LABEL_VI[a.layer] || a.layer || "—";
    const link =
      a.layer === "news" && a.source_url
        ? `<div class="am-popup-link-row">${safeNewsLink(a.source_url, "Mở bài báo →")}</div>`
        : "";
    return `<div class="am-popup-item am-sev-${escapeHtml(sev)}">
            <div class="am-popup-item-head">
              <span class="am-popup-layer">${escapeHtml(layer)}</span>
              <span class="am-sev-pill">${escapeHtml(sevVi)}</span>
            </div>
            <div class="am-popup-title">${escapeHtml(a.title || "")}</div>
            <div class="am-popup-sum">${escapeHtml(a.summary || "")}</div>
            ${link}
          </div>`;
  }

  function buildPopupHtml(props) {
    const prov = escapeHtml(props.province || "");

    let digest = [];
    try {
      digest = JSON.parse(props.news_digest_json || "[]");
    } catch (_) {
      digest = [];
    }
    if (!Array.isArray(digest)) digest = [];

    let digestBlock = "";
    if (digest.length) {
      digestBlock = `<div class="am-news-digest">
        <div class="am-popup-section-title">Tin có nhắc tới tỉnh</div>
        <ul class="am-news-digest-list">
          ${digest
            .map((it) => {
              const t = it.title || "—";
              const u = it.url;
              const line = u ? safeNewsLink(u, t) : escapeHtml(t);
              return `<li class="am-news-digest-li">${line}</li>`;
            })
            .join("")}
        </ul>
      </div>`;
    }

    let snap = [];
    try {
      snap = JSON.parse(props.weather_snapshot_json || "[]");
    } catch (_) {
      snap = [];
    }
    if (!Array.isArray(snap)) snap = [];

    let weatherBlock = "";
    if (snap.length) {
      const rows = snap
        .map((row) => {
          const tmin = row.tmin != null ? Math.round(Number(row.tmin)) : null;
          const tmax = row.tmax != null ? Math.round(Number(row.tmax)) : null;
          const tmaxHtml =
            tmax != null ? `<span class="am-w-tmax">${tmax}°C</span>` : `<span class="am-w-tmax">—</span>`;
          const tminHtml =
            tmin != null ? `<span class="am-w-tmin">${tmin}°C</span>` : "";

          const pr =
            row.precip_mm != null && !Number.isNaN(Number(row.precip_mm))
              ? `${Number(row.precip_mm).toFixed(1)} mm`
              : "—";
          const pb = row.prob_pct != null ? `${row.prob_pct}%` : "—";
          return `<div class="am-w-row">
            <span class="am-w-date">${formatShortDate(row.date)}</span>
            <div class="am-w-main">
              <div class="am-w-temps">${tmaxHtml}${tminHtml ? `<span class="am-w-tsep">/</span>${tminHtml}` : ""}</div>
              <div class="am-w-label">${escapeHtml(row.label || "—")}</div>
              <div class="am-w-meta">💧 Mưa ${escapeHtml(pr)} · ${escapeHtml(pb)}</div>
            </div>
          </div>`;
        })
        .join("");
      weatherBlock = `<div class="am-weather-snap">
        <div class="am-weather-snap-title">Dự báo 4 ngày</div>
        ${rows}
      </div>`;
    }

    let alerts = [];
    try {
      alerts = JSON.parse(props.alerts_json || "[]");
    } catch (_) {
      alerts = [];
    }
    if (!Array.isArray(alerts)) alerts = [];

    const newsAlerts = alerts.filter((a) => a.layer === "news");
    const wxAlerts = alerts.filter((a) => a.layer === "weather");

    let body = "";
    if (newsAlerts.length) {
      body += `<div class="am-popup-section-title am-popup-section-risk">Tin cảnh báo rủi ro</div>${newsAlerts.map(renderAlertItem).join("")}`;
    }
    if (wxAlerts.length) {
      body += wxAlerts.map(renderAlertItem).join("");
    }
    if (!digest.length && !snap.length && !alerts.length) {
      body = `<p class="am-popup-none">Chưa có dữ liệu cho tỉnh này.</p>`;
    } else if (!digest.length && !newsAlerts.length && !wxAlerts.length && snap.length) {
      body += `<p class="am-popup-none am-popup-footnote">Chưa có tin địa phương trong bản tin gần đây; chỉ có dự báo thời tiết.</p>`;
    }

    return `<div class="am-popup"><h3>${prov}</h3>${digestBlock}${weatherBlock}${body}</div>`;
  }

  function init() {
    const map = window.map;
    if (!map || typeof map.addSource !== "function") return;

    const metaEl = document.getElementById("map-alerts-meta");
    const toggle = document.getElementById("map-alerts-toggle");

    map.addSource("risk-alerts", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });

    map.addLayer({
      id: "risk-alerts-glow",
      type: "circle",
      source: "risk-alerts",
      paint: {
        "circle-radius": [
          "match",
          ["get", "severity"],
          "critical",
          22,
          "warning",
          18,
          "watch",
          16,
          "info",
          14,
          10,
        ],
        "circle-color": [
          "match",
          ["get", "severity"],
          "critical",
          "#dc2626",
          "warning",
          "#ea580c",
          "watch",
          "#ca8a04",
          "info",
          "#2563eb",
          "#94a3b8",
        ],
        "circle-opacity": 0.22,
        "circle-blur": 0.6,
      },
    });

    map.addLayer({
      id: "risk-alerts-circles",
      type: "circle",
      source: "risk-alerts",
      paint: {
        "circle-radius": [
          "match",
          ["get", "severity"],
          "critical",
          14,
          "warning",
          12,
          "watch",
          10,
          "info",
          8,
          5,
        ],
        "circle-color": [
          "match",
          ["get", "severity"],
          "critical",
          "#dc2626",
          "warning",
          "#f97316",
          "watch",
          "#eab308",
          "info",
          "#3b82f6",
          "#e2e8f0",
        ],
        "circle-stroke-width": 1.5,
        "circle-stroke-color": "#ffffff",
        "circle-opacity": 0.95,
      },
    });

    const popup = new mapboxgl.Popup({ closeButton: true, maxWidth: "340px" });

    function applyFilters() {
      const show = toggle && toggle.checked;
      const vis = show ? "visible" : "none";
      if (map.getLayer("risk-alerts-glow"))
        map.setLayoutProperty("risk-alerts-glow", "visibility", vis);
      if (map.getLayer("risk-alerts-circles"))
        map.setLayoutProperty("risk-alerts-circles", "visibility", vis);
      if (!show) return;
      map.setFilter("risk-alerts-glow", null);
      map.setFilter("risk-alerts-circles", null);
    }

    async function loadAlerts() {
      try {
        const r = await fetch(`${API}/alerts/geojson`);
        const data = await r.json();
        const fc = { type: "FeatureCollection", features: data.features || [] };
        map.getSource("risk-alerts").setData(fc);
        if (metaEl && data.meta) {
          const t = data.meta.generated_at;
          metaEl.textContent = t
            ? `Cập nhật: ${new Date(t).toLocaleString("vi-VN")}`
            : "Đang tải dữ liệu cảnh báo…";
        }
        applyFilters();
      } catch (e) {
        if (metaEl) metaEl.textContent = "Không tải được cảnh báo";
      }
    }

    map.on("click", "risk-alerts-circles", (e) => {
      if (!toggle || !toggle.checked) return;
      const f = e.features && e.features[0];
      if (!f) return;
      popup.setLngLat(e.lngLat).setHTML(buildPopupHtml(f.properties)).addTo(map);
    });

    map.on("mouseenter", "risk-alerts-circles", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "risk-alerts-circles", () => {
      map.getCanvas().style.cursor = "";
    });

    if (toggle) toggle.addEventListener("change", applyFilters);

    loadAlerts();
    setInterval(loadAlerts, 10 * 60 * 1000);

    if (toggle) applyFilters();
  }

  function whenMapReady() {
    const map = window.map;
    if (!map) return;
    if (map.loaded && map.loaded()) init();
    else map.once("load", init);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", whenMapReady);
  } else {
    whenMapReady();
  }
})();
