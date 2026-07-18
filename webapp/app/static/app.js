const paneByPanel = {
  chat: document.getElementById('chatResultPane'),
  validation: document.getElementById('validationResultPane'),
  comparison: document.getElementById('comparisonResultPane'),
  rootcause: document.getElementById('rootCauseResultPane'),
  insights: document.getElementById('insightsResultPane'),
};
let activePanel = 'chat';
const graphSummary = document.getElementById('graphSummary');
const graphCanvas = document.getElementById('graphCanvas');
const chatQuestion = document.getElementById('chatQuestion');
const chatBtn = document.getElementById('chatBtn');
const chatLlmEnabled = document.getElementById('chatLlmEnabled');
const chatLlmModel = document.getElementById('chatLlmModel');
const chatLlmStatus = document.getElementById('chatLlmStatus');
const chatClearBtn = document.getElementById('chatClearBtn');
const graphBtn = document.getElementById('graphBtn');
const menuToggle = document.getElementById('menuToggle');
const workspaceShell = document.querySelector('.workspace-shell');
const menuButtons = document.querySelectorAll('.menu-btn');
const featurePanels = document.querySelectorAll('.feature-panel');
const insightPages = document.querySelectorAll('.insight-page');
const validPanels = new Set(['chat', 'validation', 'comparison', 'rootcause', 'insights', 'graph']);
let chatHistory = [];
let chatMessages = [];
const INSIGHTS_TAB_META = {
  demand_supply: { label: 'Demand vs Supply trend', title: 'Demand vs Supply Trend' },
  fill_rate: { label: 'Fill Rate trend', title: 'Fill Rate Trend' },
  capacity: { label: 'Capacity Utilization trend', title: 'Capacity Utilization Trend' },
  met_split: { label: 'Demand Met vs UnMet vs Partially Met split', title: 'Demand Met vs UnMet vs Partially Met' },
};
const INSIGHTS_TABS = Object.keys(INSIGHTS_TAB_META);
const INSIGHTS_GRAINS = ['quarter', 'month', 'workweek'];
const INSIGHTS_GRAIN_LABEL = {
  quarter: 'Quarter',
  month: 'Month',
  workweek: 'Workweek',
};

function createInsightsTabState() {
  const tabs = {};
  INSIGHTS_TABS.forEach((tabName) => {
    tabs[tabName] = {
      weekId: '',
      scenarioId: '',
      activeGrain: 'quarter',
      drillSelection: null,
      data: null,
      loading: false,
      error: '',
    };
  });
  return tabs;
}

let insightsState = {
  activeTab: 'demand_supply',
  tabs: createInsightsTabState(),
};

const NODE_COLORS = {
  demand_item: '#0ea5e9',
  location: '#f59e0b',
  supply_item: '#8b5cf6',
  supply_location: '#10b981',
  supply_method: '#ef4444',
  resource: '#14b8a6',
};

const EDGE_COLORS = {
  'demand at': '#f59e0b',
  'pegs to': '#06b6d4',
  'supplies from': '#8b5cf6',
  executes: '#ef4444',
  loads: '#22c55e',
};

const LANE_META = {
  location: {
    title: 'Demand Context Lane',
    description: 'Plant/location where demand is requested and where service outcome is measured.',
  },
  demand_item: {
    title: 'Demand Lane',
    description: 'Primary demand item under analysis for met, partially met, or unmet behavior.',
  },
  supply_item: {
    title: 'Supply Lane',
    description: 'Supply items pegged to demand, including alternate or upstream items.',
  },
  supply_method: {
    title: 'Method Lane',
    description: 'Production, purchase, or transfer method used to generate supply.',
  },
  resource: {
    title: 'Resource Lane',
    description: 'Capacity/resource loading entities that can constrain fulfillment timing and quantity.',
  },
};

function laneColor(type) {
  return NODE_COLORS[type] || '#8ed2ff';
}

function edgeColor(label) {
  return EDGE_COLORS[label] || '#8ed2ff';
}

function hexToRgba(hex, alpha = 0.18) {
  const value = (hex || '').replace('#', '').trim();
  if (value.length !== 6) {
    return `rgba(255, 255, 255, ${alpha})`;
  }
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatScalar(value) {
  if (value === null || value === undefined || value === '') {
    return 'Not provided';
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  return String(value);
}

function renderRichText(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br />');
}

function renderScalarBlock(value) {
  return `<div class="result-list-item">${renderRichText(formatScalar(value))}</div>`;
}

function renderArray(value) {
  if (!Array.isArray(value) || value.length === 0) {
    return '<div class="result-list-item">None</div>';
  }

  return `<div class="result-list">${value
    .map((item) => {
      if (item !== null && typeof item === 'object') {
        return `<div class="result-section">${renderObject(item, true)}</div>`;
      }
      return renderScalarBlock(item);
    })
    .join('')}</div>`;
}

function renderKeyValueGrid(entries) {
  return `<div class="kv-grid">${entries
    .map(
      ([key, value]) => `
        <div class="kv-card">
          <strong>${escapeHtml(key)}</strong>
          <div>${renderRichText(formatScalar(value))}</div>
        </div>`,
    )
    .join('')}</div>`;
}

function renderObject(value, nested = false) {
  const entries = Object.entries(value || {});
  if (entries.length === 0) {
    return '<div class="result-list-item">None</div>';
  }

  const scalarEntries = entries.filter(([, item]) => item === null || typeof item !== 'object');
  const nestedEntries = entries.filter(([, item]) => item !== null && typeof item === 'object');

  const blocks = [];
  if (scalarEntries.length > 0) {
    blocks.push(renderKeyValueGrid(scalarEntries));
  }

  nestedEntries.forEach(([key, item]) => {
    const body = Array.isArray(item) ? renderArray(item) : renderObject(item, true);
    blocks.push(`
      <div class="result-section">
        <h3>${escapeHtml(key)}</h3>
        ${body}
      </div>
    `);
  });

  if (!nested && scalarEntries.length === entries.length) {
    return renderKeyValueGrid(entries);
  }

  return blocks.join('');
}

function pretty(data) {
  const pane = paneByPanel[activePanel] || paneByPanel.chat;
  if (data === null || typeof data !== 'object') {
    pane.innerHTML = `<div class="result-grid">${renderScalarBlock(data)}</div>`;
    return;
  }

  const sections = Object.entries(data).map(([section, value]) => {
    let body = '';

    if (typeof value === 'string') {
      body = renderScalarBlock(value);
    } else if (Array.isArray(value)) {
      body = renderArray(value);
    } else if (value !== null && typeof value === 'object') {
      body = renderObject(value);
    } else {
      body = renderScalarBlock(value);
    }

    return `
      <section class="result-section">
        <h3>${escapeHtml(section)}</h3>
        ${body}
      </section>
    `;
  });

  pane.innerHTML = `<div class="result-grid">${sections.join('')}</div>`;
}

function renderChatThread() {
  const pane = paneByPanel.chat;
  if (!pane) {
    return;
  }

  if (chatMessages.length === 0) {
    pane.innerHTML = '<div class="chat-placeholder">Ask a question to start the conversation.</div>';
    return;
  }

  pane.innerHTML = chatMessages
    .map((message) => {
      const role = message.role === 'user' ? 'user' : 'assistant';
      const roleLabel = role === 'user' ? 'You' : 'Assistant';
      const followups =
        role === 'assistant' &&
        message.details &&
        typeof message.details === 'object' &&
        Array.isArray(message.details['Suggested Follow-ups'])
          ? message.details['Suggested Follow-ups']
          : [];
      let detailPayload = message.details;
      if (followups.length > 0 && detailPayload && typeof detailPayload === 'object') {
        detailPayload = { ...detailPayload };
        delete detailPayload['Suggested Follow-ups'];
      }
      const details =
        detailPayload && typeof detailPayload === 'object' && Object.keys(detailPayload).length > 0
          ? `<div class="chat-details">${renderObject(detailPayload)}</div>`
          : '';
      const followupHtml =
        followups.length > 0
          ? `<div class="chat-followups">${followups
              .map(
                (item) =>
                  `<button class="chat-followup-btn" type="button" data-followup="${escapeHtml(String(item))}">${escapeHtml(String(item))}</button>`,
              )
              .join('')}</div>`
          : '';

      return `
        <div class="chat-message ${role}">
          <div class="chat-role">${roleLabel}</div>
          <div>${renderRichText(formatScalar(message.content))}</div>
          ${followupHtml}
          ${details}
        </div>
      `;
    })
    .join('');

  Array.from(pane.querySelectorAll('.chat-followup-btn')).forEach((button) => {
    button.addEventListener('click', () => {
      const text = button.getAttribute('data-followup') || '';
      chatQuestion.value = text;
      submitChat();
    });
  });

  pane.scrollTop = pane.scrollHeight;
}

function appendChatMessage(role, content, details = null) {
  chatMessages.push({ role, content, details });
  renderChatThread();
}

function normalizeAssistantReply(data) {
  if (!data || typeof data !== 'object') {
    return { text: 'I could not process the response.', details: null };
  }

  const reply = data['Assistant Reply'] || data.message || data.answer;
  if (typeof reply === 'string' && reply.trim()) {
    const details = { ...data };
    delete details['Assistant Reply'];
    return {
      text: reply.trim(),
      details: Object.keys(details).length ? details : null,
    };
  }

  if (data.Error) {
    return { text: String(data.Error), details: data.Details || null };
  }

  return {
    text: 'Here is what I found.',
    details: data,
  };
}

function buildGraphColumns(nodes) {
  const order = ['location', 'demand_item', 'supply_item', 'supply_method', 'resource'];
  const groups = new Map(order.map((type) => [type, []]));

  nodes.forEach((node) => {
    const type = groups.has(node.type) ? node.type : 'resource';
    groups.get(type).push(node);
  });

  return order.map((type) => ({ type, nodes: groups.get(type) }));
}

function renderGraphNodeDetails(node) {
  if (!node) {
    return '<div class="graph-help">Click a node to see details and connected lineage.</div>';
  }

  const metaEntries = Object.entries(node.meta || {});
  return `
    <div class="graph-node-panel">
      <h4>${escapeHtml(node.label)}</h4>
      <p class="graph-node-type">${escapeHtml((node.type || 'unknown').replaceAll('_', ' '))}</p>
      ${metaEntries.length > 0 ? renderKeyValueGrid(metaEntries) : '<div class="graph-help">No additional metadata for this node.</div>'}
    </div>
  `;
}

function renderGraphEdgeDetails(edge, sourceNode, targetNode) {
  if (!edge) {
    return '<div class="graph-help">Click a line to see how the lane connects demand, supply, method, or resource nodes.</div>';
  }

  const details = [
    ['Lane', edge.label],
    ['Quantity', edge.value],
    ['From', sourceNode ? `${sourceNode.label} (${sourceNode.type})` : edge.source],
    ['To', targetNode ? `${targetNode.label} (${targetNode.type})` : edge.target],
  ];

  return `
    <div class="graph-node-panel">
      <h4>${escapeHtml(edge.label)}</h4>
      <p class="graph-node-type">${escapeHtml(edge.label || 'connection lane')}</p>
      ${renderKeyValueGrid(details)}
      <div class="graph-help">This line explains the planning linkage between the connected nodes.</div>
    </div>
  `;
}

function wireGraphInteractions(nodes, edges) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const edgeByKey = new Map(edges.map((edge) => [`${edge.source}::${edge.target}::${edge.label}`, edge]));
  const detailPanel = document.getElementById('graphNodeDetails');
  const lanePanel = document.getElementById('graphLaneGuide');
  const resetBtn = document.getElementById('graphResetFocus');
  if (!detailPanel || !lanePanel) {
    return;
  }

  const connections = new Map();
  edges.forEach((edge) => {
    if (!connections.has(edge.source)) {
      connections.set(edge.source, new Set());
    }
    if (!connections.has(edge.target)) {
      connections.set(edge.target, new Set());
    }
    connections.get(edge.source).add(edge.target);
    connections.get(edge.target).add(edge.source);
  });

  const allNodes = Array.from(document.querySelectorAll('.graph-node'));
  const allEdges = Array.from(document.querySelectorAll('.graph-edge'));
  const allEdgeHits = Array.from(document.querySelectorAll('.graph-edge-hit'));
  const allLaneCards = Array.from(document.querySelectorAll('.lane-card'));

  function resetHighlights() {
    allNodes.forEach((el) => el.classList.remove('active', 'dim'));
    allEdges.forEach((el) => el.classList.remove('active', 'dim'));
    allEdgeHits.forEach((el) => el.classList.remove('active', 'dim'));
    allLaneCards.forEach((el) => el.classList.remove('active'));
  }

  function clearFocus() {
    resetHighlights();
    detailPanel.innerHTML = '<div class="graph-help">Click a node to see details and connected lineage.</div>';
  }

  function focusNode(nodeId) {
    const selected = nodeById.get(nodeId);
    if (!selected) {
      return;
    }
    resetHighlights();

    const connected = connections.get(nodeId) || new Set();
    allNodes.forEach((el) => {
      const currentId = el.getAttribute('data-node-id');
      if (currentId === nodeId || connected.has(currentId)) {
        el.classList.add('active');
      } else {
        el.classList.add('dim');
      }
    });

    allEdges.forEach((el) => {
      const source = el.getAttribute('data-source');
      const target = el.getAttribute('data-target');
      const sameLane = el.getAttribute('data-lane') === selected.type;
      if (source === nodeId || target === nodeId || (connected.has(source) && connected.has(target))) {
        el.classList.add('active');
        if (sameLane) {
          el.classList.add('active');
        }
      } else {
        el.classList.add('dim');
      }
    });

    allEdgeHits.forEach((el) => {
      const source = el.getAttribute('data-source');
      const target = el.getAttribute('data-target');
      if (source === nodeId || target === nodeId || (connected.has(source) && connected.has(target))) {
        el.classList.add('active');
      } else {
        el.classList.add('dim');
      }
    });

    allLaneCards.forEach((el) => {
      if (el.getAttribute('data-lane') === selected.type) {
        el.classList.add('active');
      }
    });

    detailPanel.innerHTML = renderGraphNodeDetails(selected);
  }

  allNodes.forEach((el) => {
    const nodeId = el.getAttribute('data-node-id');
    el.addEventListener('click', () => focusNode(nodeId));
    el.addEventListener('mouseenter', () => focusNode(nodeId));
    el.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        focusNode(nodeId);
      }
    });
  });

  allEdgeHits.forEach((el) => {
    const source = el.getAttribute('data-source');
    const target = el.getAttribute('data-target');
    const lane = el.getAttribute('data-lane');
    el.addEventListener('click', () => {
      const edge = edgeByKey.get(`${source}::${target}::${lane}`);
      resetHighlights();
      const sourceNode = nodeById.get(source);
      const targetNode = nodeById.get(target);
      allEdgeHits.forEach((hit) => {
        const hitSource = hit.getAttribute('data-source');
        const hitTarget = hit.getAttribute('data-target');
        if (hitSource === source || hitTarget === target) {
          hit.classList.add('active');
        } else {
          hit.classList.add('dim');
        }
      });
      allEdges.forEach((edgeEl) => {
        const edgeSource = edgeEl.getAttribute('data-source');
        const edgeTarget = edgeEl.getAttribute('data-target');
        if (edgeSource === source || edgeTarget === target) {
          edgeEl.classList.add('active');
        } else {
          edgeEl.classList.add('dim');
        }
      });
      allNodes.forEach((nodeEl) => {
        const nodeId = nodeEl.getAttribute('data-node-id');
        if (nodeId === source || nodeId === target) {
          nodeEl.classList.add('active');
        } else {
          nodeEl.classList.add('dim');
        }
      });
      allLaneCards.forEach((card) => {
        if (card.getAttribute('data-lane') === lane) {
          card.classList.add('active');
        }
      });
      detailPanel.innerHTML = renderGraphEdgeDetails(edge, sourceNode, targetNode);
    });
    el.addEventListener('mouseenter', () => {
      const edge = edgeByKey.get(`${source}::${target}::${lane}`);
      const sourceNode = nodeById.get(source);
      const targetNode = nodeById.get(target);
      detailPanel.innerHTML = renderGraphEdgeDetails(edge, sourceNode, targetNode);
    });
  });

  allLaneCards.forEach((el) => {
    el.addEventListener('mouseenter', () => {
      const lane = el.getAttribute('data-lane');
      allLaneCards.forEach((card) => card.classList.toggle('active', card === el));
      detailPanel.innerHTML = `<div class="graph-help"><strong>${escapeHtml(LANE_META[lane]?.title || lane)}</strong><br/>${escapeHtml(LANE_META[lane]?.description || '')}</div>`;
    });
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      clearFocus();
    });
  }

  const demandNode = nodes.find((node) => node.type === 'demand_item') || nodes[0];
  if (demandNode) {
    focusNode(demandNode.id);
  }
}

function renderGraph(data) {
  const summary = data['Graph Summary'] || {};
  const nodes = Array.isArray(data.nodes) ? data.nodes : [];
  const edges = Array.isArray(data.edges) ? data.edges : [];

  graphSummary.innerHTML = renderKeyValueGrid(Object.entries(summary));

  if (nodes.length === 0) {
    graphCanvas.innerHTML = '<div class="graph-empty">No graph data found for this item and scope.</div>';
    return;
  }

  const columns = buildGraphColumns(nodes);
  const columnGap = 190;
  const rowGap = 96;
  const width = Math.max(900, columns.length * columnGap + 120);
  const maxRows = Math.max(...columns.map((column) => Math.max(column.nodes.length, 1)));
  const height = Math.max(360, maxRows * rowGap + 80);
  const positions = new Map();

  columns.forEach((column, colIndex) => {
    column.nodes.forEach((node, rowIndex) => {
      const x = 90 + colIndex * columnGap;
      const y = 70 + rowIndex * rowGap + (height - Math.max(column.nodes.length, 1) * rowGap) / 2;
      positions.set(node.id, { x, y, node });
    });
  });

  const edgeSvg = edges
    .map((edge) => {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      if (!source || !target) {
        return '';
      }
      const midX = (source.x + target.x) / 2;
      const midY = (source.y + target.y) / 2;
      const stroke = edgeColor(edge.label);
      return `
        <line class="graph-edge-hit" data-source="${escapeHtml(edge.source)}" data-target="${escapeHtml(edge.target)}" data-lane="${escapeHtml(edge.label)}" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" stroke="transparent" stroke-width="16" />
        <line class="graph-edge" data-source="${escapeHtml(edge.source)}" data-target="${escapeHtml(edge.target)}" data-lane="${escapeHtml(edge.label)}" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" stroke="${stroke}" stroke-width="2" />
        <text x="${midX}" y="${midY - 6}" text-anchor="middle" class="graph-edge-label">${escapeHtml(edge.label)}${edge.value ? ` (${escapeHtml(edge.value)})` : ''}</text>
      `;
    })
    .join('');

  const nodeSvg = nodes
    .map((node) => {
      const pos = positions.get(node.id);
      const color = NODE_COLORS[node.type] || '#00a3e0';
      return `
        <g class="graph-node" data-node-id="${escapeHtml(node.id)}" data-node-type="${escapeHtml(node.type)}" tabindex="0" role="button" aria-label="${escapeHtml(node.label)}">
          <circle cx="${pos.x}" cy="${pos.y}" r="26" fill="${color}" opacity="0.95" />
          <text x="${pos.x}" y="${pos.y + 44}" text-anchor="middle" class="graph-node-label">${escapeHtml(node.label)}</text>
        </g>
      `;
    })
    .join('');

  const legend = Object.entries(NODE_COLORS)
    .map(([type, color]) => `<span class="legend-chip" style="border-color:${color};"><span class="legend-swatch" style="background:${color};"></span><span>${escapeHtml(type.replaceAll('_', ' '))}</span></span>`)
    .join('');

  const edgeLegend = Object.entries(EDGE_COLORS)
    .map(([label, color]) => `<span class="legend-chip legend-chip-edge" style="border-color:${color};"><span class="legend-swatch" style="background:${color};"></span><span>${escapeHtml(label)}</span></span>`)
    .join('');

  const laneGuide = columns
    .map((column) => {
      const lane = LANE_META[column.type] || { title: column.type, description: '' };
      const color = laneColor(column.type);
      return `
        <div class="lane-card" data-lane="${escapeHtml(column.type)}" style="border-color:${color};">
          <div class="lane-card-header">
            <span class="lane-swatch" style="background:${color};"></span>
            <strong>${escapeHtml(lane.title)}</strong>
          </div>
          <p>${escapeHtml(lane.description)}</p>
          <span>${column.nodes.length} node(s)</span>
        </div>
      `;
    })
    .join('');

  graphCanvas.innerHTML = `
    <div class="graph-wrap">
      <div id="graphLaneGuide" class="lane-guide">${laneGuide}</div>
      <div class="graph-legend"><strong>Node Legend</strong>${legend}</div>
      <div class="graph-legend"><strong>Line Legend</strong>${edgeLegend}</div>
      <div class="graph-interactive-layout">
        <svg class="graph-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
          ${edgeSvg}
          ${nodeSvg}
        </svg>
        <aside class="graph-side-panel">
          <button id="graphResetFocus" class="btn graph-reset-btn" type="button">Reset Focus</button>
          <div id="graphNodeDetails" class="graph-node-details"></div>
        </aside>
      </div>
    </div>
  `;

  wireGraphInteractions(nodes, edges);
}

function renderMetricBarRows(rows, options) {
  const {
    labelKey = 'bucket',
    valueKey,
    maxValue,
    barClass = '',
    valueSuffix = '',
    formatter = (value) => Number(value || 0).toFixed(2),
    tabName = 'demand_supply',
    metricName = valueKey,
  } = options;

  if (!Array.isArray(rows) || rows.length === 0) {
    return '<div class="insights-empty">No trend rows available for this metric.</div>';
  }

  return rows
    .map((row) => {
      const label = formatScalar(row[labelKey]);
      const value = Number(row[valueKey] || 0);
      const pct = maxValue > 0 ? Math.max(0, Math.min(100, (value / maxValue) * 100)) : 0;
      const tabState = insightsState.tabs[tabName] || null;
      const activeGrain = tabState ? tabState.activeGrain : 'quarter';
      const drill = tabState ? tabState.drillSelection : null;
      const isSelected =
        drill &&
        drill.metric === metricName &&
        drill.grain === activeGrain &&
        drill.bucket === String(row[labelKey] || '');
      return `
        <button
          class="insights-row drillable ${isSelected ? 'active' : ''}"
          type="button"
          data-insight-tab="${escapeHtml(tabName)}"
          data-insight-grain="${escapeHtml(activeGrain)}"
          data-insight-metric="${escapeHtml(metricName)}"
          data-insight-bucket="${escapeHtml(String(row[labelKey] || ''))}"
          data-insight-value="${escapeHtml(String(value))}"
        >
          <div class="insights-row-head">
            <span>${escapeHtml(label)}</span>
            <span>${escapeHtml(`${formatter(value)}${valueSuffix}`)}</span>
          </div>
          <div class="insights-bar-track">
            <div class="insights-bar ${barClass}" style="width:${pct}%;"></div>
          </div>
        </button>
      `;
    })
    .join('');
}

function renderDemandSupplyRows(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return '<div class="insights-empty">No Demand vs Supply rows available.</div>';
  }

  const maxValue = Math.max(
    ...rows.map((row) => Math.max(Number(row.demand_qty || 0), Number(row.supply_qty || 0))),
    0,
  );

  return rows
    .map((row) => {
      const bucket = formatScalar(row.bucket);
      const demand = Number(row.demand_qty || 0);
      const supply = Number(row.supply_qty || 0);
      const gap = Number(row.gap_qty || 0);
      const demandPct = maxValue > 0 ? Math.max(0, Math.min(100, (demand / maxValue) * 100)) : 0;
      const supplyPct = maxValue > 0 ? Math.max(0, Math.min(100, (supply / maxValue) * 100)) : 0;
      const tabState = insightsState.tabs.demand_supply;
      const activeGrain = tabState ? tabState.activeGrain : 'quarter';
      const drill = tabState ? tabState.drillSelection : null;
      const isSelected =
        drill &&
        drill.metric === 'gap_qty' &&
        drill.grain === activeGrain &&
        drill.bucket === String(row.bucket || '');

      return `
        <button
          class="insights-row drillable ${isSelected ? 'active' : ''}"
          type="button"
          data-insight-tab="demand_supply"
          data-insight-grain="${escapeHtml(activeGrain)}"
          data-insight-metric="gap_qty"
          data-insight-bucket="${escapeHtml(String(row.bucket || ''))}"
          data-insight-value="${escapeHtml(String(gap))}"
        >
          <div class="insights-row-head">
            <span>${escapeHtml(bucket)}</span>
            <span>Gap: ${escapeHtml(gap.toFixed(2))}</span>
          </div>
          <div class="insights-dual">
            <div class="insights-dual-item">
              <span>Demand ${escapeHtml(demand.toFixed(2))}</span>
              <div class="insights-bar-track"><div class="insights-bar demand" style="width:${demandPct}%;"></div></div>
            </div>
            <div class="insights-dual-item">
              <span>Supply ${escapeHtml(supply.toFixed(2))}</span>
              <div class="insights-bar-track"><div class="insights-bar supply" style="width:${supplyPct}%;"></div></div>
            </div>
          </div>
        </button>
      `;
    })
    .join('');
}

function syncInsightsControlTabs() {
  const tabButtons = Array.from(document.querySelectorAll('.analytics-control-tab'));
  if (tabButtons.length === 0) {
    return;
  }
  tabButtons.forEach((button) => {
    button.classList.toggle('active', button.getAttribute('data-tab') === insightsState.activeTab);
  });
}

function nextInsightsGrain(currentGrain) {
  const idx = INSIGHTS_GRAINS.indexOf(currentGrain);
  if (idx < 0 || idx >= INSIGHTS_GRAINS.length - 1) {
    return null;
  }
  return INSIGHTS_GRAINS[idx + 1];
}

function getInsightsTabData(tabName) {
  return insightsState.tabs[tabName] || null;
}

function extractInsightRows(data, tabName, grain) {
  const trends = data['Trend Analysis'] || {};
  if (tabName === 'demand_supply') {
    const rowsByGrain = trends['Demand vs Supply'] || {};
    return Array.isArray(rowsByGrain[grain]) ? rowsByGrain[grain] : [];
  }
  if (tabName === 'fill_rate') {
    const rowsByGrain = trends['Fill Rate'] || {};
    return Array.isArray(rowsByGrain[grain]) ? rowsByGrain[grain] : [];
  }
  if (tabName === 'capacity') {
    const rowsByGrain = trends['Capacity Utilization'] || {};
    return Array.isArray(rowsByGrain[grain]) ? rowsByGrain[grain] : [];
  }

  const split = trends['Demand Met vs UnMet vs Partially Met'] || {};
  const rowsByGrain = split.by_grain || {};
  return Array.isArray(rowsByGrain[grain]) ? rowsByGrain[grain] : [];
}

function renderInsightsDrillCard(tabName) {
  const tab = getInsightsTabData(tabName);
  if (!tab || !tab.drillSelection) {
    return `
      <section class="insights-card">
        <h3>Drill Focus</h3>
        <div class="insights-empty">Click any chart row to inspect details and drill to the next time grain.</div>
      </section>
    `;
  }

  const selected = tab.drillSelection;
  const nextGrain = nextInsightsGrain(selected.grain);
  return `
    <section class="insights-card">
      <h3>Drill Focus</h3>
      ${renderKeyValueGrid([
        ['Analytics Metric', INSIGHTS_TAB_META[tabName].label],
        ['Grain', INSIGHTS_GRAIN_LABEL[selected.grain] || selected.grain],
        ['Bucket', selected.bucket],
        ['Metric', selected.metric.replaceAll('_', ' ')],
        ['Value', Number(selected.value || 0).toFixed(2)],
      ])}
      ${
        nextGrain
          ? `<button class="btn insights-drill-btn" type="button" data-drill-next="${nextGrain}">Drill Down to ${INSIGHTS_GRAIN_LABEL[nextGrain]}</button>`
          : '<div class="insights-empty">Lowest drill level reached.</div>'
      }
    </section>
  `;
}

function renderInsightChart(tabName, tab, data) {
  const grain = tab.activeGrain;
  const rows = extractInsightRows(data, tabName, grain);

  if (tabName === 'demand_supply') {
    return renderDemandSupplyRows(rows);
  }
  if (tabName === 'fill_rate') {
    const maxValue = Math.max(...rows.map((row) => Number(row.fill_rate_pct || 0)), 100);
    return renderMetricBarRows(rows, {
      labelKey: 'bucket',
      valueKey: 'fill_rate_pct',
      maxValue,
      barClass: 'fill-rate',
      tabName,
      metricName: 'fill_rate_pct',
      valueSuffix: '%',
      formatter: (value) => Number(value || 0).toFixed(2),
    });
  }
  if (tabName === 'capacity') {
    const maxValue = Math.max(...rows.map((row) => Number(row.derived_utilization_pct || 0)), 100);
    return renderMetricBarRows(rows, {
      labelKey: 'bucket',
      valueKey: 'derived_utilization_pct',
      maxValue,
      barClass: 'capacity',
      tabName,
      metricName: 'derived_utilization_pct',
      valueSuffix: '%',
      formatter: (value) => Number(value || 0).toFixed(2),
    });
  }

  const splitRows = rows.map((row) => ({
    bucket: row.bucket,
    label: `${row.bucket} (Met ${Number(row.met_count || 0)}, Partial ${Number(row.partial_count || 0)}, UnMet ${Number(row.unmet_count || 0)})`,
    total_count: Number(row.total_count || 0),
    unmet_count: Number(row.unmet_count || 0),
    met_count: Number(row.met_count || 0),
    partial_count: Number(row.partial_count || 0),
  }));
  const maxValue = Math.max(...splitRows.map((row) => row.total_count), 1);
  return renderMetricBarRows(splitRows, {
    labelKey: 'label',
    valueKey: 'total_count',
    maxValue,
    barClass: 'met-split',
    tabName,
    metricName: 'total_count',
    formatter: (value) => Number(value || 0).toFixed(0),
  });
}

function renderInsightTabPanel(tabName, tab) {
  const meta = INSIGHTS_TAB_META[tabName];
  const isActive = tabName === insightsState.activeTab;
  const kpi = tab.data ? tab.data['KPI Summary'] || {} : {};
  const scope = tab.data ? tab.data['Insights Scope'] || {} : {};
  const confidence = tab.data ? tab.data['Confidence and Data Gaps'] || {} : {};
  const grainButtons = INSIGHTS_GRAINS.map(
    (grain) =>
      `<button class="insights-grain-btn ${grain === tab.activeGrain ? 'active' : ''}" type="button" data-grain="${grain}">${INSIGHTS_GRAIN_LABEL[grain]}</button>`,
  ).join('');

  const summary = tab.data
    ? `
      <section class="insights-kpi-grid">
        ${renderKeyValueGrid([
          ['Week ID', scope.week_id || 'Latest'],
          ['Scenario ID', scope.scenario_id || 'Latest'],
          ['Overall Fill Rate %', kpi.overall_fill_rate_pct],
          ['Total Demand Qty', kpi.total_demand_qty],
          ['Total Met Qty', kpi.total_met_qty],
        ])}
      </section>
    `
    : '<div class="insights-empty">Enter Week ID and Scenario ID, then click Go to load analytics charts.</div>';

  const chart = tab.data
    ? `
      <section class="insights-card">
        <h3>${meta.title} (${INSIGHTS_GRAIN_LABEL[tab.activeGrain]})</h3>
        ${renderInsightChart(tabName, tab, tab.data)}
      </section>
      ${renderInsightsDrillCard(tabName)}
      <section class="insights-card">
        <h3>Confidence and Data Gaps</h3>
        ${renderKeyValueGrid([
          ['Confidence', confidence.confidence || 'Unknown'],
          ['Data Gaps', Array.isArray(confidence.data_gaps) && confidence.data_gaps.length > 0 ? confidence.data_gaps.join('; ') : 'None'],
        ])}
      </section>
    `
    : '';

  const status = tab.loading
    ? '<div class="insights-empty">Loading analytics data...</div>'
    : tab.error
      ? `<div class="insights-error">${escapeHtml(tab.error)}</div>`
      : '';

  return `
    <section class="insights-subtab-panel ${isActive ? 'active' : ''}" data-tab="${tabName}">
      <section class="insights-card analytics-input-card">
        <h3>${meta.title} Inputs</h3>
        <div class="analytics-form-grid">
          <input type="text" data-input-week value="${escapeHtml(tab.weekId)}" placeholder="Week ID = CAPTURE_WK (optional, latest by default)" />
          <input type="text" data-input-scenario value="${escapeHtml(tab.scenarioId)}" placeholder="Scenario ID = SIMULATION_NAME (optional, latest by default)" />
        </div>
        <div class="analytics-actions">
          <button class="btn" type="button" data-action="go" data-tab="${tabName}">Go</button>
          <button class="btn" type="button" data-action="reset" data-tab="${tabName}">Reset</button>
        </div>
        <div class="analytics-note">If Week ID or Scenario ID is blank, analytics automatically uses the latest CAPTURE_WK and SIMULATION_NAME.</div>
      </section>
      ${status}
      ${summary}
      ${
        tab.data
          ? `<section class="insights-grains"><div class="insights-grain-label">Trend Grain</div><div class="insights-grain-group">${grainButtons}</div></section>`
          : ''
      }
      ${chart}
    </section>
  `;
}

function renderInsightsLanding() {
  const pane = paneByPanel.insights;
  if (!pane) {
    return;
  }

  pane.innerHTML = `
    <div class="insights-wrap">
      ${INSIGHTS_TABS.map((tabName) => renderInsightTabPanel(tabName, insightsState.tabs[tabName])).join('')}
    </div>
  `;

  syncInsightsControlTabs();

  const paneEl = paneByPanel.insights;
  const activeTab = insightsState.activeTab;
  const activeTabData = getInsightsTabData(activeTab);
  const activePanel = paneEl ? paneEl.querySelector(`.insights-subtab-panel[data-tab="${activeTab}"]`) : null;
  if (!paneEl || !activePanel || !activeTabData) {
    return;
  }

  const weekInput = activePanel.querySelector('[data-input-week]');
  const scenarioInput = activePanel.querySelector('[data-input-scenario]');
  const goBtn = activePanel.querySelector(`[data-action="go"][data-tab="${activeTab}"]`);
  const resetBtn = activePanel.querySelector(`[data-action="reset"][data-tab="${activeTab}"]`);

  if (goBtn && weekInput && scenarioInput) {
    goBtn.addEventListener('click', () => {
      activeTabData.weekId = weekInput.value.trim();
      activeTabData.scenarioId = scenarioInput.value.trim();
      runInsightsForTab(activeTab);
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      resetInsightsTab(activeTab);
      renderInsightsLanding();
    });
  }

  if (activeTabData.data) {
    Array.from(activePanel.querySelectorAll('.insights-grain-btn')).forEach((button) => {
      button.addEventListener('click', () => {
        const grain = button.getAttribute('data-grain');
        if (!grain || !INSIGHTS_GRAINS.includes(grain)) {
          return;
        }
        activeTabData.activeGrain = grain;
        activeTabData.drillSelection = null;
        renderInsightsLanding();
      });
    });

    Array.from(activePanel.querySelectorAll('.insights-row.drillable')).forEach((rowBtn) => {
      rowBtn.addEventListener('click', () => {
        activeTabData.drillSelection = {
          grain: rowBtn.getAttribute('data-insight-grain') || activeTabData.activeGrain,
          metric: rowBtn.getAttribute('data-insight-metric') || 'value',
          bucket: rowBtn.getAttribute('data-insight-bucket') || 'Unknown',
          value: rowBtn.getAttribute('data-insight-value') || '0',
        };
        renderInsightsLanding();
      });
    });

    const drillBtn = activePanel.querySelector('[data-drill-next]');
    if (drillBtn) {
      drillBtn.addEventListener('click', () => {
        const next = drillBtn.getAttribute('data-drill-next');
        if (!next || !INSIGHTS_GRAINS.includes(next)) {
          return;
        }
        activeTabData.activeGrain = next;
        activeTabData.drillSelection = null;
        renderInsightsLanding();
      });
    }
  }
}

function normalizeInsightsData(data) {
  if (!data || typeof data !== 'object') {
    return null;
  }
  if ((data['Insights Mode'] || '') === 'Scenario Compare' && data['Compare Scenario Insights']) {
    return {
      ...data['Compare Scenario Insights'],
      'Confidence and Data Gaps': data['Confidence and Data Gaps'] || {},
      'Insights Scope': data['Comparison Scope'] || {},
    };
  }
  return data;
}

async function runInsightsForTab(tabName) {
  const tab = getInsightsTabData(tabName);
  if (!tab) {
    return;
  }
  INSIGHTS_TABS.forEach((name) => {
    const tabState = getInsightsTabData(name);
    if (!tabState) {
      return;
    }
    tabState.loading = true;
    tabState.error = '';
    tabState.drillSelection = null;
  });
  renderInsightsLanding();

  try {
    const res = await fetch('/api/insights', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        week_id: tab.weekId || null,
        scenario_id: tab.scenarioId || null,
        base_scenario_id: null,
        compare_scenario_id: null,
        scope: {},
      }),
    });
    const contentType = res.headers.get('content-type') || '';
    const data = contentType.includes('application/json')
      ? await res.json()
      : { Error: `Unexpected response format from /api/insights (${res.status}).` };

    if (!res.ok) {
      INSIGHTS_TABS.forEach((name) => {
        const tabState = getInsightsTabData(name);
        if (!tabState) {
          return;
        }
        tabState.error = `Request failed (${res.status}).`;
        tabState.data = null;
        tabState.loading = false;
      });
      renderInsightsLanding();
      return;
    }

    const normalized = normalizeInsightsData(data);
    if (!normalized || !normalized['Trend Analysis']) {
      INSIGHTS_TABS.forEach((name) => {
        const tabState = getInsightsTabData(name);
        if (!tabState) {
          return;
        }
        tabState.error = 'Insights response did not include trend analysis.';
        tabState.data = null;
        tabState.loading = false;
      });
      renderInsightsLanding();
      return;
    }

    INSIGHTS_TABS.forEach((name) => {
      const tabState = getInsightsTabData(name);
      if (!tabState) {
        return;
      }
      tabState.weekId = tab.weekId;
      tabState.scenarioId = tab.scenarioId;
      tabState.data = normalized;
      tabState.loading = false;
      tabState.error = '';
    });
    renderInsightsLanding();
  } catch (err) {
    INSIGHTS_TABS.forEach((name) => {
      const tabState = getInsightsTabData(name);
      if (!tabState) {
        return;
      }
      tabState.loading = false;
      tabState.data = null;
      tabState.error = String(err);
    });
    renderInsightsLanding();
  }
}

function resetInsightsTab(tabName) {
  const tab = getInsightsTabData(tabName);
  if (!tab) {
    return;
  }
  tab.weekId = '';
  tab.scenarioId = '';
  tab.activeGrain = 'quarter';
  tab.drillSelection = null;
  tab.data = null;
  tab.loading = false;
  tab.error = '';
}

function renderInsights(data) {
  const normalized = normalizeInsightsData(data);
  const tab = getInsightsTabData(insightsState.activeTab);
  if (!tab) {
    return;
  }
  if (!normalized || !normalized['Trend Analysis']) {
    tab.error = 'Insights response did not include trend analysis.';
    tab.data = null;
  } else {
    tab.data = normalized;
    tab.error = '';
  }
  tab.loading = false;
  renderInsightsLanding();
}

function activatePanel(panelName, updateHash = true) {
  if (!validPanels.has(panelName)) {
    panelName = 'chat';
  }

  activePanel = panelName;
  workspaceShell.classList.toggle('chat-merged', panelName === 'chat');

  menuButtons.forEach((button) => {
    const isActive = button.dataset.panel === panelName;
    button.classList.toggle('active', isActive);
  });

  featurePanels.forEach((panel) => {
    const isActive = panel.dataset.panel === panelName;
    panel.classList.toggle('active', isActive);
  });

  insightPages.forEach((page) => {
    const isActive = page.dataset.panel === panelName;
    page.classList.toggle('active', isActive);
  });

  if (updateHash) {
    const targetHash = `#${panelName}`;
    if (window.location.hash !== targetHash) {
      window.location.hash = targetHash;
    }
  }
}

function getPanelFromHash() {
  const hashPanel = (window.location.hash || '').replace('#', '').trim().toLowerCase();
  return validPanels.has(hashPanel) ? hashPanel : 'chat';
}

function syncPanelFromUrl() {
  activatePanel(getPanelFromHash(), false);
}

function setMenuCollapsed(collapsed) {
  workspaceShell.classList.toggle('menu-collapsed', collapsed);
  menuToggle.textContent = collapsed ? 'Expand' : 'Collapse';
  menuToggle.setAttribute('aria-label', collapsed ? 'Expand menu' : 'Collapse menu');
}

async function callApi(path, payload) {
  try {
    const options = payload
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      : {};

    const res = await fetch(path, options);
    const contentType = res.headers.get('content-type') || '';
    const data = contentType.includes('application/json')
      ? await res.json()
      : { Error: `Unexpected response format from ${path}.` };

    if (!res.ok) {
      pretty({ Error: `Request failed (${res.status})`, Details: data });
      return;
    }

    if (
      activePanel === 'insights' &&
      data &&
      typeof data === 'object' &&
      (data['Trend Analysis'] || data['Insights Mode'] === 'Scenario Compare')
    ) {
      renderInsights(data);
    } else {
      pretty(data);
    }
    return data;
  } catch (err) {
    pretty({ Error: String(err), Note: 'Please try again.' });
    return null;
  }
}

function setLlmControls() {
  const enabled = chatLlmEnabled.checked;
  chatLlmModel.disabled = !enabled;
  if (!enabled) {
    chatLlmStatus.textContent = 'LLM summary is off. Chat will use built-in grounded responses.';
  } else if (chatLlmModel.options.length > 0) {
    chatLlmStatus.textContent = `Using Ollama model: ${chatLlmModel.value}`;
  } else {
    chatLlmStatus.textContent = 'Ollama model list is unavailable. The default configured model will be used if reachable.';
  }
}

async function loadLlmModels() {
  try {
    const res = await fetch('/api/llm/models');
    const data = await res.json();
    const models = Array.isArray(data.models) ? data.models : [];
    const defaultModel = data.default_model || 'gemma3:latest';

    chatLlmModel.innerHTML = '';

    if (models.length === 0) {
      const option = document.createElement('option');
      option.value = defaultModel;
      option.textContent = defaultModel;
      chatLlmModel.appendChild(option);
    } else {
      models.forEach((modelName) => {
        const option = document.createElement('option');
        option.value = modelName;
        option.textContent = modelName;
        if (modelName === defaultModel) {
          option.selected = true;
        }
        chatLlmModel.appendChild(option);
      });
    }

    if (!data.reachable) {
      chatLlmStatus.textContent = 'Ollama is not reachable. Chat will fall back to built-in grounded responses.';
    } else {
      setLlmControls();
    }
  } catch (err) {
    chatLlmStatus.textContent = 'Could not load Ollama models. Chat can still run with built-in grounded responses.';
  }
  setLlmControls();
}

document.getElementById('summaryBtn').addEventListener('click', () => {
  callApi('/api/datasets/summary');
});

async function submitChat() {
  activatePanel('chat');
  const question = chatQuestion.value.trim();
  if (!question) {
    appendChatMessage('assistant', 'Please type your question so I can help.');
    return;
  }

  const historyForApi = [...chatHistory];
  appendChatMessage('user', question);
  appendChatMessage('assistant', 'Thinking...');

  chatBtn.disabled = true;
  chatBtn.textContent = 'Asking...';
  try {
    const chatSiteEl = document.getElementById('chatSite');
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        week_id: document.getElementById('chatWeek').value || null,
        scenario_id: document.getElementById('chatScenario').value || null,
        llm_enabled: chatLlmEnabled.checked,
        llm_model: chatLlmEnabled.checked ? chatLlmModel.value || null : null,
        history: historyForApi,
        scope: {
          site: chatSiteEl ? chatSiteEl.value || null : null,
        },
      }),
    });

    const contentType = res.headers.get('content-type') || '';
    const data = contentType.includes('application/json')
      ? await res.json()
      : { Error: `Unexpected response format from /api/chat (${res.status}).` };

    chatMessages.pop();

    if (!res.ok) {
      appendChatMessage('assistant', `Request failed (${res.status}).`, data);
      return;
    }

    const assistant = normalizeAssistantReply(data);
    appendChatMessage('assistant', assistant.text, assistant.details);

    chatHistory.push({ role: 'user', content: question });
    chatHistory.push({ role: 'assistant', content: assistant.text });
    if (chatHistory.length > 20) {
      chatHistory = chatHistory.slice(-20);
    }

    chatQuestion.value = '';
  } finally {
    if (chatMessages.length > 0 && chatMessages[chatMessages.length - 1].content === 'Thinking...') {
      chatMessages.pop();
      renderChatThread();
    }
    chatBtn.disabled = false;
    chatBtn.textContent = 'Ask Assistant';
  }
}

async function submitKnowledgeGraph() {
  graphBtn.disabled = true;
  graphBtn.textContent = 'Loading...';
  graphSummary.textContent = 'Building lineage graph...';
  graphCanvas.innerHTML = '';
  try {
    const res = await fetch('/api/knowledge-graph', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_id: document.getElementById('kgItem').value || null,
        week_id: document.getElementById('kgWeek').value || null,
        scenario_id: document.getElementById('kgScenario').value || null,
        scope: {
          site: document.getElementById('kgSite').value || null,
        },
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      graphSummary.innerHTML = renderScalarBlock(`Knowledge Graph request failed (${res.status}).`);
      graphCanvas.innerHTML = '';
      return;
    }
    renderGraph(data);
  } catch (err) {
    graphSummary.innerHTML = renderScalarBlock(String(err));
    graphCanvas.innerHTML = '';
  } finally {
    graphBtn.disabled = false;
    graphBtn.textContent = 'Show Knowledge Graph';
  }
}

chatBtn.addEventListener('click', () => {
  submitChat();
});

chatClearBtn.addEventListener('click', () => {
  chatHistory = [];
  chatMessages = [];
  renderChatThread();
});

chatLlmEnabled.addEventListener('change', () => {
  setLlmControls();
});

chatLlmModel.addEventListener('change', () => {
  setLlmControls();
});

graphBtn.addEventListener('click', () => {
  submitKnowledgeGraph();
});

menuButtons.forEach((button) => {
  button.addEventListener('click', () => {
    activatePanel(button.dataset.panel);
  });
});

Array.from(document.querySelectorAll('.analytics-control-tab')).forEach((button) => {
  button.addEventListener('click', () => {
    const tabName = button.getAttribute('data-tab') || 'demand_supply';
    if (!INSIGHTS_TABS.includes(tabName)) {
      return;
    }
    insightsState.activeTab = tabName;
    activatePanel('insights');
    renderInsightsLanding();
  });
});

menuToggle.addEventListener('click', () => {
  const collapsed = !workspaceShell.classList.contains('menu-collapsed');
  setMenuCollapsed(collapsed);
});

chatQuestion.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    submitChat();
  }
});

document.getElementById('validateBtn').addEventListener('click', () => {
  activatePanel('validation');
  paneByPanel.validation.textContent = 'Running validation...';
  callApi('/api/validate', {
    week_id: document.getElementById('valWeek').value || null,
    scenario_id: document.getElementById('valScenario').value || null,
    scope: {
      site: document.getElementById('valSite').value || null,
      product: document.getElementById('valProduct').value || null,
    },
    focus_areas: ['master_data', 'bom', 'parameters', 'output_sanity'],
  });
});

document.getElementById('compareBtn').addEventListener('click', () => {
  activatePanel('comparison');
  paneByPanel.comparison.textContent = 'Running scenario comparison...';
  callApi('/api/compare', {
    week_id: document.getElementById('cmpWeek').value || null,
    base_scenario_id: document.getElementById('cmpBase').value || null,
    compare_scenario_id: document.getElementById('cmpCompare').value || null,
    scope: {
      site: document.getElementById('cmpSite').value || null,
    },
    metrics: ['unmet_demand', 'capacity_utilization', 'lateness'],
  });
});

document.getElementById('rootCauseBtn').addEventListener('click', () => {
  activatePanel('rootcause');
  paneByPanel.rootcause.textContent = 'Running root cause analysis...';
  callApi('/api/root-cause', {
    week_id: document.getElementById('rcWeek').value || null,
    scenario_id: document.getElementById('rcScenario').value || null,
    demand_id: document.getElementById('rcDemand').value || null,
    scope: {
      node: document.getElementById('rcNode').value || null,
    },
  });
});

loadLlmModels();
syncPanelFromUrl();
setMenuCollapsed(false);
renderChatThread();
renderInsightsLanding();

window.addEventListener('hashchange', syncPanelFromUrl);
window.addEventListener('popstate', syncPanelFromUrl);
