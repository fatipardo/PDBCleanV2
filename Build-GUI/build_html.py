#!/usr/bin/env python3
"""
build_html.py — Generate a self-contained HTML structure browser.

Given a CSV file with structure metadata and a directory of .cif files,
produces a single HTML file with a filterable table, 3D viewer, and
per-chain style/color controls.

Usage:
  python3 build_html.py <CSV> <STRUCTURES_DIR> [options]

  CSV             CSV file with structure metadata
  STRUCTURES_DIR  Directory containing .cif structure files

Options:
  -o, --output PATH   Output HTML file (default: index.html next to CSV)
  --id-col COLUMN     CSV column whose values match file name prefixes
                      (auto-detected if omitted)
  --title TEXT        Page title (default: "Structure Browser")

File naming convention:
  Each .cif file must start with the value in the ID column, e.g.:
    CSV row  PDBid = "4cmp"  →  files "4cmp+01.cif", "4cmp+02.cif", ...
  The part before the first '+' (or the full stem if no '+') is the prefix.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def make_key(col_name):
    """Turn a CSV column header into a clean JS identifier."""
    key = re.sub(r'[^a-z0-9]+', '_', col_name.lower()).strip('_')
    return key or 'col'

def is_numeric(s):
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# ── data loading ──────────────────────────────────────────────────────────────

def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        sys.exit(f'Error: {path} has no data rows.')
    fieldnames = list(rows[0].keys())
    return rows, fieldnames

def drop_index_col(fieldnames, rows):
    """Remove an unnamed or auto-index first column (common in pandas exports)."""
    if not fieldnames:
        return fieldnames, rows
    first = fieldnames[0]
    # Unnamed
    if not first.strip():
        return [f for f in fieldnames if f.strip()], [{k: v for k, v in r.items() if k.strip()} for r in rows]
    # Sequential integers 0, 1, 2, …
    try:
        vals = [int(r.get(first, '')) for r in rows[:min(10, len(rows))]]
        if vals == list(range(len(vals))):
            return fieldnames[1:], [{k: v for k, v in r.items() if k != first} for r in rows]
    except (ValueError, TypeError):
        pass
    return fieldnames, rows

def scan_structures(directory):
    """Return {prefix: [fname, ...]} for all .cif files in directory."""
    if not os.path.isdir(directory):
        sys.exit(f'Error: {directory} is not a directory.')
    file_map = {}
    for fname in sorted(os.listdir(directory)):
        if fname.endswith('.cif'):
            prefix = fname.split('+')[0]
            file_map.setdefault(prefix, []).append(fname)
    if not file_map:
        sys.exit(f'Error: no .cif files found in {directory}')
    return file_map

def detect_id_col(rows, file_prefixes, fieldnames):
    """Return the column name with the most overlap with file prefix values."""
    prefix_set = {p.lower() for p in file_prefixes}
    best_col, best_score = None, -1
    for col in fieldnames:
        if not col.strip():
            continue
        vals = {str(r.get(col, '')).strip().lower() for r in rows}
        score = len(vals & prefix_set)
        if score > best_score:
            best_score, best_col = score, col
    return best_col


# ── entry building ────────────────────────────────────────────────────────────

def build_entries(rows, file_map, id_col, data_cols):
    """
    Returns (entries, col_keys):
      entries   = one dict per .cif file with clean-key metadata
      col_keys  = {original col name: JS-safe key}
    """
    seen = {'file', 'pdbid'}
    col_keys = {}
    for col in data_cols:
        key = make_key(col)
        orig, n = key, 1
        while key in seen:
            key = f'{orig}_{n}'
            n += 1
        seen.add(key)
        col_keys[col] = key

    id_to_meta = {}
    for row in rows:
        pid = str(row.get(id_col, '') or '').strip()
        if pid:
            id_to_meta[pid] = {col_keys[c]: str(row.get(c, '') or '') for c in data_cols}

    all_files = sorted(f for files in file_map.values() for f in files)
    entries = []
    for fname in all_files:
        prefix = fname.split('+')[0]
        entry = {'file': fname, 'pdbid': prefix}
        entry.update(id_to_meta.get(prefix, {}))
        entries.append(entry)

    return entries, col_keys


# ── column analysis ────────────────────────────────────────────────────────────

def analyze_columns(entries, data_cols, col_keys):
    """
    Returns:
      col_configs    list of {key, label, type} for the COLUMNS JS array
      filter_configs list of filter descriptors for FILTERS JS array + HTML widgets
    """
    col_configs = [
        {'key': 'file',  'label': 'File',   'type': 'text'},
        {'key': 'pdbid', 'label': 'PDB ID', 'type': 'text'},
    ]
    filter_configs = []

    for col in data_cols:
        key   = col_keys[col]
        label = col
        vals  = [str(e.get(key, '')) for e in entries]
        non_empty = [v for v in vals if v]

        if not non_empty:
            col_configs.append({'key': key, 'label': label, 'type': 'text'})
            continue

        if all(is_numeric(v) for v in non_empty):
            nums   = [float(v) for v in non_empty]
            is_int = all(float(v) == int(float(v)) for v in non_empty)
            ctype  = 'numeric_int' if is_int else 'numeric'
            col_configs.append({'key': key, 'label': label, 'type': ctype})
            if is_int:
                filter_configs.append({'key': key, 'label': label, 'type': 'range_min',
                                       'min': int(min(nums)), 'max': int(max(nums))})
            else:
                filter_configs.append({'key': key, 'label': label, 'type': 'range_max',
                                       'min': round(min(nums), 4), 'max': round(max(nums), 4)})
        elif len(set(non_empty)) <= 40:
            col_configs.append({'key': key, 'label': label, 'type': 'categorical'})
            filter_configs.append({'key': key, 'label': label, 'type': 'dropdown',
                                   'values': sorted(set(non_empty))})
        else:
            col_configs.append({'key': key, 'label': label, 'type': 'text'})

    return col_configs, filter_configs


# ── HTML fragment builders ─────────────────────────────────────────────────────

def build_filter_html(filter_configs):
    """Generate HTML for filter widgets (dropdowns and range sliders)."""
    parts = []
    for f in filter_configs:
        key, label, ftype = f['key'], f['label'], f['type']

        if ftype == 'dropdown':
            opts = ''.join(
                '<option value="{v}">{d}</option>'.format(
                    v=v, d=(v.title() if v == v.upper() else v))
                for v in f['values']
            )
            parts.append(
                '<div class="filter-row">'
                f'<label>{label}</label>'
                f'<select id="f_{key}" onchange="applyFilters()">'
                f'<option value="">All</option>{opts}'
                '</select></div>'
            )

        elif ftype == 'range_min':
            mn, mx = f['min'], f['max']
            parts.append(
                '<div class="filter-row">'
                f'<label>From {label}</label>'
                f'<input type="range" id="f_{key}" min="{mn}" max="{mx}" value="{mn}"'
                f' oninput="document.getElementById(\'fv_{key}\').textContent=this.value;applyFilters()">'
                f'<span id="fv_{key}" class="range-val">{mn}</span>'
                '</div>'
            )

        elif ftype == 'range_max':
            mn, mx = f['min'], f['max']
            step = '0.01' if mx < 1000 else '1'
            disp = f'{mx:.2f}' if mx < 1000 else str(int(mx))
            parts.append(
                '<div class="filter-row">'
                f'<label>{label} &le;</label>'
                f'<input type="range" id="f_{key}" min="{mn}" max="{mx}" value="{mx}" step="{step}"'
                f' oninput="document.getElementById(\'fv_{key}\').textContent='
                f'parseFloat(this.value).toFixed(2);applyFilters()">'
                f'<span id="fv_{key}" class="range-val">{disp}</span>'
                '</div>'
            )

    return '\n      '.join(parts)

def build_table_headers(col_configs):
    """Generate <th> elements for the table header row."""
    parts = ['<th class="check-col"></th>']
    for col in col_configs:
        parts.append(f'<th data-col="{col["key"]}">{col["label"]}</th>')
    return '\n          '.join(parts)


# ── HTML template ──────────────────────────────────────────────────────────────
# Placeholders: %%%TITLE%%%, %%%ENTRIES%%%, %%%COLUMNS%%%, %%%FILTERS%%%,
#               %%%FILTER_HTML%%%, %%%TABLE_HEADERS%%%

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%%%TITLE%%%</title>
<script src="https://3dmol.org/build/3Dmol-min.js"></script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; font-size: 13px; background: #0f1117; color: #e2e8f0; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

header { padding: 10px 16px; background: #1a1d2e; border-bottom: 1px solid #2d3148; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
header h1 { font-size: 16px; font-weight: 600; color: #a78bfa; letter-spacing: .5px; }
#status { margin-left: auto; font-size: 12px; color: #64748b; }

.main { display: flex; flex: 1; overflow: hidden; }

/* ── LEFT PANEL ─────────────────────────────────────────────────────── */
.panel-left { width: 450px; min-width: 200px; max-width: 70vw; display: flex; flex-direction: column; flex-shrink: 0; }
.resize-handle { width: 5px; background: #2d3148; cursor: col-resize; flex-shrink: 0; transition: background .15s; }
.resize-handle:hover, .resize-handle.dragging { background: #7c3aed; }

.filters { padding: 10px 12px; background: #12151f; border-bottom: 1px solid #2d3148; display: flex; flex-direction: column; gap: 7px; }
.filter-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.filter-row label { font-size: 11px; color: #94a3b8; white-space: nowrap; }
select, input[type=range], input[type=text] { background: #1e2235; border: 1px solid #3a3f5c; color: #e2e8f0; border-radius: 4px; padding: 3px 6px; font-size: 12px; }
select { cursor: pointer; }
select:focus, input:focus { outline: none; border-color: #7c3aed; }
#search { width: 100%; padding: 5px 8px; }
input[type=range] { flex: 1; accent-color: #7c3aed; cursor: pointer; }
.range-val { font-size: 11px; color: #a78bfa; min-width: 38px; }

.table-actions { padding: 6px 12px; background: #12151f; border-bottom: 1px solid #2d3148; display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
#rowCount { font-size: 11px; color: #64748b; }
.btn { padding: 4px 12px; border-radius: 5px; border: none; cursor: pointer; font-size: 12px; font-weight: 500; transition: background .15s; }
.btn-primary { background: #7c3aed; color: #fff; }
.btn-primary:hover { background: #6d28d9; }
.btn-secondary { background: #1e2235; color: #94a3b8; border: 1px solid #3a3f5c; }
.btn-secondary:hover { background: #2d3148; color: #e2e8f0; }
.btn:disabled { opacity: .4; cursor: not-allowed; }
#selCount { font-size: 11px; color: #a78bfa; margin-left: auto; }

.table-wrap { flex: 1; overflow-y: auto; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
thead th { position: sticky; top: 0; background: #1a1d2e; padding: 6px 8px; text-align: left; font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid #2d3148; cursor: pointer; user-select: none; white-space: nowrap; }
thead th:hover { color: #a78bfa; }
thead th.sort-asc::after  { content: " \\u25b2"; color: #a78bfa; }
thead th.sort-desc::after { content: " \\u25bc"; color: #a78bfa; }
tbody tr { border-bottom: 1px solid #1e2235; cursor: pointer; transition: background .1s; }
tbody tr:hover { background: #1e2235; }
tbody tr.selected { background: #2d1f4e; }
td { padding: 5px 8px; white-space: nowrap; }
td.check-col { width: 28px; }
td input[type=checkbox] { accent-color: #7c3aed; cursor: pointer; width: 13px; height: 13px; }
.org { max-width: 150px; overflow: hidden; text-overflow: ellipsis; }
.tag { display: inline-block; padding: 1px 5px; border-radius: 3px; font-size: 10px; font-weight: 500; }
.tag-xray { background: #1e3a5f; color: #60a5fa; }
.tag-em   { background: #1a3a2a; color: #34d399; }
.tag-nmr  { background: #3a2a1a; color: #fb923c; }

/* ── CENTER (VIEWER + SEQUENCE) ───────────────────────────────────────── */
.panel-center { flex: 1; min-width: 0; display: flex; flex-direction: column; }
#viewport { flex: 1; background: #060809; position: relative; min-height: 0; }

/* ── SEQUENCE PANEL ─────────────────────────────────────────────────── */
.seq-panel { border-top: 1px solid #2d3148; background: #0c0e16; display: flex; flex-direction: column; flex-shrink: 0; }
.seq-panel.collapsed { height: 28px; overflow: hidden; }
.seq-panel:not(.collapsed) { height: 190px; }
.seq-panel-hdr { padding: 4px 12px; background: #1a1d2e; border-bottom: 1px solid #2d3148; display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; flex-shrink: 0; }
.seq-panel-hdr:hover { background: #22264a; }
.seq-panel-title { font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: .5px; flex: 1; }
.seq-content { flex: 1; overflow-y: auto; padding: 6px 12px; display: flex; flex-direction: column; gap: 8px; }
.seq-struct-title { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; font-size: 11px; color: #64748b; }
.seq-chain-row { display: flex; align-items: flex-start; gap: 6px; margin-bottom: 3px; }
.seq-chain-lbl { font-size: 10px; font-weight: 700; width: 18px; flex-shrink: 0; margin-top: 3px; text-align: center; }
.seq-track { font-family: 'Courier New', monospace; font-size: 12px; display: flex; flex-wrap: wrap; line-height: 1.6; flex: 1; }
.seq-res { display: inline-block; width: 12px; text-align: center; cursor: pointer; border-radius: 2px; }
.seq-res:hover { background: #2d3148 !important; opacity: 1 !important; }
.seq-res.hi { background: #f59e0b !important; color: #0f1117 !important; opacity: 1 !important; }
.seq-clear-btn { background: none; border: 1px solid #3a3f5c; color: #64748b; border-radius: 3px; cursor: pointer; font-size: 10px; padding: 0 5px; line-height: 1.9; flex-shrink: 0; white-space: nowrap; margin-top: 1px; }
.seq-clear-btn:hover { color: #f87171; border-color: #f87171; }

/* ── RIGHT CONTROLS ───────────────────────────────────────────────────── */
.panel-controls { width: 268px; flex-shrink: 0; background: #0c0e16; border-left: 1px solid #2d3148; display: flex; flex-direction: column; overflow: hidden; }

.ctrl-top { padding: 8px 12px; background: #1a1d2e; border-bottom: 1px solid #2d3148; display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.ctrl-title { font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: .5px; flex: 1; }

.struct-list { flex: 1; overflow-y: auto; }
.empty-hint { padding: 28px 16px; font-size: 12px; color: #2a2f45; text-align: center; line-height: 1.6; }

.struct-item { border-bottom: 1px solid #1a1d2e; }
.struct-header { display: flex; align-items: center; gap: 6px; padding: 7px 10px; background: #12151f; }
.cdot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.struct-name { flex: 1; font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.struct-btns { display: flex; gap: 3px; flex-shrink: 0; }
.icon-btn { background: none; border: 1px solid #3a3f5c; color: #64748b; border-radius: 3px; cursor: pointer; font-size: 11px; padding: 1px 6px; line-height: 1.4; transition: all .1s; }
.icon-btn:hover { color: #e2e8f0; border-color: #64748b; }
.rm-btn:hover { color: #f87171 !important; border-color: #f87171 !important; }

.quick-row { display: flex; gap: 3px; padding: 3px 10px 4px; flex-wrap: wrap; }
.qs { background: #1a1d2e; border: 1px solid #3a3f5c; color: #64748b; border-radius: 3px; cursor: pointer; font-size: 10px; padding: 1px 5px; transition: all .1s; }
.qs:hover { background: #2d3148; color: #e2e8f0; }

.chain-list { padding: 3px 10px 9px; display: flex; flex-direction: column; gap: 3px; }
.chain-row { display: flex; align-items: center; gap: 5px; }
.chain-lbl { font-size: 11px; color: #94a3b8; width: 52px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; }
.style-sel { flex: 1; min-width: 0; background: #1e2235; border: 1px solid #3a3f5c; color: #e2e8f0; border-radius: 3px; padding: 2px 4px; font-size: 11px; cursor: pointer; }
.style-sel:focus { outline: none; border-color: #7c3aed; }
.chain-clr { width: 24px; height: 22px; padding: 1px 2px; border: 1px solid #3a3f5c; border-radius: 3px; cursor: pointer; background: #1e2235; flex-shrink: 0; }

::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #0c0e16; }
::-webkit-scrollbar-thumb { background: #2d3148; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #6d28d9; }
</style>
</head>
<body>

<header>
  <h1>%%%TITLE%%%</h1>
  <span id="status">Ready</span>
</header>

<div class="main">

  <div class="panel-left">
    <div class="filters">
      <input type="text" id="search" placeholder="Search file, ID, or text fields…">
      %%%FILTER_HTML%%%
    </div>
    <div class="table-actions">
      <span id="rowCount"></span>
      <button class="btn btn-secondary" id="selectAllBtn">Select all</button>
      <button class="btn btn-secondary" id="clearBtn">Clear</button>
      <span id="selCount"></span>
      <button class="btn btn-primary" id="loadBtn" disabled>Visualize</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          %%%TABLE_HEADERS%%%
        </tr></thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>
  </div>

  <div id="resizeHandle" class="resize-handle"></div>

  <div class="panel-center">
    <div id="viewport"></div>
    <div id="seqPanel" class="seq-panel collapsed" style="display:none">
      <div class="seq-panel-hdr" onclick="toggleSeqPanel()">
        <span class="seq-panel-title">Sequences</span>
        <span id="seqCollapseIcon" style="font-size:10px;color:#64748b">\\u25b2</span>
      </div>
      <div id="seqContent" class="seq-content"></div>
    </div>
  </div>

  <div class="panel-controls">
    <div class="ctrl-top">
      <span class="ctrl-title">Structures <span id="ctrlCount"></span></span>
      <button class="btn btn-secondary" id="clearAllBtn"
              style="display:none;font-size:11px;padding:2px 8px">Clear all</button>
    </div>
    <div id="structureList" class="struct-list">
      <div class="empty-hint">Select structures from the table and click
        <strong>Visualize</strong> to load them here.</div>
    </div>
  </div>

</div>

<script>
// ── injected data ─────────────────────────────────────────────────────────
const ENTRIES = %%%ENTRIES%%%;
const COLUMNS = %%%COLUMNS%%%;
const FILTERS = %%%FILTERS%%%;

// ── constants ─────────────────────────────────────────────────────────────
const COLORS = [
  '#818cf8','#34d399','#f59e0b','#f87171','#38bdf8',
  '#a78bfa','#fb923c','#4ade80','#e879f9','#facc15',
  '#60a5fa','#f472b6','#2dd4bf','#fb7185','#a3e635'
];
const STYLE_NAMES = ['cartoon','stick','sphere','line','hidden'];

// ── state ─────────────────────────────────────────────────────────────────
let viewer       = null;
let sortCol      = COLUMNS[0].key;
let sortDir      = 1;
let filtered     = [...ENTRIES];
let colorIndex   = 0;
// fname -> { model, color, chains: { id -> { style, color } }, sequences: { chain -> [{seqId,resName}] } }
let loadedModels = {};
let highlightedResidues = {}; // fname -> { chain -> Set<seqId> }
let seqCollapsed = false;

// ── init ──────────────────────────────────────────────────────────────────
function init() {
  viewer = $3Dmol.createViewer(document.getElementById('viewport'), { backgroundColor: '#060809' });
  window.addEventListener('resize', () => viewer.resize());

  renderTable();
  document.getElementById('search').addEventListener('input', applyFilters);
  document.getElementById('loadBtn').addEventListener('click', loadSelected);
  document.getElementById('clearBtn').addEventListener('click', clearSelection);
  document.getElementById('selectAllBtn').addEventListener('click', selectAll);
  document.getElementById('clearAllBtn').addEventListener('click', clearAll);
  document.querySelectorAll('thead th[data-col]').forEach(th => {
    th.addEventListener('click', () => {
      sortDir = sortCol === th.dataset.col ? sortDir * -1 : 1;
      sortCol = th.dataset.col;
      updateSortHeaders();
      renderTable();
    });
  });
}

// ── filters ───────────────────────────────────────────────────────────────
function applyFilters() {
  const q = document.getElementById('search').value.toLowerCase();
  filtered = ENTRIES.filter(e => {
    if (q) {
      const textCols = ['file', 'pdbid',
        ...COLUMNS.filter(c => c.type === 'categorical' || c.type === 'text').map(c => c.key)];
      if (!textCols.some(k => String(e[k] || '').toLowerCase().includes(q))) return false;
    }
    for (const f of FILTERS) {
      const el = document.getElementById('f_' + f.key);
      if (!el) continue;
      if (f.type === 'dropdown') {
        if (el.value && e[f.key] !== el.value) return false;
      } else if (f.type === 'range_min') {
        if (parseFloat(e[f.key] || 0) < parseFloat(el.value)) return false;
      } else if (f.type === 'range_max') {
        const v = parseFloat(e[f.key]);
        if (!isNaN(v) && v > parseFloat(el.value)) return false;
      }
    }
    return true;
  });
  renderTable();
}

// ── table ─────────────────────────────────────────────────────────────────
function updateSortHeaders() {
  document.querySelectorAll('thead th[data-col]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.col === sortCol) th.classList.add(sortDir === 1 ? 'sort-asc' : 'sort-desc');
  });
}

function renderCell(e, col) {
  const v = String(e[col.key] !== undefined ? e[col.key] : '');
  if (col.key === 'file')  return `<td><strong>${v.replace(/\\.cif$/, '')}</strong></td>`;
  if (col.key === 'pdbid') return `<td>${v}</td>`;
  if (!v) return '<td>\\u2014</td>';
  if (col.type === 'numeric') {
    const n = parseFloat(v);
    return `<td>${isNaN(n) ? '\\u2014' : n.toFixed(2)}</td>`;
  }
  if (col.type === 'numeric_int') return `<td>${v}</td>`;
  if (col.type === 'categorical') {
    const vu = v.toUpperCase();
    if (vu.includes('X-RAY'))    return '<td><span class="tag tag-xray">X-ray</span></td>';
    if (vu.includes('ELECTRON')) return '<td><span class="tag tag-em">EM</span></td>';
    if (vu.includes('NMR'))      return '<td><span class="tag tag-nmr">NMR</span></td>';
    const display = v.split(';')[0].trim().replace(/\\b\\w/g, c => c.toUpperCase());
    return `<td class="org" title="${v.replace(/"/g, '&quot;')}">${display}</td>`;
  }
  return `<td>${v}</td>`;
}

function renderTable() {
  const sorted = [...filtered].sort((a, b) => {
    let av = a[sortCol], bv = b[sortCol];
    const col = COLUMNS.find(c => c.key === sortCol);
    if (col && (col.type === 'numeric' || col.type === 'numeric_int')) {
      av = parseFloat(av) || 0; bv = parseFloat(bv) || 0;
    }
    if (av < bv) return -sortDir; if (av > bv) return sortDir; return 0;
  });

  const selFiles = getSelectedFiles();
  document.getElementById('tableBody').innerHTML = sorted.map(e => {
    const isSel = selFiles.has(e.file);
    const ef    = e.file.replace(/'/g, "\\'");
    const cells = COLUMNS.map(col => renderCell(e, col)).join('');
    return `<tr class="${isSel ? 'selected' : ''}" data-file="${e.file}" onclick="toggleRow('${ef}')">
      <td class="check-col"><input type="checkbox" ${isSel ? 'checked' : ''}
        onclick="event.stopPropagation();toggleRow('${ef}')"></td>
      ${cells}
    </tr>`;
  }).join('');
  document.getElementById('rowCount').textContent =
    `${sorted.length} file${sorted.length !== 1 ? 's' : ''}`;
  updateSelCount();
}

function getSelectedFiles() {
  const s = new Set();
  document.querySelectorAll('#tableBody input[type=checkbox]:checked')
    .forEach(cb => s.add(cb.closest('tr').dataset.file));
  return s;
}

function toggleRow(file) {
  const tr = document.querySelector(`tr[data-file="${CSS.escape(file)}"]`);
  if (!tr) return;
  const cb = tr.querySelector('input[type=checkbox]');
  cb.checked = !cb.checked;
  tr.classList.toggle('selected', cb.checked);
  updateSelCount();
}

function clearSelection() {
  document.querySelectorAll('#tableBody input[type=checkbox]:checked').forEach(cb => {
    cb.checked = false; cb.closest('tr').classList.remove('selected');
  });
  updateSelCount();
}

function selectAll() {
  document.querySelectorAll('#tableBody input[type=checkbox]').forEach(cb => {
    cb.checked = true; cb.closest('tr').classList.add('selected');
  });
  updateSelCount();
}

function updateSelCount() {
  const n = document.querySelectorAll('#tableBody input[type=checkbox]:checked').length;
  document.getElementById('selCount').textContent = n > 0 ? `${n} selected` : '';
  document.getElementById('loadBtn').disabled = n === 0;
}

// ── CIF parser: chains + per-chain sequence ───────────────────────────────
const AA1 = {
  ALA:'A',ARG:'R',ASN:'N',ASP:'D',CYS:'C',GLN:'Q',GLU:'E',GLY:'G',
  HIS:'H',ILE:'I',LEU:'L',LYS:'K',MET:'M',PHE:'F',PRO:'P',SER:'S',
  THR:'T',TRP:'W',TYR:'Y',VAL:'V',
  MSE:'M',SEC:'U',HSD:'H',HSE:'H',HSP:'H',HYP:'P',
  DA:'A',DT:'T',DG:'G',DC:'C',DU:'U',A:'A',T:'T',G:'G',C:'C',U:'U',
};
function toOneLetter(r) { return AA1[r] || (r.length === 1 ? r : '?'); }

function parseCIF(text) {
  const loopMatch = text.match(/loop_\\s+((?:_atom_site\\.\\S+\\s*)+)/);
  if (!loopMatch) return { chains: [], sequences: {} };
  const cols = [...loopMatch[1].matchAll(/_atom_site\\.(\\S+)/g)].map(m => m[1]);
  let chainIdx = cols.indexOf('auth_asym_id'); if (chainIdx < 0) chainIdx = cols.indexOf('label_asym_id');
  let seqIdx   = cols.indexOf('auth_seq_id');  if (seqIdx   < 0) seqIdx   = cols.indexOf('label_seq_id');
  let resIdx   = cols.indexOf('auth_comp_id'); if (resIdx   < 0) resIdx   = cols.indexOf('label_comp_id');
  if (chainIdx < 0) return { chains: [], sequences: {} };
  const maxIdx = Math.max(chainIdx, seqIdx >= 0 ? seqIdx : 0, resIdx >= 0 ? resIdx : 0);
  const dataStart = text.indexOf('\\n', loopMatch.index + loopMatch[0].length);
  const chainSet = new Set(), sequences = {}, seen = {};
  for (const row of text.slice(dataStart).split('\\n')) {
    const r = row.trim();
    if (!r || r.startsWith('#') || r.startsWith('_') || r.startsWith('loop_') || r.startsWith('data_')) {
      if (chainSet.size) break; continue;
    }
    const p = r.split(/\\s+/);
    if (p.length <= maxIdx) continue;
    const chain = p[chainIdx];
    chainSet.add(chain);
    if (seqIdx >= 0 && resIdx >= 0) {
      const key = chain + '|' + p[seqIdx];
      if (!seen[key]) {
        seen[key] = true;
        if (!sequences[chain]) sequences[chain] = [];
        sequences[chain].push({ seqId: p[seqIdx], resName: p[resIdx] });
      }
    }
  }
  return { chains: [...chainSet].sort(), sequences };
}

// ── loading ───────────────────────────────────────────────────────────────
async function loadSelected() {
  const files = [...getSelectedFiles()].filter(f => !loadedModels[f]);
  if (!files.length) return;

  const btn = document.getElementById('loadBtn');
  btn.disabled = true; btn.textContent = 'Loading\\u2026';
  document.getElementById('status').textContent = `Loading ${files.length} file(s)\\u2026`;

  let loaded = 0, failed = 0;
  for (const fname of files) {
    const color = COLORS[colorIndex % COLORS.length];
    colorIndex++;
    try {
      const resp = await fetch('structures/' + encodeURIComponent(fname));
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const text = await resp.text();
      const { chains, sequences } = parseCIF(text);
      const chainState = {};
      for (const c of (chains.length ? chains : [''])) {
        chainState[c] = { style: 'cartoon', color };
      }
      const model = viewer.addModel(text, 'mmcif');
      // translate centroid to origin so structures open near 0,0,0
      const atoms = model.selectedAtoms({});
      if (atoms.length) {
        const n  = atoms.length;
        const cx = atoms.reduce((s, a) => s + a.x, 0) / n;
        const cy = atoms.reduce((s, a) => s + a.y, 0) / n;
        const cz = atoms.reduce((s, a) => s + a.z, 0) / n;
        atoms.forEach(a => { a.x -= cx; a.y -= cy; a.z -= cz; });
      }
      loadedModels[fname] = { model, color, chains: chainState, sequences };
      applyStyles(fname);
      loaded++;
    } catch (err) {
      console.error('Failed:', fname, err);
      failed++;
    }
  }

  viewer.zoomTo(); viewer.render();
  renderControls();
  renderSequence();

  btn.disabled = (getSelectedFiles().size === 0);
  btn.textContent = 'Visualize';
  const total = Object.keys(loadedModels).length;
  document.getElementById('status').textContent = failed
    ? `${loaded} loaded, ${failed} failed \\u2014 ${total} total`
    : `${total} structure(s) loaded`;
}

// ── 3Dmol style application ───────────────────────────────────────────────
function applyStyles(fname) {
  const entry = loadedModels[fname];
  if (!entry) return;
  viewer.setStyle({ model: entry.model }, {});
  for (const [chain, state] of Object.entries(entry.chains)) {
    if (state.style === 'hidden') continue;
    const sel   = chain ? { model: entry.model, chain } : { model: entry.model };
    const style = {};
    style[state.style] = { color: state.color };
    viewer.setStyle(sel, style);
  }
  // overlay highlight spheres for toggled residues
  const hi = highlightedResidues[fname];
  if (hi) {
    for (const [chain, seqIds] of Object.entries(hi)) {
      if (!seqIds.size) continue;
      const resi = [...seqIds].map(s => parseInt(s)).filter(n => !isNaN(n));
      if (!resi.length) continue;
      const sel = chain ? { model: entry.model, chain, resi } : { model: entry.model, resi };
      viewer.addStyle(sel, { sphere: { color: '#f59e0b', opacity: 0.7, radius: 1.5 } });
    }
  }
  viewer.render();
}

// ── controls panel ────────────────────────────────────────────────────────
function renderControls() {
  const entries = Object.entries(loadedModels);
  const n = entries.length;
  document.getElementById('ctrlCount').textContent = n ? `(${n})` : '';
  document.getElementById('clearAllBtn').style.display = n ? '' : 'none';

  const list = document.getElementById('structureList');
  if (!n) {
    list.innerHTML = '<div class="empty-hint">Select structures from the table and click'
      + ' <strong>Visualize</strong> to load them here.</div>';
    return;
  }

  list.innerHTML = entries.map(([fname, entry]) => {
    const stem  = fname.replace(/\\.cif$/, '');
    const safeF = fname.replace(/[^a-z0-9]/gi, '_');
    const ef    = fname.replace(/\\\\/g, '\\\\\\\\').replace(/'/g, "\\'");

    const quickBtns = STYLE_NAMES.map(s =>
      `<button class="qs" onclick="applyAllChains('${ef}','${s}')">`
      + `${s.charAt(0).toUpperCase() + s.slice(1)}</button>`
    ).join('');

    const chainRows = Object.entries(entry.chains).map(([chain, state]) => {
      const ec   = chain.replace(/'/g, "\\'");
      const opts = STYLE_NAMES.map(s =>
        `<option value="${s}"${state.style === s ? ' selected' : ''}>`
        + `${s.charAt(0).toUpperCase() + s.slice(1)}</option>`
      ).join('');
      return `<div class="chain-row">
        <span class="chain-lbl" title="Chain ${chain || '(all)'}">${chain || 'all'}</span>
        <select class="style-sel" onchange="updateChainStyle('${ef}','${ec}',this.value)">${opts}</select>
        <input type="color" class="chain-clr" value="${state.color}"
               onchange="updateChainColor('${ef}','${ec}',this.value)">
      </div>`;
    }).join('');

    return `<div class="struct-item" id="si_${safeF}">
      <div class="struct-header">
        <span class="cdot" style="background:${entry.color}"></span>
        <span class="struct-name" title="${fname}">${stem}</span>
        <div class="struct-btns">
          <button class="icon-btn" onclick="zoomToStruct('${ef}')" title="Zoom to">&#8857;</button>
          <button class="icon-btn rm-btn" onclick="removeStructure('${ef}')" title="Remove">&times;</button>
        </div>
      </div>
      <div class="quick-row">${quickBtns}</div>
      <div class="chain-list">${chainRows}</div>
    </div>`;
  }).join('');
}

// ── per-chain controls ────────────────────────────────────────────────────
function updateChainStyle(fname, chain, style) {
  if (!loadedModels[fname]) return;
  loadedModels[fname].chains[chain].style = style;
  applyStyles(fname);
}

function updateChainColor(fname, chain, color) {
  if (!loadedModels[fname]) return;
  loadedModels[fname].chains[chain].color = color;
  const keys = Object.keys(loadedModels[fname].chains);
  if (keys[0] === chain) {
    loadedModels[fname].color = color;
    const dot = document.querySelector(`#si_${fname.replace(/[^a-z0-9]/gi, '_')} .cdot`);
    if (dot) dot.style.background = color;
  }
  applyStyles(fname);
}

function applyAllChains(fname, style) {
  const entry = loadedModels[fname];
  if (!entry) return;
  for (const chain of Object.keys(entry.chains)) entry.chains[chain].style = style;
  applyStyles(fname);
  renderControls();
}

function zoomToStruct(fname) {
  const entry = loadedModels[fname];
  if (!entry) return;
  viewer.zoomTo({ model: entry.model });
  viewer.render();
}

function removeStructure(fname) {
  const entry = loadedModels[fname];
  if (!entry) return;
  viewer.removeModel(entry.model);
  viewer.render();
  delete loadedModels[fname];
  delete highlightedResidues[fname];
  renderControls();
  renderSequence();
  const total = Object.keys(loadedModels).length;
  document.getElementById('status').textContent =
    total ? `${total} structure(s) loaded` : 'Ready';
}

function clearAll() {
  for (const entry of Object.values(loadedModels)) viewer.removeModel(entry.model);
  loadedModels = {};
  highlightedResidues = {};
  viewer.render();
  renderControls();
  renderSequence();
  document.getElementById('status').textContent = 'Ready';
}

// ── sequence panel ────────────────────────────────────────────────────────
function toggleSeqPanel() {
  seqCollapsed = !seqCollapsed;
  document.getElementById('seqPanel').classList.toggle('collapsed', seqCollapsed);
  document.getElementById('seqCollapseIcon').textContent = seqCollapsed ? '\\u25b2' : '\\u25bc';
  viewer.resize();
}

function renderSequence() {
  const panel   = document.getElementById('seqPanel');
  const content = document.getElementById('seqContent');
  const entries = Object.entries(loadedModels);
  if (!entries.length) { panel.style.display = 'none'; return; }
  panel.style.display = '';
  content.innerHTML = entries.map(([fname, entry]) => {
    const stem = fname.replace(/\\.cif$/, '');
    const hi   = highlightedResidues[fname] || {};
    const ef   = fname.replace(/\\\\/g, '\\\\\\\\').replace(/'/g, "\\'");
    const chainTracks = Object.entries(entry.sequences || {}).map(([chain, residues]) => {
      const chainHi  = hi[chain] || new Set();
      const ec       = chain.replace(/'/g, "\\'");
      const chainClr = (entry.chains[chain] || {}).color || entry.color;
      const resSpans = residues.map(({seqId, resName}) => {
        const letter = toOneLetter(resName);
        const isHi   = chainHi.has(seqId);
        const style  = isHi ? '' : `color:${chainClr};opacity:0.8`;
        return `<span class="seq-res${isHi ? ' hi' : ''}" style="${style}" `
          + `title="${resName} ${seqId}" onclick="toggleResidue('${ef}','${ec}','${seqId}')">${letter}</span>`;
      }).join('');
      const clearBtn = chainHi.size
        ? `<button class="seq-clear-btn" onclick="clearChainHighlights('${ef}','${ec}')">\\u2715 ${chainHi.size}</button>`
        : '';
      return `<div class="seq-chain-row">
        <span class="seq-chain-lbl" style="color:${chainClr}">${chain || '\\u00b7'}</span>
        ${clearBtn}<div class="seq-track">${resSpans}</div>
      </div>`;
    }).join('');
    return `<div class="seq-struct">
      <div class="seq-struct-title"><span class="cdot" style="background:${entry.color}"></span><span>${stem}</span></div>
      ${chainTracks}
    </div>`;
  }).join('');
}

function toggleResidue(fname, chain, seqId) {
  if (!highlightedResidues[fname]) highlightedResidues[fname] = {};
  if (!highlightedResidues[fname][chain]) highlightedResidues[fname][chain] = new Set();
  const s = highlightedResidues[fname][chain];
  if (s.has(seqId)) s.delete(seqId); else s.add(seqId);
  applyStyles(fname);
  renderSequence();
}

function clearChainHighlights(fname, chain) {
  if (highlightedResidues[fname]) delete highlightedResidues[fname][chain];
  applyStyles(fname);
  renderSequence();
}

// ── left-panel resize ─────────────────────────────────────────────────────
(function() {
  const handle = document.getElementById('resizeHandle');
  const panel  = document.querySelector('.panel-left');
  let dragging = false, startX = 0, startW = 0;

  handle.addEventListener('mousedown', e => {
    dragging = true;
    startX   = e.clientX;
    startW   = panel.getBoundingClientRect().width;
    handle.classList.add('dragging');
    document.body.style.cursor     = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const minW = parseInt(getComputedStyle(panel).minWidth) || 200;
    const maxW = window.innerWidth * 0.7;
    const w    = Math.min(maxW, Math.max(minW, startW + (e.clientX - startX)));
    panel.style.width = w + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    document.body.style.cursor     = '';
    document.body.style.userSelect = '';
    if (viewer) viewer.resize();
  });
})();

window.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
"""


# ── HTML generation ────────────────────────────────────────────────────────────

def generate_html(entries, col_configs, filter_configs, title, filter_html, table_headers):
    html = HTML_TEMPLATE
    html = html.replace('%%%TITLE%%%',          title)
    html = html.replace('%%%ENTRIES%%%',        json.dumps(entries, indent=2))
    html = html.replace('%%%COLUMNS%%%',        json.dumps(col_configs))
    html = html.replace('%%%FILTERS%%%',        json.dumps(filter_configs))
    html = html.replace('%%%FILTER_HTML%%%',    filter_html)
    html = html.replace('%%%TABLE_HEADERS%%%',  table_headers)
    return html


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Generate a self-contained HTML structure browser.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('csv_file',        help='CSV file with structure metadata')
    parser.add_argument('structures_dir',  help='Directory containing .cif files')
    parser.add_argument('-o', '--output',  default=None,
                        help='Output HTML (default: index.html next to CSV)')
    parser.add_argument('--id-col',        default=None,
                        help='CSV column matching file name prefixes (auto-detected)')
    parser.add_argument('--title',         default='Structure Browser',
                        help='Page title (default: "Structure Browser")')
    args = parser.parse_args()

    # ── CSV ──────────────────────────────────────────────────────────────────
    print(f'Reading CSV: {args.csv_file}')
    rows, fieldnames = read_csv(args.csv_file)
    fieldnames, rows = drop_index_col(fieldnames, rows)
    print(f'  {len(rows)} rows, columns: {", ".join(fieldnames)}')

    # ── structures ───────────────────────────────────────────────────────────
    print(f'Scanning structures: {args.structures_dir}')
    file_map = scan_structures(args.structures_dir)
    total_files = sum(len(v) for v in file_map.values())
    print(f'  {total_files} .cif files, {len(file_map)} unique ID prefixes')

    # ── ID column ────────────────────────────────────────────────────────────
    if args.id_col:
        if args.id_col not in fieldnames:
            sys.exit(f'Error: --id-col {args.id_col!r} not in CSV columns: {fieldnames}')
        id_col = args.id_col
        print(f'ID column: {id_col!r}')
    else:
        id_col = detect_id_col(rows, list(file_map.keys()), fieldnames)
        if id_col is None:
            sys.exit('Error: could not auto-detect ID column. Use --id-col.')
        print(f'ID column (auto-detected): {id_col!r}')

    data_cols = [c for c in fieldnames if c != id_col]

    # ── entries ──────────────────────────────────────────────────────────────
    entries, col_keys = build_entries(rows, file_map, id_col, data_cols)
    print(f'Entries: {len(entries)} (one per .cif file)')

    csv_ids  = {str(r.get(id_col, '') or '').strip() for r in rows}
    file_ids = set(file_map.keys())
    no_file  = csv_ids - file_ids
    no_csv   = file_ids - csv_ids
    if no_file:
        print(f'  Note: {len(no_file)} CSV ID(s) with no matching file — '
              f'{sorted(no_file)[:5]}{"..." if len(no_file) > 5 else ""}')
    if no_csv:
        print(f'  Note: {len(no_csv)} file prefix(es) not in CSV (no metadata)')

    # ── columns ──────────────────────────────────────────────────────────────
    col_configs, filter_configs = analyze_columns(entries, data_cols, col_keys)
    print(f'Columns: {len(col_configs)} total, '
          f'{len(filter_configs)} filter(s) generated')

    # ── generate ─────────────────────────────────────────────────────────────
    filter_html   = build_filter_html(filter_configs)
    table_headers = build_table_headers(col_configs)
    html          = generate_html(entries, col_configs, filter_configs,
                                  args.title, filter_html, table_headers)

    # ── write ────────────────────────────────────────────────────────────────
    output = args.output or str(Path(args.csv_file).parent / 'index.html')
    Path(output).write_text(html, encoding='utf-8')
    print(f'Output: {output} ({len(html) // 1024} KB)')


if __name__ == '__main__':
    main()
