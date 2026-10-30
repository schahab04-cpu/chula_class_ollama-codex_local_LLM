const wisp = (() => {
  const TAU = Math.PI * 2;
  const KEYS = ["coreR", "glow", "halo", "reach", "wander", "flow", "swirl", "stiff", "buoy", "spin", "tilt",
    "drift", "driftF", "breathP", "breathA", "nuc", "moteRate", "motePull", "moteOrbit", "react"];
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const row = (values, colors, tau, gap, dart, events) => ({ values, colors: colors.flatMap(hex), tau, gap, dart, events });
  // Event letters: t twitch, l lean, b mote burst, f thought flash. Repeats weight the pick.
  const STATES = {
    loading: row([.72, .45, 3.2, .55, .5, .25, .3, .7, .35, .12, .6, .15, .08, 5.5, .03, .05, .8, .05, .1, 0],
      ["#d6e8f5", "#7fa6c9", "#24405e"], .9, 6, 0, "tttb"),
    listening: row([1, .8, 4.2, 1, .7, .5, 1.1, 1, .2, .55, 1, .45, .16, 4.2, .035, .12, 1.4, 0, .35, .65],
      ["#e9fffb", "#5ce8d6", "#0f6f8c"], .55, 3.5, 7, "ttttlllbb"),
    transcribing: row([.88, .95, 3.6, .62, .25, .9, 1.8, 1.5, 0, 1.2, 1.15, .15, .1, 2.4, .02, .2, .5, .9, 1.4, 0],
      ["#f2fbff", "#8fd8ff", "#2a5fb0"], .3, 0, 0, ""),
    thinking: row([.92, .75, 4, .74, .35, .3, 2.6, .8, 0, -.28, .85, .25, .09, 3.4, .045, .35, 2, .25, .7, 0],
      ["#f0e9ff", "#a88bff", "#3d2a9e"], .7, 4, 0, "ttlllfffff"),
    speaking: row([1, .9, 5, 1.05, .9, .75, .25, 1.2, .12, .1, .45, .6, .22, 5, .02, .1, 2.2, -.25, .1, 1],
      ["#fff6e0", "#ffd27a", "#b8562a"], .4, 2.8, 9, "ttttllbbbb"),
    error: row([.78, .5, 3, .6, .25, .2, 0, .5, -.55, 0, .35, .08, .05, 7, .025, .03, .25, -.05, 0, 0],
      ["#ffe6e0", "#ff7a6a", "#7a1f2e"], .8, 9, 0, "t"),
  };
  const rand = (a, b) => a + Math.random() * (b - a);
  const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
  const ease = (dt, tau) => 1 - Math.exp(-dt / tau);
  const follow = (v, to, dt, up, down) => v + (to - v) * ease(dt, to > v ? up : down);
  const gapAfter = (mean) => Math.min(mean * 3, Math.max(mean * .3, -Math.log(1 - Math.random()) * mean));
  const shuffle = (a) => { for (let i = a.length - 1; i > 0; i -= 1) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

  const PERM = shuffle(new Uint8Array(256).map((_, i) => i));
  const GRID = new Float32Array(256).map(() => Math.random() * 2 - 1);
  const cell = (x, y) => GRID[PERM[(PERM[x & 255] + y) & 255]];
  function noise(x, y) {
    const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi;
    const u = fx * fx * fx * (fx * (fx * 6 - 15) + 10), v = fy * fy * fy * (fy * (fy * 6 - 15) + 10);
    const a = cell(xi, yi), b = cell(xi + 1, yi), c = cell(xi, yi + 1);
    return a + (b - a) * u + (c - a + (a - b - c + cell(xi + 1, yi + 1)) * u) * v;
  }

  let canvas = null, ctx = null, raf = 0, observer = null, quiet = false, needsResize = true, low = false;
  let width = 0, height = 0, dpr = 1, unit = 1, ox = 0, oy = 0, lastFrame = 0, frameAvg = 1 / 60, age = 0;
  let stateName = "loading", S = STATES.loading, filament = "#fff";
  const mid = {}, cur = {}, colorMid = [], color = [], baked = [], sprites = {};
  let analyser = null, timeBuf = null, freqBuf = null, binHz = 1, micRms = 0, micProb = 0, micFresh = 0;
  let lv = 0, lo = 0, md = 0, hi = 0, slow = 0, heard = 0, histHead = 0, onsetWait = 0;
  const peaks = [.35, .25, .25, .25], hist = new Float32Array(64), scratch = new Float32Array(48);
  let clock = 0, breathPhase = 0, driftPhase = 0, spinAngle = 0, spinNow = 0, breath = 0, coreNow = 1;
  let cx = 0, cy = 0, cvx = 0, cvy = 0, dartX = 0, dartY = 0, dartEnd = 0, nextDart = 0, nextEvent = 0, echoAt = 0;
  let leanX = 0, leanY = 0, leanToX = 0, leanToY = 0, leanEnd = 0, perk = 0, sag = 0, flash = 0, moteDebt = 0;
  let tendrils = [];
  const motes = Array.from({ length: 48 }, () => ({ life: 0, max: 1, x: 0, y: 0, vx: 0, vy: 0, size: .1, seed: 0 }));
  const anyTendril = () => tendrils[Math.floor(Math.random() * tendrils.length)];

  function makeTendrils() {
    const kinds = shuffle(["long", "long", "long", "mid", "mid", "mid", "mid", "mid", "sprout", "sprout", "sprout"]);
    return kinds.map((kind, i) => {
      const y = .78 - 1.56 * (i + .5) / 11 + rand(-.06, .06), r = Math.sqrt(1 - y * y), a = i * 2.39996 + rand(-.35, .35);
      const n = { long: 12, mid: 9, sprout: 6 }[kind];
      const len = { long: rand(2.2, 2.9), mid: rand(1.4, 2.1), sprout: rand(.6, .95) }[kind];
      const b0 = rand(.1, 1), b1 = rand(.1, 1), b2 = rand(.1, 1), sum = b0 + b1 + b2;
      return { kind, n, seg: len / (n - 1), width: { long: rand(.075, .1), mid: rand(.06, .085), sprout: rand(.055, .07) }[kind],
        x: r * Math.cos(a), y, z: r * Math.sin(a), rx: 0, ry: 0, depth: 1, k: rand(38, 110), damp: rand(2.8, 6.2),
        seed: rand(0, 200), hand: Math.random() < .2 ? -1 : 1, flowMul: rand(.6, 1.5), lag: rand(0, .12), phase: rand(0, 100),
        b0: b0 / sum, b1: b1 / sum, b2: b2 / sum, birth: rand(.1, 2.6), grow: 0, flare: 0,
        px: new Float32Array(n), py: new Float32Array(n), vx: new Float32Array(n), vy: new Float32Array(n) };
    });
  }
  function reset() {
    stateName = "loading";
    S = STATES.loading;
    tendrils = makeTendrils();
    KEYS.forEach((key, i) => { mid[key] = cur[key] = S.values[i]; });
    S.colors.forEach((value, i) => { colorMid[i] = color[i] = value; });
    motes.forEach((m) => { m.life = 0; });
    clock = age = lastFrame = cx = cy = cvx = cvy = lv = lo = md = hi = slow = heard = 0;
    dartX = dartY = dartEnd = leanX = leanY = leanToX = leanToY = leanEnd = perk = sag = flash = echoAt = 0;
    spinNow = cur.spin; frameAvg = 1 / 60; low = false; nextEvent = gapAfter(S.gap); nextDart = 1;
    if (quiet) {
      tendrils.forEach((t) => { t.grow = 1; });
      for (let i = 0; i < 180; i += 1) stepTendrils(1 / 60);
    }
  }

  const css = (i, a) => "rgba(" + Math.round(color[i]) + "," + Math.round(color[i + 1]) + "," + Math.round(color[i + 2]) + "," + a + ")";
  function sprite(name, size) {
    if (!sprites[name]) { sprites[name] = document.createElement("canvas"); sprites[name].width = sprites[name].height = size; }
    const g = sprites[name].getContext("2d");
    g.clearRect(0, 0, size, size);
    return g;
  }
  function radial(name, size, stops) {
    const g = sprite(name, size), fill = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    stops.forEach((stop) => fill.addColorStop(stop[0], css(stop[1], stop[2])));
    g.fillStyle = fill;
    g.fillRect(0, 0, size, size);
  }
  function bake() {
    radial("core", 192, [[0, 0, 1], [.34, 0, .92], [.58, 3, .72], [.8, 3, .46], [.91, 3, .62], [1, 3, 0]]);
    radial("halo", 128, [[0, 6, .9], [.28, 6, .42], [.62, 6, .1], [1, 6, 0]]);
    radial("glow", 64, [[0, 3, .85], [.35, 3, .32], [1, 3, 0]]);
    radial("spark", 64, [[0, 0, 1], [.22, 0, .85], [.5, 3, .28], [1, 3, 0]]);
    const g = sprite("leaf", 64);
    g.beginPath(); g.moveTo(4, 32); g.quadraticCurveTo(26, 8, 60, 32); g.quadraticCurveTo(26, 56, 4, 32);
    g.fillStyle = css(3, .9);
    g.fill();
    filament = css(3, 1);
    color.forEach((value, i) => { baked[i] = value; });
  }
  function resize() {
    const box = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, low ? 1.25 : 2);
    canvas.width = width = Math.max(1, Math.round(box.width * dpr));
    canvas.height = height = Math.max(1, Math.round(box.height * dpr));
    unit = Math.min(width, height) * .085;
    ox = width * .5;
    oy = height * .46;
    needsResize = false;
  }
  function blend(dt) {
    const k = ease(dt, S.tau / 2);
    KEYS.forEach((key, i) => { mid[key] += (S.values[i] - mid[key]) * k; cur[key] += (mid[key] - cur[key]) * k; });
    let stale = false;
    for (let i = 0; i < 9; i += 1) {
      colorMid[i] += (S.colors[i] - colorMid[i]) * k;
      color[i] += (colorMid[i] - color[i]) * k;
      if (Math.abs(color[i] - baked[i]) >= 3) stale = true;
    }
    if (stale) bake();
  }

  const toUnit = (rms, floorDb, topDb) => clamp01((20 * Math.log10(rms + 1e-5) - floorDb) / (topDb - floorDb));
  function normalize(i, x, dt, floor) {
    peaks[i] = Math.max(x, peaks[i] * Math.exp(-dt / 6));
    return clamp01(x / Math.max(peaks[i], floor));
  }
  function bandMean(fromHz, toHz) {
    const a = Math.max(1, Math.round(fromHz / binHz)), b = Math.min(freqBuf.length - 1, Math.round(toHz / binHz));
    let sum = 0;
    for (let i = a; i <= b; i += 1) sum += freqBuf[i];
    return sum / (255 * (b - a + 1));
  }
  function readAudio(dt) {
    let toLv = 0, toLo = 0, toMd = 0, toHi = 0, toHeard = 0;
    micFresh = Math.max(0, micFresh - dt);
    if (stateName === "speaking" && analyser) {
      analyser.getFloatTimeDomainData(timeBuf);
      let sum = 0;
      for (let i = 0; i < timeBuf.length; i += 1) sum += timeBuf[i] * timeBuf[i];
      toLv = normalize(0, toUnit(Math.sqrt(sum / timeBuf.length), -50, -14), dt, .35);
      analyser.getByteFrequencyData(freqBuf);
      toLo = normalize(1, bandMean(90, 300), dt, .25);
      toMd = normalize(2, bandMean(300, 1800), dt, .25);
      toHi = normalize(3, bandMean(1800, 6000), dt, .25);
    } else if (stateName === "listening" && micFresh > 0) {
      toHeard = micProb;
      toLv = toLo = toMd = normalize(0, toUnit(micRms, -58, -22) * (.35 + .65 * micProb), dt, .35);
      toHi = toLv * .5;
    }
    lv = follow(lv, toLv, dt, .035, .18);
    lo = follow(lo, toLo, dt, .03, .14);
    md = follow(md, toMd, dt, .03, .12);
    hi = follow(hi, toHi, dt, .02, .09);
    slow += (lv - slow) * ease(dt, .45);
    heard = follow(heard, toHeard, dt, .06, .35);
    hist[histHead++ & 63] = lv;
    onsetWait -= dt;
    if (!quiet && cur.react > .5 && onsetWait <= 0 && lv - slow > .18) {
      onsetWait = .11;
      for (let i = 2 + Math.floor(Math.random() * 3); i > 0; i -= 1) kick(anyTendril(), rand(5, 9) * cur.react, true);
    }
  }

  function kick(t, strength, outward) {
    const last = t.n - 1, d = Math.hypot(t.px[last] - t.px[0], t.py[last] - t.py[0]) + 1e-4;
    let dx = (t.px[last] - t.px[0]) / d, dy = (t.py[last] - t.py[0]) / d;
    if (!outward) [dx, dy] = Math.random() < .5 ? [-dy, dx] : [dy, -dx];
    for (let i = 1; i <= last; i += 1) {
      t.vx[i] += dx * strength * (i / last) ** 2;
      t.vy[i] += dy * strength * (i / last) ** 2;
    }
    t.flare = 1;
    if (outward && Math.random() < .5) spawnMote(t.px[last], t.py[last], dx * rand(.4, 1.1), dy * rand(.4, 1.1));
  }
  function spawnMote(x, y, vx, vy) {
    const m = motes.find((item) => item.life <= 0);
    if (!m) return;
    Object.assign(m, { x, y, vx, vy, size: rand(.06, .16), seed: rand(0, 200) });
    m.life = m.max = rand(1.8, 4.5);
  }
  function fire(kind) {
    if (kind === "t") {
      for (let i = 1 + Math.floor(Math.random() * 3); i > 0; i -= 1) kick(anyTendril(), rand(3, 6), false);
      if (!echoAt && Math.random() < .25) echoAt = clock + rand(.14, .24);
    } else if (kind === "l") {
      const a = rand(0, TAU), r = rand(.35, .7);
      leanToX = Math.cos(a) * r; leanToY = Math.sin(a) * r * .7; leanEnd = clock + rand(.8, 2.2);
    } else if (kind === "b") {
      const t = anyTendril();
      for (let i = 3 + Math.floor(Math.random() * 5); i > 0; i -= 1) spawnMote(t.px[t.n - 1], t.py[t.n - 1], rand(-1.2, 1.2), rand(-1.2, 1.2));
    } else if (kind === "f") flash = 1;
  }
  function schedule() {
    if (quiet) return;
    if (clock >= nextEvent) {
      if (S.events) fire(S.events[Math.floor(Math.random() * S.events.length)]);
      nextEvent = clock + (S.gap ? gapAfter(S.gap) : 1);
    }
    if (echoAt && clock >= echoAt) { echoAt = 0; fire("t"); }
    if (S.dart && clock >= nextDart) {
      const a = rand(0, TAU), r = rand(.5, 1.1);
      dartX = Math.cos(a) * r; dartY = Math.sin(a) * r * .7; dartEnd = clock + rand(.35, 1.4); nextDart = clock + gapAfter(S.dart);
    }
    if (dartEnd && clock >= dartEnd) { dartEnd = 0; dartX = dartY = 0; }
    if (leanEnd && clock >= leanEnd) { leanEnd = 0; leanToX = leanToY = 0; }
  }

  function moveCore(dt) {
    breathPhase += dt * TAU / cur.breathP * (1 + .35 * noise(clock * .13, 9));
    breath = Math.sin(breathPhase) + .4 * noise(clock * .4, 31);
    driftPhase += dt * cur.driftF;
    leanX += (leanToX - leanX) * ease(dt, .35);
    leanY += (leanToY - leanY) * ease(dt, .35);
    perk *= Math.exp(-dt / .5);
    sag *= Math.exp(-dt / .9);
    flash *= Math.exp(-dt / .35);
    const amp = quiet ? 0 : cur.drift * (1 - .6 * heard) * 1.3;
    const tx = amp * (noise(driftPhase, 11) + .5 * noise(driftPhase * 2.3, 23)) + dartX + leanX * .35;
    const ty = amp * .7 * (noise(driftPhase, 47) + .5 * noise(driftPhase * 2.3, 59)) + dartY + leanY * .35;
    cvx += ((tx - cx) * 14 - cvx * 5.5) * dt;
    cvy += ((ty - cy) * 14 - cvy * 5.5) * dt;
    cx += cvx * dt;
    cy += cvy * dt;
    const voice = quiet ? 0 : cur.react;
    coreNow = cur.coreR * (1 + cur.breathA * breath) * (1 + voice * (.1 * lo + .04 * lv) + .06 * perk - .06 * sag);
    const spinTo = quiet ? 0 : cur.spin * (1 + heard * (.9 + .5 * lv)) * (1 - .3 * sag);
    spinNow += (spinTo - spinNow) * ease(dt, .4);
    spinAngle += spinNow * dt;
  }
  function stepTendrils(dt) {
    const tilt = cur.tilt + .18 * noise(clock * .07, 5), roll = .35 * noise(clock * .05, 8);
    const cs = Math.cos(spinAngle), ss = Math.sin(spinAngle), ct = Math.cos(tilt), st = Math.sin(tilt), cr = Math.cos(roll), sr = Math.sin(roll);
    const voice = quiet ? 0 : cur.react;
    const swirl = (cur.swirl + .7 * heard) * Math.max(-1, Math.min(1, spinNow / .15));
    const buoy = cur.buoy - .4 * sag;
    const wander = cur.wander * (1 + 1.4 * md * voice);
    const reach = cur.reach * (1 + (quiet ? 0 : heard * (.18 + .25 * lv))) + .18 * perk;
    const flowGain = (quiet ? .25 : 1) * (1 + 1.2 * lv * cur.react);
    for (const t of tendrils) {
      const x1 = t.x * cs + t.z * ss, z1 = t.z * cs - t.x * ss, y2 = t.y * ct - z1 * st;
      t.rx = x1 * cr - y2 * sr;
      t.ry = x1 * sr + y2 * cr;
      t.depth = .55 + .45 * (.5 + .5 * (t.y * st + z1 * ct));
      t.px[0] = cx + t.rx * coreNow * .9;
      t.py[0] = cy + t.ry * coreNow * .9;
      t.phase += dt * cur.flow * t.flowMul * flowGain;
      if (clock > t.birth) t.grow += (1 - t.grow) * ease(dt, .8);
      t.flare *= Math.exp(-dt / .28);
      const bandLevel = t.b0 * lo + t.b1 * md + t.b2 * hi, last = t.n - 1, keep = Math.exp(-t.damp * dt);
      for (let i = 1; i <= last; i += 1) {
        const u = i / last;
        const ripple = (.6 * hist[(histHead - 1 - Math.round((t.lag + u * .16) * 60)) & 63] + .4 * bandLevel) * voice;
        const len = t.seg * t.grow * reach * (1 + .35 * ripple);
        const ang = -swirl * t.hand * u ** 1.4 + wander * noise(t.seed + u * 1.7, t.phase) * (.25 + u);
        const ca = Math.cos(ang), sa = Math.sin(ang);
        const tx = t.px[i - 1] + (t.rx * ca - t.ry * sa + leanX * u) * len;
        const ty = t.py[i - 1] + (t.rx * sa + t.ry * ca + leanY * u - buoy * u * 1.2) * len;
        const k = t.k * cur.stiff * (1 - .55 * u);
        t.vx[i] = (t.vx[i] + (tx - t.px[i]) * k * dt) * keep;
        t.vy[i] = (t.vy[i] + (ty - t.py[i]) * k * dt) * keep;
        t.px[i] += t.vx[i] * dt;
        t.py[i] += t.vy[i] * dt;
        const dx = t.px[i] - t.px[i - 1], dy = t.py[i] - t.py[i - 1], d = Math.hypot(dx, dy), cap = t.seg * t.grow * 1.5 + .001;
        if (d > cap) { t.px[i] = t.px[i - 1] + dx * cap / d; t.py[i] = t.py[i - 1] + dy * cap / d; }
      }
    }
  }
  function stepMotes(dt) {
    moteDebt += dt * (cur.moteRate + 8 * hi * cur.react) * (quiet ? .25 : 1);
    for (; moteDebt >= 1; moteDebt -= 1) {
      const t = anyTendril(), tip = Math.random() < .55, a = rand(0, TAU);
      spawnMote(tip ? t.px[t.n - 1] : cx + Math.cos(a) * coreNow, tip ? t.py[t.n - 1] : cy + Math.sin(a) * coreNow, rand(-.25, .25), rand(-.35, .1));
    }
    const keep = Math.exp(-1.1 * dt);
    for (const m of motes) {
      if (m.life <= 0) continue;
      m.life -= dt;
      const dx = m.x - cx, dy = m.y - cy, d = Math.hypot(dx, dy) + .01, nx = dx / d, ny = dy / d;
      m.vx = (m.vx + (-nx * cur.motePull * 2.2 - ny * cur.moteOrbit * 1.2 + .5 * noise(m.seed, clock * .3)) * dt) * keep;
      m.vy = (m.vy + (-ny * cur.motePull * 2.2 + nx * cur.moteOrbit * 1.2 + .5 * noise(m.seed + 40, clock * .3) - .12) * dt) * keep;
      m.x += m.vx * dt;
      m.y += m.vy * dt;
      if (cur.motePull > .4 && d < coreNow * .8) m.life = Math.min(m.life, .12);
    }
  }

  function stamp(name, x, y, size, alpha) {
    const s = size * unit;
    ctx.globalAlpha = clamp01(alpha);
    ctx.drawImage(sprites[name], ox + x * unit - s / 2, oy + y * unit - s / 2, s, s);
  }
  function drawRibbon(t, alpha) {
    const last = t.n - 1, s = scratch;
    for (let i = 0; i <= last; i += 1) {
      const a = Math.max(0, i - 1), b = Math.min(last, i + 1), dx = t.px[b] - t.px[a], dy = t.py[b] - t.py[a], d = Math.hypot(dx, dy) + 1e-4;
      const w = (t.width * (1 - i / last) ** .8 * t.grow + .008) * .5;
      s[i * 4] = ox + (t.px[i] - dy / d * w) * unit; s[i * 4 + 1] = oy + (t.py[i] + dx / d * w) * unit;
      s[i * 4 + 2] = ox + (t.px[i] + dy / d * w) * unit; s[i * 4 + 3] = oy + (t.py[i] - dx / d * w) * unit;
    }
    ctx.globalAlpha = clamp01(alpha);
    ctx.beginPath();
    ctx.moveTo(s[0], s[1]);
    for (let i = 1; i <= last; i += 1) ctx.quadraticCurveTo(s[i * 4 - 4], s[i * 4 - 3], (s[i * 4 - 4] + s[i * 4]) / 2, (s[i * 4 - 3] + s[i * 4 + 1]) / 2);
    ctx.lineTo(s[last * 4 + 2], s[last * 4 + 3]);
    for (let i = last; i > 0; i -= 1) ctx.quadraticCurveTo(s[i * 4 + 2], s[i * 4 + 3], (s[i * 4 + 2] + s[i * 4 - 2]) / 2, (s[i * 4 + 3] + s[i * 4 - 1]) / 2);
    ctx.closePath();
    ctx.fill();
  }
  function draw() {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, width, height);
    ctx.globalCompositeOperation = "lighter";
    const voice = cur.react * (quiet ? .3 : 1);
    const glow = cur.glow * (1 + .35 * lv * voice + .2 * perk - .15 * sag);
    stamp("halo", cx, cy, 2 * cur.halo * (1 + (.25 * slow + .12 * lv) * voice) * (1 + .03 * breath), .34 * glow);
    ctx.fillStyle = filament;
    for (const t of tendrils) {
      const last = t.n - 1, tone = t.depth * (.55 + .45 * glow) + .4 * t.flare;
      for (let i = 1; i <= last; i += 1) {
        const u = i / last, size = (t.width * 4.2 * (1 - .68 * u) + .1) * (.25 + .75 * t.grow), alpha = .2 * tone * (1 - .55 * u);
        stamp("glow", t.px[i], t.py[i], size, alpha);
        if (!low) stamp("glow", (t.px[i] + t.px[i - 1]) / 2, (t.py[i] + t.py[i - 1]) / 2, size, alpha);
      }
      drawRibbon(t, tone * .75);
    }
    const stretch = 1 + Math.min(.14, Math.hypot(cvx, cvy) * .06), angle = Math.atan2(cvy, cvx), ca = Math.cos(angle), sa = Math.sin(angle);
    const coreSize = coreNow * 2.25 * unit;
    ctx.globalAlpha = clamp01(.55 + .5 * glow);
    ctx.setTransform(ca * stretch, sa * stretch, -sa / stretch, ca / stretch, ox + cx * unit, oy + cy * unit);
    ctx.drawImage(sprites.core, -coreSize / 2, -coreSize / 2, coreSize, coreSize);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const spread = coreNow * (.59 + .31 * lo * voice);
    for (let i = 0; i < 4; i += 1) stamp("glow", cx + noise(clock * .35, i * 37.1) * spread, cy + noise(clock * .35, i * 37.1 + 9) * spread, coreNow * 1.15, .3 * glow);
    stamp("spark", cx + (noise(clock * .9, 71) * cur.nuc + leanX * .3) * coreNow, cy + (noise(clock * .9, 83) * cur.nuc + leanY * .3) * coreNow,
      coreNow * (.8 + .4 * lv * voice), .75 + .5 * flash);
    for (const t of tendrils) {
      if (t.grow < .03) continue;
      const last = t.n - 1, x = t.px[last], y = t.py[last];
      const pulse = (.62 + .38 * noise(t.seed, clock * 1.7) + .45 * t.flare + .4 * hi * voice) * t.depth * t.grow;
      if (t.kind === "sprout") {
        const a = Math.atan2(y - t.py[last - 1], x - t.px[last - 1]), s = (.34 + .12 * t.flare) * t.grow * unit;
        ctx.globalAlpha = clamp01(pulse);
        ctx.setTransform(Math.cos(a), Math.sin(a), -Math.sin(a), Math.cos(a), ox + x * unit, oy + y * unit);
        ctx.drawImage(sprites.leaf, -s * .06, -s / 2, s, s);
        ctx.setTransform(1, 0, 0, 1, 0, 0);
      }
      stamp("spark", x, y, t.kind === "long" ? .2 : .26, pulse);
    }
    for (const m of motes) {
      if (m.life > 0) stamp("spark", m.x, m.y, m.size, Math.sin(Math.PI * clamp01(m.life / m.max)) ** .7 * (.6 + .4 * noise(m.seed, clock * 3)));
    }
  }
  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (lastFrame && now - lastFrame < (quiet ? 31 : 14.6)) return;
    const raw = lastFrame ? (now - lastFrame) / 1000 : 1 / 60;
    lastFrame = now;
    const dt = raw > .25 ? 1 / 60 : Math.min(raw, 1 / 30);
    if (needsResize || Math.min(window.devicePixelRatio || 1, low ? 1.25 : 2) !== dpr) resize();
    if (width < 2 || height < 2) return;
    age += raw;
    frameAvg += (Math.min(raw, .1) - frameAvg) * .02;
    if (!low && !quiet && age > 4 && frameAvg > .021) { low = true; needsResize = true; }
    clock += dt * (1 + .25 * noise(clock * .05, 77));
    blend(dt);
    readAudio(dt);
    schedule();
    moveCore(dt);
    stepTendrils(dt);
    stepMotes(dt);
    draw();
  }

  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  quiet = motionQuery.matches;
  motionQuery.addEventListener("change", (event) => {
    quiet = event.matches;
    if (quiet) tendrils.forEach((t) => { t.grow = 1; });
  });
  return Object.freeze({
    start(element) {
      if (raf) return;
      canvas = element;
      ctx = canvas.getContext("2d");
      observer = new ResizeObserver(() => { needsResize = true; });
      observer.observe(canvas);
      needsResize = true;
      reset();
      bake();
      raf = requestAnimationFrame(frame);
    },
    stop() {
      cancelAnimationFrame(raf);
      raf = 0;
      if (observer) observer.disconnect();
      micFresh = 0;
    },
    setState(name) {
      if (!STATES[name] || name === stateName) return;
      stateName = name;
      S = STATES[name];
      nextEvent = clock + rand(.6, 1.4);
      nextDart = clock + (S.dart ? gapAfter(S.dart) : 1);
      peaks.fill(.25);
      peaks[0] = .35;
    },
    setMic(samples, speechProbability) {
      let sum = 0;
      for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
      micRms = Math.sqrt(sum / (samples.length || 1));
      micProb = speechProbability;
      micFresh = .3;
    },
    setAnalyser(node) {
      analyser = node;
      if (!node) return;
      node.fftSize = 1024;
      node.smoothingTimeConstant = .3;
      node.minDecibels = -85;
      node.maxDecibels = -25;
      timeBuf = new Float32Array(node.fftSize);
      freqBuf = new Uint8Array(node.frequencyBinCount);
      binHz = node.context.sampleRate / node.fftSize;
    },
    cue(name) {
      if (name === "speech-start") {
        perk = 1;
        if (!quiet) tendrils.forEach((t) => kick(t, rand(1.2, 2.6), true));
      } else if (name === "misfire") sag = 1;
    },
  });
})();
