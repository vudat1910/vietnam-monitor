const VN_PROVINCE_NAMES = [
  "Toàn quốc",
  "Hà Nội",
  "Thành phố Hồ Chí Minh",
  "Hải Phòng",
  "Đà Nẵng",
  "Cần Thơ",
  "An Giang",
  "Bà Rịa - Vũng Tàu",
  "Bắc Giang",
  "Bắc Kạn",
  "Bạc Liêu",
  "Bắc Ninh",
  "Bến Tre",
  "Bình Định",
  "Bình Dương",
  "Bình Phước",
  "Bình Thuận",
  "Cà Mau",
  "Cao Bằng",
  "Đắk Lắk",
  "Đắk Nông",
  "Điện Biên",
  "Đồng Nai",
  "Đồng Tháp",
  "Gia Lai",
  "Hà Giang",
  "Hà Nam",
  "Hà Tĩnh",
  "Hải Dương",
  "Hậu Giang",
  "Hòa Bình",
  "Hưng Yên",
  "Khánh Hòa",
  "Kiên Giang",
  "Kon Tum",
  "Lai Châu",
  "Lâm Đồng",
  "Lạng Sơn",
  "Lào Cai",
  "Long An",
  "Nam Định",
  "Nghệ An",
  "Ninh Bình",
  "Ninh Thuận",
  "Phú Thọ",
  "Phú Yên",
  "Quảng Bình",
  "Quảng Nam",
  "Quảng Ngãi",
  "Quảng Ninh",
  "Quảng Trị",
  "Sóc Trăng",
  "Sơn La",
  "Tây Ninh",
  "Thái Bình",
  "Thái Nguyên",
  "Thanh Hóa",
  "Thừa Thiên Huế",
  "Tiền Giang",
  "Trà Vinh",
  "Tuyên Quang",
  "Vĩnh Long",
  "Vĩnh Phúc",
  "Yên Bái"
];

const geoCache = new Map(); 
const forecastCache = new Map(); 

let state = { province: "Hà Nội" };
let currentForecastAbort = null;
let currentRequestToken = 0;

function norm(s) {
  return (s || "")
    .toString()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function weatherCodeToText(code) {
  if ([0].includes(code)) return "Trời quang";
  if ([1, 2, 3].includes(code)) return "Ít mây / Nhiều mây";
  if ([45, 48].includes(code)) return "Sương mù";
  if ([51, 53, 55, 61, 63, 65, 80, 81, 82].includes(code)) return "Mưa";
  if ([71, 73, 75, 85, 86].includes(code)) return "Tuyết";
  if ([95, 96, 99].includes(code)) return "Giông bão";
  return "Không rõ";
}

function weatherCodeToIcon(code, isNight = false) {
  if ([0].includes(code)) return isNight ? "🌙" : "☀️";
  if ([1, 2, 3].includes(code)) return "⛅️";
  if ([45, 48].includes(code)) return "🌫️";
  if ([51, 53, 55, 61, 63, 65, 80, 81, 82].includes(code)) return "🌧️";
  if ([71, 73, 75, 85, 86].includes(code)) return "❄️";
  if ([95, 96, 99].includes(code)) return "⛈️";
  return "☁️";
}

function degToWindText(deg) {
  if (typeof deg !== "number") return "—";
  const dirs = ["B", "ĐB", "Đ", "ĐN", "N", "TN", "T", "TB"];
  const idx = Math.round(((deg % 360) / 45)) % 8;
  return dirs[idx];
}

function formatDateLabel(isoDate, i) {
  const date = new Date(isoDate);
  if (i === 0) return "Hôm nay";
  if (i === 1) return "Ngày mai";
  return date.toLocaleDateString("vi-VN", { weekday: "short", day: "2-digit", month: "2-digit" });
}

function findNearestHourIndex(isoTimes, targetIso) {
  if (!Array.isArray(isoTimes) || !isoTimes.length) return -1;
  const t = new Date(targetIso).getTime();
  let best = 0;
  let bestDiff = Infinity;
  for (let i = 0; i < isoTimes.length; i++) {
    const d = Math.abs(new Date(isoTimes[i]).getTime() - t);
    if (d < bestDiff) {
      bestDiff = d;
      best = i;
    }
  }
  return best;
}

async function geocodeStrictVN(query, provinceNameForMatch) {
  const cacheKey = `geo|${query}`;
  if (geoCache.has(cacheKey)) return geoCache.get(cacheKey);

  const url =
    `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(query)}` +
    `&count=10&language=vi&format=json&countryCode=VN`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Geocoding API lỗi: ${res.status}`);
  const data = await res.json();
  const results = Array.isArray(data?.results) ? data.results : [];
  if (!results.length) throw new Error(`Không tìm thấy tọa độ cho: ${query}`);

  if (provinceNameForMatch) {
    const pNorm = norm(provinceNameForMatch.replace(/^Thành phố\s+/i, "").replace(/^Tỉnh\s+/i, ""));
    const picked =
      results.find((x) => norm(x?.admin1) === pNorm) ||
      results.find((x) => norm(x?.admin1).includes(pNorm) || pNorm.includes(norm(x?.admin1))) ||
      results[0];
    const out = { lat: picked.latitude, lon: picked.longitude };
    geoCache.set(cacheKey, out);
    return out;
  }

  const out = { lat: results[0].latitude, lon: results[0].longitude };
  geoCache.set(cacheKey, out);
  return out;
}

async function geocodePlace(provinceName) {
  if (provinceName === "Toàn quốc") return { lat: 21.0278, lon: 105.8342 };

  return geocodeStrictVN(provinceName, provinceName);
}

async function fetchForecastForSelection(provinceName) {
  const loc = await geocodePlace(provinceName);
  const key = `wx|${provinceName}|${loc.lat},${loc.lon}`;
  if (forecastCache.has(key)) return forecastCache.get(key);

  if (currentForecastAbort) currentForecastAbort.abort();
  currentForecastAbort = new AbortController();

  const url =
    `http://localhost:5000/weather-proxy?lat=${loc.lat}&lon=${loc.lon}&days=8` +
    `&_fields=current,hourly,daily`;

  const res = await fetch(url, { signal: currentForecastAbort.signal });
  if (!res.ok) throw new Error(`Weather API lỗi: ${res.status}`);
  const data = await res.json();
  forecastCache.set(key, data);
  return data;
}

function ensureWeatherUI() {
  const wrapper = document.getElementById("weather-wrapper");
  if (!wrapper) return null;
  if (wrapper.dataset.ready === "1") return wrapper;

  wrapper.innerHTML = `
    <div class="weather-header-row">
      <div class="weather-title">DỰ BÁO THỜI TIẾT</div>
      <div class="weather-controls">
        <select id="weather-province" class="weather-select"></select>
      </div>
    </div>

    <div class="weather-top-cards">
      <div class="weather-top-card" id="w-card-current"></div>
      <div class="weather-top-card" id="w-card-today"></div>
      <div class="weather-top-card" id="w-card-night"></div>
    </div>

    <div class="weather-7d-header">DỰ BÁO THỜI TIẾT 7 NGÀY TỚI</div>
    <div class="weather-7d-strip" id="weather-7d"></div>
  `;

  wrapper.dataset.ready = "1";
  return wrapper;
}

function setWeatherLoading(message) {
  const currentCard = document.getElementById("w-card-current");
  const todayCard = document.getElementById("w-card-today");
  const nightCard = document.getElementById("w-card-night");
  const strip = document.getElementById("weather-7d");

  const msg = message || "Đang tải dữ liệu thời tiết...";
  const box = `
    <div class="weather-top-head"><span>THÔNG BÁO</span><span class="weather-updated"></span></div>
    <div class="weather-top-body">
      <div class="weather-icon">⏳</div>
      <div class="weather-metrics">
        <div class="weather-metric"><span class="k">Trạng thái</span><span class="v">${msg}</span></div>
      </div>
    </div>
  `;
  if (currentCard) currentCard.innerHTML = box;
  if (todayCard) todayCard.innerHTML = "";
  if (nightCard) nightCard.innerHTML = "";
  if (strip) strip.innerHTML = "";
}

function setWeatherError(message) {
  const currentCard = document.getElementById("w-card-current");
  const strip = document.getElementById("weather-7d");
  const msg = message || "Không tải được dữ liệu thời tiết.";
  const box = `
    <div class="weather-top-head"><span>LỖI</span><span class="weather-updated"></span></div>
    <div class="weather-top-body">
      <div class="weather-icon">⚠️</div>
      <div class="weather-metrics">
        <div class="weather-metric"><span class="k">Chi tiết</span><span class="v">${msg}</span></div>
      </div>
    </div>
  `;
  if (currentCard) currentCard.innerHTML = box;
  if (strip) strip.innerHTML = "";
}

function populateProvinceSelect(selected) {
  const select = document.getElementById("weather-province");
  if (!select) return;
  if (select.options.length === 0) {
    VN_PROVINCE_NAMES.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    });
  }
  select.value = selected;
}

function renderWeather(provinceName, data) {
  const daily = data?.daily;
  const current = data?.current;
  const hourly = data?.hourly;
  if (!daily?.time?.length) return;

  const days = Math.min(7, daily.time.length);

  const todayMax = daily.temperature_2m_max?.[0];
  const todayMin = daily.temperature_2m_min?.[0];
  const todayCode = daily.weathercode?.[0];
  const todayRainProb = daily.precipitation_probability_max?.[0];
  const todayWind = daily.windspeed_10m_max?.[0];

  let nightTemp = todayMin;
  let nightHum = undefined;
  let nightWind = undefined;
  let nightCode = todayCode;
  if (hourly?.time?.length) {
    const target = daily.time[0] + "T21:00";
    const idx = findNearestHourIndex(hourly.time, target);
    if (idx >= 0) {
      nightTemp = hourly.temperature_2m?.[idx] ?? nightTemp;
      nightHum = hourly.relative_humidity_2m?.[idx];
      nightWind = hourly.windspeed_10m?.[idx];
      nightCode = hourly.weathercode?.[idx] ?? nightCode;
    }
  }

  const curTemp = current?.temperature_2m;
  const curHum = current?.relative_humidity_2m;
  const curWind = current?.windspeed_10m;
  const curWindDir = current?.winddirection_10m;
  const curCode = current?.weathercode;

  const labelPlace = provinceName;

  const currentCard = document.getElementById("w-card-current");
  if (currentCard) {
    currentCard.innerHTML = `
      <div class="weather-top-head">
        <span>THỜI TIẾT HIỆN TẠI</span>
        <span class="weather-updated">${labelPlace}</span>
      </div>
      <div class="weather-top-body">
        <div class="weather-icon">${weatherCodeToIcon(curCode)}</div>
        <div class="weather-metrics">
          <div class="weather-metric"><span class="k">Nhiệt độ</span><span class="v">${typeof curTemp === "number" ? Math.round(curTemp) + "°C" : "—"}</span></div>
          <div class="weather-metric"><span class="k">Thời tiết</span><span class="v">${weatherCodeToText(curCode)}</span></div>
          <div class="weather-metric"><span class="k">Độ ẩm</span><span class="v">${typeof curHum === "number" ? curHum + "%" : "—"}</span></div>
          <div class="weather-metric"><span class="k">Gió</span><span class="v">${degToWindText(curWindDir)} • ${typeof curWind === "number" ? Math.round(curWind) + " km/h" : "—"}</span></div>
        </div>
      </div>
    `;
  }

  const todayCard = document.getElementById("w-card-today");
  if (todayCard) {
    todayCard.innerHTML = `
      <div class="weather-top-head">
        <span>DỰ BÁO NGÀY HÔM NAY</span>
        <span class="weather-updated">${formatDateLabel(daily.time[0], 0)}</span>
      </div>
      <div class="weather-top-body">
        <div class="weather-icon">${weatherCodeToIcon(todayCode)}</div>
        <div class="weather-metrics">
          <div class="weather-metric"><span class="k">Nhiệt độ</span><span class="v">${typeof todayMin === "number" && typeof todayMax === "number" ? `${Math.round(todayMin)}–${Math.round(todayMax)}°C` : "—"}</span></div>
          <div class="weather-metric"><span class="k">Thời tiết</span><span class="v">${weatherCodeToText(todayCode)}</span></div>
          <div class="weather-metric"><span class="k">Xác suất mưa</span><span class="v">${typeof todayRainProb === "number" ? todayRainProb + "%" : "—"}</span></div>
          <div class="weather-metric"><span class="k">Gió max</span><span class="v">${typeof todayWind === "number" ? Math.round(todayWind) + " km/h" : "—"}</span></div>
        </div>
      </div>
    `;
  }

  const nightCard = document.getElementById("w-card-night");
  if (nightCard) {
    nightCard.innerHTML = `
      <div class="weather-top-head">
        <span>DỰ BÁO ĐÊM HÔM NAY</span>
        <span class="weather-updated">21:00</span>
      </div>
      <div class="weather-top-body">
        <div class="weather-icon">${weatherCodeToIcon(nightCode, true)}</div>
        <div class="weather-metrics">
          <div class="weather-metric"><span class="k">Nhiệt độ</span><span class="v">${typeof nightTemp === "number" ? Math.round(nightTemp) + "°C" : "—"}</span></div>
          <div class="weather-metric"><span class="k">Thời tiết</span><span class="v">${weatherCodeToText(nightCode)}</span></div>
          <div class="weather-metric"><span class="k">Độ ẩm</span><span class="v">${typeof nightHum === "number" ? nightHum + "%" : "—"}</span></div>
          <div class="weather-metric"><span class="k">Gió</span><span class="v">${typeof nightWind === "number" ? Math.round(nightWind) + " km/h" : "—"}</span></div>
        </div>
      </div>
    `;
  }

  const strip = document.getElementById("weather-7d");
  if (strip) strip.innerHTML = "";
  for (let i = 0; i < days; i++) {
    const dLabel = i === 0 ? "Hôm nay" : new Date(daily.time[i]).toLocaleDateString("vi-VN", { weekday: "long" });
    const dDate = new Date(daily.time[i]).toLocaleDateString("vi-VN");
    const max = daily.temperature_2m_max?.[i];
    const min = daily.temperature_2m_min?.[i];
    const code = daily.weathercode?.[i];
    const pProb = daily.precipitation_probability_max?.[i];
    const pSum = daily.precipitation_sum?.[i];
    const w = daily.windspeed_10m_max?.[i];

    const el = document.createElement("div");
    el.className = "weather-day-card";
    el.innerHTML = `
      <div class="d">${dLabel}</div>
      <div class="dt">${dDate}</div>
      <div class="wi">
        <div class="weather-icon" style="width:38px;height:38px;border-radius:10px;font-size:20px;">${weatherCodeToIcon(code)}</div>
        <div>
          <div class="tmax">${typeof max === "number" ? Math.round(max) + "°C" : "—"}</div>
          <div class="tmin">${typeof min === "number" ? Math.round(min) + "°C" : "—"}</div>
        </div>
      </div>
      <div class="weather-mini">
        <div><span>💧 Mưa</span><span>${typeof pProb === "number" ? pProb + "%" : "—"}</span></div>
        <div><span>🌧️ Lượng</span><span>${typeof pSum === "number" ? pSum + " mm" : "—"}</span></div>
        <div><span>🌬️ Gió</span><span>${typeof w === "number" ? Math.round(w) + " km/h" : "—"}</span></div>
        <div><span>Trạng thái</span><span>${weatherCodeToText(code)}</span></div>
      </div>
    `;
    strip?.appendChild(el);
  }
}

async function refreshDistrictsForProvince(provinceName) {
  populateDistrictSelect(["Đang tải..."], "Đang tải...", false);

  if (provinceName === "Toàn quốc") {
    populateDistrictSelect(["Tất cả quận/huyện"], "Tất cả quận/huyện", false);
    state.district = "Tất cả quận/huyện";
    return;
  }

  try {
    const districts = await fetchDistrictsForProvince(provinceName);
    populateDistrictSelect(districts, "Tất cả quận/huyện", districts.length > 0);
    state.district = "Tất cả quận/huyện";
  } catch (e) {
    populateDistrictSelect(["Tất cả quận/huyện"], "Tất cả quận/huyện", false);
    state.district = "Tất cả quận/huyện";
  }
}

async function refreshForecast() {
  const p = state.province;
  const token = ++currentRequestToken;

  setWeatherLoading(`Đang tải: ${p}`);

  try {
    const data = await fetchForecastForSelection(p);
    if (token !== currentRequestToken) return;
    renderWeather(p, data);
  } catch (err) {
    if (err?.name === "AbortError") return;
    if (token !== currentRequestToken) return;
    setWeatherError(`Không lấy được thời tiết cho "${p}".`);
    console.error("[WEATHER] Forecast lỗi", p, err);
  }
}

async function initWeather() {
  const wrapper = ensureWeatherUI();
  if (!wrapper) return;
  state = { province: "Hà Nội" };
  populateProvinceSelect(state.province);
  await refreshForecast();

  const provinceSelect = document.getElementById("weather-province");

  if (provinceSelect) {
    provinceSelect.onchange = async () => {
      state.province = provinceSelect.value || "Hà Nội";
      await refreshForecast();
    };
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initWeather);
} else {
  initWeather();
}

