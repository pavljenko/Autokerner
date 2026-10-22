/* Автокернер, веб-версия: расчёт в отдельном потоке — Pyodide и пакет
   autokerner. Страница шлёт команды, поток отвечает тем же id. */
let api = null;
let py = null;

function reply(id, extra, transfer) {
  self.postMessage(Object.assign({ id: id }, extra), transfer || []);
}

self.onmessage = async function (e) {
  const m = e.data;
  try {
    if (m.type === 'init') {
      importScripts(m.pyodide + 'pyodide.js');
      py = await loadPyodide({ indexURL: m.pyodide });
      await py.loadPackage(['fonttools', 'brotli']);
      py.FS.mkdirTree('/ak/autokerner');
      for (const name of Object.keys(m.sources)) {
        py.FS.writeFile('/ak/autokerner/' + name, m.sources[name]);
      }
      py.runPython("import sys; sys.path.insert(0, '/ak')");
      api = py.pyimport('autokerner.web');
      reply(m.id, { ok: true });
    } else if (m.type === 'open') {
      const data = py.toPy(m.bytes);
      const info = api.open_font(data, m.name);
      data.destroy();
      reply(m.id, { json: info });
    } else if (m.type === 'calc') {
      const progress = function (text) { self.postMessage({ progress: String(text) }); };
      const summary = api.calculate(m.options, progress);
      const bytes = api.new_font();
      const font = bytes.toJs();
      bytes.destroy();
      reply(m.id, { json: summary, font: font }, [font.buffer]);
    } else if (m.type === 'edits') {
      reply(m.id, { json: api.edits(m.query || '') });
    } else if (m.type === 'files') {
      reply(m.id, { json: api.report_files() });
    }
  } catch (err) {
    reply(m.id, { error: String((err && err.message) || err) });
  }
};
