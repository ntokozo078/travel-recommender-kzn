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
        Food: "🥘", Shopping: "🛍️", Entertainment: "🎉",
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
        trip: { category: "All", loadshedding: "auto", indoor: false, limit: PAGE, loc: null },
        map: null, clanMap: null, markers: [],
        token: 0,                                    // guards against stale async renders
    };

    // ------------------------------------------------------------------ utils
    const $ = (sel, root = document) => root.querySelector(sel);
    const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
    const view = $("#view");

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
                await renderHeritage(id, token, query.get("q"));
            } else if (parts[0] === "trip") {
                highlightNav("trip");
                if (query.get("category")) state.trip.category = query.get("category");
                const lat = parseFloat(query.get("lat")), lon = parseFloat(query.get("lon"));
                if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
                    // arriving from a clan page: start from the clan's origin instead of Durban
                    state.trip.loc = { lat, lon, label: (query.get("from") || "").slice(0, 80) || null };
                    state.trip.category = query.get("category") || "All";
                }
                await renderTrip(token);
            } else {
                highlightNav("home");
                await renderHome(token);
            }
        } catch (err) {
            console.error(err);
            if (token === state.token) setView(failure("We couldn't load that page. Is the server running?"));
        }
        document.title = "iKhaya KZN · Heritage & Trip Planner";
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
        api("/api/recommend?limit=3").then((data) => {
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
          <div><strong>${ctx.loadshedding ? "Load-shedding likely" : "Power looks stable"}</strong>
          <span>Simulated schedule, evenings 18:00–21:00</span></div></div>`;
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
        document.title = `${meta.label} · iKhaya KZN`;
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
    function tripCard(p, i) {
        const reasons = p.reasons.map((r) => `<span class="pill ${esc(r.tone)}">${esc(r.text)}</span>`).join("");
        const dist = p.distance_km != null ? ` · ${p.distance_km} km away` : "";
        return `
        <article class="card" data-id="${p.id}" style="animation-delay:${Math.min(i, 8) * 40}ms">
          <div class="card-media">
            ${img(p.image_url, p.name)}
            <span class="rank">#${i + 1}</span>
            <span class="score ${p.score < 0 ? "neg" : ""}">${p.score > 0 ? "+" : ""}${p.score} pts</span>
            <span class="cat-tag">${esc(CATEGORY_EMOJI[p.category] || "📍")} ${esc(p.category)}</span>
          </div>
          <div class="card-body">
            <h3 class="card-title">${esc(p.name)}</h3>
            <div class="meta"><span>📍 ${esc(p.address)}${esc(dist)}</span><span>🕒 ${esc(p.opening_hours)}</span></div>
            <p class="card-desc clamp">${esc(p.description)}</p>
            <div class="reasons">${reasons}</div>
            <div class="card-foot">
              <span>${p.is_indoor ? "🏠 Indoor" : "🌳 Outdoor"}${p.has_generator ? " · 🔌 Generator" : ""}</span>
              <span style="display:flex;gap:.4rem">
                ${state.map ? `<button class="btn btn-dark btn-sm" data-focus="${p.id}" type="button">Map</button>` : ""}
                <a class="btn btn-dark btn-sm" target="_blank" rel="noopener"
                   href="https://www.google.com/maps/search/?api=1&query=${p.latitude},${p.longitude}">Directions</a>
              </span>
            </div>
          </div>
        </article>`;
    }

    const locText = (loc) => !loc ? "Showing picks around Durban"
        : loc.label ? `📍 Near the ${loc.label} clan's origin` : "📍 Using your location";

    async function ensureCategories() {
        if (!state.categories) state.categories = await api("/api/categories");
        return state.categories;
    }

    async function renderTrip(token) {
        setView(loading("Planning your trip…"));
        const cats = await ensureCategories();
        if (token !== state.token) return;
        const t = state.trip;
        t.limit = PAGE;
        if (t.category !== "All" && !cats.some((c) => c.name === t.category)) t.category = "All";
        const total = cats.reduce((n, c) => n + c.count, 0);
        document.title = "Plan a trip · iKhaya KZN";

        setView(`
        <section class="trip-head">
          <div class="wrap">
            <p class="eyebrow hero-eyebrow">Trip planner</p>
            <h1 class="h-display">Where to, today?</h1>
            <p>Places across KwaZulu-Natal ranked for the current weather, load-shedding and your location.</p>
            <div class="ctx-grid" id="ctx"><div class="ctx"><span class="ico">⏳</span><div><b>Checking conditions…</b></div></div></div>
          </div>
        </section>
        <div class="bead-strip" aria-hidden="true"></div>

        <div class="wrap">
          <div class="controls">
            <div class="chips" id="cats" role="group" aria-label="Category">
              ${[{ name: "All", count: total }, ...cats].map((c) => `
                <button class="chip" type="button" data-cat="${esc(c.name)}" aria-pressed="${c.name === t.category}">
                  ${esc(CATEGORY_EMOJI[c.name] || "📍")} ${esc(c.name)}<small>${c.count}</small></button>`).join("")}
            </div>
            <div class="controls-row">
              <label class="switch"><input type="checkbox" id="indoor" ${t.indoor ? "checked" : ""}><span class="track"></span> Indoor only</label>
              <div style="display:flex;gap:.7rem;align-items:center;flex-wrap:wrap">
                <span class="count" id="loc-note">${esc(locText(t.loc))}</span>
                <button class="btn btn-dark btn-sm" id="locate" type="button">${t.loc ? "Reset location" : "📍 Use my location"}</button>
              </div>
            </div>
          </div>

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

        $("#cats").addEventListener("click", (e) => {
            const b = e.target.closest("[data-cat]");
            if (!b) return;
            t.category = b.dataset.cat; t.limit = PAGE;
            $$("#cats .chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b)));
            history.replaceState(null, "", `#/trip${t.category === "All" ? "" : "?category=" + encodeURIComponent(t.category)}`);
            loadTrip(token);
        });
        $("#indoor").addEventListener("change", (e) => { t.indoor = e.target.checked; t.limit = PAGE; loadTrip(token); });
        $("#locate").addEventListener("click", () => toggleLocation(token));
        $("#trip-list").addEventListener("click", (e) => {
            const b = e.target.closest("[data-focus]");
            if (b) focusPlace(Number(b.dataset.focus));
        });

        await loadTrip(token);
    }

    function toggleLocation(token) {
        const t = state.trip;
        const btn = $("#locate");
        if (t.loc) {
            t.loc = null;
            btn.textContent = "📍 Use my location";
            $("#loc-note").textContent = locText(null);
            return loadTrip(token);
        }
        if (!navigator.geolocation) { $("#loc-note").textContent = "Location isn't supported by this browser"; return; }
        btn.disabled = true; btn.textContent = "Locating…";
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                t.loc = { lat: pos.coords.latitude, lon: pos.coords.longitude };
                btn.disabled = false; btn.textContent = "Reset location";
                $("#loc-note").textContent = locText(t.loc);
                loadTrip(token);
            },
            () => {
                btn.disabled = false; btn.textContent = "📍 Use my location";
                $("#loc-note").textContent = "Couldn't get your location. Check browser permissions.";
            },
            { timeout: 8000 });
    }

    async function loadTrip(token) {
        const t = state.trip;
        const list = $("#trip-list");
        if (!list) return;
        if (t.limit === PAGE) list.innerHTML = '<div class="skeleton"></div>'.repeat(4);

        const params = new URLSearchParams({ category: t.category, limit: t.limit, loadshedding: t.loadshedding });
        if (t.indoor) params.set("indoor", "1");
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
        list.innerHTML = data.results.length
            ? data.results.map((p, i) => tripCard(p, i)).join("")
            : `<div class="empty" style="grid-column:1/-1">No places match these filters yet.</div>`;
        $("#result-count").textContent = `Showing ${data.results.length} of ${data.total} places, best match first`;
        $("#more-wrap").innerHTML = data.results.length < data.total
            ? `<button class="btn btn-dark" id="more" type="button">Show more</button>` : "";
        const more = $("#more");
        if (more) more.addEventListener("click", () => { t.limit += PAGE; loadTrip(token); });
        drawMarkers(data.results);
    }

    function renderContext(ctx, token) {
        const w = ctx.weather, mode = state.trip.loadshedding;
        $("#ctx").innerHTML = `
          <div class="ctx"><span class="ico">${weatherEmoji[w.icon] || "🌤️"}</span>
            <div><b>${esc(w.condition)} · ${Math.round(w.temp_c)}°C</b>
            <span>${esc(w.advice)}${w.source === "fallback" ? " (offline estimate)" : ""}</span></div></div>
          <div class="ctx"><span class="ico">${ctx.loadshedding ? "⚡" : "💡"}</span>
            <div><b>${ctx.loadshedding ? "Load-shedding active" : "Power looks stable"}</b>
            <span>Simulated, try what-if mode:</span>
            <div class="seg" role="group" aria-label="Load-shedding mode">
              ${[["auto", "Auto"], ["on", "On"], ["off", "Off"]].map(([v, l]) =>
                  `<button type="button" data-ls="${v}" aria-pressed="${mode === v}">${l}</button>`).join("")}
            </div></div></div>`;
        $$("#ctx [data-ls]").forEach((b) => b.addEventListener("click", () => {
            state.trip.loadshedding = b.dataset.ls; state.trip.limit = PAGE; loadTrip(token);
        }));
    }

    // ------------------------------------------------------------------ map (Leaflet, optional)
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
    }

    function drawMarkers(places) {
        const map = state.map;
        if (!map) return;
        state.markers.forEach((m) => m.marker.remove());
        state.markers = [];
        const pts = [];
        places.forEach((p, i) => {
            const icon = L.divIcon({ className: "", html: `<div class="map-pin ${i < 3 ? "top" : ""}">${i + 1}</div>`, iconSize: [28, 28], iconAnchor: [14, 14] });
            const marker = L.marker([p.latitude, p.longitude], { icon, title: p.name }).addTo(map)
                .bindPopup(`<strong>${esc(p.name)}</strong><br>${esc(p.category)}`);
            marker.on("click", () => highlightCard(p.id));
            state.markers.push({ id: p.id, marker });
            pts.push([p.latitude, p.longitude]);
        });
        const loc = state.trip.loc;
        if (loc) {
            const me = L.divIcon({ className: "", html: loc.label ? '<div class="map-pin top">★</div>' : '<div class="map-pin me">You</div>', iconSize: [28, 28], iconAnchor: [14, 14] });
            const marker = L.marker([loc.lat, loc.lon], { icon: me }).addTo(map);
            state.markers.push({ id: -1, marker });
        }
        if (pts.length) map.fitBounds(pts, { padding: [30, 30], maxZoom: 11 });
        setTimeout(() => map.invalidateSize(), 50);
    }

    function focusPlace(id) {
        const m = state.markers.find((x) => x.id === id);
        if (!m || !state.map) return;
        state.map.flyTo(m.marker.getLatLng(), 12, { duration: .8 });
        m.marker.openPopup();
        $("#map").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function highlightCard(id) {
        $$(".card.focus").forEach((c) => c.classList.remove("focus"));
        const card = $(`.card[data-id="${id}"]`);
        if (card) { card.classList.add("focus"); card.scrollIntoView({ behavior: "smooth", block: "center" }); }
    }

    // ------------------------------------------------------------------ boot
    window.addEventListener("hashchange", route);
    route();     // script is deferred, so the DOM is ready
})();
