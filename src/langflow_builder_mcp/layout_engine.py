"""Advanced layout engine for Langflow flows.

This module provides intelligent layout algorithms that create clean,
readable flow layouts with:
- Meaningful clusters of related components
- Clear pathways for connection lines
- Subway-map style visual hierarchy
- Pattern-specific layouts (agent, RAG, multi-tool)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict, Tuple
from collections import defaultdict


# =============================================================================
# Constants
# =============================================================================

# Node dimensions (Langflow standard)
DEFAULT_NODE_WIDTH = 384
DEFAULT_NODE_HEIGHT = 550

# Spacing constants for clean layouts
HORIZONTAL_GAP = 800  # Gap between horizontally adjacent nodes
VERTICAL_GAP = 600  # Gap between vertically stacked nodes
CLUSTER_GAP = 400  # Gap between nodes in same cluster
LANE_HEIGHT = 1000  # Vertical space for each horizontal "lane"
SUPPORT_OFFSET_Y = 700  # How far above/below main path for support nodes


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NodeInfo:
    """Essential info about a node for layout calculations."""
    id: str
    component_type: str
    display_name: str
    category: str  # input, output, agent, model, tool, memory, retriever, etc.
    x: float
    y: float
    width: float
    height: float
    incoming: List[str] = field(default_factory=list)
    outgoing: List[str] = field(default_factory=list)
    depth: int = 0
    cluster_id: Optional[str] = None


@dataclass
class Cluster:
    """A logical grouping of related nodes."""
    id: str
    name: str
    role: str  # "main_path", "tools", "memory", "retrieval", "processing"
    node_ids: List[str]
    anchor_node_id: Optional[str] = None  # Primary node in cluster (e.g., Agent)
    position: Tuple[float, float] = (0, 0)  # Cluster center position


@dataclass
class ConnectionPath:
    """Represents a connection line path for collision detection."""
    source_id: str
    target_id: str
    source_x: float
    source_y: float
    target_x: float
    target_y: float

    @property
    def danger_zone(self) -> Tuple[float, float, float, float]:
        """Return (x1, y1, x2, y2) bounding box of the bezier curve path.

        Bezier curves bulge outward, so we add padding.
        """
        x1 = self.source_x
        x2 = self.target_x
        y1 = min(self.source_y, self.target_y) - 50
        y2 = max(self.source_y, self.target_y) + 50
        return (x1, y1, x2, y2)

    def intersects_node(self, node: NodeInfo) -> bool:
        """Check if this connection path intersects with a node."""
        dz = self.danger_zone
        # Node boundaries
        nx1, ny1 = node.x, node.y
        nx2, ny2 = node.x + node.width, node.y + node.height

        # Check rectangle intersection
        return not (nx2 < dz[0] or nx1 > dz[2] or ny2 < dz[1] or ny1 > dz[3])


@dataclass
class LayoutResult:
    """Result of a layout operation."""
    positions: Dict[str, Tuple[float, float]]  # node_id -> (x, y)
    clusters: List[Cluster]
    main_path: List[str]
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# Node Categorization
# =============================================================================


def categorize_node(node: Dict[str, Any]) -> str:
    """Categorize a node by its role in the flow.

    Returns one of: 'input', 'output', 'agent', 'model', 'tool', 'memory',
    'retriever', 'embedding', 'processing', 'prompt', 'data', 'other'
    """
    node_data = node.get("data", {})
    node_config = node_data.get("node", {})
    component_type = (node_config.get("key") or node_data.get("type", "")).lower()
    display_name = (node_config.get("display_name") or "").lower()

    # Input/Output detection
    if "chatinput" in component_type or component_type == "input":
        return "input"
    if "chatoutput" in component_type or component_type == "output":
        return "output"
    if "textinput" in component_type:
        return "input"
    if "textoutput" in component_type:
        return "output"

    # Agent detection (high priority)
    if "agent" in component_type:
        return "agent"

    # Model detection
    if any(x in component_type for x in ["model", "openai", "anthropic", "groq",
                                          "ollama", "llm", "chatvertexai", "azurechat"]):
        return "model"

    # Tool detection
    if any(x in component_type for x in ["tool", "calculator", "websearch",
                                          "pythonrepl", "serpapi", "tavily"]):
        return "tool"

    # Memory detection
    if "memory" in component_type:
        return "memory"

    # Retriever/VectorStore detection
    if any(x in component_type for x in ["retriever", "vectorstore", "qdrant",
                                          "pinecone", "chroma", "weaviate", "astra"]):
        return "retriever"

    # Embedding detection
    if "embed" in component_type:
        return "embedding"

    # Prompt detection
    if "prompt" in component_type:
        return "prompt"

    # Data/Document processing
    if any(x in component_type for x in ["loader", "splitter", "parser",
                                          "document", "file", "url", "text"]):
        return "data"

    # Processing (transformers, etc.)
    if any(x in component_type for x in ["transform", "filter", "combine"]):
        return "processing"

    return "other"


def get_node_dimensions(node: Dict[str, Any]) -> Tuple[float, float]:
    """Get node width and height from stored values or defaults."""
    width = node.get("width")
    height = node.get("height")

    if width is None:
        measured = node.get("measured", {})
        width = measured.get("width")
    if height is None:
        measured = node.get("measured", {})
        height = measured.get("height")

    return (width or DEFAULT_NODE_WIDTH, height or DEFAULT_NODE_HEIGHT)


# =============================================================================
# Graph Analysis
# =============================================================================


def build_node_graph(nodes: List[Dict], edges: List[Dict]) -> Dict[str, NodeInfo]:
    """Build a graph representation from flow nodes and edges."""
    node_map: Dict[str, NodeInfo] = {}

    # Create NodeInfo for each node
    for node in nodes:
        if node.get("type") == "noteNode":
            continue  # Skip note nodes

        node_id = node.get("id")
        node_data = node.get("data", {})
        node_config = node_data.get("node", {})
        pos = node.get("position", {"x": 0, "y": 0})
        width, height = get_node_dimensions(node)

        component_type = node_config.get("key") or node_data.get("type", "")
        display_name = node_config.get("display_name", component_type)

        node_map[node_id] = NodeInfo(
            id=node_id,
            component_type=component_type,
            display_name=display_name,
            category=categorize_node(node),
            x=pos.get("x", 0),
            y=pos.get("y", 0),
            width=width,
            height=height,
        )

    # Add edge information
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in node_map and target in node_map:
            node_map[source].outgoing.append(target)
            node_map[target].incoming.append(source)

    # Calculate depths (distance from input nodes)
    _calculate_depths(node_map)

    return node_map


def _calculate_depths(node_map: Dict[str, NodeInfo]) -> None:
    """Calculate depth (distance from inputs) for each node."""
    # Find input nodes (no incoming edges)
    queue = [(nid, 0) for nid, info in node_map.items() if not info.incoming]
    visited = set()

    while queue:
        nid, depth = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        node_map[nid].depth = depth

        for target in node_map[nid].outgoing:
            if target not in visited:
                queue.append((target, depth + 1))

    # Assign depth 0 to any unvisited (isolated or cyclic)
    for nid, info in node_map.items():
        if nid not in visited:
            info.depth = 0


def find_main_path(node_map: Dict[str, NodeInfo]) -> List[str]:
    """Find the main data flow path from input to output.

    This is typically the longest path through "important" nodes
    (input -> agent/processing -> output).
    """
    # Find input nodes
    inputs = [nid for nid, info in node_map.items() if info.category == "input"]
    if not inputs:
        # Fall back to nodes with no incoming edges
        inputs = [nid for nid, info in node_map.items() if not info.incoming]

    if not inputs:
        return []

    # BFS to find longest path to output
    best_path: List[str] = []

    def find_path(start: str) -> List[str]:
        from collections import deque
        queue = deque([(start, [start])])
        longest = []

        while queue:
            current, path = queue.popleft()
            info = node_map.get(current)
            if not info:
                continue

            # Check if this is an output or terminal node
            if info.category == "output" or not info.outgoing:
                if len(path) > len(longest):
                    longest = path

            for next_node in info.outgoing:
                if next_node not in path:  # Avoid cycles
                    queue.append((next_node, path + [next_node]))

        return longest

    for inp in inputs:
        path = find_path(inp)
        if len(path) > len(best_path):
            best_path = path

    return best_path


# =============================================================================
# Cluster Detection
# =============================================================================


def detect_clusters(node_map: Dict[str, NodeInfo]) -> List[Cluster]:
    """Detect logical clusters of related nodes.

    Clustering rules:
    1. Each agent forms a cluster with its direct model, tools, and memory
    2. Retrieval components cluster together (embeddings + vectorstore)
    3. Data processing chains form clusters
    4. Input and Output nodes are their own clusters
    """
    clusters: List[Cluster] = []
    assigned: set = set()

    # 1. Find agent clusters (agent + model + tools + memory)
    for nid, info in node_map.items():
        if info.category == "agent" and nid not in assigned:
            cluster_nodes = [nid]
            assigned.add(nid)

            # Find nodes that connect TO the agent (models, tools, memory)
            for source_id in info.incoming:
                source = node_map.get(source_id)
                if source and source.category in ("model", "tool", "memory"):
                    cluster_nodes.append(source_id)
                    assigned.add(source_id)

            clusters.append(Cluster(
                id=f"agent-cluster-{nid}",
                name=f"{info.display_name} Cluster",
                role="agent",
                node_ids=cluster_nodes,
                anchor_node_id=nid,
            ))

    # 2. Find retrieval clusters (embeddings + vectorstore + retriever)
    for nid, info in node_map.items():
        if info.category == "retriever" and nid not in assigned:
            cluster_nodes = [nid]
            assigned.add(nid)

            # Find connected embeddings
            for source_id in info.incoming:
                source = node_map.get(source_id)
                if source and source.category == "embedding":
                    cluster_nodes.append(source_id)
                    assigned.add(source_id)

            clusters.append(Cluster(
                id=f"retrieval-cluster-{nid}",
                name="Retrieval Cluster",
                role="retrieval",
                node_ids=cluster_nodes,
                anchor_node_id=nid,
            ))

    # 3. Input cluster
    input_nodes = [nid for nid, info in node_map.items()
                   if info.category == "input" and nid not in assigned]
    if input_nodes:
        for nid in input_nodes:
            assigned.add(nid)
        clusters.append(Cluster(
            id="input-cluster",
            name="Inputs",
            role="input",
            node_ids=input_nodes,
            anchor_node_id=input_nodes[0],
        ))

    # 4. Output cluster
    output_nodes = [nid for nid, info in node_map.items()
                    if info.category == "output" and nid not in assigned]
    if output_nodes:
        for nid in output_nodes:
            assigned.add(nid)
        clusters.append(Cluster(
            id="output-cluster",
            name="Outputs",
            role="output",
            node_ids=output_nodes,
            anchor_node_id=output_nodes[0],
        ))

    # 5. Data processing cluster
    data_nodes = [nid for nid, info in node_map.items()
                  if info.category in ("data", "processing", "prompt") and nid not in assigned]
    if data_nodes:
        for nid in data_nodes:
            assigned.add(nid)
        clusters.append(Cluster(
            id="data-cluster",
            name="Data Processing",
            role="processing",
            node_ids=data_nodes,
            anchor_node_id=data_nodes[0] if data_nodes else None,
        ))

    # 6. Remaining nodes get their own cluster
    remaining = [nid for nid in node_map if nid not in assigned]
    if remaining:
        clusters.append(Cluster(
            id="other-cluster",
            name="Other Components",
            role="other",
            node_ids=remaining,
            anchor_node_id=remaining[0] if remaining else None,
        ))

    return clusters


# =============================================================================
# Line Collision Detection & Resolution
# =============================================================================


def find_line_collisions(
    positions: Dict[str, Tuple[float, float]],
    node_map: Dict[str, NodeInfo],
    edges: List[Dict],
) -> List[Dict[str, Any]]:
    """Find nodes that are blocking connection lines.

    Returns list of collision info with suggestions for fixing.
    """
    collisions = []

    # Build connection paths
    paths: List[ConnectionPath] = []
    for edge in edges:
        src_id = edge.get("source")
        tgt_id = edge.get("target")

        if src_id not in positions or tgt_id not in positions:
            continue
        if src_id not in node_map or tgt_id not in node_map:
            continue

        src_info = node_map[src_id]
        tgt_info = node_map[tgt_id]
        src_pos = positions[src_id]
        tgt_pos = positions[tgt_id]

        # Connection exits from right edge of source, enters left edge of target
        paths.append(ConnectionPath(
            source_id=src_id,
            target_id=tgt_id,
            source_x=src_pos[0] + src_info.width + 7,
            source_y=src_pos[1] + src_info.height / 2,
            target_x=tgt_pos[0] - 7,
            target_y=tgt_pos[1] + tgt_info.height / 2,
        ))

    # Check each node against each path
    for path in paths:
        for nid, info in node_map.items():
            if nid == path.source_id or nid == path.target_id:
                continue

            # Update node position for checking
            if nid in positions:
                info.x, info.y = positions[nid]

            if path.intersects_node(info):
                dz = path.danger_zone
                collisions.append({
                    "node_id": nid,
                    "node_name": info.display_name,
                    "blocks_connection": f"{path.source_id} → {path.target_id}",
                    "node_y_range": (info.y, info.y + info.height),
                    "line_y_range": (dz[1], dz[3]),
                    "suggestion": f"Move above y={dz[1] - info.height - 50:.0f} or below y={dz[3] + 50:.0f}",
                })

    return collisions


# =============================================================================
# Layout Analysis & Scoring
# =============================================================================


def score_layout(
    positions: Dict[str, Tuple[float, float]],
    node_map: Dict[str, NodeInfo],
    edges: List[Dict],
) -> Dict[str, Any]:
    """Score a layout based on clarity metrics.

    Returns scores for:
    - line_crossings: Number of connection lines that cross
    - node_overlaps: Number of nodes that overlap
    - line_collisions: Number of nodes blocking lines
    - horizontal_flow: How well left-to-right ordering is maintained
    - spacing_consistency: How consistent spacing is
    """
    scores = {
        "line_crossings": 0,
        "node_overlaps": 0,
        "line_collisions": 0,
        "horizontal_flow_violations": 0,
        "overall_score": 100,
    }

    # Count line collisions
    collisions = find_line_collisions(positions, node_map, edges)
    scores["line_collisions"] = len(collisions)

    # Count node overlaps
    node_list = list(node_map.values())
    for i, n1 in enumerate(node_list):
        if n1.id not in positions:
            continue
        x1, y1 = positions[n1.id]
        for n2 in node_list[i+1:]:
            if n2.id not in positions:
                continue
            x2, y2 = positions[n2.id]

            # Check rectangle overlap
            if (x1 < x2 + n2.width and x1 + n1.width > x2 and
                y1 < y2 + n2.height and y1 + n1.height > y2):
                scores["node_overlaps"] += 1

    # Check horizontal flow (source should be left of target)
    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src in positions and tgt in positions:
            if positions[src][0] >= positions[tgt][0]:
                scores["horizontal_flow_violations"] += 1

    # Calculate overall score (start at 100, deduct for issues)
    scores["overall_score"] = max(0, 100
        - scores["line_collisions"] * 10
        - scores["node_overlaps"] * 20
        - scores["horizontal_flow_violations"] * 5
    )

    return scores
