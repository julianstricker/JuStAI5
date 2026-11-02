// Generates the documentation diagrams as standalone SVGs (dark card, readable on both themes).
//   node scripts/make-doc-diagrams.mjs  ->  docs/img/<name>.<lang>.svg
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../docs/img');
mkdirSync(out, { recursive: true });

const C = { bg: '#12112e', card: '#1d1b45', line: '#ffffff26', text: '#ece9ff', mute: '#a9a6d6', acc: '#7c5cff', mint: '#3ee8b5', peach: '#ffb86b', pink: '#ff7eb6' };
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const FONT = "ui-rounded, 'SF Pro Rounded', Nunito, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

const t = (x, y, s, o = {}) =>
  `<text x="${x}" y="${y}" fill="${o.fill || C.text}" font-size="${o.size || 15}" font-weight="${o.weight || 500}" text-anchor="${o.anchor || 'middle'}"${o.mono ? ` font-family="ui-monospace,SFMono-Regular,Menlo,monospace"` : ''}>${esc(s)}</text>`;
const box = (x, y, w, h, o = {}) =>
  `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${o.r ?? 16}" fill="${o.fill || C.card}" stroke="${o.stroke || C.line}" stroke-width="${o.sw || 1.5}"${o.dash ? ` stroke-dasharray="${o.dash}"` : ''}/>`;
// card with a title and optional lines of small text
const node = (x, y, w, h, title, lines = [], o = {}) => {
  const col = o.color || C.acc;
  let s = box(x, y, w, h, { stroke: col, fill: o.fill });
  s += `<rect x="${x}" y="${y}" width="6" height="${h}" rx="3" fill="${col}"/>`;
  s += t(x + w / 2 + 3, y + 28, title, { size: o.size || 16, weight: 700 });
  lines.forEach((l, i) => (s += t(x + w / 2 + 3, y + 52 + i * 21, l, { size: 13, fill: C.mute })));
  return s;
};
const chip = (x, y, w, label, col = C.acc) =>
  `<rect x="${x}" y="${y}" width="${w}" height="30" rx="15" fill="${col}22" stroke="${col}" stroke-width="1.3"/>` + t(x + w / 2, y + 20, label, { size: 13, fill: C.text });
const arrow = (x1, y1, x2, y2, col = C.mute, dash) => {
  const a = Math.atan2(y2 - y1, x2 - x1);
  const hx = (d) => [x2 - 10 * Math.cos(a + d), y2 - 10 * Math.sin(a + d)];
  const [ax, ay] = hx(0.45), [bx, by] = hx(-0.45);
  return `<path d="M${x1} ${y1} L${x2} ${y2}" stroke="${col}" stroke-width="2" fill="none"${dash ? ` stroke-dasharray="${dash}"` : ''}/><path d="M${ax} ${ay} L${x2} ${y2} L${bx} ${by}" stroke="${col}" stroke-width="2" fill="none" stroke-linejoin="round"/>`;
};
const circle = (x, y, n, col = C.acc) => `<circle cx="${x}" cy="${y}" r="18" fill="${col}"/>` + t(x, y + 6, n, { size: 17, weight: 800, fill: '#0e0d24' });
const wrap = (w, h, body, title) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(title)}" font-family="${FONT}">` +
  `<defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="${C.acc}"/><stop offset="1" stop-color="${C.mint}"/></linearGradient></defs>` +
  `<rect width="${w}" height="${h}" rx="22" fill="${C.bg}"/><rect x="1" y="1" width="${w - 2}" height="${h - 2}" rx="21" fill="none" stroke="${C.line}"/>` +
  `<rect x="0" y="0" width="${w}" height="5" rx="2" fill="url(#g)" opacity=".9"/>` +
  body + `</svg>`;

const T = {
  en: {
    how: { title: 'How JuStAI5 works', room: 'In every room', room1: 'Camera with microphone', room2: 'Speaker or tablet', room3: 'Any screen', srv: 'Your JuStAI5 server', srvSub: 'runs at home, in your network', hears: 'Hears', hearsS: 'wakeword, speech', sees: 'Sees', seesS: 'people, pets, objects', rem: 'Remembers', remS: 'facts, habits', acts: 'Acts', actsS: 'plugins, automations', ai: 'AI model', ai1: 'Google Gemini (cloud)', ai2: 'or Ollama (local)', back: 'The answer plays in the same room, never anywhere else.', ask: '“Hey Jarvis …”' },
    inst: { title: 'Installation in four steps', s: [['One command', 'on a Linux PC'], ['Open the web page', 'and log in'], ['Add a room', 'phone or camera'], ['Say “Hey Jarvis”', 'and ask']], foot: 'About 15 minutes, no programming needed.' },
    rooms: { title: 'Rooms, devices and endpoints', room: 'Room: Kitchen', dev: 'Devices', d1: 'Camera', d1s: 'video + microphone', d2: 'Speaker', d2s: 'network or in the camera', d3: 'Tablet', d3s: 'screen + device app', ep: 'Interaction endpoint', epS: 'where you talk to the assistant', mic: 'mic', spk: 'speaker', cam: 'camera', dsp: 'display', pol: 'Room policies', pol1: 'vision allowed', pol2: 'faces allowed', pol3: 'cloud media allowed', foot: 'Answers always return to the room where the question was asked.' },
    arch: { title: 'Containers and networks', home: 'Your home network', cams: 'Cameras', cams2: 'RTSP · ONVIF · Tapo', ui: 'Browser · phone · tablet', ui2: 'admin UI and device app', cloud: 'Optional cloud AI', cloud2: 'Google Gemini', core: 'core', coreS: 'API · audio · AI · vision', go: 'go2rtc', goS: 'media: streams, talkback', pg: 'postgres', pgS: 'PostgreSQL 17 + pgvector', sb: 'sandbox', sbS: 'untrusted plugins', internal: 'internal network: no internet', docker: 'Docker Compose on your server' },
    pipe: { title: 'From a spoken sentence to the answer', row1: ['Microphone', 'Echo cancel', 'Voice detect', 'Wakeword', 'Which room?'], row2: ['Speech to text', 'AI + tools', 'Text to speech', 'Output router', 'Speaker / screen'], sub1: ['camera, phone, tablet', 'never hears itself', 'Silero VAD', 'openWakeWord', 'one winner'], sub2: ['faster-whisper', 'Gemini or Ollama', 'Piper', 'same room', 'the answer'], loc: 'runs locally on your server', opt: 'cloud or local, your choice' },
    priv: { title: 'What stays at home', local: 'Stays on your server', l: ['Wakeword and voice detection', 'Speech to text and text to speech', 'Face and object recognition', 'Memory and all recordings', 'Passwords and keys (encrypted)'], cloud: 'Optional: cloud AI', c: ['Your question as text', 'Images or audio only if the room allows it', 'Or use Ollama and send nothing at all'], pol: 'You decide per room', polS: 'Rooms → Policies' },
    vibe: { title: 'Three ways to build JuStAI5 further', w: [['Ask JuStAI5', 'Tell the assistant what you want. It writes the plugin itself.'], ['Build a plugin', 'Use a coding assistant. Review, test, upload as a zip.'], ['Change the core', 'Fork, change in small steps, open a pull request.']], easy: 'easiest', mid: 'most popular', adv: 'for tinkerers', share: 'Share it: plugin zip or pull request' },
  },
  de: {
    how: { title: 'So funktioniert JuStAI5', room: 'In jedem Raum', room1: 'Kamera mit Mikrofon', room2: 'Lautsprecher oder Tablet', room3: 'Beliebiger Bildschirm', srv: 'Dein JuStAI5-Server', srvSub: 'läuft zu Hause, in deinem Netz', hears: 'Hört', hearsS: 'Wakeword, Sprache', sees: 'Sieht', seesS: 'Personen, Tiere, Dinge', rem: 'Merkt sich', remS: 'Fakten, Gewohnheiten', acts: 'Handelt', actsS: 'Plugins, Automationen', ai: 'KI-Modell', ai1: 'Google Gemini (Cloud)', ai2: 'oder Ollama (lokal)', back: 'Die Antwort kommt im selben Raum an, nirgendwo sonst.', ask: '„Hey Jarvis …“' },
    inst: { title: 'Installation in vier Schritten', s: [['Ein Befehl', 'auf einem Linux-PC'], ['Webseite öffnen', 'und anmelden'], ['Raum anlegen', 'Handy oder Kamera'], ['„Hey Jarvis“ sagen', 'und fragen']], foot: 'Etwa 15 Minuten, ohne Programmierkenntnisse.' },
    rooms: { title: 'Räume, Geräte und Endpoints', room: 'Raum: Küche', dev: 'Geräte', d1: 'Kamera', d1s: 'Video + Mikrofon', d2: 'Lautsprecher', d2s: 'im Netz oder in der Kamera', d3: 'Tablet', d3s: 'Bildschirm + Geräte-App', ep: 'Interaction Endpoint', epS: 'dort sprichst du mit dem Assistenten', mic: 'Mikrofon', spk: 'Lautsprecher', cam: 'Kamera', dsp: 'Display', pol: 'Raum-Richtlinien', pol1: 'Vision erlaubt', pol2: 'Gesichter erlaubt', pol3: 'Cloud-Medien erlaubt', foot: 'Antworten kommen immer in dem Raum an, in dem gefragt wurde.' },
    arch: { title: 'Container und Netzwerke', home: 'Dein Heimnetz', cams: 'Kameras', cams2: 'RTSP · ONVIF · Tapo', ui: 'Browser · Handy · Tablet', ui2: 'Admin-Oberfläche und Geräte-App', cloud: 'Optionale Cloud-KI', cloud2: 'Google Gemini', core: 'core', coreS: 'API · Audio · KI · Vision', go: 'go2rtc', goS: 'Medien: Streams, Talkback', pg: 'postgres', pgS: 'PostgreSQL 17 + pgvector', sb: 'sandbox', sbS: 'nicht vertrauenswürdige Plugins', internal: 'internes Netz: kein Internet', docker: 'Docker Compose auf deinem Server' },
    pipe: { title: 'Vom gesprochenen Satz zur Antwort', row1: ['Mikrofon', 'Echo-Entfernung', 'Spracherkennung', 'Wakeword', 'Welcher Raum?'], row2: ['Sprache zu Text', 'KI + Tools', 'Text zu Sprache', 'Output Router', 'Lautsprecher / Display'], sub1: ['Kamera, Handy, Tablet', 'hört sich nie selbst', 'Silero VAD', 'openWakeWord', 'ein Gewinner'], sub2: ['faster-whisper', 'Gemini oder Ollama', 'Piper', 'gleicher Raum', 'die Antwort'], loc: 'läuft lokal auf deinem Server', opt: 'Cloud oder lokal, deine Wahl' },
    priv: { title: 'Was zu Hause bleibt', local: 'Bleibt auf deinem Server', l: ['Wakeword und Spracherkennung', 'Sprache zu Text und Text zu Sprache', 'Gesichts- und Objekterkennung', 'Gedächtnis und alle Aufnahmen', 'Passwörter und Schlüssel (verschlüsselt)'], cloud: 'Optional: Cloud-KI', c: ['Deine Frage als Text', 'Bilder oder Audio nur, wenn der Raum es erlaubt', 'Oder Ollama nutzen und gar nichts senden'], pol: 'Du entscheidest pro Raum', polS: 'Räume → Richtlinien' },
    vibe: { title: 'Drei Wege, JuStAI5 weiterzubauen', w: [['JuStAI5 fragen', 'Sag dem Assistenten, was du willst. Er schreibt das Plugin selbst.'], ['Plugin bauen', 'Mit einem Coding-Assistenten. Prüfen, testen, als Zip hochladen.'], ['Den Kern ändern', 'Forken, in kleinen Schritten ändern, Pull Request öffnen.']], easy: 'am einfachsten', mid: 'am beliebtesten', adv: 'für Tüftler', share: 'Teilen: Plugin-Zip oder Pull Request' },
  },
};

const diagrams = {
  how(s) {
    const d = s.how;
    let b = t(450, 40, d.title, { size: 20, weight: 800 });
    // rooms column
    b += box(30, 70, 230, 250, { stroke: C.mint, dash: '6 6' }) + t(145, 98, d.room, { size: 14, fill: C.mint, weight: 700 });
    [d.room1, d.room2, d.room3].forEach((l, i) => (b += box(50, 115 + i * 62, 190, 48, { r: 12 }) + t(145, 145 + i * 62, l, { size: 14 })));
    // server
    b += box(330, 70, 300, 250, { stroke: C.acc, sw: 2.5, fill: '#221f55' }) + t(480, 100, d.srv, { size: 17, weight: 800 }) + t(480, 120, d.srvSub, { size: 12, fill: C.mute });
    [[d.hears, d.hearsS, C.acc], [d.sees, d.seesS, C.mint], [d.rem, d.remS, C.peach], [d.acts, d.actsS, C.pink]].forEach(([a, c, col], i) => {
      const x = 348 + (i % 2) * 138, y = 138 + Math.floor(i / 2) * 86;
      b += box(x, y, 126, 72, { r: 14, stroke: col }) + t(x + 63, y + 30, a, { size: 15, weight: 700 }) + t(x + 63, y + 52, c, { size: 11.5, fill: C.mute });
    });
    // ai
    b += box(700, 100, 170, 170, { stroke: C.peach }) + t(785, 140, d.ai, { size: 17, weight: 800 }) + t(785, 180, d.ai1, { size: 13, fill: C.mute }) + t(785, 202, d.ai2, { size: 13, fill: C.mute });
    b += arrow(262, 160, 328, 160, C.mint) + arrow(632, 185, 698, 185, C.peach) + arrow(698, 215, 632, 215, C.peach);
    // return path
    b += `<path d="M480 322 V356 H145 V324" stroke="${C.mint}" stroke-width="2" fill="none" stroke-dasharray="7 6"/>` + arrow(145, 340, 145, 322, C.mint);
    b += t(312, 384, d.back, { size: 13.5, fill: C.mint });
    return wrap(900, 405, b, d.title);
  },
  inst(s) {
    const d = s.inst;
    let b = t(450, 40, d.title, { size: 20, weight: 800 });
    const cols = [C.acc, C.mint, C.peach, C.pink];
    d.s.forEach(([a, c], i) => {
      const x = 30 + i * 215;
      b += box(x, 75, 195, 130, { stroke: cols[i] }) + circle(x + 38, 112, i + 1, cols[i]) + t(x + 97, 160, a, { size: 16, weight: 700 }) + t(x + 97, 184, c, { size: 13, fill: C.mute });
      if (i < 3) b += arrow(x + 198, 140, x + 213, 140, C.mute);
    });
    b += t(450, 240, d.foot, { size: 14, fill: C.mute });
    b += box(130, 256, 640, 38, { r: 10, fill: '#0c0b22' }) + t(450, 281, 'curl -fsSL …/install.sh | bash', { size: 14, fill: C.mint, mono: true });
    return wrap(900, 320, b, d.title);
  },
  rooms(s) {
    const d = s.rooms;
    let b = t(450, 40, d.title, { size: 20, weight: 800 });
    b += box(30, 65, 840, 285, { stroke: C.mint, dash: '6 6' }) + t(95, 92, d.room, { size: 14, fill: C.mint, weight: 700 });
    b += t(130, 125, d.dev, { size: 13, fill: C.mute, weight: 700 });
    [[d.d1, d.d1s, C.acc], [d.d2, d.d2s, C.peach], [d.d3, d.d3s, C.pink]].forEach(([a, c, col], i) => (b += box(50, 138 + i * 68, 210, 58, { r: 12, stroke: col }) + `<rect x="50" y="${138 + i * 68}" width="6" height="58" rx="3" fill="${col}"/>` + t(158, 160 + i * 68, a, { size: 15, weight: 700 }) + t(158, 180 + i * 68, c, { size: 11.5, fill: C.mute })));
    // endpoint
    b += box(340, 115, 270, 215, { stroke: C.acc, sw: 2.5, fill: '#221f55' }) + t(475, 145, d.ep, { size: 17, weight: 800 }) + t(475, 165, d.epS, { size: 12, fill: C.mute });
    [[d.mic, C.acc], [d.spk, C.peach], [d.cam, C.acc], [d.dsp, C.pink]].forEach(([a, col], i) => (b += chip(358 + (i % 2) * 124, 190 + Math.floor(i / 2) * 44, 112, a, col)));
    b += arrow(262, 167, 338, 205, C.mute) + arrow(262, 235, 338, 235, C.mute) + arrow(262, 303, 338, 265, C.mute);
    // policies
    b += box(660, 115, 190, 215, { stroke: C.mint }) + t(755, 145, d.pol, { size: 15, weight: 800 });
    [d.pol1, d.pol2, d.pol3].forEach((l, i) => (b += `<circle cx="684" cy="${186 + i * 38}" r="9" fill="${C.mint}"/>` + t(684, 191 + i * 38, '✓', { size: 12, fill: '#0e0d24', weight: 800 }) + t(700, 191 + i * 38, l, { size: 13, anchor: 'start' })));
    b += t(450, 372, d.foot, { size: 13.5, fill: C.mint });
    return wrap(900, 395, b, d.title);
  },
  arch(s) {
    const d = s.arch;
    let b = t(450, 38, d.title, { size: 20, weight: 800 });
    b += box(30, 60, 840, 330, { stroke: C.acc, dash: '8 6', fill: 'none' }) + t(120, 85, d.docker, { size: 12.5, fill: C.acc, weight: 700 });
    b += node(340, 105, 220, 84, d.core, [d.coreS], { color: C.acc, size: 18 });
    b += node(70, 105, 200, 84, d.go, [d.goS], { color: C.mint, size: 18 });
    b += node(340, 270, 220, 84, d.pg, [d.pgS], { color: C.peach, size: 18 });
    b += node(630, 105, 200, 84, d.sb, [d.sbS], { color: C.pink, size: 18 });
    b += arrow(272, 147, 338, 147, C.mint) + arrow(338, 160, 272, 160, C.mint);
    b += arrow(450, 191, 450, 268, C.peach);
    b += arrow(562, 147, 628, 147, C.pink) + arrow(628, 160, 562, 160, C.pink);
    b += t(730, 215, d.internal, { size: 11.5, fill: C.pink });
    // outside
    b += box(70, 270, 200, 84, { r: 14 }) + t(170, 300, d.cams, { size: 15, weight: 700 }) + t(170, 322, d.cams2, { size: 12, fill: C.mute });
    b += arrow(170, 268, 170, 191, C.mint, '5 5');
    b += box(630, 270, 200, 84, { r: 14 }) + t(730, 300, d.cloud, { size: 15, weight: 700 }) + t(730, 322, d.cloud2, { size: 12, fill: C.mute });
    b += `<path d="M562 175 H600 V312 H628" stroke="${C.peach}" stroke-width="2" fill="none" stroke-dasharray="5 5"/>` + arrow(610, 312, 628, 312, C.peach);
    b += t(450, 413, d.home + ': ' + d.ui + ' · ' + d.ui2, { size: 12.5, fill: C.mute });
    return wrap(900, 435, b, d.title);
  },
  pipe(s) {
    const d = s.pipe;
    let b = t(450, 38, d.title, { size: 20, weight: 800 });
    const row = (labels, subs, y, cols) =>
      labels.map((l, i) => {
        const x = 24 + i * 174;
        return box(x, y, 152, 78, { r: 14, stroke: cols[i] }) + t(x + 76, y + 33, l, { size: 14.5, weight: 700 }) + t(x + 76, y + 56, subs[i], { size: 11.5, fill: C.mute }) + (i < 4 ? arrow(x + 154, y + 39, x + 172, y + 39, C.mute) : '');
      }).join('');
    b += row(d.row1, d.sub1, 90, [C.mint, C.mint, C.mint, C.mint, C.mint]);
    b += row(d.row2, d.sub2, 220, [C.mint, C.peach, C.mint, C.acc, C.acc]);
    b += `<path d="M810 168 V194 H100 V220" stroke="${C.mute}" stroke-width="2" fill="none"/>` + arrow(100, 200, 100, 218, C.mute);
    b += `<rect x="24" y="330" width="14" height="14" rx="4" fill="${C.mint}"/>` + t(46, 342, d.loc, { size: 12.5, anchor: 'start', fill: C.mute });
    b += `<rect x="290" y="330" width="14" height="14" rx="4" fill="${C.peach}"/>` + t(312, 342, d.opt, { size: 12.5, anchor: 'start', fill: C.mute });
    return wrap(900, 365, b, d.title);
  },
  priv(s) {
    const d = s.priv;
    let b = t(450, 38, d.title, { size: 20, weight: 800 });
    b += box(30, 62, 420, 250, { stroke: C.mint, sw: 2.2, fill: '#1a2a3d' }) + t(240, 94, '🏠 ' + d.local, { size: 17, weight: 800, fill: C.mint });
    d.l.forEach((l, i) => (b += `<circle cx="62" cy="${130 + i * 34}" r="9" fill="${C.mint}"/>` + t(62, 135 + i * 34, '✓', { size: 12, fill: '#0e0d24', weight: 800 }) + t(80, 135 + i * 34, l, { size: 13.5, anchor: 'start' })));
    b += box(480, 62, 390, 250, { stroke: C.peach, dash: '7 6' }) + t(675, 94, '☁ ' + d.cloud, { size: 17, weight: 800, fill: C.peach });
    d.c.forEach((l, i) => (b += `<circle cx="512" cy="${130 + i * 34}" r="4" fill="${C.peach}"/>` + t(526, 135 + i * 34, l, { size: 13.5, anchor: 'start' })));
    b += arrow(452, 187, 478, 187, C.mute, '5 5');
    b += box(250, 332, 400, 56, { r: 14, stroke: C.acc }) + t(450, 358, d.pol, { size: 15, weight: 800 }) + t(450, 377, d.polS, { size: 12, fill: C.mute });
    return wrap(900, 410, b, d.title);
  },
  vibe(s) {
    const d = s.vibe;
    let b = t(450, 40, d.title, { size: 20, weight: 800 });
    const tags = [d.easy, d.mid, d.adv], cols = [C.mint, C.acc, C.peach];
    d.w.forEach(([a, c], i) => {
      const x = 30 + i * 285;
      b += box(x, 70, 265, 170, { stroke: cols[i] }) + circle(x + 36, 108, i + 1, cols[i]) + `<rect x="${x + 150}" y="94" width="${100}" height="24" rx="12" fill="${cols[i]}22" stroke="${cols[i]}"/>` + t(x + 200, 111, tags[i], { size: 11.5 });
      b += t(x + 132, 156, a, { size: 17, weight: 800 });
      // wrapped description (two lines)
      const words = c.split(' '); let l1 = '', l2 = '';
      words.forEach((w) => ((l1 + ' ' + w).length < 34 && !l2 ? (l1 += ' ' + w) : (l2 += ' ' + w)));
      b += t(x + 132, 186, l1.trim(), { size: 12.5, fill: C.mute }) + t(x + 132, 206, l2.trim().slice(0, 44), { size: 12.5, fill: C.mute });
      b += arrow(x + 132, 242, x + 132, 276, cols[i]);
    });
    b += box(200, 280, 500, 50, { r: 25, stroke: C.mint, fill: '#1a2a3d' }) + t(450, 311, '🌍 ' + d.share, { size: 15, weight: 700 });
    return wrap(900, 350, b, d.title);
  },
};

let n = 0;
for (const lang of ['en', 'de']) for (const [name, fn] of Object.entries(diagrams)) { writeFileSync(path.join(out, `${name}.${lang}.svg`), fn(T[lang])); n++; }
console.log(`Wrote ${n} diagrams to ${out}`);
