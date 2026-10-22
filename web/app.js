/* Автокернер, веб-версия: страница. Расчёт — в отдельном потоке (Pyodide),
   шрифт никуда не уходит. Всё живёт внутри #ak-app и ничего не трогает
   снаружи: ни стили сайта, ни его виджеты. */
(function () {
  'use strict';
  var root = document.getElementById('ak-app');
  if (!root || root.getAttribute('data-ak-ready')) return;
  root.setAttribute('data-ak-ready', '1');

  var DATA = __AK_DATA__;
  // язык — как у сайта: английская версия открывается с ?lang=en
  var EN = /(^|[?&])lang=en(&|$)/.test(location.search);
  var L = EN ? 1 : 0;
  var W = {
    drop_title: ['Перетащите сюда файл шрифта', 'Drop a font file here'],
    pick: ['Выбрать файл', 'Choose a file'],
    drop_note: ['TTF, OTF, WOFF или WOFF2, статичное начертание. Файл не покидает ваш компьютер: расчёт идёт прямо в браузере.',
                'TTF, OTF, WOFF or WOFF2, a static style. The file never leaves your computer: everything runs in your browser.'],
    engine_loading: ['Загружаю движок расчёта — около 15 МБ, только в первый раз…', 'Loading the engine — about 15 MB, first time only…'],
    engine_failed: ['Движок не загрузился: %s. Обновите страницу.', 'The engine did not load: %s. Please reload the page.'],
    reading: ['Читаю шрифт…', 'Reading the font…'],
    err_variable: ['Это вариативный шрифт. Веб-версия правит статичные начертания; для вариативных есть сценарий Автокернер для FontLab 8.',
                   'This is a variable font. The web version works on static styles; for variable fonts there is the Autokerner script for FontLab 8.'],
    err_collection: ['Это коллекция (TTC). Сохраните начертания отдельными файлами.', 'This is a font collection (TTC). Save the styles as separate files.'],
    err_not_a_font: ['Это не файл шрифта, или он повреждён.', 'This is not a font file, or it is damaged.'],
    err_no_outlines: ['В шрифте нет контуров TrueType или CFF.', 'The font has no TrueType or CFF outlines.'],
    another: ['Другой файл', 'Another file'],
    meta: ['%s знаков · %s · %s · UPM %s', '%s glyphs · %s · %s · UPM %s'],
    meta_kern: ['кернинг: %s пар', 'kerning: %s pairs'],
    meta_nokern: ['без кернинга', 'no kerning'],
    big: ['Большой шрифт: расчёт займёт несколько минут.', 'A big font: the calculation will take a few minutes.'],
    download: ['Скачать шрифт', 'Download the font'],
    fea: ['Кернинг .fea', 'Kerning .fea'],
    csv: ['Поля .csv', 'Sidebearings .csv'],
    first: ['Выберите, что считать, и нажмите «Посчитать».', 'Choose what to calculate and press Calculate.'],
    done: ['Посчитано за %s с. Новый файл — кнопкой «Скачать шрифт».', 'Calculated in %s s. Get the new file with Download the font.'],
    check_ok: ['Новый файл прочитан обратно и сверен с расчётом: всё сходится.', 'The new file was read back and checked against the calculation: everything matches.'],
    check_bad: ['Сверка нашла расхождения: %s. Напишите, пожалуйста, на pavljenko@ya.ru — пришлите шрифт, если можно.',
                'The check found differences: %s. Please write to pavljenko@ya.ru, with the font if you can.'],
    kept: ['Имя шрифта, контуры и прочие таблицы прежние: меняются только поля, ширины и кернинг.',
           'The font name, outlines and other tables stay as they were: only sidebearings, widths and kerning change.'],
    now: ['Сейчас', 'Now'],
    after: ['После', 'After'],
    preview_hint: ['Строки набраны самими файлами — исходным и новым, с их кернингом. Синим — знаки с новыми полями.',
                   'Both lines are set with the files themselves — the original and the new one, with their kerning. Blue — glyphs with new sidebearings.'],
    size: ['Кегль', 'Size'],
    not_yet: ['Здесь появится итог расчёта.', 'The result will appear here.'],
    edits_hint: ['Поиск по символу или имени знака показывает все его пары.', 'Searching by character or glyph name lists all pairs of a glyph.'],
    writing: ['записываю шрифт', 'writing the font'],
    checking: ['сверяю записанное', 'checking the result'],
    stopped: ['Остановлено. Шрифт не менялся.', 'Stopped. Nothing was changed.'],
    foot: ['Расчёт идёт в вашем браузере, файл никуда не загружается. Автокернер бесплатный, с открытым кодом. Для FontLab 8 есть сценарий с тем же расчётом — он работает и с вариативными шрифтами. Нашли ошибку? <a href="mailto:pavljenko@ya.ru">pavljenko@ya.ru</a>',
           'Everything runs in your browser; the file is not uploaded anywhere. Autokerner is free and open source. There is also a script for FontLab 8 with the same calculation — it works with variable fonts too. Found a bug? <a href="mailto:pavljenko@ya.ru">pavljenko@ya.ru</a>'],
    unit_pct: ['%', '%']
  };
  var STORE = 'autokerner-web:options';
  var RULE = ['looseness', 'spacing_threshold', 'word_gap', 'space_edge', 'kern_strength', 'kern_threshold',
              'kern_clearance', 'kern_precision', 'kern_limit', 'kern_round', 'kern_max_tight', 'kern_max_loose', 'kern_figures'];

  function t(k) { var x = W[k] || DATA.texts[k]; return x ? x[L] : k; }
  function fmt(s) {
    var a = arguments, i = 1;
    return s.replace(/%(\.0f|[sd])/g, function () { return a[i++]; });
  }
  function num(x) { return Number(x).toLocaleString(EN ? 'en-US' : 'ru-RU'); }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }
  function q(name) { return root.querySelector('[data-ak="' + name + '"]'); }
  function store(get, value) {
    try {
      if (get) return JSON.parse(localStorage.getItem(STORE) || 'null');
      localStorage.setItem(STORE, JSON.stringify(value));
    } catch (e) { return null; }
  }

  // ── разметка ──

  function check(field, text, tip) {
    return '<label class="ak-check" title="' + esc(tip || '') + '"><input type="checkbox" data-o="' + field + '"><span>' + esc(text) + '</span></label>';
  }
  function row(field, label, tip, control) {
    return '<label class="ak-row" title="' + esc(tip || '') + '"><span>' + esc(label) + '</span>' + control(field) + '</label>';
  }
  function numberBox(min, max, step) {
    return function (field) {
      return '<input type="number" inputmode="numeric" data-o="' + field + '" min="' + min + '" max="' + max + '" step="' + (step || 1) + '">';
    };
  }
  function selectBox(items) {
    return function (field) {
      return '<select data-o="' + field + '">' + items.map(function (it) {
        return '<option value="' + esc(it[0]) + '">' + esc(it[1]) + '</option>';
      }).join('') + '</select>';
    };
  }
  var pm = t('per_mille').trim();
  var fineHtml =
    '<div class="ak-h5">' + esc(t('sub_spacing')) + '</div>' +
    row('looseness', t('looseness') + ', %', t('looseness_tip'), numberBox(-30, 30)) +
    row('spacing_threshold', t('threshold') + ', ' + pm, t('threshold_tip'), numberBox(2, 60)) +
    row('word_gap', t('word_gap') + ', %', t('word_gap_tip'), numberBox(25, 80)) +
    row('space_edge', t('space_fit'), t('space_fit_tip'), selectBox(t('space_fit_items').split('|').map(function (s, i) { return [i ? '0' : '1', s]; }))) +
    '<div class="ak-h5">' + esc(t('sub_kerning')) + '</div>' +
    row('kern_strength', t('strength') + ', %', t('strength_tip'), numberBox(30, 200, 5)) +
    row('kern_threshold', t('kthreshold') + ', ' + pm, t('kthreshold_tip'), numberBox(1, 40)) +
    row('kern_clearance', t('clearance') + ', ' + pm, t('clearance_tip'), numberBox(0, 80)) +
    row('kern_figures', t('figures'), t('figures_tip'), selectBox(t('figures_items').split('|').map(function (s, i) { return [DATA.figures[i], s]; }))) +
    row('kern_precision', t('precision'), t('precision_tip'), selectBox(DATA.precision.map(function (x) { return [x, x + ' ' + pm]; }))) +
    row('kern_limit', t('limit'), t('limit_tip'), selectBox(DATA.limits.map(function (x) { return [x, x ? num(x) : t('no_limit')]; }))) +
    row('kern_round', t('round'), t('round_tip'), selectBox(DATA.rounds.map(function (x) { return [x, String(x)]; }))) +
    row('kern_max_tight', t('max_tight') + ', ' + pm, t('max_tight_tip'), numberBox(0, 400)) +
    row('kern_max_loose', t('max_loose') + ', ' + pm, t('max_loose_tip'), numberBox(0, 400)) +
    '<p style="margin-top:12px"><button type="button" class="ak-btn ak-quiet" data-ak="reset">' + esc(t('reset')) + '</button></p>';

  root.innerHTML =
    '<div data-ak="start">' +
      '<div class="ak-drop" data-ak="drop">' +
        '<div class="ak-h3" role="heading" aria-level="2">' + esc(t('drop_title')) + '</div>' +
        '<button type="button" class="ak-btn" data-ak="pick">' + esc(t('pick')) + '</button>' +
        '<p class="ak-note">' + esc(t('drop_note')) + '</p>' +
      '</div>' +
      '<div class="ak-engine" data-ak="engine"></div>' +
    '</div>' +
    '<input type="file" accept=".ttf,.otf,.woff,.woff2" class="ak-hidden" data-ak="file">' +
    '<div class="ak-hidden" data-ak="work">' +
      '<div class="ak-font"><div><b data-ak="fname"></b><div class="ak-meta" data-ak="fmeta"></div></div>' +
        '<button type="button" class="ak-btn ak-quiet" data-ak="another">' + esc(t('another')) + '</button></div>' +
      '<div class="ak-main">' +
        '<div class="ak-side">' +
          '<div class="ak-sec"><div class="ak-h4" role="heading" aria-level="3">' + esc(t('sec_what')) + '</div>' +
            check('spacing', t('do_spacing'), t('do_spacing_tip')) +
            check('space', t('do_space'), t('do_space_tip')) +
            check('kerning', t('do_kerning'), t('do_kerning_tip')) +
            '<div class="ak-sub" data-ak="mode">' +
              '<div class="ak-muted" style="font-size:14px">' + esc(t('mode_label')) + '</div>' +
              '<label class="ak-check"><input type="radio" name="ak-mode" value="replace" data-o="kern_mode"><span>' + esc(t('mode_replace')) + '</span></label>' +
              '<label class="ak-check"><input type="radio" name="ak-mode" value="merge" data-o="kern_mode"><span>' + esc(t('mode_merge')) + '</span></label>' +
              '<div class="ak-hint" data-ak="mode-note"></div>' +
            '</div>' +
            check('nbsp_follows_space', t('nbsp'), t('nbsp_tip')) +
          '</div>' +
          '<div class="ak-sec"><div class="ak-h4" role="heading" aria-level="3">' + esc(t('sec_rule')) + '</div>' +
            '<select data-ak="preset">' + DATA.preset_keys.map(function (k) {
              return '<option value="' + k + '">' + esc(k === 'custom' ? t('custom') : DATA.titles[k][L]) + '</option>';
            }).join('') + '</select>' +
            '<div class="ak-preset-note" data-ak="preset-note"></div>' +
            '<details><summary>' + esc(t('fine')) + '</summary><div class="ak-fine">' + fineHtml + '</div></details>' +
          '</div>' +
          '<div class="ak-run">' +
            '<button type="button" class="ak-btn ak-wide" data-ak="calc">' + esc(t('calc')) + '</button>' +
            '<div class="ak-bar"><i data-ak="bar"></i></div>' +
            '<div class="ak-status" data-ak="status"></div>' +
          '</div>' +
        '</div>' +
        '<div class="ak-results">' +
          '<div class="ak-tabs" role="tablist">' + ['summary', 'preview', 'edits'].map(function (k, i) {
            return '<button type="button" role="tab" class="ak-tab' + (i ? '' : ' ak-on') + '" data-tab="' + k + '">' + esc(t('tab_' + k)) + '</button>';
          }).join('') + '</div>' +
          '<div class="ak-get ak-hidden" data-ak="get">' +
            '<button type="button" class="ak-btn" data-ak="download">' + esc(t('download')) + '</button>' +
            '<button type="button" class="ak-btn ak-quiet" data-ak="fea">' + esc(t('fea')) + '</button>' +
            '<button type="button" class="ak-btn ak-quiet" data-ak="csv">' + esc(t('csv')) + '</button>' +
          '</div>' +
          '<div data-pane="summary"><div class="ak-empty">' + esc(t('not_yet')) + '</div></div>' +
          '<div data-pane="preview" class="ak-hidden">' +
            '<div class="ak-prev-tools">' +
              '<input type="text" data-ak="ptext" spellcheck="false">' +
              '<label>' + esc(t('size')) + ' <input type="range" min="16" max="160" value="48" data-ak="psize"></label>' +
              '<label><input type="checkbox" checked data-ak="pkern"> ' + esc(t('preview_kern')) + '</label>' +
            '</div>' +
            '<div class="ak-lines" data-ak="lines"></div>' +
            '<p class="ak-hint2">' + esc(t('preview_hint')) + '</p>' +
          '</div>' +
          '<div data-pane="edits" class="ak-hidden">' +
            '<input type="search" data-ak="search" placeholder="' + esc(t('search')) + '">' +
            '<p class="ak-hint2">' + esc(t('edits_hint')) + '</p>' +
            '<div class="ak-edits" data-ak="edits"></div>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<p class="ak-foot">' + t('foot') + '</p>';

  // ── поток расчёта ──

  var worker = null, ready = null, seq = 0, waiting = {};
  var font = null;          // {name, bytes, info, face}
  var result = null;        // {summary, bytes, face, file}
  var running = false, started = 0;

  function startWorker() {
    if (ready) return ready;
    var src = new Blob([DATA.worker], { type: 'text/javascript' });
    worker = new Worker(URL.createObjectURL(src));
    worker.onmessage = function (e) {
      var m = e.data;
      if (m.progress !== undefined) return onProgress(m.progress);
      var w = waiting[m.id];
      if (!w) return;
      delete waiting[m.id];
      if (m.error) w.reject(new Error(m.error)); else w.resolve(m);
    };
    worker.onerror = function (e) {
      Object.keys(waiting).forEach(function (id) { waiting[id].reject(new Error(e.message || 'worker')); delete waiting[id]; });
    };
    q('engine').textContent = t('engine_loading');
    ready = call({ type: 'init', pyodide: DATA.pyodide, sources: DATA.sources }).then(function () {
      q('engine').textContent = '';
    }, function (err) {
      ready = null;
      q('engine').innerHTML = '<span class="ak-error">' + esc(fmt(t('engine_failed'), err.message)) + '</span>';
      throw err;
    });
    return ready;
  }

  function call(msg, transfer) {
    return new Promise(function (resolve, reject) {
      msg.id = ++seq;
      waiting[msg.id] = { resolve: resolve, reject: reject };
      worker.postMessage(msg, transfer || []);
    });
  }

  function stopWorker() {
    if (worker) worker.terminate();
    worker = null; ready = null;
    Object.keys(waiting).forEach(function (id) { waiting[id].reject(new Error('stopped')); delete waiting[id]; });
  }

  // ── шрифт ──

  function readFile(file) {
    if (!file) return;
    status(t('reading'));
    file.arrayBuffer().then(function (buf) {
      return startWorker().then(function () { return openBytes(file.name, buf); });
    }).catch(function (err) { status(t('error') + ': ' + err.message, true); });
  }

  function openBytes(name, buf) {
    var copy = buf.slice(0);
    return call({ type: 'open', bytes: new Uint8Array(copy), name: name }, [copy]).then(function (m) {
      var info = JSON.parse(m.json);
      if (info.error) {
        if (font) status(t('err_' + info.error), true);
        else { q('engine').innerHTML = '<span class="ak-error">' + esc(t('err_' + info.error)) + '</span>'; status(''); }
        return;
      }
      font = { name: name, bytes: buf, info: info };
      result = null;
      return addFace(buf, 'before').then(function (family) {
        font.face = family;
        showFont();
      });
    });
  }

  var faces = {};
  function addFace(buf, kind) {
    if (faces[kind]) document.fonts.delete(faces[kind]);
    var family = 'ak-' + kind + '-' + (++seq);
    var face = new FontFace(family, buf.slice(0));
    faces[kind] = face;
    return face.load().then(function () { document.fonts.add(face); return family; });
  }

  function showFont() {
    var i = font.info;
    q('start').classList.add('ak-hidden');
    q('work').classList.remove('ak-hidden');
    q('fname').textContent = (i.family || font.name) + (i.style ? ' ' + i.style : '');
    var fmtName = i.flavor ? i.flavor.toUpperCase() + ' (' + i.outlines + ')' : (i.outlines === 'CFF' ? 'OTF (CFF)' : 'TTF');
    q('fmeta').textContent = fmt(t('meta'), num(i.glyphs), fmtName,
      i.kern_pairs ? fmt(t('meta_kern'), num(i.kern_pairs)) : t('meta_nokern'), i.upm) +
      (i.glyphs > 1200 ? ' · ' + t('big') : '');
    q('get').classList.add('ak-hidden');
    root.querySelector('[data-pane="summary"]').innerHTML = '<div class="ak-empty">' + esc(t('not_yet')) + '</div>';
    q('edits').innerHTML = '';
    status(t('first'));
    bar(0);
    drawPreview();
  }

  // ── настройки ──

  function controls() { return root.querySelectorAll('[data-o]'); }
  function readOptions() {
    var o = {};
    controls().forEach(function (el) {
      var k = el.getAttribute('data-o');
      if (el.type === 'checkbox') o[k] = el.checked;
      else if (el.type === 'radio') { if (el.checked) o[k] = el.value; }
      else if (k === 'space_edge') o[k] = el.value === '1';
      else if (k === 'kern_figures') o[k] = el.value;
      else o[k] = Number(el.value);
    });
    return o;
  }
  function fill(o) {
    controls().forEach(function (el) {
      var k = el.getAttribute('data-o');
      if (!(k in o)) return;
      if (el.type === 'checkbox') el.checked = !!o[k];
      else if (el.type === 'radio') el.checked = el.value === o[k];
      else if (k === 'space_edge') el.value = o[k] ? '1' : '0';
      else el.value = String(o[k]);
    });
    sync();
  }
  function presetOf(o) {
    for (var i = 0; i < DATA.preset_keys.length - 1; i++) {
      var k = DATA.preset_keys[i], p = Object.assign({}, DATA.defaults, DATA.presets[k]);
      if (RULE.every(function (f) { return String(p[f]) === String(o[f]); })) return k;
    }
    return 'custom';
  }
  function sync() {
    var o = readOptions();
    var k = presetOf(o);
    q('preset').value = k;
    q('preset-note').textContent = k === 'custom' ? t('custom_note') : DATA.notes[k][L];
    q('mode').style.opacity = o.kerning ? 1 : 0.4;
    q('mode-note').textContent = o.kern_mode === 'merge' ? t('mode_merge_note') : t('mode_replace_note');
    q('calc').disabled = !running && !(o.spacing || o.space || o.kerning);
  }
  function onChange() {
    sync();
    store(false, readOptions());
    if (result) status(t('stale'));
  }

  // ── расчёт ──

  function status(text, bad) {
    var s = q('status');
    s.textContent = text;
    s.classList.toggle('ak-error', !!bad);
  }
  function bar(x) { q('bar').style.width = Math.round(Math.max(0, Math.min(1, x)) * 100) + '%'; }

  function onProgress(text) {
    var shown = text;
    if (text === 'запись') shown = t('writing');
    else if (text === 'сверка') shown = t('checking');
    else if (EN) {
      DATA.tr.some(function (p) {
        var re = new RegExp(p[0]);
        if (re.test(text)) { shown = text.replace(re, p[1].replace(/\\(\d)/g, '$$$1')); return true; }
        return false;
      });
    }
    status(shown);
    var m = /знак (\d+) из (\d+)/.exec(text);
    if (/^апроши/.test(text)) bar(0.04);
    else if (m && /^кернинг: мастер/.test(text)) bar(0.05 + 0.75 * m[1] / m[2]);
    else if (m) bar(0.8 + 0.12 * m[1] / m[2]);
    else if (text === 'запись') bar(0.94);
    else if (text === 'сверка') bar(0.97);
  }

  function calculate() {
    if (running) return stop();
    if (!font) return;
    running = true;
    started = Date.now();
    q('calc').textContent = t('stop');
    status(t('progress'));
    bar(0.02);
    var opts = readOptions();
    startWorker().then(function () {
      return call({ type: 'calc', options: JSON.stringify(opts) });
    }).then(function (m) {
      var summary = JSON.parse(m.json);
      var bytes = m.font.buffer.slice(m.font.byteOffset, m.font.byteOffset + m.font.byteLength);
      return addFace(bytes, 'after').then(function (family) {
        result = { summary: summary, bytes: bytes, face: family };
        running = false;
        q('calc').textContent = t('calc');
        bar(1);
        status(fmt(t('done'), ((Date.now() - started) / 1000).toFixed(0)));
        q('get').classList.remove('ak-hidden');
        drawSummary();
        drawPreview();
        if (currentTab === 'edits') loadEdits();
        // на узком экране итог — под настройками: показать его
        if (window.innerWidth <= 900) root.querySelector('.ak-results').scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }).catch(function (err) {
      running = false;
      q('calc').textContent = t('calc');
      if (err.message !== 'stopped') status(t('error') + ': ' + err.message, true);
    });
  }

  function stop() {
    stopWorker();
    running = false;
    q('calc').textContent = t('calc');
    bar(0);
    status(t('stopped'));
    // поток начинается заново и снова читает шрифт — тот же файл
    if (font) startWorker().then(function () { return openBytes(font.name, font.bytes); }).then(function () { status(t('stopped')); });
  }

  // ── итог ──

  function card(title, big, caption) {
    return '<div class="ak-card"><small>' + esc(title) + '</small><strong class="ak-num">' + big + '</strong><span>' + caption + '</span></div>';
  }

  function drawSummary() {
    var s = result.summary, h = '<div class="ak-cards">';
    if (!s.spacing) h += card(t('spacing'), '—', esc(t('not_calc')));
    else if (s.spacing.changed) h += card(t('spacing'), num(s.spacing.changed), esc(fmt(t('spacing_cap'), num(s.spacing.of))));
    else h += card(t('spacing'), '0', esc(t('spacing_none')));
    if (!s.space_on) h += card(t('space'), '—', esc(t('not_calc')));
    else if (s.space) h += card(t('space'), num(s.space[0]) + ' → ' + num(s.space[1]), esc(EN ? 'units' : 'единиц'));
    else h += card(t('space'), '—', esc(t('space_none')));
    var k = s.kerning;
    if (!k) h += card(t('kerning'), '—', esc(t('not_calc')));
    else {
      var size = fmt(EN ? '≈ %s KB in the file' : '≈ %s КБ в файле', num(Math.max(1, Math.round(k.size / 1000))));
      if (k.mode === 'replace') {
        h += card(t('kerning'), num(k.before) + ' → ' + num(k.written) + ' <span style="font-size:15px">' + esc(t('kern_pairs')) + '</span>',
          esc(t('kern_whole')) + '<br>' + esc(fmt(t('kern_whole_n'), k.left, k.right, num(k.cells), num(k.pairs))) + '<br>' + esc(size));
      } else {
        h += card(t('kerning'), num(k.before) + ' → ' + num(k.before + k.written) + ' <span style="font-size:15px">' + esc(t('kern_pairs')) + '</span>',
          esc(fmt(t('kern_missing'), num(k.written))) + '<br>' + esc(size));
      }
    }
    h += '</div>';
    if (s.check === 0) h += '<div class="ak-ok">✓ ' + esc(t('check_ok')) + ' ' + esc(t('kept')) + '</div>';
    else h += '<div class="ak-warn">' + esc(fmt(t('check_bad'), num(s.check))) + '</div>';
    if (k && k.truncated) h += '<div class="ak-warn">' + esc(fmt(t('truncated'), EN ? 'some' : 'часть')) + '</div>';
    if (s.collisions.length) {
      var list = s.collisions.slice(0, 4).map(function (c) { return c.slice(0, 3).join(''); }).join(', ');
      h += '<div class="ak-warn">' + esc(fmt(t('collisions'), list, s.collisions.length)) + '</div>';
    }
    if (s.control.length) {
      h += '<div class="ak-h" role="heading" aria-level="3">' + esc(t('control')) + '</div><table><tr><th>' + esc(t('pair')) + '</th><th>' + esc(t('now')) + '</th><th>' + esc(t('after')) + '</th></tr>';
      s.control.forEach(function (c) {
        h += '<tr><td style="font-family:' + font.face + ';font-size:20px">' + esc(c[0]) + '</td><td>' + c[1] + '</td><td><b>' + c[2] + '</b></td></tr>';
      });
      h += '</table>';
    }
    root.querySelector('[data-pane="summary"]').innerHTML = h;
  }

  // ── строка ──

  function drawPreview() {
    if (!font) return;
    var text = q('ptext').value, size = q('psize').value + 'px';
    var kern = q('pkern').checked ? 'normal' : 'none';
    var style = 'font-size:' + size + ';font-kerning:' + kern + ';font-feature-settings:"kern" ' + (q('pkern').checked ? 1 : 0) + ';';
    var h = '<div class="ak-line"><small>' + esc(t('now')) + '</small><div style="font-family:' + font.face + ';' + style + '">' + esc(text) + '</div></div>';
    if (result) {
      var changed = result.summary.changed_chars, out = '';
      Array.from(text).forEach(function (ch) {
        out += changed.indexOf(ch) >= 0 ? '<span class="ak-c">' + esc(ch) + '</span>' : esc(ch);
      });
      h += '<div class="ak-line"><small>' + esc(t('after')) + '</small><div style="font-family:' + result.face + ';' + style + '">' + out + '</div></div>';
    }
    q('lines').innerHTML = h;
  }

  // ── правки ──

  var editsTimer = null;
  function loadEdits() {
    if (!result) { q('edits').innerHTML = '<div class="ak-empty">' + esc(t('not_yet')) + '</div>'; return; }
    call({ type: 'edits', query: q('search').value }).then(function (m) {
      var e = JSON.parse(m.json), h = '<div>';
      h += '<div class="ak-h" role="heading" aria-level="3">' + esc(fmt(t('edits_glyphs'), e.spacing.length)) + '</div><div class="ak-scroll"><table><tr><th></th><th>' + esc(t('glyph')) + '</th><th>' +
        esc(t('lsb')) + '</th><th>' + esc(t('rsb')) + '</th><th>' + esc(t('width')) + '</th></tr>';
      e.spacing.forEach(function (r) {
        h += '<tr><td class="ak-g" style="font-family:' + font.face + '">' + esc(r[0]) + '</td><td class="ak-name">' + esc(r[1]) + '</td><td>' +
          r[2] + ' → <b>' + r[3] + '</b></td><td>' + r[4] + ' → <b>' + r[5] + '</b></td><td>' + r[6] + ' → <b>' + r[7] + '</b></td></tr>';
      });
      h += '</table></div></div><div>';
      var title = e.not_found ? fmt(t('edits_pairs_none'), q('search').value) :
        (e.glyph ? fmt(t('edits_pairs_glyph'), e.glyph, e.pairs.length) : fmt(t('edits_pairs_top'), e.pairs.length));
      h += '<div class="ak-h" role="heading" aria-level="3">' + esc(title) + '</div><div class="ak-scroll"><table><tr><th></th><th>' + esc(t('pair')) + '</th><th>' +
        esc(t('now')) + '</th><th>' + esc(t('after')) + '</th></tr>';
      e.pairs.forEach(function (r) {
        h += '<tr><td class="ak-g" style="font-family:' + result.face + '">' + esc(r[0]) + '</td><td class="ak-name">' + esc(r[1] + ' ' + r[2]) +
          '</td><td>' + r[3] + '</td><td><b>' + r[4] + '</b></td></tr>';
      });
      q('edits').innerHTML = h + '</table></div></div>';
    }).catch(function (err) { status(t('error') + ': ' + err.message, true); });
  }

  // ── файлы ──

  function save(name, data, type) {
    var url = URL.createObjectURL(new Blob([data], { type: type }));
    var a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }
  function saveReport(ext) {
    call({ type: 'files' }).then(function (m) {
      var files = JSON.parse(m.json);
      Object.keys(files).forEach(function (name) {
        if (name.slice(-ext.length) === ext) save(name, files[name], 'text/plain;charset=utf-8');
      });
    });
  }

  // ── события ──

  var currentTab = 'summary';
  root.addEventListener('click', function (e) {
    var el = e.target.closest('[data-ak],[data-tab]');
    if (!el) return;
    var what = el.getAttribute('data-ak'), tab = el.getAttribute('data-tab');
    if (tab) {
      currentTab = tab;
      root.querySelectorAll('.ak-tab').forEach(function (b) { b.classList.toggle('ak-on', b === el); });
      root.querySelectorAll('[data-pane]').forEach(function (p) { p.classList.toggle('ak-hidden', p.getAttribute('data-pane') !== tab); });
      if (tab === 'preview') drawPreview();
      if (tab === 'edits') loadEdits();
    } else if (what === 'pick' || what === 'another') {
      q('file').click();
    } else if (what === 'calc') {
      calculate();
    } else if (what === 'reset') {
      fill(Object.assign({}, DATA.defaults));
      onChange();
    } else if (what === 'download' && result) {
      save(result.summary.file_name, result.bytes, 'font/' + (font.info.flavor || (font.info.outlines === 'CFF' ? 'otf' : 'ttf')));
    } else if (what === 'fea') {
      saveReport('.fea');
    } else if (what === 'csv') {
      saveReport('.csv');
    }
  });
  q('file').addEventListener('change', function () { readFile(this.files[0]); this.value = ''; });
  root.addEventListener('change', function (e) {
    if (e.target.getAttribute('data-o')) onChange();
    if (e.target === q('preset')) {
      var k = q('preset').value;
      if (k !== 'custom') {
        var o = readOptions();
        RULE.forEach(function (f) { o[f] = DATA.defaults[f]; });
        Object.assign(o, DATA.presets[k]);
        fill(o);
        onChange();
      }
    }
  });
  root.addEventListener('input', function (e) {
    if (e.target === q('ptext') || e.target === q('psize') || e.target === q('pkern')) drawPreview();
    if (e.target === q('search')) { clearTimeout(editsTimer); editsTimer = setTimeout(loadEdits, 250); }
  });
  ['dragenter', 'dragover'].forEach(function (ev) {
    root.addEventListener(ev, function (e) { e.preventDefault(); q('drop').classList.add('ak-over'); startWorker(); });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    root.addEventListener(ev, function (e) { e.preventDefault(); q('drop').classList.remove('ak-over'); });
  });
  root.addEventListener('drop', function (e) {
    var f = e.dataTransfer && e.dataTransfer.files[0];
    if (f) readFile(f);
  });
  // движок грузится, когда посетитель потянулся к инструменту, — не вместе со страницей
  ['pointerenter', 'focusin', 'touchstart'].forEach(function (ev) {
    root.addEventListener(ev, function () { startWorker(); }, { once: true, passive: true });
  });

  q('ptext').value = DATA.sample;
  fill(Object.assign({}, DATA.defaults, store(true) || {}));
  // для проверки на стенде: загрузить шрифт по адресу
  window.AutokernerApp = { open: function (name, buf) { return startWorker().then(function () { return openBytes(name, buf); }); } };
})();
