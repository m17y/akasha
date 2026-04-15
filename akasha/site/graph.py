"""知识图谱页面生成。"""

from __future__ import annotations

from pathlib import Path

from .mkdocs_config import _extract_title


def _ensure_g6_js(docs_dir: Path) -> None:
    """确保 G6 JS 文件存在于 docs/assets/js/ 下。"""
    js_dir = docs_dir / "assets" / "js"
    js_file = js_dir / "g6.min.js"
    if js_file.exists():
        return

    js_dir.mkdir(parents=True, exist_ok=True)
    try:
        import urllib.request

        print("[graph] 下载 AntV G6...")
        urllib.request.urlretrieve(
            "https://unpkg.com/@antv/g6@4/dist/g6.min.js",
            str(js_file),
        )
    except Exception as e:
        print(f"[graph] G6 下载失败: {e}，图谱可能无法显示")


def _generate_graph_page(docs_dir: Path, link_map: dict[str, str]) -> bool:
    """扫描所有 wiki 页面，生成 AntV G6 交互式知识图谱页面。"""
    import hashlib
    import json
    import re

    wiki_dir = docs_dir / "wiki"
    if not wiki_dir.exists():
        return False

    _ensure_g6_js(docs_dir)

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

    # 用字符串拼接而非 f-string，避免 JS 花括号与 Python/Jinja2 冲突
    cat_labels_json = json.dumps(cat_labels, ensure_ascii=False)
    stats = f"{len(g6_nodes)} 个节点 · {len(g6_edges)} 条关联"

    html = (
        "---\nhide:\n  - navigation\n  - toc\n---\n\n"
        "# 知识图谱\n\n"
        '<div id="graph-app">\n'
        '  <div id="sidebar">\n'
        '    <div class="legend">\n'
        '      <span class="dot" style="background:#4a9eff"></span> 文章\n'
        '      <span class="dot" style="background:#10b981"></span> 概念\n'
        '      <span class="dot" style="background:#f59e0b"></span> 实体\n'
        "    </div>\n"
        '    <div id="sidebar-list"></div>\n'
        '    <div id="node-detail" style="display:none">\n'
        '      <h3 id="detail-name"></h3>\n'
        '      <p id="detail-category"></p>\n'
        '      <a id="detail-link" href="#">查看页面 →</a>\n'
        "    </div>\n"
        "  </div>\n"
        '  <div id="graph-container"></div>\n'
        "</div>\n\n"
        "<style>\n"
        "#graph-app { display: flex; height: 70vh; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; margin: 1em 0; }\n"
        "#sidebar { width: 220px; border-right: 1px solid #e0e0e0; overflow-y: auto; padding: 12px; background: #fafafa; flex-shrink: 0; }\n"
        "#graph-container { flex: 1; background: #fff; }\n"
        ".legend { margin-bottom: 12px; font-size: 13px; }\n"
        ".dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 2px; margin-left: 8px; }\n"
        ".sidebar-group { margin-bottom: 12px; }\n"
        ".sidebar-group h4 { margin: 4px 0; font-size: 13px; color: #666; }\n"
        ".sidebar-item { padding: 4px 8px; margin: 2px 0; border-radius: 4px; cursor: pointer; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }\n"
        ".sidebar-item:hover { background: #e8f0fe; }\n"
        ".sidebar-item.active { background: #4a9eff; color: #fff; }\n"
        "#node-detail { margin-top: 16px; padding-top: 12px; border-top: 1px solid #ddd; }\n"
        "#node-detail h3 { font-size: 14px; margin: 0 0 4px; }\n"
        "#node-detail p { font-size: 12px; color: #888; margin: 0 0 8px; }\n"
        "#node-detail a { font-size: 12px; }\n"
        "</style>\n\n"
        '<script src="/assets/js/g6.min.js"></script>\n'
        "<script>\n"
        "document.addEventListener('DOMContentLoaded', function() {\n"
        "  var data = " + graph_data + ";\n"
        "  var sidebarData = " + sidebar_json + ";\n"
        "  var catLabels = " + cat_labels_json + ";\n"
        "\n"
        "  var container = document.getElementById('graph-container');\n"
        "  var width = container.offsetWidth || 800;\n"
        "  var height = container.offsetHeight || 500;\n"
        "\n"
        "  var graph = new G6.Graph({\n"
        "    container: 'graph-container',\n"
        "    width: width, height: height,\n"
        "    fitView: true, fitViewPadding: 40, animate: true,\n"
        "    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },\n"
        "    layout: { type: 'force', preventOverlap: true, nodeSpacing: 60, linkDistance: 150, nodeStrength: -200, edgeStrength: 0.3, alphaDecay: 0.02 },\n"
        "    defaultEdge: { style: { stroke: '#ccc', lineWidth: 1.5, endArrow: true } },\n"
        "    nodeStateStyles: { highlight: { stroke: '#f59e0b', lineWidth: 3, shadowBlur: 10, shadowColor: '#f59e0b' }, dim: { opacity: 0.3 } },\n"
        "    edgeStateStyles: { highlight: { stroke: '#f59e0b', lineWidth: 2 }, dim: { opacity: 0.15 } }\n"
        "  });\n"
        "  graph.data(data);\n"
        "  graph.render();\n"
        "\n"
        "  graph.on('node:click', function(e) { highlightNode(e.item.getID()); });\n"
        "  graph.on('canvas:click', function() { clearHighlight(); });\n"
        "  graph.on('node:dblclick', function(e) { var m = e.item.getModel(); if (m.url) window.location.href = '/' + m.url; });\n"
        "\n"
        "  function highlightNode(nodeId) {\n"
        "    clearHighlight();\n"
        "    var item = graph.findById(nodeId);\n"
        "    if (!item) return;\n"
        "    graph.setItemState(item, 'highlight', true);\n"
        "    var edges = graph.getEdges();\n"
        "    var neighborIds = new Set();\n"
        "    edges.forEach(function(edge) {\n"
        "      var src = edge.getSource().getID(), tgt = edge.getTarget().getID();\n"
        "      if (src === nodeId || tgt === nodeId) { graph.setItemState(edge, 'highlight', true); neighborIds.add(src); neighborIds.add(tgt); }\n"
        "      else { graph.setItemState(edge, 'dim', true); }\n"
        "    });\n"
        "    graph.getNodes().forEach(function(node) { var id = node.getID(); if (id !== nodeId && !neighborIds.has(id)) graph.setItemState(node, 'dim', true); });\n"
        "    var model = item.getModel();\n"
        "    document.getElementById('node-detail').style.display = 'block';\n"
        "    document.getElementById('detail-name').textContent = model.fullName;\n"
        "    document.getElementById('detail-category').textContent = catLabels[model.category] || model.category;\n"
        "    var link = document.getElementById('detail-link');\n"
        "    if (model.url) { link.href = '/' + model.url; link.style.display = 'inline'; } else { link.style.display = 'none'; }\n"
        "    document.querySelectorAll('.sidebar-item').forEach(function(el) { el.classList.toggle('active', el.dataset.id === nodeId); });\n"
        "  }\n"
        "\n"
        "  function clearHighlight() {\n"
        "    graph.getNodes().forEach(function(n) { graph.clearItemStates(n); });\n"
        "    graph.getEdges().forEach(function(e) { graph.clearItemStates(e); });\n"
        "    document.getElementById('node-detail').style.display = 'none';\n"
        "    document.querySelectorAll('.sidebar-item.active').forEach(function(el) { el.classList.remove('active'); });\n"
        "  }\n"
        "\n"
        "  var listEl = document.getElementById('sidebar-list');\n"
        "  ['article', 'concept', 'entity', 'other'].forEach(function(cat) {\n"
        "    var items = sidebarData[cat]; if (!items || !items.length) return;\n"
        "    var group = document.createElement('div'); group.className = 'sidebar-group';\n"
        "    group.innerHTML = '<h4>' + (catLabels[cat] || cat) + ' (' + items.length + ')</h4>';\n"
        "    items.forEach(function(item) {\n"
        "      var el = document.createElement('div'); el.className = 'sidebar-item';\n"
        "      el.textContent = item.name; el.dataset.id = item.id;\n"
        "      el.onclick = function() { highlightNode(item.id); graph.focusItem(item.id, true); };\n"
        "      group.appendChild(el);\n"
        "    });\n"
        "    listEl.appendChild(group);\n"
        "  });\n"
        "\n"
        "  window.addEventListener('resize', function() { if (graph && !graph.get('destroyed')) graph.changeSize(container.offsetWidth, container.offsetHeight); });\n"
        "});\n"
        "</script>\n\n"
        "<small>" + stats + "</small>\n"
    )

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
