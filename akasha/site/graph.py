"""知识图谱页面生成。"""

from __future__ import annotations

from pathlib import Path

from .mkdocs_config import _extract_title


def _generate_graph_page(docs_dir: Path, link_map: dict[str, str]) -> bool:
    """扫描所有 wiki 页面，生成 AntV G6 交互式知识图谱页面。"""
    import hashlib
    import json
    import re

    wiki_dir = docs_dir / "wiki"
    if not wiki_dir.exists():
        return False

    # 收集节点和边
    nodes: dict[str, dict] = {}  # id → {name, category, url}
    edges: list[tuple[str, str]] = []

    for md_file in wiki_dir.rglob("*.md"):
        if md_file.name == "graph.md":
            continue
        title = _extract_title(md_file)
        node_id = _safe_id(title)

        # 类型 + 页面 URL
        rel = str(md_file.relative_to(wiki_dir))
        if rel.startswith("concepts"):
            category = "concept"
        elif rel.startswith("entities"):
            category = "entity"
        elif rel.startswith("articles"):
            category = "article"
        else:
            category = "other"

        # mkdocs URL: wiki/articles/xxx.md → wiki/articles/xxx/
        url_path = str(md_file.relative_to(docs_dir)).replace(".md", "/")
        nodes[node_id] = {"name": title, "category": category, "url": url_path}

        text = md_file.read_text(encoding="utf-8")

        # 从 frontmatter 提取 related
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = parts[1]
                for line in fm.split("\n"):
                    line = line.strip()
                    if line.startswith("related:"):
                        related_str = line[8:].strip().strip("[]")
                        for item in related_str.split(","):
                            item = item.strip().strip('"').strip("'")
                            if item:
                                target_id = _safe_id(item)
                                if target_id != node_id:
                                    nodes.setdefault(
                                        target_id,
                                        {"name": item, "category": "other", "url": ""},
                                    )
                                    edges.append((node_id, target_id))
                    elif line.startswith("- "):
                        item = line[2:].strip().strip('"').strip("'")
                        if item:
                            target_id = _safe_id(item)
                            if target_id != node_id:
                                nodes.setdefault(
                                    target_id,
                                    {"name": item, "category": "other", "url": ""},
                                )
                                edges.append((node_id, target_id))

        # 从正文提取 [[双链]]
        for m in re.finditer(r"\[\[([^\]]+)\]\]", text):
            ref_name = m.group(1).strip()
            ref_id = _safe_id(ref_name)
            if ref_id != node_id and ref_id:
                nodes.setdefault(
                    ref_id, {"name": ref_name, "category": "other", "url": ""}
                )
                edges.append((node_id, ref_id))

    if not nodes:
        return False

    edges = list(set(edges))

    # 构建 G6 数据
    color_map = {
        "article": "#4a9eff",
        "concept": "#10b981",
        "entity": "#f59e0b",
        "other": "#6b7280",
    }
    size_map = {"article": 40, "concept": 30, "entity": 30, "other": 20}

    g6_nodes = []
    for nid, info in nodes.items():
        cat = info["category"]
        label = info["name"] if len(info["name"]) <= 10 else info["name"][:8] + ".."
        g6_nodes.append(
            {
                "id": nid,
                "label": label,
                "fullName": info["name"],
                "category": cat,
                "url": info.get("url", ""),
                "size": size_map.get(cat, 20),
                "style": {
                    "fill": color_map.get(cat, "#6b7280"),
                    "stroke": "#fff",
                    "lineWidth": 2,
                },
                "labelCfg": {"style": {"fill": "#333", "fontSize": 11}},
            }
        )

    g6_edges = [{"source": s, "target": t} for s, t in edges]

    graph_data = json.dumps({"nodes": g6_nodes, "edges": g6_edges}, ensure_ascii=False)

    # 按类型分组构建侧边栏数据
    sidebar_data = {}
    for nid, info in nodes.items():
        cat = info["category"]
        if cat not in sidebar_data:
            sidebar_data[cat] = []
        sidebar_data[cat].append(
            {"id": nid, "name": info["name"], "url": info.get("url", "")}
        )

    sidebar_json = json.dumps(sidebar_data, ensure_ascii=False)

    cat_labels = {
        "article": "文章",
        "concept": "概念",
        "entity": "实体",
        "other": "其他",
    }

    html = f"""---
hide:
  - navigation
  - toc
---

# 知识图谱

{{% raw %}}

<div id="graph-app">
  <div id="sidebar">
    <div class="legend">
      <span class="dot" style="background:#4a9eff"></span> 文章
      <span class="dot" style="background:#10b981"></span> 概念
      <span class="dot" style="background:#f59e0b"></span> 实体
    </div>
    <div id="sidebar-list"></div>
    <div id="node-detail" style="display:none">
      <h3 id="detail-name"></h3>
      <p id="detail-category"></p>
      <a id="detail-link" href="#">查看页面 →</a>
    </div>
  </div>
  <div id="graph-container"></div>
</div>

<style>
#graph-app {{ display: flex; height: 70vh; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; margin: 1em 0; }}
#sidebar {{ width: 220px; border-right: 1px solid #e0e0e0; overflow-y: auto; padding: 12px; background: #fafafa; flex-shrink: 0; }}
#graph-container {{ flex: 1; background: #fff; }}
.legend {{ margin-bottom: 12px; font-size: 13px; }}
.dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 2px; margin-left: 8px; }}
.sidebar-group {{ margin-bottom: 12px; }}
.sidebar-group h4 {{ margin: 4px 0; font-size: 13px; color: #666; }}
.sidebar-item {{ padding: 4px 8px; margin: 2px 0; border-radius: 4px; cursor: pointer; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.sidebar-item:hover {{ background: #e8f0fe; }}
.sidebar-item.active {{ background: #4a9eff; color: #fff; }}
#node-detail {{ margin-top: 16px; padding-top: 12px; border-top: 1px solid #ddd; }}
#node-detail h3 {{ font-size: 14px; margin: 0 0 4px; }}
#node-detail p {{ font-size: 12px; color: #888; margin: 0 0 8px; }}
#node-detail a {{ font-size: 12px; }}
</style>

<script src="https://gw.alipayobjects.com/os/antv/pkg/_antv.g6-0.x/build/g6.js"></script>
<script src="https://unpkg.com/@antv/g6@4/dist/g6.min.js"></script>
<script>
document.addEventListener('DOMContentLoaded', function() {{
  var data = {graph_data};
  var sidebarData = {sidebar_json};
  var catLabels = {json.dumps(cat_labels, ensure_ascii=False)};

  var container = document.getElementById('graph-container');
  var width = container.offsetWidth || 800;
  var height = container.offsetHeight || 500;

  var graph = new G6.Graph({{
    container: 'graph-container',
    width: width,
    height: height,
    fitView: true,
    fitViewPadding: 40,
    animate: true,
    modes: {{
      default: ['drag-canvas', 'zoom-canvas', 'drag-node']
    }},
    layout: {{
      type: 'force',
      preventOverlap: true,
      nodeSpacing: 60,
      linkDistance: 150,
      nodeStrength: -200,
      edgeStrength: 0.3,
      alphaDecay: 0.02
    }},
    defaultEdge: {{
      style: {{ stroke: '#ccc', lineWidth: 1.5, endArrow: true }},
    }},
    nodeStateStyles: {{
      highlight: {{ stroke: '#f59e0b', lineWidth: 3, shadowBlur: 10, shadowColor: '#f59e0b' }},
      dim: {{ opacity: 0.3 }}
    }},
    edgeStateStyles: {{
      highlight: {{ stroke: '#f59e0b', lineWidth: 2 }},
      dim: {{ opacity: 0.15 }}
    }}
  }});

  graph.data(data);
  graph.render();

  // 点击节点 → 高亮关联 + 显示详情
  graph.on('node:click', function(e) {{
    highlightNode(e.item.getID());
  }});

  // 点击画布空白 → 清除高亮
  graph.on('canvas:click', function() {{
    clearHighlight();
  }});

  // 双击节点 → 跳转页面
  graph.on('node:dblclick', function(e) {{
    var model = e.item.getModel();
    if (model.url) window.location.href = '/' + model.url;
  }});

  function highlightNode(nodeId) {{
    clearHighlight();
    var item = graph.findById(nodeId);
    if (!item) return;
    graph.setItemState(item, 'highlight', true);
    // 高亮相邻节点和边
    var edges = graph.getEdges();
    var neighborIds = new Set();
    edges.forEach(function(edge) {{
      var src = edge.getSource().getID();
      var tgt = edge.getTarget().getID();
      if (src === nodeId || tgt === nodeId) {{
        graph.setItemState(edge, 'highlight', true);
        neighborIds.add(src);
        neighborIds.add(tgt);
      }} else {{
        graph.setItemState(edge, 'dim', true);
      }}
    }});
    graph.getNodes().forEach(function(node) {{
      var id = node.getID();
      if (id !== nodeId && !neighborIds.has(id)) {{
        graph.setItemState(node, 'dim', true);
      }}
    }});
    // 更新详情面板
    var model = item.getModel();
    document.getElementById('node-detail').style.display = 'block';
    document.getElementById('detail-name').textContent = model.fullName;
    document.getElementById('detail-category').textContent = catLabels[model.category] || model.category;
    var link = document.getElementById('detail-link');
    if (model.url) {{ link.href = '/' + model.url; link.style.display = 'inline'; }}
    else {{ link.style.display = 'none'; }}
    // 侧边栏高亮
    document.querySelectorAll('.sidebar-item').forEach(function(el) {{
      el.classList.toggle('active', el.dataset.id === nodeId);
    }});
  }}

  function clearHighlight() {{
    graph.getNodes().forEach(function(n) {{ graph.clearItemStates(n); }});
    graph.getEdges().forEach(function(e) {{ graph.clearItemStates(e); }});
    document.getElementById('node-detail').style.display = 'none';
    document.querySelectorAll('.sidebar-item.active').forEach(function(el) {{ el.classList.remove('active'); }});
  }}

  // 构建侧边栏
  var listEl = document.getElementById('sidebar-list');
  ['article', 'concept', 'entity', 'other'].forEach(function(cat) {{
    var items = sidebarData[cat];
    if (!items || !items.length) return;
    var group = document.createElement('div');
    group.className = 'sidebar-group';
    group.innerHTML = '<h4>' + (catLabels[cat] || cat) + ' (' + items.length + ')</h4>';
    items.forEach(function(item) {{
      var el = document.createElement('div');
      el.className = 'sidebar-item';
      el.textContent = item.name;
      el.dataset.id = item.id;
      el.onclick = function() {{ highlightNode(item.id); graph.focusItem(item.id, true); }};
      group.appendChild(el);
    }});
    listEl.appendChild(group);
  }});

  // 窗口大小变化
  window.addEventListener('resize', function() {{
    if (graph && !graph.get('destroyed')) {{
      graph.changeSize(container.offsetWidth, container.offsetHeight);
    }}
  }});
}});
</script>

<small>{len(g6_nodes)} 个节点 · {len(g6_edges)} 条关联</small>
{{% endraw %}}
"""

    graph_path = wiki_dir / "graph.md"
    graph_path.write_text(html, encoding="utf-8")
    return True


def _safe_id(name: str) -> str:
    """生成短哈希 ID。"""
    import hashlib
    import re

    clean = re.sub(r"\s+", "", name.strip().lower())
    h = hashlib.md5(clean.encode()).hexdigest()[:8]
    return f"n{h}"
