/*  This file is part of Lazylibrarian.
 *  The setup wizard: typical settings for the user's country, see lazylibrarian/setupwizard.py.
 *  A native <dialog> without jQuery or Bootstrap, so the bookstrap (Bootstrap 3) and the modern
 *  (Bootstrap 5) interfaces share it.
 *  Step 1 picks the language, which is switched at once like the language menu does, and the country.
 *  The next steps only show what will change for them, already ticked, for the user to check.
 *  The texts come from wizard_presets in the current language.
 */
(function () {
  'use strict';
  var T = {};
  var dlg = null, data = null, state = {}, step = 0, autoOpened = false, busy = false;
  var langSwitched = false, showAll = {}, editing = {};

  function t(key) { return T[key] || key; }

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') { node.textContent = attrs[k]; }
      else if (k === 'class') { node.className = attrs[k]; }
      else if (k.slice(0, 2) === 'on') { node.addEventListener(k.slice(2), attrs[k]); }
      else if (attrs[k] !== false && attrs[k] !== null && attrs[k] !== undefined) { node.setAttribute(k, attrs[k]); }
    });
    (kids || []).forEach(function (kid) { if (kid) { node.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid); } });
    return node;
  }

  function show(value) {
    if (value === true) { return t('on'); }
    if (value === false) { return t('off'); }
    return value === '' || value === null || value === undefined ? '—' : String(value);
  }

  // IMP_PREFLANG is shown as the language names of its codes, like the buttons on the config page
  function codeList(csv) {
    return String(csv || '').split(',').map(function (c) { return c.trim(); }).filter(Boolean);
  }

  function buttonOf(row, code) {
    code = code.toLowerCase();
    return row.choices.filter(function (b) { return b.codes.some(function (c) { return c.toLowerCase() === code; }); })[0];
  }

  // a choice is a plain value, or {value, label}
  function option(c) { return typeof c === 'object' ? c : {value: c, label: c}; }

  function display(row, value) {
    if (row.kind === 'choice') {
      var match = row.choices.map(option).filter(function (c) { return c.value === value; })[0];
      return match ? match.label || '—' : show(value);
    }
    if (row.kind !== 'langs') { return show(value); }
    var labels = [];
    codeList(value).forEach(function (code) {
      var b = buttonOf(row, code), label = b ? b.label : code;
      if (labels.indexOf(label) < 0) { labels.push(label); }
    });
    return labels.length ? labels.join(', ') : '—';
  }

  // the languages as buttons: selected first, numbered in their order, click to switch one on or off
  function langButtons(row, onchange) {
    var s = state[row.key], more = false;
    var box = el('div', {'class': 'llw-chips', role: 'group', 'aria-label': row.label});
    function position(b) {
      var codes = codeList(s.value).map(function (c) { return c.toLowerCase(); });
      var found = b.codes.map(function (c) { return codes.indexOf(c.toLowerCase()); }).filter(function (i) { return i >= 0; });
      return found.length ? Math.min.apply(null, found) : -1;
    }
    function toggle(b, on) {
      var lower = b.codes.map(function (c) { return c.toLowerCase(); });
      var codes = codeList(s.value).filter(function (c) { return lower.indexOf(c.toLowerCase()) < 0; });
      if (!on) { codes = codes.concat(b.codes); }
      setValue(row, codes.join(', '));
      onchange(); draw();
    }
    function chip(b, on, n) {
      return el('button', {type: 'button', 'class': 'llw-chip' + (on ? ' llw-chip-on' : ''), title: b.codes.join(', '),
        'aria-pressed': on ? 'true' : 'false', onclick: function () { toggle(b, on); }},
        [n ? el('span', {'class': 'llw-chip-n', text: String(n)}) : null, b.label]);
    }
    function draw() {
      var selected = row.choices.filter(function (b) { return position(b) >= 0; })
        .sort(function (a, b) { return position(a) - position(b); });
      var rest = row.choices.filter(function (b) { return position(b) < 0; });
      var shown = rest.filter(function (b) { return more || b.shown; });
      var kids = selected.map(function (b, i) { return chip(b, true, row.numbered === false ? 0 : i + 1); })
        .concat(shown.map(function (b) { return chip(b, false); }));
      if (shown.length < rest.length) {
        kids.push(el('button', {type: 'button', 'class': 'llw-link llw-small', text: t('show_langs') + ' (' + rest.length + ')',
          onclick: function () { more = true; draw(); }}));
      }
      box.replaceChildren.apply(box, kids);
    }
    draw();
    return box;
  }

  function checkResponse(r) {
    if (!r.ok) { throw new Error(r.status + ' ' + r.statusText); }
    return r;
  }

  function getJSON(url) {
    return fetch(url, {credentials: 'same-origin'}).then(checkResponse).then(function (r) { return r.json(); });
  }

  function post(url, body) {
    return fetch(url, {method: 'POST', credentials: 'same-origin', body: new URLSearchParams(body)}).then(checkResponse);
  }

  function toast(text) {
    var node = el('div', {'class': 'llw-toast', role: 'status', text: text});
    document.body.appendChild(node);
    setTimeout(function () { node.remove(); }, 6000);
  }

  function rows() {
    var all = [];
    (data ? data.steps : []).forEach(function (s) { all = all.concat(s.rows); });
    return all;
  }

  // the proposals of a newly loaded country replace the old ones, except where the user edited or unticked a row
  function load(country) {
    var langs = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || '']).join(',');
    var url = 'wizard_presets?langs=' + encodeURIComponent(langs) + (country ? '&country=' + encodeURIComponent(country) : '');
    busy = true; render();
    return getJSON(url).then(function (res) {
      data = res; T = res.strings || {};
      rows().forEach(function (row) {
        var old = state[row.key];
        if (!old || !old.edited) { state[row.key] = {ticked: row.changed, value: row.proposed, edited: false}; }
      });
      busy = false; render();
    }).catch(function (e) { busy = false; render(String(e)); });
  }

  // like the language menu: the browser shows the new language from now on, the wizard reloads its texts
  function switchLanguage(lang) {
    var choice = (data.languages || []).filter(function (l) { return l.code === lang; })[0] || {};
    var country = data.country;
    var countryLang = (data.languages || []).filter(function (l) { return l.country === country; })[0];
    if (choice.country && (!countryLang || countryLang.code !== lang)) { country = choice.country; }
    busy = true; render();
    post('switch_interface', {lang: lang}).then(function () {
      langSwitched = true;
      return load(country);
    }).catch(function (e) { busy = false; render(String(e)); });
  }

  function setValue(row, value) {
    var s = state[row.key];
    s.value = value; s.edited = true; s.ticked = value !== row.current;
  }

  function folderBadge(row, badge) {
    var value = state[row.key].value;
    clearTimeout(badge._timer);
    badge._timer = setTimeout(function () {
      getJSON('wizard_check_folder?path=' + encodeURIComponent(value)).then(function (res) {
        badge.textContent = t('folder_' + res.status);
        badge.className = 'llw-badge llw-' + res.status;
      }).catch(function () {});
    }, 400);
  }

  // the control that changes a row's value
  function control(row, onchange) {
    var s = state[row.key], input, badge = null;
    if (row.kind === 'langs') {
      return langButtons(row, onchange);
    } else if (row.kind === 'choice') {
      var sel = el('select', {onchange: function () { setValue(row, sel.value); onchange(); }},
        row.choices.map(option).map(function (c) {
          return el('option', {value: c.value, text: c.label, selected: c.value === s.value ? 'selected' : false});
        }));
      input = sel;
    } else if (row.kind === 'months') {
      input = el('span', {'class': 'llw-muted', text: row.proposed});
    } else {
      var text = el('input', {type: 'text', value: s.value, spellcheck: 'false', oninput: function () {
        setValue(row, text.value); onchange(); if (badge) { folderBadge(row, badge); }
      }});
      input = text;
      if (row.kind === 'folder') { badge = el('span', {'class': 'llw-badge'}); folderBadge(row, badge); }
    }
    return el('div', {'class': 'llw-edit'}, [input, badge]);
  }

  function tickBox(row) {
    var box = el('input', {type: 'checkbox', 'aria-label': row.label, onchange: function () { state[row.key].ticked = box.checked; }});
    box.checked = state[row.key].ticked;
    return el('label', {'class': 'llw-tick'}, [box]);
  }

  // a yes/no setting is one checkbox: it is the value, and it is saved when it differs from now
  function boolRow(row) {
    var s = state[row.key];
    var note = el('span', {'class': 'llw-cur', text: t('current') + ': ' + show(row.current)});
    var check = el('input', {type: 'checkbox', role: 'switch', 'class': 'llw-toggle', onchange: function () {
      setValue(row, check.checked); note.hidden = s.value === row.current;
    }});
    check.checked = !!s.value;
    note.hidden = s.value === row.current;
    return el('div', {'class': 'llw-row'}, [el('div', {'class': 'llw-main'}, [
      el('label', {'class': 'llw-boolrow'}, [check, el('span', {'class': 'llw-label', text: row.label}), note]),
      row.help ? el('div', {'class': 'llw-help llw-indent', text: row.help}) : null
    ])]);
  }

  // a setting to fill in: the control, with the current value below
  function formRow(row) {
    if (row.kind === 'bool') { return boolRow(row); }
    var tick = tickBox(row);
    var sync = function () { tick.firstChild.checked = state[row.key].ticked; };
    return el('div', {'class': 'llw-row'}, [tick, el('div', {'class': 'llw-main'}, [
      el('div', {'class': 'llw-label', text: row.label}),
      row.help ? el('div', {'class': 'llw-help', text: row.help}) : null,
      control(row, sync),
      el('div', {'class': 'llw-cur', text: t('current') + ': ' + display(row, row.current)})
    ])]);
  }

  // a change worked out for the country: old -> new, to check, and to edit only if wanted
  function reviewRow(row) {
    if (editing[row.key] || row.kind === 'langs' || row.kind === 'bool') { return formRow(row); }
    var s = state[row.key];
    var diff = s.value !== row.current
      ? [el('span', {'class': 'llw-old', text: display(row, row.current)}), ' → ', el('strong', {text: display(row, s.value)})]
      : [el('span', {text: display(row, row.current)})];
    return el('div', {'class': 'llw-row'}, [tickBox(row), el('div', {'class': 'llw-main'}, [
      el('div', {'class': 'llw-label'}, [row.label + ' ',
        row.kind === 'months' ? null : el('button', {type: 'button', 'class': 'llw-link llw-small', text: t('edit'),
          onclick: function () { editing[row.key] = true; render(); }})]),
      row.help ? el('div', {'class': 'llw-help', text: row.help}) : null,
      el('div', {'class': 'llw-diff'}, diff)
    ])]);
  }

  function languageStep() {
    var langSel = el('select', {id: 'llw-lang', onchange: function () { switchLanguage(langSel.value); }},
      data.languages.map(function (l) { return el('option', {value: l.code, text: l.label, selected: l.code === data.lang ? 'selected' : false}); }));
    var sel = el('select', {id: 'llw-country', onchange: function () { load(sel.value); }},
      data.countries.map(function (c) { return el('option', {value: c.code, text: c.label, selected: c.code === data.country ? 'selected' : false}); }));
    return [
      el('p', {'class': 'llw-muted', text: t('intro')}),
      el('div', {'class': 'llw-pick'}, [el('label', {'for': 'llw-lang', text: t('language')}), langSel]),
      el('div', {'class': 'llw-pick'}, [el('label', {'for': 'llw-country', text: t('country')}), sel])
    ];
  }

  function reviewStep(s) {
    var changed = s.rows.filter(function (row) { return row.changed || state[row.key].edited; });
    var body = [el('p', {'class': 'llw-muted', text: changed.length ? t('review') : t('no_changes')})];
    changed.forEach(function (row) { body.push(reviewRow(row)); });
    var rest = s.rows.filter(function (row) { return changed.indexOf(row) < 0; });
    if (rest.length) {
      if (showAll[s.id]) {
        rest.forEach(function (row) { body.push(reviewRow(row)); });
      } else {
        body.push(el('button', {type: 'button', 'class': 'llw-link llw-more', text: t('show_all') + ' (' + rest.length + ')',
          onclick: function () { showAll[s.id] = true; render(); }}));
      }
    }
    return body;
  }

  function summary() {
    var ticked = rows().filter(function (row) { return state[row.key].ticked; });
    var where = el('div', {'class': 'llw-note llw-where'}, [el('i', {'class': 'fa fa-magic', 'aria-hidden': 'true'}), ' ' + t('where')]);
    if (!ticked.length) { return [el('p', {'class': 'llw-muted', text: t('nothing')}), where]; }
    return [el('table', {'class': 'llw-summary'}, [
      el('thead', {}, [el('tr', {}, [el('th'), el('th', {text: t('setting')}), el('th', {text: t('change')})])]),
      el('tbody', {}, ticked.map(function (row) {
        var box = el('input', {type: 'checkbox', checked: 'checked', 'aria-label': row.label,
          onchange: function () { state[row.key].ticked = box.checked; }});
        return el('tr', {}, [el('td', {}, [box]), el('td', {text: row.label}),
          el('td', {}, [el('span', {'class': 'llw-old', text: display(row, row.current)}), ' → ',
            el('strong', {text: display(row, state[row.key].value)})])]);
      }))
    ]), where];
  }

  function apply() {
    var values = {};
    rows().forEach(function (row) { if (state[row.key].ticked) { values[row.key] = state[row.key].value; } });
    busy = true; render();
    post('wizard_apply', {values: JSON.stringify(values)}).then(function (r) { return r.json(); }).then(function (res) {
      busy = false;
      if (!res.ok) { render(res.error || t('failed')); return; }
      var msg = t('saved').replace('%(count)s', res.changed.length) + ' ' + t('where');
      if (res.warnings && res.warnings.length) { msg += ' ' + res.warnings.join(' '); }
      // the page was drawn with the old settings: reload it, the message is shown again after the reload
      try { sessionStorage.setItem('llw-toast', msg); } catch (e) { toast(msg); }
      langSwitched = false; close(); location.reload();
    }).catch(function (e) { busy = false; render(String(e)); });
  }

  function render(error) {
    if (!dlg) { return; }
    var steps = data ? data.steps : [];
    var last = steps.length;  // the summary
    var body = [];
    if (busy || !data) {
      body.push(el('p', {'class': 'llw-muted', text: t('loading')}));
    } else if (step === 0) {
      body = languageStep();
    } else if (step < last) {
      var s = steps[step];
      if (s.id === 'other' || s.id === 'providers') {
        if (s.id === 'other' && data.auth_missing) {
          body.push(el('div', {'class': 'llw-note'}, [t('auth') + ' ', el('a', {href: 'config#interface', text: t('auth_link')})]));
        }
        s.rows.forEach(function (row) { body.push(formRow(row)); });
      } else {
        body = reviewStep(s);
      }
    } else {
      body = summary();
    }
    if (error) { body.unshift(el('div', {'class': 'llw-error', role: 'alert', text: error})); }

    var title = !data ? (T.title || 'Setup Wizard') : (step < last ? steps[step].title : t('summary'));
    var dots = el('ol', {'class': 'llw-steps'}, steps.concat([{title: t('summary')}]).map(function (s, i) {
      return el('li', {'class': i === step ? 'llw-on' : (i < step ? 'llw-done' : ''), title: s.title, text: String(i + 1)});
    }));
    var ready = !busy && data;
    var foot = [
      autoOpened ? el('button', {type: 'button', 'class': 'llw-link', text: t('dismiss'), onclick: function () {
        post('wizard_dismiss', {}).catch(function () {}); close(); toast(t('where'));
      }}) : null,
      el('span', {'class': 'llw-grow'}),
      el('button', {type: 'button', 'class': 'llw-btn', text: t('cancel'), onclick: close}),
      step > 0 ? el('button', {type: 'button', 'class': 'llw-btn', text: t('back'), disabled: ready ? false : 'disabled',
        onclick: function () { step -= 1; render(); }}) : null,
      step > 0 && step < last ? el('button', {type: 'button', 'class': 'llw-btn', text: t('skip'), disabled: ready ? false : 'disabled',
        onclick: function () { steps[step].rows.forEach(function (row) { state[row.key].ticked = false; }); step += 1; render(); }}) : null,
      step < last
        ? el('button', {type: 'button', 'class': 'llw-btn llw-primary', text: t('next'), disabled: ready ? false : 'disabled',
          onclick: function () { step += 1; render(); }})
        : el('button', {type: 'button', 'class': 'llw-btn llw-primary', text: t('apply'), disabled: ready ? false : 'disabled', onclick: apply})
    ];
    dlg.replaceChildren(
      el('header', {}, [el('h2', {text: title}), dots]),
      el('div', {'class': 'llw-body'}, body),
      el('footer', {}, foot)
    );
  }

  // the page behind still shows the old language, reload it when the wizard switched it
  function close() {
    if (dlg && dlg.open) { dlg.close(); }
  }

  function open(auto) {
    autoOpened = !!auto;
    if (!dlg) {
      dlg = el('dialog', {'class': 'llw', 'aria-label': 'Setup Wizard'});
      dlg.addEventListener('close', function () { if (langSwitched) { location.reload(); } });
      document.body.appendChild(dlg);
    }
    step = 0; state = {}; data = null; showAll = {}; editing = {}; langSwitched = false;
    render();
    if (dlg.showModal) { dlg.showModal(); } else { dlg.setAttribute('open', 'open'); }
    load('');
  }

  window.LLSetupWizard = {open: function () { open(false); }};

  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('#setupwizard')) { e.preventDefault(); open(false); }
  });

  // a new install: offer the wizard once per browser session, "don't show again" stops it for good
  function autoOpen() {
    try {
      var saved = sessionStorage.getItem('llw-toast');
      if (saved) { sessionStorage.removeItem('llw-toast'); toast(saved); }
    } catch (e) { /* private mode */ }
    var root = document.getElementById('llw-root');
    if (!root || root.getAttribute('data-autoopen') !== '1') { return; }
    try { if (sessionStorage.getItem('llw-offered')) { return; } sessionStorage.setItem('llw-offered', '1'); } catch (e) { /* private mode */ }
    open(true);
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', autoOpen); } else { autoOpen(); }
})();
