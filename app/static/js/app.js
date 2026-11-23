/* iKhaya KZN — single-page front end (heritage explorer + trip planner) */
(() => {
    "use strict";

    // ------------------------------------------------------------------ config
    const HERITAGE = [
        { id: "clans",   label: "Clans",   emoji: "🛡️", color: "#c2562b", blurb: "Find your surname, izithakazelo and origins" },
        { id: "herbs",   label: "Herbs",   emoji: "🌿", color: "#2e8b57", blurb: "Medicinal plants of traditional healing" },
        { id: "foods",   label: "Foods",   emoji: "🍲", color: "#e0a526", blurb: "Beloved dishes of the Zulu table" },
        { id: "rituals", label: "Rituals", emoji: "✨", color: "#d6457b", blurb: "Ceremonies that mark life's milestones" },
        { id: "dance",   label: "Dance",   emoji: "🥁", color: "#1f5f8b", blurb: "Rhythm, song and celebration" },
        { id: "dress",   label: "Dress",   emoji: "👗", color: "#c2562b", blurb: "Attire that tells a story" },
        { id: "beads",   label: "Beads",   emoji: "📿", color: "#e0a526", blurb: "The colourful language of beadwork" },
        { id: "places",  label: "Places",  emoji: "📍", color: "#2e8b57", blurb: "Sites preserving Zulu history" },
    ];
    const CATEGORY_EMOJI = {
        All: "🗺️", Beach: "🏖️", Nature: "🌿", Adventure: "🧗", Culture: "🏛️",
        Food: "🥘", Shopping: "🛍️", Entertainment: "🎉", Nightlife: "🌙", Stay: "🛏️",
    };
    const PAGE = 12;
    const FALLBACK_IMG = "data:image/svg+xml;utf8," + encodeURIComponent(
        `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 160 100' preserveAspectRatio='xMidYMid slice'>
           <rect width='160' height='100' fill='#f3ead8'/>
           <g fill='#e0a526' opacity='.55'><path d='M0 100 20 60 40 100z'/><path d='M40 100 60 60 80 100z'/><path d='M80 100 100 60 120 100z'/><path d='M120 100 140 60 160 100z'/></g>
           <g fill='#c2562b' opacity='.55'><path d='M20 60 30 40 40 60z'/><path d='M60 60 70 40 80 60z'/><path d='M100 60 110 40 120 60z'/><path d='M140 60 150 40 160 60z'/></g>
         </svg>`);

    const state = {
        cache: {},                                   // heritage json by section
        categories: null,
        filters: null,
        trip: { category: "All", loadshedding: "auto", indoor: false, price: "", subcategory: "", region: "",
                openNow: false, openLate: false, vibe: "", mix: false, at: "", date: "", limit: PAGE, loc: null },
        map: null, clanMap: null, layer: null, markers: [], stayLimits: {}, places: new Map(),
        token: 0,                                    // guards against stale async renders
    };

    // ------------------------------------------------------------------ utils
    const $ = (sel, root = document) => root.querySelector(sel);
    const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
    const view = $("#view");

    // ---- page title and description, kept in step with the hash route (tabs, history, link previews)
    const SITE = "iKhaya KZN";
    const DEFAULT_TITLE = `${SITE} · Zulu heritage & KwaZulu-Natal trip planner`;
    const DEFAULT_DESCRIPTION = "Explore Zulu clans, herbs, foods and ceremonies, then plan a KwaZulu-Natal trip that adapts to today's weather, time of day and load-shedding.";
    function setMeta(title, description = DEFAULT_DESCRIPTION) {
        const full = title ? `${title} · ${SITE}` : DEFAULT_TITLE;
        document.title = full;
        const set = (selector, value) => { const el = document.querySelector(selector); if (el) el.setAttribute("content", value); };
        set('meta[name="description"]', description);
        set('meta[property="og:title"]', full);
        set('meta[property="og:description"]', description);
        set('meta[property="og:url"]', location.href);
        set('meta[name="twitter:title"]', full);
        set('meta[name="twitter:description"]', description);
    }
    const TRIP_META = {
        All: ["Plan a trip in KwaZulu-Natal", "Places across KwaZulu-Natal ranked for the weather, time of day and load-shedding on the day you choose."],
        Nightlife: ["Nightlife in KwaZulu-Natal", "Bars, pubs, clubs and more across KwaZulu-Natal, ranked for the time of day, with opening hours where they are known."],
        Entertainment: ["Entertainment in KwaZulu-Natal", "Cinemas, theatres, casinos, water parks and more across KwaZulu-Natal, ranked for the weather and time of day."],
        Stay: ["Places to stay in KwaZulu-Natal", "Hotels, guest houses, hostels, chalets and camp sites across KwaZulu-Natal, grouped by region."],
    };
    const tripMeta = (category) => TRIP_META[category]
        || [`Plan a trip: ${category}`, `${category} places across KwaZulu-Natal, ranked for the weather, time of day and load-shedding.`];

    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

    async function api(path) {
        const res = await fetch(path, { headers: { Accept: "application/json" } });
        if (!res.ok) throw new Error(`${path} → ${res.status}`);
        return res.json();
    }

    const img = (src, alt) =>
        `<img src="${esc(src || FALLBACK_IMG)}" alt="${esc(alt)}" loading="lazy" decoding="async">`;

    // swap any broken image for the bead-pattern placeholder
    document.addEventListener("error", (e) => {
        const t = e.target;
        if (t.tagName === "IMG" && t.src !== FALLBACK_IMG && !t.dataset.fallback) {
            t.dataset.fallback = "1";
            t.src = FALLBACK_IMG;
        }
    }, true);

    const weatherEmoji = { sun: "☀️", "cloud-sun": "⛅", cloud: "☁️", fog: "🌫️", rain: "🌧️", storm: "⛈️", snow: "❄️" };

    function setView(html) {
        view.innerHTML = html;
        window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
    }
    const loading = (msg = "Loading…") =>
        `<div class="loading"><div class="spinner"></div>${esc(msg)}</div>`;
    const failure = (msg) =>
        `<div class="wrap section"><div class="empty"><h3>Something went wrong</h3><p>${esc(msg)}</p>
         <p style="margin-top:1rem"><a class="btn btn-dark btn-sm" href="#/">Back home</a></p></div></div>`;

    // ------------------------------------------------------------------ router
    function parseHash() {
        const raw = location.hash.replace(/^#/, "") || "/";
        const [path, qs = ""] = raw.split("?");
        return { parts: path.split("/").filter(Boolean), query: new URLSearchParams(qs) };
    }

    function highlightNav(name, section) {
        $$(".main-nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === name));
        const sub = $("#subnav");
        sub.hidden = name !== "heritage";
        if (name === "heritage") {
            $("#subnav-links").innerHTML = HERITAGE.map((s) =>
                `<a href="#/heritage/${s.id}" class="${s.id === section ? "active" : ""}">${s.emoji} ${s.label}</a>`).join("");
            const active = $("#subnav-links a.active");
            if (active) active.scrollIntoView({ inline: "center", block: "nearest" });
        }
    }

    async function route() {
        const { parts, query } = parseHash();
        const token = ++state.token;
        destroyMap();
        try {
            if (parts[0] === "heritage") {
                const id = HERITAGE.some((s) => s.id === parts[1]) ? parts[1] : "clans";
                highlightNav("heritage", id);
                const sec = HERITAGE.find((x) => x.id === id);
                setMeta(id === "clans" ? "Surname & clan explorer" : `${sec.label}: Zulu heritage`, `${sec.blurb}.`);
                await renderHeritage(id, token, query.get("q"));
            } else if (parts[0] === "itinerary") {
                highlightNav("itinerary");
                setMeta("My trip", "Your saved places grouped by day, with approximate straight-line distances. Saved in this browser only.");
                renderItinerary(token);
            } else if (parts[0] === "info") {
                highlightNav("info");
                setMeta("Travel info for KwaZulu-Natal", "Emergency numbers, getting around, money and tipping, SIM cards, etiquette, and load-shedding and water-outage tips for visitors.");
                await renderInfo(token);
            } else if (parts[0] === "trip") {
                highlightNav("trip");
                if (query.get("category")) state.trip.category = query.get("category");
                const lat = parseFloat(query.get("lat")), lon = parseFloat(query.get("lon"));
                if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
                    // arriving from a clan page: start from the clan's origin instead of Durban
                    state.trip.loc = { lat, lon, label: (query.get("from") || "").slice(0, 80) || null };
                    state.trip.category = query.get("category") || "All";
                }
                setMeta(...tripMeta(state.trip.category));
                await renderTrip(token);
            } else {
                highlightNav("home");
                setMeta("");
                await renderHome(token);
            }
        } catch (err) {
            console.error(err);
            if (token === state.token) setView(failure("We couldn't load that page. Is the server running?"));
        }
    }

    // ------------------------------------------------------------------ home
    async function renderHome(token) {
        setView(`
        <section class="hero">
          <div class="hero-inner">
            <div>
              <p class="eyebrow hero-eyebrow">Zulu heritage · KwaZulu-Natal</p>
              <h1 class="h-display">Know where you come from. <em>Discover where to go.</em></h1>
              <p class="lead">Trace your clan, explore the herbs, foods and ceremonies of the Zulu people, then plan a KZN trip that adapts to today's weather and power cuts.</p>
              <div class="hero-actions">
                <a class="btn btn-primary" href="#/heritage/clans">Explore heritage</a>
                <a class="btn btn-ghost" href="#/trip">Plan a trip →</a>
              </div>
            </div>
            <aside class="live-card" aria-label="Right now in KZN">
              <h2>Right now in Durban</h2>
              <div id="home-live">${loading("Checking the sky…")}</div>
            </aside>
          </div>
        </section>

        <section class="section">
          <div class="wrap">
            <p class="eyebrow">Heritage</p>
            <div class="row-head"><h2 class="h-display">Eight ways into the culture</h2></div>
            <div class="tile-grid">
              ${HERITAGE.map((s) => `
                <a class="tile" href="#/heritage/${s.id}" style="--tile:${s.color}">
                  <span class="tile-emoji">${s.emoji}</span>
                  <h3>${s.label}</h3>
                  <p>${esc(s.blurb)}</p>
                </a>`).join("")}
            </div>
          </div>
        </section>

        <section class="section band">
          <div class="wrap">
            <p class="eyebrow">Trip planner</p>
            <div class="row-head">
              <h2 class="h-display">Today's best picks</h2>
              <a class="link-arrow" href="#/trip">See all recommendations →</a>
            </div>
            <div class="grid" id="home-picks" style="margin-top:1.6rem">
              ${'<div class="skeleton"></div>'.repeat(3)}
            </div>
          </div>
        </section>

        <section class="section">
          <div class="wrap">
            <p class="eyebrow">How it works</p>
            <h2 class="h-display">Heritage and travel, together</h2>
            <div class="steps">
              <div class="step"><div class="num">1</div><h3>Learn the story</h3><p>Browse clans, healing herbs, food, ceremonies, dance, dress and beadwork.</p></div>
              <div class="step"><div class="num">2</div><h3>We check conditions</h3><p>Live weather and power status shape every recommendation.</p></div>
              <div class="step"><div class="num">3</div><h3>Visit the places</h3><p>From cultural villages to beaches, see ranked picks with a clear reason for each.</p></div>
            </div>
          </div>
        </section>`);

        // live context + picks load independently so the page appears instantly
        api("/api/recommend?limit=3&tourist=1").then((data) => {   // tourist mode: three different kinds of place
            if (token !== state.token) return;
            $("#home-live").innerHTML = contextRows(data.context);
            $("#home-picks").innerHTML = data.results.map((p, i) => tripCard(p, i)).join("") ||
                `<div class="empty">No places yet.</div>`;
        }).catch(() => {
            if (token !== state.token) return;
            $("#home-live").innerHTML = `<p>Live conditions are unavailable right now.</p>`;
            $("#home-picks").innerHTML = `<div class="empty">Recommendations are unavailable right now.</div>`;
        });
    }

    function contextRows(ctx) {
        const w = ctx.weather;
        return `
        <div class="live-row"><div class="live-icon">${weatherEmoji[w.icon] || "🌤️"}</div>
          <div><strong>${esc(w.condition)} · ${Math.round(w.temp_c)}°C</strong>
          <span>${esc(w.advice)}${w.source === "fallback" ? " (offline estimate)" : ""}</span></div></div>
        <div class="live-row"><div class="live-icon">${ctx.loadshedding ? "⚡" : "💡"}</div>
          <div><strong>${ctx.loadshedding ? "Load-shedding likely" : "Power looks stable"}<span class="sim-tag" title="No live Eskom feed: this follows a made-up evening schedule">Simulated</span></strong>
          <span>Made-up schedule: evenings 18:00–21:00 South African time</span></div></div>`;
    }

    // ------------------------------------------------------------------ heritage
    async function loadSection(id) {
        if (!state.cache[id]) state.cache[id] = await api(`/api/heritage/${id}`);
        return state.cache[id];
    }

    async function renderHeritage(id, token, q) {
        setView(loading());
        const data = await loadSection(id);
        if (token !== state.token) return;
        const meta = HERITAGE.find((s) => s.id === id);
        if (id === "clans") return renderClans(data.clans, q);

        setView(`
        <div class="wrap">
          <div class="page-head">
            <p class="eyebrow">${meta.emoji} Heritage</p>
            <h1 class="h-display">${esc(data.title)}</h1>
            <p>${esc(data.subtitle)}</p>
          </div>
          <div class="toolbar">
            <label class="search">
              <input id="filter" type="search" aria-label="Search" placeholder="Search ${esc(meta.label.toLowerCase())}…" autocomplete="off"></label>
            <span class="count" id="count"></span>
          </div>
          <div class="grid" id="list"></div>
        </div>`);

        const draw = (q = "") => {
            const needle = q.trim().toLowerCase();
            const items = data.items.filter((it) =>
                !needle || [it.name, it.isizulu, it.desc, it.infoBoxText].some((t) => String(t || "").toLowerCase().includes(needle)));
            $("#count").textContent = `${items.length} of ${data.items.length}`;
            $("#list").innerHTML = items.length
                ? items.map((it, i) => heritageCard(it, id, i)).join("")
                : `<div class="empty" style="grid-column:1/-1">Nothing matches “${esc(q)}”.</div>`;
        };
        draw();
        $("#filter").addEventListener("input", (e) => draw(e.target.value));
    }

    function heritageCard(it, section, i) {
        const type = ["green", "orange", "blue"].includes(it.infoBoxType) ? it.infoBoxType : "green";
        const visit = section === "places"
            ? `<a class="btn btn-dark btn-sm" href="#/trip?category=Culture">Plan a visit →</a>`
            : `<span class="pill good">Public heritage</span>`;
        return `
        <article class="card" style="animation-delay:${Math.min(i, 8) * 40}ms">
          <div class="card-media">${img(it.image, it.name)}</div>
          <div class="card-body">
            <h3 class="card-title">${esc(it.name)}</h3>
            ${it.isizulu ? `<div class="card-sub">${esc(it.isizulu)}</div>` : ""}
            <p class="card-desc">${esc(it.desc)}</p>
            ${it.infoBoxText ? `<div class="note ${type}"><b>${esc(it.infoBoxTitle)}</b>${esc(it.infoBoxText)}</div>` : ""}
            <div class="card-foot">${visit}<span>📖 ${esc(it.attribution)}</span></div>
          </div>
        </article>`;
    }

    // ------------------------------------------------------------------ itinerary (kept in this browser only)
    const TRIP_KEY = "ikhaya.itinerary.v1";
    const MAX_TRIP_ITEMS = 60;
    const MAX_TRIP_DAYS = 14;
    let tripData = { start: "", days: [[]] };            // days: arrays of saved places

    const clip = (v, n) => String(v ?? "").slice(0, n);
    const fmtDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-ZA", { weekday: "short", day: "numeric", month: "short" });
    const addDays = (iso, n) => { const d = new Date(`${iso}T12:00:00`); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };

    /** Rebuild a saved place from untrusted storage: right types, sane ranges, clipped text. */
    function cleanItem(raw) {
        if (!raw || typeof raw !== "object") return null;
        const id = Number(raw.id), lat = Number(raw.lat), lon = Number(raw.lon);
        if (![id, lat, lon].every(Number.isFinite) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
        const name = clip(raw.name, 150).trim();
        if (!name) return null;
        return {
            id, name, lat, lon, category: clip(raw.category, 40), sub: clip(raw.sub, 60), region: clip(raw.region, 40),
            address: clip(raw.address, 200), hours: clip(raw.hours, 255),
            phone: /^[0-9+()\-. /]{5,40}$/.test(String(raw.phone || "")) ? String(raw.phone) : "",
        };
    }

    function tripLoad() {
        try {
            const raw = JSON.parse(localStorage.getItem(TRIP_KEY) || "null");
            if (raw && Array.isArray(raw.days)) {
                const seen = new Set();
                const days = raw.days.slice(0, MAX_TRIP_DAYS).map((d) => (Array.isArray(d) ? d : []).map(cleanItem)
                    .filter((i) => i && !seen.has(i.id) && seen.add(i.id)).slice(0, MAX_TRIP_ITEMS));
                tripData = { start: /^\d{4}-\d{2}-\d{2}$/.test(String(raw.start || "")) ? raw.start : "", days: days.length ? days : [[]] };
            }
        } catch { /* storage unavailable or corrupt: start with an empty trip */ }
    }
    function tripSave() {
        try { localStorage.setItem(TRIP_KEY, JSON.stringify(tripData)); } catch { /* private mode: the trip lasts for this visit only */ }
        updateTripBadge();
    }
    const tripItems = () => tripData.days.flat();
    const tripHas = (id) => tripItems().some((i) => i.id === id);

    function tripAdd(p) {
        if (tripHas(p.id)) return false;
        if (tripItems().length >= MAX_TRIP_ITEMS) { showToast(`Your trip is full (${MAX_TRIP_ITEMS} places).`); return false; }
        const item = cleanItem({
            id: p.id, name: p.name, lat: p.latitude, lon: p.longitude, category: p.category, sub: p.subcategory_label,
            region: p.region, address: p.address, hours: p.opening_hours_raw || p.opening_hours, phone: p.phone,
        });
        if (!item) return false;
        tripData.days[tripData.days.length - 1].push(item);
        tripSave();
        return true;
    }
    function tripRemove(id) {
        tripData.days = tripData.days.map((d) => d.filter((i) => i.id !== id));
        tripSave();
    }
    function tripMove(id, toDay) {
        const item = tripItems().find((i) => i.id === id);
        if (!item || !tripData.days[toDay]) return;
        tripData.days = tripData.days.map((d) => d.filter((i) => i.id !== id));
        tripData.days[toDay].push(item);
        tripSave();
    }
    function tripShift(id, step) {
        for (const day of tripData.days) {
            const i = day.findIndex((x) => x.id === id), j = i + step;
            if (i >= 0 && j >= 0 && j < day.length) { [day[i], day[j]] = [day[j], day[i]]; tripSave(); return; }
        }
    }
    function tripAddDay() {
        if (tripData.days.length < MAX_TRIP_DAYS) { tripData.days.push([]); tripSave(); }
    }

    function updateTripBadge() {
        const badge = $("#trip-badge");
        if (!badge) return;
        const n = tripItems().length;
        badge.hidden = n === 0;
        badge.textContent = String(n);
    }

    let toastTimer = null;
    function showToast(message) {
        const el = $("#toast");
        if (!el) return;
        el.textContent = message;
        el.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
    }

    function syncTripButton(btn, id) {
        const inTrip = tripHas(id);
        btn.textContent = inTrip ? "✓ In trip" : "＋ Trip";
        btn.classList.toggle("btn-in", inTrip);
        btn.classList.toggle("btn-dark", !inTrip);
        btn.setAttribute("aria-pressed", String(inTrip));
    }

    // one handler for every "+ Trip" button, wherever the card is shown
    document.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-trip]");
        if (!btn) return;
        const id = Number(btn.dataset.trip);
        if (tripHas(id)) {
            tripRemove(id);
            showToast("Removed from your trip");
        } else {
            const place = state.places.get(id);
            if (place && tripAdd(place)) showToast(`Added to Day ${tripData.days.length}. Open My trip to plan it.`);
        }
        $$(`[data-trip="${id}"]`).forEach((b) => syncTripButton(b, id));
    });

    /** Straight-line distance between two points (great circle). It is NOT a driving distance. */
    function straightKm(a, b) {
        const rad = (d) => (d * Math.PI) / 180;
        const dLat = rad(b.lat - a.lat), dLon = rad(b.lon - a.lon);
        const x = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
        return 2 * 6371 * Math.asin(Math.sqrt(x));
    }
    const fmtKm = (km) => (km < 10 ? km.toFixed(1) : String(Math.round(km)));

    const forecastCache = new Map();
    function forecastFor(lat, lon) {
        const key = `${lat.toFixed(1)},${lon.toFixed(1)}`;
        if (!forecastCache.has(key)) {
            forecastCache.set(key, api(`/api/forecast?lat=${lat}&lon=${lon}`).catch(() => ({ days: [] })));
        }
        return forecastCache.get(key);
    }

    function renderItinerary(token) {
        const items = tripItems();
        const rerender = () => renderItinerary(token);

        const actions = h("div", { class: "it-actions no-print" },
            h("label", { class: "field" }, "First day of your trip",
                h("input", {
                    type: "date", id: "trip-start", value: tripData.start || "",
                    onchange: (e) => { tripData.start = /^\d{4}-\d{2}-\d{2}$/.test(e.target.value) ? e.target.value : ""; tripSave(); rerender(); },
                })),
            h("button", { class: "btn btn-dark btn-sm", type: "button", text: "＋ Add a day", onclick: () => { tripAddDay(); rerender(); } }),
            h("button", { class: "btn btn-dark btn-sm", type: "button", text: "🖨️ Print", onclick: () => window.print() }),
            items.length ? h("button", {
                class: "link-btn", type: "button", text: "Clear trip",
                onclick: () => { if (confirm("Remove every place from your trip?")) { tripData = { start: tripData.start, days: [[]] }; tripSave(); rerender(); } },
            }) : null);

        const days = tripData.days.map((day, di) => {
            const iso = tripData.start ? addDays(tripData.start, di) : "";
            let total = 0;
            const rows = day.map((it, ii) => {
                const prev = ii > 0 ? day[ii - 1] : null;
                let leg = null;
                if (prev) {
                    const km = straightKm(prev, it);
                    total += km;
                    leg = h("li", { class: "it-leg", "aria-label": "Approximate straight-line distance" },
                        `↓ about ${fmtKm(km)} km in a straight line (approximate)`);
                }
                const meta = [it.sub || it.category, it.region, it.address].filter(Boolean).join(" · ");
                const row = h("li", { class: "it-item" },
                    h("span", { class: "it-num", text: String(ii + 1) }),
                    h("div", { class: "it-body" },
                        h("strong", { text: it.name }),
                        meta ? h("span", { class: "muted", text: meta }) : null,
                        it.hours ? h("span", { class: "muted", text: `🕒 ${it.hours}` }) : null,
                        it.phone ? h("a", { href: `tel:${it.phone.replace(/[^0-9+]/g, "")}`, text: `📞 ${it.phone}` }) : null),
                    h("div", { class: "it-controls no-print" },
                        h("button", { class: "icon-btn", type: "button", title: "Move up", "aria-label": `Move ${it.name} up`, disabled: ii === 0, text: "↑", onclick: () => { tripShift(it.id, -1); rerender(); } }),
                        h("button", { class: "icon-btn", type: "button", title: "Move down", "aria-label": `Move ${it.name} down`, disabled: ii === day.length - 1, text: "↓", onclick: () => { tripShift(it.id, 1); rerender(); } }),
                        h("select", {
                            "aria-label": `Move ${it.name} to another day`,
                            onchange: (e) => { tripMove(it.id, Number(e.target.value)); rerender(); },
                        }, tripData.days.map((_, k) => h("option", { value: String(k), selected: k === di, text: `Day ${k + 1}` }))),
                        h("button", { class: "icon-btn", type: "button", title: "Remove", "aria-label": `Remove ${it.name}`, text: "✕", onclick: () => { tripRemove(it.id); rerender(); } })));
                return [leg, row];
            });
            const forecastSlot = h("span", { class: "it-forecast muted" });
            if (iso && day.length) {
                forecastFor(day[0].lat, day[0].lon).then((data) => {
                    const f = (data.days || []).find((x) => x.date === iso);
                    if (f && token === state.token) {
                        forecastSlot.textContent = `${weatherEmoji[f.icon] || "🌤️"} ${f.condition}, ${Math.round(f.temp_c)}°C${f.rain_chance_pct != null ? `, ${f.rain_chance_pct}% chance of rain` : ""} (forecast)`;
                    }
                });
            }
            return h("section", { class: "it-day" },
                h("header", { class: "it-day-head" },
                    h("h2", { class: "h-display", text: iso ? `Day ${di + 1} · ${fmtDay(iso)}` : `Day ${di + 1}` }),
                    day.length > 1 ? h("span", { class: "pill", title: "Sum of the straight-line distances between stops: not a driving distance", text: `≈ ${fmtKm(total)} km between stops (approximate)` }) : null,
                    forecastSlot),
                day.length ? h("ol", { class: "it-list" }, rows.flat()) : h("p", { class: "muted it-empty", text: "Nothing planned for this day yet." }));
        });

        view.replaceChildren(h("div", { class: "wrap" },
            h("div", { class: "page-head" },
                h("p", { class: "eyebrow", text: "🧳 Itinerary" }),
                h("h1", { class: "h-display", text: "My trip" }),
                h("p", { class: "no-print", text: "Add places from the planner with the ＋ Trip button, then arrange them by day. Your trip is saved in this browser only." })),
            h("p", { class: "print-only", text: "Printed from iKhaya KZN. Details can be out of date: check opening hours before you go." }),
            items.length ? actions : null,
            items.length ? days : h("div", { class: "empty" },
                h("p", { text: "Your trip is empty." }),
                h("p", { style: "margin-top:1rem" }, h("a", { class: "btn btn-dark btn-sm", href: "#/trip", text: "Find places to add" }))),
            items.length ? h("p", { class: "notice it-note" },
                "Distances are straight-line estimates between places, not driving distances or travel times. ",
                "Opening hours and other details come from the places' listings and may be out of date, so check before you go.") : null));
        window.scrollTo({ top: 0 });
    }

    // ------------------------------------------------------------------ travel info
    async function renderInfo(token) {
        setView(loading());
        const data = await api("/api/info");
        if (token !== state.token) return;
        const checkPill = () => h("span", { class: "pill warn", title: "This can change or vary by place: confirm it with your host, the venue or the local authority", text: "Check locally" });

        const sections = data.sections.map((sec) => {
            const numbers = (sec.numbers || []).filter((n) => /^\d{3,6}$/.test(String(n.number))).map((n) =>
                h("a", { class: "call-card", href: `tel:${n.number}` },
                    h("strong", { class: "call-num", text: n.number }),
                    h("span", { text: n.label }),
                    n.note ? h("small", { class: "muted", text: n.note }) : null));
            const items = (sec.items || []).map((it) =>
                h("article", { class: "info-card" },
                    h("h3", { text: it.title }),
                    h("p", { text: it.text }),
                    it.check ? checkPill() : null));
            const link = sec.link && /^#\//.test(sec.link.href)
                ? h("p", { class: "info-link" }, h("a", { class: "btn btn-dark btn-sm", href: sec.link.href, text: sec.link.text })) : null;
            return h("section", { class: "info-section", id: `info-${sec.id}` },
                h("h2", { class: "h-display", text: `${sec.icon} ${sec.title}` }),
                sec.intro ? h("p", { class: "muted", text: sec.intro }) : null,
                numbers.length ? h("div", { class: "call-grid" }, numbers) : null,
                items.length ? h("div", { class: "info-grid" }, items) : null,
                link);
        });

        const toc = data.sections.map((sec) => h("button", {
            class: "chip chip-sm", type: "button", text: `${sec.icon} ${sec.title}`,
            onclick: () => { const el = document.getElementById(`info-${sec.id}`); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); },
        }));

        view.replaceChildren(h("div", { class: "wrap" },
            h("div", { class: "page-head" },
                h("p", { class: "eyebrow", text: "ℹ️ Before and during your trip" }),
                h("h1", { class: "h-display", text: data.title }),
                h("p", { text: data.subtitle })),
            h("p", { class: "notice", text: data.disclaimer }),
            h("div", { class: "chips info-toc", role: "navigation", "aria-label": "Sections" }, toc),
            sections));
        window.scrollTo({ top: 0 });
    }

    // ------------------------------------------------------------------ clans
    // Everything on this page is built with DOM nodes + textContent (never innerHTML with data),
    // so surnames, search terms and API text can't inject markup.
    const CONFIDENCE = {
        verified: ["Verified", "good"],
        "oral-tradition": ["Oral tradition", "info"],
        unverified: ["Unverified", "warn"],
    };
    const normKey = (s) => String(s ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "")
        .toLowerCase().replace(/[^a-z0-9]/g, "");
    const validCoords = (o) => o && [o.lat, o.lng].every((n) => typeof n === "number" && Number.isFinite(n)) &&
        Math.abs(o.lat) <= 90 && Math.abs(o.lng) <= 180;
    const hasItems = (a) => Array.isArray(a) && a.length > 0;

    /** Tiny element builder: h("div", {class: "x", text: "hi", onclick: fn}, child, ...) */
    function h(tag, props = {}, ...kids) {
        const el = document.createElement(tag);
        for (const [k, v] of Object.entries(props)) {
            if (v == null || v === false) continue;
            if (k === "class") el.className = v;
            else if (k === "text") el.textContent = v;
            else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
            else el.setAttribute(k, v === true ? "" : v);
        }
        for (const kid of kids.flat()) {
            if (kid != null && kid !== false) el.append(kid);   // strings become text nodes
        }
        return el;
    }

    /** A titled section, or null when there is nothing to show (so empty headings never appear). */
    function section(title, ...content) {
        const body = content.flat().filter(Boolean);
        return body.length ? h("section", { class: "clan-section" }, h("h4", { text: title }), body) : null;
    }
    const field = (label, value) => value
        ? h("p", { class: "clan-field" }, h("b", { text: label }), " ", value) : null;

    function destroyClanMap() {
        if (state.clanMap) { state.clanMap.remove(); state.clanMap = null; }
    }

    function renderClans(clans, initialQuery) {
        const sorted = [...clans].sort((a, b) => a.surname.localeCompare(b.surname));
        const letters = new Set(sorted.map((c) => c.surname[0].toUpperCase()));
        const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
        let letter = "";
        let searchSeq = 0;

        setView(`
        <div class="wrap">
          <div class="page-head">
            <p class="eyebrow">🛡️ Heritage</p>
            <h1 class="h-display">Surname &amp; Clan Explorer</h1>
            <p>Search a Zulu surname, or a praise name (isithakazelo) to see which clans use it.</p>
          </div>
          <form class="clan-search" id="clan-form" autocomplete="off" role="search">
            <div class="clan-field-wrap">
              <input id="clan-input" type="text" maxlength="80" placeholder="e.g. Ndlovu, Buthelezi, Mpangazitha"
                     aria-label="Surname or praise name" role="combobox" aria-expanded="false"
                     aria-controls="clan-suggest" aria-autocomplete="list" autocapitalize="words" spellcheck="false">
              <ul id="clan-suggest" class="suggest" role="listbox" hidden></ul>
            </div>
            <button class="btn btn-dark" type="submit">Search</button>
          </form>
          <p class="clan-disclaimer">ℹ️ Clan histories vary between families and regions.</p>
          <div class="clan-result" id="clan-result" aria-live="polite"></div>
          <section class="directory">
            <h3>📚 A–Z clan directory <span class="muted" style="font-size:.85rem;font-family:var(--font-body)">(${sorted.length} surnames)</span></h3>
            <div class="az" id="az"></div>
            <div class="surnames" id="surnames"></div>
          </section>
        </div>`);

        const input = $("#clan-input");
        const box = $("#clan-result");
        const list = $("#clan-suggest");

        // ---- search + result rendering ----
        const openClan = (name) => { input.value = name; closeSuggest(); runSearch(name, true); };

        async function runSearch(q, scroll = false) {
            q = q.trim();
            const mine = ++searchSeq;
            if (!q) {
                box.replaceChildren();
                destroyClanMap();
                return;
            }
            box.replaceChildren(h("div", { class: "loading" }, h("div", { class: "spinner" }), "Searching…"));
            try {
                const res = await api(`/api/heritage/clans/search?q=${encodeURIComponent(q)}`);
                const record = res.surname_match
                    ? await api(`/api/heritage/clans/${encodeURIComponent(res.surname_match.surname)}`) : null;
                if (mine !== searchSeq || !box.isConnected) return;

                destroyClanMap();
                const nodes = [];
                let mount = null;
                if (record) {
                    const built = buildRecord(record);
                    nodes.push(built.node);
                    mount = built.mount;
                }
                if (res.praise_match) {
                    const others = res.praise_match.clans.filter((c) => !record || c.surname !== record.surname);
                    if (others.length) nodes.push(sharedBlock(res.praise_match.name, others, Boolean(record)));
                }
                if (!nodes.length) nodes.push(notFound(q, res.did_you_mean));

                box.replaceChildren(...nodes);
                if (mount) mount();
                if (record) setMeta(`${record.surname} clan`, `Izithakazelo (praise names) and origins for the ${record.surname} surname.`);
                if (location.hash.startsWith("#/heritage/clans")) {
                    history.replaceState(null, "", `#/heritage/clans?q=${encodeURIComponent(q)}`);
                }
                if (scroll) box.scrollIntoView({ behavior: "smooth", block: "start" });
            } catch (err) {
                console.error(err);
                if (mine === searchSeq) box.replaceChildren(h("div", { class: "empty", text: "We couldn't search right now. Please try again." }));
            }
        }

        function notFound(q, suggestions) {
            const chips = (suggestions || []).map((s) =>
                h("button", { class: "chip", type: "button", onclick: () => openClan(s.text) },
                    s.text, s.kind === "praise_name" ? h("small", { text: "praise name" }) : null));
            return h("div", { class: "empty" },
                h("strong", { text: "No clan found for “" + q + "”." }), h("br"),
                chips.length ? "Did you mean:" : "We're always adding records. Try Ndlovu, Buthelezi or Zulu.",
                chips.length ? h("div", { class: "chips clan-did-you-mean" }, chips) : null);
        }

        function sharedBlock(name, clansUsing, alsoSurname) {
            return h("section", { class: "clan-shared" },
                h("h4", { text: alsoSurname ? `Other clans that use the praise name “${name}”` : `Clans that use the praise name “${name}”` }),
                h("div", { class: "chips" }, clansUsing.map((c) =>
                    h("button", { class: "chip", type: "button", onclick: () => openClan(c.surname), text: c.surname }))));
        }

        function buildRecord(rec) {
            const e = rec.enrichment;
            const o = e.origin || {};

            // Izithakazelo: every praise name is its own chip; a note shows under it when we have one.
            const notes = new Map((e.izithakazelo_notes || []).map((n) => [normKey(n.name), n.note]));
            const names = [...rec.praise_names];
            (e.izithakazelo_notes || []).forEach((n) => { if (!names.some((x) => normKey(x) === normKey(n.name))) names.push(n.name); });
            const praise = names.length ? h("ul", { class: "praise-list" }, names.map((name) => {
                const note = notes.get(normKey(name));
                return h("li", { class: "praise" + (note ? " has-note" : "") },
                    h("button", {
                        class: "chip praise-chip", type: "button", text: name,
                        title: "See which clans use this praise name",
                        onclick: () => { input.value = name; runSearch(name, true); },
                    }),
                    note ? h("p", { class: "praise-note", text: note }) : null);
            })) : null;

            const meaning = section("📖 Meaning & ancestor",
                field("Meaning", e.meaning), field("Ancestor", e.ancestor), field("Totem & taboos", e.taboos_or_totem));

            const mapNode = validCoords(o) && window.L ? h("div", { class: "clan-map", id: "clan-map", role: "img", "aria-label": `Map pin for the origin of the ${rec.surname} clan` }) : null;
            const origin = section("🧭 Origin",
                rec.base_origin ? h("p", { text: rec.base_origin }) : null,
                o.summary ? h("p", { text: o.summary }) : null,
                field("Region", o.region), field("Migration", o.migration_note), mapNode);

            // Filled in by mount() once the (read-only) nearby-places request returns.
            const nearbyList = h("div", { class: "nearby-list" });
            const nearby = validCoords(o)
                ? h("section", { class: "clan-section", hidden: true }, h("h4", { text: "🏞️ Places near the clan's origin" }), nearbyList) : null;

            const related = section("🔗 Related clans", hasItems(e.related_clans) ? h("div", { class: "chips" }, e.related_clans.map((r) =>
                r.found
                    ? h("button", { class: "chip", type: "button", onclick: () => openClan(r.name), text: r.name })
                    : h("span", { class: "pill", text: r.name }))) : null);

            const foundIn = section("📍 Found today in", hasItems(e.today_found_in) ? h("div", { class: "chips" },
                e.today_found_in.map((p) => h("span", { class: "pill", text: p }))) : null);

            const people = section("⭐ Notable people", hasItems(e.notable_people) ? h("ul", { class: "clan-list" },
                e.notable_people.map((p) => h("li", { text: p }))) : null);

            const sources = section("📚 Sources", hasItems(e.sources) ? h("ul", { class: "clan-list" },
                e.sources.map((s) => h("li", {}, /^https?:\/\//i.test(s)
                    ? h("a", { href: s, target: "_blank", rel: "noopener noreferrer", text: s }) : s))) : null);

            const conf = CONFIDENCE[e.confidence];
            const node = h("article", { class: "clan-card" },
                h("header", { class: "clan-head" },
                    h("div", {},
                        h("p", { class: "eyebrow", text: "Clan record" }),
                        h("h3", { text: rec.surname }),
                        hasItems(e.alt_spellings) ? h("p", { class: "muted clan-alt", text: "Also spelled: " + e.alt_spellings.join(", ") }) : null),
                    conf ? h("span", { class: `pill ${conf[1]}`, title: "How well sourced this record is", text: conf[0] }) : null),
                section("🗣️ Izithakazelo (praise names)", praise),
                meaning, origin, nearby, related, foundIn, people, sources,
                rec.has_enrichment ? null : h("p", { class: "clan-pending", text: "Detailed history for this clan is still being researched." }),
                correctionBlock(rec.surname));

            const mount = () => {
                if (!mapNode || !mapNode.isConnected) return;
                const map = L.map(mapNode, { scrollWheelZoom: false }).setView([o.lat, o.lng], 9);
                L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
                const icon = L.divIcon({ className: "", html: '<div class="map-pin top">★</div>', iconSize: [28, 28], iconAnchor: [14, 14] });
                L.marker([o.lat, o.lng], { icon, title: `${rec.surname} origin` }).addTo(map);
                state.clanMap = map;
                setTimeout(() => map.invalidateSize(), 50);
            };
            const mountAll = () => { mount(); loadNearby(); };

            async function loadNearby() {
                if (!nearby || !validCoords(o)) return;
                try {
                    const data = await api(`/api/places/near?lat=${o.lat}&lon=${o.lng}&limit=5`);
                    if (!nearby.isConnected || !data.results.length) return;
                    nearbyList.replaceChildren(
                        h("ul", { class: "nearby-places" }, data.results.map((p) => h("li", {},
                            h("span", { class: "nearby-name", text: p.name }),
                            h("span", { class: "pill", text: p.category }),
                            h("span", { class: "muted nearby-dist", text: `${p.distance_km} km away` })))),
                        h("a", {
                            class: "btn btn-dark btn-sm", text: "Plan a visit →",
                            href: `#/trip?lat=${o.lat}&lon=${o.lng}&from=${encodeURIComponent(rec.surname)}`,
                        }));
                    nearby.hidden = false;
                } catch (err) { console.error(err); }   // optional section: stay hidden on failure
            }
            return { node, mount: mountAll };
        }

        // ---- "Suggest a correction" ----
        function correctionBlock(surname) {
            const status = h("p", { class: "correction-status", role: "status" });
            const message = h("textarea", { id: "corr-message", rows: "4", maxlength: "1000", required: true, placeholder: "What should be corrected or added? If you can, mention where the information comes from." });
            const contact = h("input", { id: "corr-contact", type: "text", maxlength: "120", placeholder: "Your name or email (optional)", autocomplete: "off" });
            const trap = h("input", { type: "text", name: "website", tabindex: "-1", autocomplete: "off", "aria-hidden": "true", class: "hp" });
            const send = h("button", { class: "btn btn-dark btn-sm", type: "submit", text: "Send suggestion" });
            const form = h("form", { class: "correction-form", hidden: true },
                h("label", { for: "corr-message", text: "Your suggestion" }), message,
                h("label", { for: "corr-contact", text: "Contact (optional)" }), contact, trap,
                h("div", { class: "correction-actions" }, send, status));
            form.addEventListener("submit", async (ev) => {
                ev.preventDefault();
                send.disabled = true;
                status.textContent = "Sending…";
                try {
                    const res = await fetch("/api/clan-corrections", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ surname, message: message.value, contact: contact.value, website: trap.value }),
                    });
                    const body = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error(body.error || "Could not send your suggestion.");
                    status.textContent = "Thank you! Your suggestion was received.";
                    message.value = ""; contact.value = "";
                } catch (err) {
                    status.textContent = err.message;
                } finally {
                    send.disabled = false;
                }
            });
            const toggle = h("button", { class: "link-btn", type: "button", "aria-expanded": "false", text: "✏️ Suggest a correction" });
            toggle.addEventListener("click", () => {
                form.hidden = !form.hidden;
                toggle.setAttribute("aria-expanded", String(!form.hidden));
                if (!form.hidden) message.focus();
            });
            return h("footer", { class: "clan-foot" }, toggle, form);
        }

        // ---- autocomplete ----
        let items = [], active = -1, timer = null, suggestSeq = 0;
        function closeSuggest() {
            items = []; active = -1;
            list.hidden = true; list.replaceChildren();
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
        }
        function drawSuggest() {
            list.replaceChildren(...items.map((s, i) => h("li", {
                role: "option", id: `clan-sg-${i}`, "aria-selected": String(i === active),
                class: "suggest-item" + (i === active ? " active" : ""),
                onmousedown: (ev) => { ev.preventDefault(); openClan(s.text); },
            }, h("span", { text: s.text }),
            s.kind !== "surname" ? h("small", { text: s.kind === "praise_name" ? "praise name" : "other spelling" }) : null)));
            list.hidden = items.length === 0;
            input.setAttribute("aria-expanded", String(items.length > 0));
            if (active >= 0) input.setAttribute("aria-activedescendant", `clan-sg-${active}`);
            else input.removeAttribute("aria-activedescendant");
        }
        input.addEventListener("input", () => {
            clearTimeout(timer);
            const q = input.value.trim();
            if (!q) { closeSuggest(); return; }
            timer = setTimeout(async () => {
                const mine = ++suggestSeq;
                try {
                    const data = await api(`/api/heritage/clans/suggest?q=${encodeURIComponent(q)}`);
                    if (mine !== suggestSeq || document.activeElement !== input) return;
                    items = data.suggestions; active = -1; drawSuggest();
                } catch { closeSuggest(); }
            }, 150);
        });
        input.addEventListener("keydown", (ev) => {
            if (ev.key === "ArrowDown" && items.length) { ev.preventDefault(); active = (active + 1) % items.length; drawSuggest(); }
            else if (ev.key === "ArrowUp" && items.length) { ev.preventDefault(); active = (active - 1 + items.length) % items.length; drawSuggest(); }
            else if (ev.key === "Enter" && active >= 0) { ev.preventDefault(); openClan(items[active].text); }
            else if (ev.key === "Escape") closeSuggest();
        });
        input.addEventListener("blur", closeSuggest);
        $("#clan-form").addEventListener("submit", (ev) => { ev.preventDefault(); closeSuggest(); runSearch(input.value, false); });

        // ---- A-Z directory ----
        const drawDirectory = () => {
            const shown = letter ? sorted.filter((c) => c.surname[0].toUpperCase() === letter) : sorted;
            $("#surnames").replaceChildren(...shown.map((c) =>
                h("button", { class: "chip", type: "button", text: c.surname, onclick: () => openClan(c.surname) })));
            $("#az").replaceChildren(...alphabet.map((l) => h("button", {
                type: "button", text: l, "aria-pressed": String(l === letter), disabled: !letters.has(l),
                onclick: () => { letter = letter === l ? "" : l; drawDirectory(); },
            })));
        };
        drawDirectory();

        if (initialQuery) { input.value = initialQuery.slice(0, 80); runSearch(initialQuery, false); }
    }

    // ------------------------------------------------------------------ trip planner
    const VIBE_OPTIONS = [["", "Any"], ["nightlife", "Nightlife"], ["family", "Family"], ["nature", "Nature"],
        ["culture", "Culture"], ["food", "Food"], ["budget", "Budget"]];

    function tripCard(p, i, opts = {}) {
        const reasons = p.reasons.map((r) => `<span class="pill ${esc(r.tone)}">${esc(r.text)}${r.points ? ` <b class="pts" title="Points added to or taken from the ranking">${r.points > 0 ? "+" : "−"}${Math.abs(r.points)}</b>` : ""}</span>`).join("");

        // Only show what we actually know: unknown fields are left out, never filled in.
        const where = [p.address || p.region, p.distance_km != null ? `${p.distance_km} km away` : null].filter(Boolean).join(" · ");
        const hours = p.opening_hours_raw || p.opening_hours;
        // A plain Google Maps search link: no scraping, no affiliate links.
        const staysUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`accommodation near ${p.latitude},${p.longitude}`)}`;
        const phoneOk = typeof p.phone === "string" && /^[0-9+()\-. \/]{5,40}$/.test(p.phone);   // same rule as the server
        const phoneDigits = phoneOk ? p.phone.replace(/[^0-9+]/g, "") : "";
        const links = [
            p.website && /^https?:\/\//i.test(p.website)
                ? `<a href="${esc(p.website)}" target="_blank" rel="noopener noreferrer nofollow">🌐 Website</a>` : "",
            phoneDigits ? `<a href="tel:${esc(phoneDigits)}">📞 ${esc(p.phone)}</a>` : "",
        ].filter(Boolean).join("");
        const tags = [
            p.subcategory_label ? `<span class="pill">${esc(p.subcategory_label)}</span>` : "",
            p.min_age ? `<span class="pill warn" title="Minimum age listed for this venue">Age ${esc(p.min_age)}+</span>` : "",
        ].join("");

        state.places.set(p.id, p);                      // lets the "+ Trip" button find the full place
        const inTrip = tripHas(p.id);
        return `
        <article class="card" data-id="${p.id}" style="animation-delay:${Math.min(i, 8) * 40}ms">
          <div class="card-media">
            ${img(p.image_url, p.name)}
            ${opts.stay ? "" : `<span class="rank">#${i + 1}</span>
            <span class="score ${p.score < 0 ? "neg" : ""}">${p.score > 0 ? "+" : ""}${p.score} pts</span>`}
            <span class="cat-tag">${esc(CATEGORY_EMOJI[p.category] || "📍")} ${esc(p.category)}</span>
          </div>
          <div class="card-body">
            <h3 class="card-title">${esc(p.name)}</h3>
            ${tags ? `<div class="reasons">${tags}</div>` : ""}
            <div class="meta">
              ${where ? `<span>📍 ${esc(where)}</span>` : ""}
              ${hours ? `<span>🕒 ${esc(hours)}</span>` : ""}
              ${p.marine ? `<span>🌊 Waves up to ${esc(Number(p.marine.wave_height_m).toFixed(1))} m forecast</span>` : ""}
              ${links ? `<span class="links">${links}</span>` : ""}
            </div>
            <p class="card-desc clamp">${esc(p.description)}</p>
            ${reasons ? `<div class="reasons">${reasons}</div>` : ""}
            ${p.safety_rated ? "" : `<p class="unrated" title="No safety rating is available for this place. This is not a judgement either way.">ⓘ Not safety-rated</p>`}
            ${opts.stay ? "" : `<p class="stays-link"><a href="${esc(staysUrl)}" target="_blank" rel="noopener noreferrer">🛏️ Find stays near here</a></p>`}
            <div class="card-foot">
              <span>${p.is_indoor ? "🏠 Indoor" : "🌳 Outdoor"}${p.has_generator ? " · 🔌 Generator" : ""}${p.price_tier ? ` · <span class="price-tag" title="Price level">${esc(p.price_tier)}</span>` : ""}</span>
              <span style="display:flex;gap:.4rem">
                ${state.map ? `<button class="btn btn-dark btn-sm" data-focus="${p.id}" type="button">Map</button>` : ""}
                <button class="btn btn-sm ${inTrip ? "btn-in" : "btn-dark"}" type="button" data-trip="${p.id}" aria-pressed="${inTrip}">${inTrip ? "✓ In trip" : "＋ Trip"}</button>
                <a class="btn btn-dark btn-sm" target="_blank" rel="noopener"
                   href="https://www.google.com/maps/search/?api=1&query=${p.latitude},${p.longitude}">Directions</a>
              </span>
            </div>
          </div>
        </article>`;
    }

    const locText = (loc) => !loc ? "Showing picks around Durban"
        : loc.label ? `📍 Near the ${loc.label} clan's origin` : "📍 Using your location";

    async function ensureFilters() {
        if (!state.filters) {
            try { state.filters = await api("/api/filters"); } catch { state.filters = { prices: {} }; }
        }
        return state.filters;
    }

    async function ensureCategories() {
        if (!state.categories) state.categories = await api("/api/categories");
        return state.categories;
    }

    /** The seven-day strip. Choosing a day ranks places for that day's forecast. */
    async function drawDateStrip(token) {
        const box = $("#date-strip");
        if (!box) return;
        const t = state.trip;
        let data;
        try { data = await api(`/api/forecast${t.loc ? `?lat=${t.loc.lat}&lon=${t.loc.lon}` : ""}`); } catch { data = { days: [] }; }
        if (token !== state.token || !$("#date-strip")) return;
        const days = data.days || [];
        if (t.date && !days.some((d) => d.date === t.date)) t.date = "";          // e.g. the page was left open overnight
        if (!days.length) {
            t.date = "";
            box.innerHTML = '<span class="count">The forecast is unavailable right now, so places are ranked for today.</span>';
            return;
        }
        const chosen = t.date || days[0].date;
        box.innerHTML = days.map((d, i) => `
            <button class="day-chip" type="button" data-date="${i === 0 ? "" : esc(d.date)}" aria-pressed="${d.date === chosen}"
                    title="${esc(d.condition)}, high ${esc(Math.round(d.temp_c))}°C${d.rain_chance_pct != null ? `, ${esc(d.rain_chance_pct)}% chance of rain` : ""}">
              <span class="d-name">${i === 0 ? "Today" : esc(fmtDay(d.date))}</span>
              <span class="d-ico" aria-hidden="true">${weatherEmoji[d.icon] || "🌤️"}</span>
              <span class="d-temp">${esc(Math.round(d.temp_c))}°</span>
              ${d.rain_chance_pct != null ? `<span class="d-rain">${esc(d.rain_chance_pct)}%</span>` : ""}
            </button>`).join("");
    }

    /** How many planner filters differ from the defaults (shown on the "More filters" summary). */
    function activeFilters() {
        const t = state.trip;
        return [t.subcategory, t.region, t.openNow, t.openLate, t.vibe, t.mix, t.at, t.date, t.indoor, t.price].filter(Boolean).length;
    }

    function drawSubcats() {
        const t = state.trip, box = $("#subcats");
        if (!box) return;
        const subs = ((state.filters && state.filters.subcategories) || {})[t.category] || [];
        if (!subs.length) { box.hidden = true; box.replaceChildren(); t.subcategory = ""; return; }
        if (t.subcategory && !subs.some((s) => s.slug === t.subcategory)) t.subcategory = "";
        const total = ((state.categories || []).find((c) => c.name === t.category) || {}).count || "";
        box.hidden = false;
        box.innerHTML = [{ slug: "", label: `All ${t.category}`, count: total }, ...subs].map((s) =>
            `<button class="chip chip-sm" type="button" data-subcat="${esc(s.slug)}" aria-pressed="${s.slug === t.subcategory}">${esc(s.label)}<small>${esc(s.count)}</small></button>`).join("");
    }

    function syncFilterUi() {
        const n = activeFilters();
        const clear = $("#clear-filters"), count = $("#filter-count"), mix = $("#mix");
        $$("[data-no-stay]").forEach((el) => { el.hidden = state.trip.category === "Stay"; });   // meaningless for places to sleep
        if (clear) clear.hidden = n === 0;
        if (count) count.textContent = n ? `(${n} active)` : "";
        if (mix) {
            mix.disabled = state.trip.category !== "All";
            mix.closest(".switch").title = mix.disabled ? "Choose the All category to mix categories" : "No single category fills the top results";
        }
    }

    async function renderTrip(token) {
        setView(loading("Planning your trip…"));
        const cats = await ensureCategories();
        const filters = await ensureFilters();
        if (token !== state.token) return;
        const t = state.trip;
        const priceCounts = filters.prices || {};
        const anyPrices = Object.values(priceCounts).some((n) => n > 0);
        const regionList = filters.regions || [];
        if (t.price && !priceCounts[t.price]) t.price = "";
        if (t.region && !regionList.some((r) => r.name === t.region)) t.region = "";
        if (t.category !== "All" && !cats.some((c) => c.name === t.category)) t.category = "All";
        t.limit = PAGE;
        const total = cats.filter((c) => c.in_all !== false).reduce((n, c) => n + c.count, 0);

        setView(`
        <section class="trip-head">
          <div class="wrap">
            <p class="eyebrow hero-eyebrow">Trip planner</p>
            <h1 class="h-display">Where to, today?</h1>
            <p>Places across KwaZulu-Natal ranked for the current weather, time of day, load-shedding and your location.</p>
            <div class="ctx-grid" id="ctx"><div class="ctx"><span class="ico">⏳</span><div><b>Checking conditions…</b></div></div></div>
          </div>
        </section>
        <div class="bead-strip" aria-hidden="true"></div>

        <div class="wrap">
          <div class="controls">
            <div class="date-row"><span class="count">📅 Pick a date</span><div class="date-strip" id="date-strip" role="group" aria-label="Pick a date"><span class="count">Loading the forecast…</span></div></div>
            <div class="chips" id="cats" role="group" aria-label="Category">
              ${[{ name: "All", count: total }, ...cats].map((c) => `
                <button class="chip" type="button" data-cat="${esc(c.name)}" aria-pressed="${c.name === t.category}">
                  ${esc(CATEGORY_EMOJI[c.name] || "📍")} ${esc(c.name)}<small>${esc(c.count)}</small></button>`).join("")}
            </div>
            <div class="chips" id="subcats" role="group" aria-label="Type of place" hidden></div>
            <div class="controls-row">
              <div class="filter-group">
                <label class="switch" data-no-stay><input type="checkbox" id="indoor" ${t.indoor ? "checked" : ""}><span class="track"></span> Indoor only</label>
                <label class="switch" data-no-stay title="Only places whose listed hours show they are open at this time"><input type="checkbox" id="open-now" ${t.openNow ? "checked" : ""}><span class="track"></span> Open now</label>
                <label class="switch" data-no-stay title="Only places whose listed hours run past 23:00"><input type="checkbox" id="open-late" ${t.openLate ? "checked" : ""}><span class="track"></span> Open late</label>
                <label class="switch" data-no-stay><input type="checkbox" id="mix" ${t.mix ? "checked" : ""}><span class="track"></span> Mix categories</label>
                <div class="budget" role="group" aria-label="Budget, up to">
                  <span class="count">Budget</span>
                  ${anyPrices ? `<div class="seg">${["", "$", "$$", "$$$"].map((tier) => `
                    <button type="button" data-price="${esc(tier)}" aria-pressed="${t.price === tier}"
                      ${tier && !priceCounts[tier] ? 'disabled title="No places with this price yet"' : ""}>${tier ? esc(tier) : "Any"}</button>`).join("")}</div>`
                    : `<span class="count" title="Prices are only shown where they are known">Price info not available yet</span>`}
                </div>
              </div>
              <div style="display:flex;gap:.7rem;align-items:center;flex-wrap:wrap">
                <span class="count" id="loc-note">${esc(locText(t.loc))}</span>
                <button class="btn btn-dark btn-sm" id="locate" type="button">${t.loc ? "Reset location" : "📍 Use my location"}</button>
              </div>
            </div>
            <details class="more-filters" ${t.region || t.vibe || t.at ? "open" : ""}>
              <summary>More filters <span id="filter-count"></span></summary>
              <div class="more-grid">
                <label class="field">Region
                  <select id="region">
                    <option value="">Any region</option>
                    ${regionList.map((r) => `<option value="${esc(r.name)}" ${t.region === r.name ? "selected" : ""}>${esc(r.name)} (${esc(r.count)})</option>`).join("")}
                  </select>
                </label>
                <div class="field">Vibe
                  <div class="chips" role="group" aria-label="Vibe">
                    ${VIBE_OPTIONS.map(([v, l]) => `<button class="chip chip-sm" type="button" data-vibe="${esc(v)}" aria-pressed="${t.vibe === v}">${esc(l)}</button>`).join("")}
                  </div>
                </div>
                <label class="field">Time of day (South African time)
                  <span class="time-row"><input type="time" id="at" value="${esc(t.at)}"><button class="link-btn" id="at-now" type="button">Now</button></span>
                </label>
              </div>
            </details>
            <button class="link-btn" id="clear-filters" type="button" hidden>Clear all filters</button>
          </div>

          <div id="notices"></div>

          <div class="trip-layout">
            <div>
              <p class="count" id="result-count" style="margin-bottom:1rem" role="status"></p>
              <div class="trip-grid" id="trip-list"></div>
              <div style="text-align:center;margin-top:1.8rem" id="more-wrap"></div>
            </div>
            <aside class="map-col"><div id="map" role="region" aria-label="Map of recommended places"></div></aside>
          </div>
        </div>`);

        initMap();
        drawSubcats();
        syncFilterUi();
        drawDateStrip(token);

        const reload = () => { t.limit = PAGE; state.stayLimits = {}; syncFilterUi(); loadTrip(token); };

        $("#date-strip").addEventListener("click", (e) => {
            const b = e.target.closest("[data-date]");
            if (!b) return;
            t.date = b.dataset.date;
            $$("#date-strip .day-chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b)));
            reload();
        });
        $("#cats").addEventListener("click", (e) => {
            const b = e.target.closest("[data-cat]");
            if (!b) return;
            t.category = b.dataset.cat; t.subcategory = "";
            if (t.category === "Stay") {
                Object.assign(t, { openNow: false, openLate: false, indoor: false, mix: false });
                ["#open-now", "#open-late", "#indoor", "#mix"].forEach((sel) => { $(sel).checked = false; });
            }
            $$("#cats .chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b)));
            history.replaceState(null, "", `#/trip${t.category === "All" ? "" : "?category=" + encodeURIComponent(t.category)}`);
            setMeta(...tripMeta(t.category));
            drawSubcats();
            reload();
        });
        $("#subcats").addEventListener("click", (e) => {
            const b = e.target.closest("[data-subcat]");
            if (!b) return;
            t.subcategory = b.dataset.subcat;
            $$("#subcats .chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b)));
            reload();
        });
        $$("#view [data-price]").forEach((b) => b.addEventListener("click", () => {
            t.price = b.dataset.price;
            $$("#view [data-price]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
            reload();
        }));
        $$("#view [data-vibe]").forEach((b) => b.addEventListener("click", () => {
            t.vibe = b.dataset.vibe;
            $$("#view [data-vibe]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
            reload();
        }));
        $("#indoor").addEventListener("change", (e) => { t.indoor = e.target.checked; reload(); });
        $("#open-now").addEventListener("change", (e) => { t.openNow = e.target.checked; reload(); });
        $("#open-late").addEventListener("change", (e) => { t.openLate = e.target.checked; reload(); });
        $("#mix").addEventListener("change", (e) => { t.mix = e.target.checked; reload(); });
        $("#region").addEventListener("change", (e) => { t.region = e.target.value; reload(); });
        $("#at").addEventListener("change", (e) => { t.at = /^\d{2}:\d{2}$/.test(e.target.value) ? e.target.value : ""; reload(); });
        $("#at-now").addEventListener("click", () => { t.at = ""; $("#at").value = ""; reload(); });
        $("#clear-filters").addEventListener("click", clearFilters);
        $("#locate").addEventListener("click", () => toggleLocation(token));
        $("#trip-list").addEventListener("click", (e) => {
            const b = e.target.closest("[data-focus]");
            if (b) focusPlace(Number(b.dataset.focus));
            if (e.target.closest("[data-clear]")) clearFilters();
            const moreStay = e.target.closest("[data-more-stay]");
            if (moreStay) {
                const name = moreStay.dataset.moreStay;
                state.stayLimits[name] = (state.stayLimits[name] || PAGE) + PAGE;
                loadTrip(token);
            }
        });

        async function clearFilters() {
            Object.assign(t, { subcategory: "", region: "", openNow: false, openLate: false, vibe: "", mix: false, at: "", date: "", indoor: false, price: "" });
            await renderTrip(token);
        }

        await loadTrip(token);
    }

    function toggleLocation(token) {
        const t = state.trip;
        const btn = $("#locate");
        if (t.loc) {
            t.loc = null;
            btn.textContent = "📍 Use my location";
            $("#loc-note").textContent = locText(null);
            drawDateStrip(token);
            return loadTrip(token);
        }
        if (!navigator.geolocation) { $("#loc-note").textContent = "Location isn't supported by this browser"; return; }
        btn.disabled = true; btn.textContent = "Locating…";
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                t.loc = { lat: pos.coords.latitude, lon: pos.coords.longitude };
                btn.disabled = false; btn.textContent = "Reset location";
                $("#loc-note").textContent = locText(t.loc);
                drawDateStrip(token);
                loadTrip(token);
            },
            () => {
                btn.disabled = false; btn.textContent = "📍 Use my location";
                $("#loc-note").textContent = "Couldn't get your location. Check browser permissions.";
            },
            { timeout: 8000 });
    }

    /** Places to stay: one section per region (each fetched on its own, 12 at a time) so every region is represented. */
    async function loadStays(token) {
        const t = state.trip;
        const list = $("#trip-list");
        const regionNames = t.region ? [t.region] : ((state.filters && state.filters.regions) || []).map((r) => r.name);
        const base = new URLSearchParams({ category: "Stay", loadshedding: t.loadshedding, points: "1" });
        if (t.subcategory) base.set("subcategory", t.subcategory);
        if (t.price) base.set("price", t.price);
        if (t.vibe) base.set("vibe", t.vibe);
        if (t.at) base.set("at", t.at);
        if (t.date) base.set("date", t.date);
        if (t.loc) { base.set("lat", t.loc.lat); base.set("lon", t.loc.lon); }
        list.innerHTML = '<div class="skeleton"></div>'.repeat(3);

        const sections = await Promise.all(regionNames.map(async (name) => {
            const limit = state.stayLimits[name] || PAGE;
            const params = new URLSearchParams(base);
            params.set("region", name);
            params.set("limit", limit);
            try { return { name, data: await api(`/api/recommend?${params}`) }; } catch { return { name, data: null }; }
        }));
        if (token !== state.token) return;

        const loaded = sections.filter((s) => s.data && s.data.total > 0);
        const first = sections.find((s) => s.data);
        if (first) renderContext(first.data.context, token);
        renderNotices([]);
        $("#more-wrap").innerHTML = "";

        if (!loaded.length) {
            list.innerHTML = `<div class="empty" style="grid-column:1/-1">${sections.some((s) => !s.data)
                ? "We couldn't load places to stay. Please try again."
                : "No places to stay match these filters."}${activeFilters() ? '<p style="margin-top:1rem"><button class="btn btn-dark btn-sm" type="button" data-clear="1">Clear all filters</button></p>' : ""}</div>`;
            $("#result-count").textContent = "";
            drawMarkers([], [], false);
            return;
        }
        const shown = loaded.reduce((n, s) => n + s.data.results.length, 0);
        const total = loaded.reduce((n, s) => n + s.data.total, 0);
        $("#result-count").textContent = `Showing ${shown} of ${total} places to stay, grouped by region. Prices and availability are not listed: check with the place.`;
        list.innerHTML = loaded.map(({ name, data }) => `
            <section class="region-group" style="grid-column:1/-1">
              <h3 class="region-head">${esc(name)} <small>${esc(data.total)}</small></h3>
              <div class="trip-grid">${data.results.map((p, i) => tripCard(p, i, { stay: true })).join("")}</div>
              ${data.results.length < data.total ? `<p style="text-align:center;margin-top:1rem"><button class="btn btn-dark btn-sm" type="button" data-more-stay="${esc(name)}">Show more in ${esc(name)}</button></p>` : ""}
            </section>`).join("");
        drawMarkers([], loaded.flatMap((s) => s.data.points || s.data.results), false);
    }

    /** General safety and age notices (tips only: they say nothing about any particular venue). */
    function renderNotices(results) {
        const box = $("#notices");
        if (!box) return;
        const nightlife = state.trip.category === "Nightlife" || results.some((p) => p.category === "Nightlife");
        const adults = nightlife || results.some((p) => p.subcategory === "casino" || p.min_age >= 18);
        box.innerHTML = (nightlife ? `
            <aside class="notice" aria-label="Safety tips for going out at night">
              <h3>🌙 Going out at night? General tips</h3>
              <ul>
                <li>Use a licensed e-hailing service or a pre-booked ride.</li>
                <li>Never drink and drive.</li>
                <li>Keep your valuables out of sight.</li>
                <li>Go out in a group.</li>
                <li>Check a venue's opening hours before you go.</li>
              </ul>
              <p class="muted">General advice only. It says nothing about any particular venue or area.</p>
            </aside>` : "") + (adults ? `<p class="notice notice-age"><strong>Many venues are 18+. Bring ID.</strong></p>` : "");
    }

    async function loadTrip(token) {
        const t = state.trip;
        const list = $("#trip-list");
        if (!list) return;
        if (t.category === "Stay") return loadStays(token);
        if (t.limit === PAGE) list.innerHTML = '<div class="skeleton"></div>'.repeat(4);

        const params = new URLSearchParams({ category: t.category, limit: t.limit, loadshedding: t.loadshedding, points: "1" });
        if (t.subcategory) params.set("subcategory", t.subcategory);
        if (t.region) params.set("region", t.region);
        if (t.indoor) params.set("indoor", "1");
        if (t.openNow) params.set("open_now", "1");
        if (t.openLate) params.set("open_late", "1");
        if (t.price) params.set("price", t.price);
        if (t.vibe) params.set("vibe", t.vibe);
        if (t.mix && t.category === "All") params.set("tourist", "1");
        if (t.at) params.set("at", t.at);
        if (t.date) params.set("date", t.date);
        if (t.loc) { params.set("lat", t.loc.lat); params.set("lon", t.loc.lon); }

        let data;
        try {
            data = await api(`/api/recommend?${params}`);
        } catch (err) {
            if (token === state.token) list.innerHTML = `<div class="empty" style="grid-column:1/-1">We couldn't load recommendations. Please try again.</div>`;
            return;
        }
        if (token !== state.token) return;

        renderContext(data.context, token);
        renderNotices(data.results);
        const hoursFilter = t.openNow || t.openLate;
        list.innerHTML = data.results.length
            ? data.results.map((p, i) => tripCard(p, i)).join("")
            : `<div class="empty" style="grid-column:1/-1">No places match these filters.
                 ${hoursFilter ? "<br>Many places have no opening hours listed, so they can't appear under Open now or Open late." : ""}
                 ${activeFilters() ? '<p style="margin-top:1rem"><button class="btn btn-dark btn-sm" type="button" data-clear="1">Clear all filters</button></p>' : ""}</div>`;
        $("#result-count").textContent = `Showing ${data.results.length} of ${data.total} places, best match first`
            + (hoursFilter ? ". Only places whose listed hours confirm it are shown" : "");
        $("#more-wrap").innerHTML = data.results.length < data.total
            ? `<button class="btn btn-dark" id="more" type="button">Show more</button>` : "";
        const more = $("#more");
        if (more) more.addEventListener("click", () => { t.limit += PAGE; loadTrip(token); });
        drawMarkers(data.results, data.points);
    }

    function renderContext(ctx, token) {
        const w = ctx.weather, mode = state.trip.loadshedding, t = ctx.time;
        $("#ctx").innerHTML = `
          <div class="ctx"><span class="ico">${weatherEmoji[w.icon] || "🌤️"}</span>
            <div><b>${esc(w.condition)} · ${Math.round(w.temp_c)}°C</b>
            <span>${w.date ? `Forecast for ${esc(fmtDay(w.date))}${w.temp_min_c != null ? `, low ${esc(Math.round(w.temp_min_c))}°C` : ""}. ` : ""}${esc(w.advice)}${w.rain_chance_pct != null ? ` ${esc(w.rain_chance_pct)}% chance of rain.` : ""}${w.source === "fallback" ? " (offline estimate)" : ""}</span></div></div>
          <div class="ctx"><span class="ico">${ctx.loadshedding ? "⚡" : "💡"}</span>
            <div><b>${ctx.loadshedding ? "Load-shedding active" : "Power looks stable"}<span class="sim-tag" title="No live Eskom feed: this follows a made-up evening schedule">Simulated</span></b>
            <span>Not live data. Try what-if mode:</span>
            <div class="seg" role="group" aria-label="Load-shedding mode">
              ${[["auto", "Auto"], ["on", "On"], ["off", "Off"]].map(([v, l]) =>
                  `<button type="button" data-ls="${v}" aria-pressed="${mode === v}">${l}</button>`).join("")}
            </div></div></div>
          ${t ? `<div class="ctx"><span class="ico">${t.evening ? "🌙" : "☀️"}</span>
            <div><b>${t.evening ? "Evening mode" : "Daytime"} · ${esc(t.time)}${t.date && t.what_if && w.date ? ` on ${esc(fmtDay(t.date))}` : t.what_if ? " (what-if)" : ""}</b>
            <span>South African time. ${t.evening ? "Nightlife and evening venues rank higher; places closed now rank lower." : "Places that are open now rank higher."}</span></div></div>` : ""}`;
        $$("#ctx [data-ls]").forEach((b) => b.addEventListener("click", () => {
            state.trip.loadshedding = b.dataset.ls; state.trip.limit = PAGE; loadTrip(token);
        }));
    }

    // ------------------------------------------------------------------ map (Leaflet + markercluster, both optional)
    function initMap() {
        const el = $("#map");
        if (!el) return;
        if (!window.L) { el.closest(".map-col").hidden = true; return; }
        state.map = L.map(el, { scrollWheelZoom: false }).setView([-29.2, 30.9], 7);
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 18, attribution: "&copy; OpenStreetMap contributors",
        }).addTo(state.map);
    }

    function destroyMap() {
        if (state.clanMap) { state.clanMap.remove(); state.clanMap = null; }
        if (state.map) { state.map.remove(); state.map = null; }
        state.markers = [];
        state.layer = null;
    }

    /** Numbered pins for the places in the list; every other match as a small dot, clustered when it is crowded. */
    function drawMarkers(places, points, numbered = true) {
        const map = state.map;
        if (!map) return;
        if (state.layer) { state.layer.remove(); state.layer = null; }
        state.markers = [];

        const rankOf = new Map(numbered ? places.map((p, i) => [p.id, i]) : []);
        const all = points && points.length ? points : places;
        const layer = typeof L.markerClusterGroup === "function"
            ? L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 45 })
            : L.layerGroup();

        const bounds = [];
        all.forEach((p) => {
            const rank = rankOf.get(p.id);
            const icon = rank !== undefined
                ? L.divIcon({ className: "", html: `<div class="map-pin ${rank < 3 ? "top" : ""}">${rank + 1}</div>`, iconSize: [28, 28], iconAnchor: [14, 14] })
                : L.divIcon({ className: "", html: '<div class="map-dot"></div>', iconSize: [12, 12], iconAnchor: [6, 6] });
            const marker = L.marker([p.latitude, p.longitude], { icon, title: p.name, zIndexOffset: rank !== undefined ? 500 : 0 })
                .bindPopup(`<strong>${esc(p.name)}</strong><br>${esc(p.category)}`);
            marker.on("click", () => highlightCard(p.id));
            layer.addLayer(marker);
            state.markers.push({ id: p.id, marker });
            bounds.push([p.latitude, p.longitude]);
        });
        layer.addTo(map);
        state.layer = layer;

        const loc = state.trip.loc;
        if (loc) {
            const me = L.divIcon({ className: "", html: loc.label ? '<div class="map-pin top">★</div>' : '<div class="map-pin me">You</div>', iconSize: [28, 28], iconAnchor: [14, 14] });
            const marker = L.marker([loc.lat, loc.lon], { icon: me }).addTo(map);
            state.markers.push({ id: -1, marker });
        }
        map.invalidateSize();                       // the container may have been laid out after the map was created
        if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 11 });
        setTimeout(() => map.invalidateSize(), 50);
    }

    function focusPlace(id) {
        const m = state.markers.find((x) => x.id === id);
        if (!m || !state.map) return;
        const open = () => m.marker.openPopup();
        if (state.layer && typeof state.layer.zoomToShowLayer === "function") {
            state.layer.zoomToShowLayer(m.marker, open);       // un-clusters first when the pin is inside a cluster
        } else {
            state.map.flyTo(m.marker.getLatLng(), 12, { duration: .8 });
            open();
        }
        $("#map").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function highlightCard(id) {
        $$(".card.focus").forEach((c) => c.classList.remove("focus"));
        const card = $(`.card[data-id="${id}"]`);
        if (card) { card.classList.add("focus"); card.scrollIntoView({ behavior: "smooth", block: "center" }); }
    }

    // ------------------------------------------------------------------ boot
    window.addEventListener("hashchange", route);
    $(".skip-link").addEventListener("click", (e) => { e.preventDefault(); view.focus(); });
    tripLoad();
    updateTripBadge();
    route();     // script is deferred, so the DOM is ready
})();
