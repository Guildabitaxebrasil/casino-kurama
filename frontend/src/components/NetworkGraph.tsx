import { useRef, useEffect, useState } from 'react';
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force';
import { select } from 'd3-selection';
import { drag } from 'd3-drag';
import type { NodeInfo } from '../api/types';
import LoadingSpinner from './LoadingSpinner';

interface Props {
  nodes: NodeInfo[];
  loading: boolean;
}

interface GraphNode {
  id: string;
  label: string;
  status: 'active' | 'syncing' | 'inactive';
  url: string;
  chain_length: number;
  pending_tx: number;
  latency_ms: number | null;
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
  vx?: number;
  vy?: number;
}

interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
}

const NODE_RADIUS = 28;

function getNodeStatus(node: NodeInfo): 'active' | 'syncing' | 'inactive' {
  if (!node.active) return 'inactive';
  if ((node.difficulty || 0) > 0) return 'syncing';
  return 'active';
}

function getStatusColor(status: string): string {
  if (status === 'active') return '#3fb950';
  if (status === 'syncing') return '#d29922';
  return '#f85149';
}

function getStatusLabel(status: string): string {
  if (status === 'active') return 'Ativo';
  if (status === 'syncing') return 'Sincronizando';
  return 'Inativo';
}

export default function NetworkGraph({ nodes, loading }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<{ node: GraphNode; x: number; y: number } | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 });

  useEffect(() => {
    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      setDimensions({ width: rect.width || 800, height: 500 });
    }
  }, []);

  const graphNodes: GraphNode[] = nodes.map(n => ({
    id: n.node_id,
    label: n.node_id.slice(0, 6),
    status: getNodeStatus(n),
    url: n.url,
    chain_length: n.blocks || 0,
    pending_tx: 0,
    latency_ms: n.latency_ms,
  }));

  // Create a complete graph (every node connected to every other)
  const graphLinks: GraphLink[] = [];
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      graphLinks.push({ source: nodes[i].node_id, target: nodes[j].node_id });
    }
  }

  const { width, height } = dimensions;

  return (
    <div ref={containerRef} className="relative" style={{ height }}>
      {loading && (
        <div className="absolute inset-0 bg-kur-bg/60 flex items-center justify-center z-10 rounded-lg">
          <LoadingSpinner />
        </div>
      )}

      {nodes.length === 0 && !loading && (
        <div className="flex items-center justify-center h-full text-kur-text-muted">
          <div className="text-center">
            <p className="text-lg mb-2">Nenhum nó conectado</p>
            <p className="text-sm">Registre nós para visualizar a rede P2P</p>
          </div>
        </div>
      )}

      {nodes.length === 1 && !loading && (
        <div className="flex items-center justify-center h-full">
          <div className="text-center">
            <div
              className="w-16 h-16 rounded-full mx-auto mb-3 flex items-center justify-center text-xs font-mono font-bold"
              style={{
                backgroundColor: `${getStatusColor(getNodeStatus(nodes[0]))}20`,
                border: `2px solid ${getStatusColor(getNodeStatus(nodes[0]))}`,
                color: getStatusColor(getNodeStatus(nodes[0])),
              }}
            >
              {nodes[0].node_id.slice(0, 4)}
            </div>
            <p className="text-kur-text text-sm font-mono">{nodes[0].node_id.slice(0, 16)}...</p>
            <p className="text-kur-text-muted text-xs mt-1">Único nó na rede</p>
            <p className="text-kur-text-muted text-xs">Conecte mais nós para formar a rede P2P</p>
          </div>
        </div>
      )}

      {nodes.length >= 2 && (
        <GraphCanvas
          graphNodes={graphNodes}
          graphLinks={graphLinks}
          width={width}
          height={height}
          onHover={(data) => setTooltip(data)}
          onLeave={() => setTooltip(null)}
        />
      )}

      {tooltip && (
        <div
          className="absolute z-20 bg-kur-bg-card border border-kur-border rounded-lg p-3 text-xs pointer-events-none shadow-xl"
          style={{ left: tooltip.x + 15, top: tooltip.y - 80, minWidth: 200 }}
        >
          <p className="font-bold text-kur-accent mb-1 font-mono">{tooltip.node.id.slice(0, 16)}...</p>
          <div className="space-y-1 text-kur-text">
            <p><span className="text-kur-text-muted">URL:</span> {tooltip.node.url}</p>
            <p><span className="text-kur-text-muted">Status:</span>{' '}
              <span style={{ color: getStatusColor(tooltip.node.status) }}>{getStatusLabel(tooltip.node.status)}</span>
            </p>
            <p><span className="text-kur-text-muted">Blocos:</span> {tooltip.node.chain_length}</p>
            {tooltip.node.pending_tx > 0 && (
              <p><span className="text-kur-text-muted">Pendentes:</span> {tooltip.node.pending_tx}</p>
            )}
            <p><span className="text-kur-text-muted">Latência:</span> {tooltip.node.latency_ms ?? 'N/A'}ms</p>
          </div>
        </div>
      )}
    </div>
  );
}

function GraphCanvas({
  graphNodes, graphLinks, width, height, onHover, onLeave,
}: {
  graphNodes: GraphNode[];
  graphLinks: GraphLink[];
  width: number;
  height: number;
  onHover: (data: { node: GraphNode; x: number; y: number } | null) => void;
  onLeave: () => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current) return;

    const svg = select(svgRef.current);

    const simulation = forceSimulation(graphNodes as any)
      .force('link', forceLink(graphLinks as any).id((d: any) => d.id).distance(120))
      .force('charge', forceManyBody().strength(-350))
      .force('center', forceCenter(width / 2, height / 2))
      .force('collide', forceCollide(NODE_RADIUS + 10));

    // Draw links
    const linkElements = svg
      .append('g')
      .selectAll('line')
      .data(graphLinks)
      .enter()
      .append('line')
      .attr('stroke', '#30363d')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.5);

    // Draw nodes
    const nodeGroup = svg.append('g');
    const nodeElements = nodeGroup
      .selectAll('g')
      .data(graphNodes)
      .enter()
      .append('g')
      .style('cursor', 'pointer')
      .on('mouseover', (event: any, d: any) => {
        const rect = svgRef.current!.getBoundingClientRect();
        onHover({ node: d, x: event.clientX - rect.left, y: event.clientY - rect.top });
      })
      .on('mouseout', () => onLeave());

    // Node circles
    nodeElements
      .append('circle')
      .attr('r', NODE_RADIUS)
      .attr('fill', (d: any) => `${getStatusColor(d.status)}20`)
      .attr('stroke', (d: any) => getStatusColor(d.status))
      .attr('stroke-width', 2);

    // Node labels
    nodeElements
      .append('text')
      .text((d: any) => d.label)
      .attr('text-anchor', 'middle')
      .attr('dy', '0.35em')
      .attr('fill', '#e6edf3')
      .attr('font-size', '11px')
      .attr('font-family', 'monospace')
      .attr('font-weight', 'bold');

    // Pulse animation for active nodes
    nodeElements
      .filter((d: any) => d.status === 'active')
      .append('circle')
      .attr('r', NODE_RADIUS + 4)
      .attr('fill', 'none')
      .attr('stroke', '#3fb950')
      .attr('stroke-width', 2)
      .attr('stroke-opacity', 0.4)
      .append('animate')
      .attr('attributeName', 'r')
      .attr('values', `${NODE_RADIUS + 4};${NODE_RADIUS + 12};${NODE_RADIUS + 4}`)
      .attr('dur', '2s')
      .attr('repeatCount', 'indefinite');

    // Tick: update positions
    simulation.on('tick', () => {
      linkElements
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);

      nodeElements.attr('transform', (d: any) => `translate(${d.x},${d.y})`);
    });

    // Drag behavior
    const dragBehavior = drag<SVGGElement, GraphNode>()
      .on('start', (event: any, d: any) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event: any, d: any) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event: any, d: any) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeElements.call(dragBehavior as any);

    return () => {
      simulation.stop();
      svg.selectAll('*').remove();
    };
  }, [graphNodes, graphLinks, width, height, onHover, onLeave]);

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      className="bg-kur-bg rounded-lg"
      style={{ overflow: 'visible' }}
    />
  );
}
