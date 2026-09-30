/**
 * SunburstChart Component
 * 
 * A D3-based sunburst chart showing hierarchical data:
 * Category → Status → Engineer
 */
import React, { useRef, useEffect, useState } from 'react';
import * as d3 from 'd3';
import './SunburstChart.css';

function SunburstChart({ 
  data, 
  width = 500, 
  height = 500,
  onCategoryClick,
  onEngineerClick 
}) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [tooltip, setTooltip] = useState({ visible: false, x: 0, y: 0, content: '' });

  useEffect(() => {
    if (!data || !data.categories || data.categories.length === 0 || !svgRef.current) {
      return;
    }

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const radius = Math.min(width, height) / 2;
    const innerRadius = radius * 0.18;

    // Create hierarchical structure for D3
    const hierarchyData = {
      name: 'Total',
      children: data.categories.map(cat => ({
        name: cat.name,
        category: cat.key,
        color: cat.color,
        children: cat.statuses.map(status => ({
          name: status.name,
          category: cat.key,
          status: status.key,
          color: status.color,
          children: status.engineers.map(eng => ({
            name: eng.name,
            value: eng.value,
            category: cat.key,
            status: status.key,
            engineer: eng.name,
            color: status.color
          }))
        }))
      }))
    };

    // Create hierarchy and partition layout
    const root = d3.hierarchy(hierarchyData)
      .sum(d => d.value || 0)
      .sort((a, b) => b.value - a.value);

    const partition = d3.partition()
      .size([2 * Math.PI, radius]);

    partition(root);

    // Create arc generator
    const arc = d3.arc()
      .startAngle(d => d.x0)
      .endAngle(d => d.x1)
      .padAngle(d => Math.min((d.x1 - d.x0) / 2, 0.005))
      .padRadius(radius / 2)
      .innerRadius(d => {
        if (d.depth === 0) return 0;
        if (d.depth === 1) return innerRadius;
        if (d.depth === 2) return innerRadius + (radius - innerRadius) * 0.33;
        return innerRadius + (radius - innerRadius) * 0.63;
      })
      .outerRadius(d => {
        if (d.depth === 0) return innerRadius;
        if (d.depth === 1) return innerRadius + (radius - innerRadius) * 0.33;
        if (d.depth === 2) return innerRadius + (radius - innerRadius) * 0.63;
        return radius - 2;
      });

    // Create main group
    const g = svg
      .attr('width', width)
      .attr('height', height)
      .append('g')
      .attr('transform', `translate(${width / 2},${height / 2})`);

    // Draw arcs
    g.selectAll('path')
      .data(root.descendants().filter(d => d.depth > 0))
      .join('path')
      .attr('d', arc)
      .attr('fill', d => {
        if (d.depth === 1) return d.data.color;
        if (d.depth === 2) return d.data.color;
        if (d.depth === 3) {
          // Lighter version of the color
          const color = d3.color(d.data.color);
          return color ? color.brighter(0.5).toString() : '#ccc';
        }
        return '#ccc';
      })
      .attr('fill-opacity', d => d.depth === 3 ? 0.8 : 1)
      .attr('stroke', '#fff')
      .attr('stroke-width', d => d.depth === 1 ? 2 : 1)
      .style('cursor', 'pointer')
      .on('mouseenter', function(event, d) {
        d3.select(this).attr('fill-opacity', 0.6);
        
        let content = '';
        if (d.depth === 1) {
          content = `<strong>${d.data.name}</strong><br/>${d.value} tasks`;
        } else if (d.depth === 2) {
          content = `<strong>${d.parent.data.name} → ${d.data.name}</strong><br/>${d.value} tasks`;
        } else if (d.depth === 3) {
          content = `<strong>${d.data.name}</strong><br/>${d.parent.parent.data.name} → ${d.parent.data.name}<br/>${d.value} tasks`;
        }
        
        const rect = containerRef.current?.getBoundingClientRect();
        if (rect) {
          setTooltip({ 
            visible: true, 
            x: event.clientX - rect.left + 10, 
            y: event.clientY - rect.top - 10, 
            content 
          });
        }
      })
      .on('mouseleave', function(event, d) {
        d3.select(this).attr('fill-opacity', d.depth === 3 ? 0.8 : 1);
        setTooltip({ visible: false, x: 0, y: 0, content: '' });
      })
      .on('click', function(event, d) {
        if (d.depth === 1 && onCategoryClick) {
          onCategoryClick(d.data.category);
        } else if (d.depth === 2 && onCategoryClick) {
          onCategoryClick(d.data.category);
        } else if (d.depth === 3 && onEngineerClick) {
          onEngineerClick(d.data.engineer);
        }
      });

    // Add labels for segments with enough space
    const labelArc = d3.arc()
      .startAngle(d => d.x0)
      .endAngle(d => d.x1)
      .innerRadius(d => {
        if (d.depth === 1) return innerRadius + (radius - innerRadius) * 0.16;
        if (d.depth === 2) return innerRadius + (radius - innerRadius) * 0.47;
        return innerRadius + (radius - innerRadius) * 0.77;
      })
      .outerRadius(d => {
        if (d.depth === 1) return innerRadius + (radius - innerRadius) * 0.16;
        if (d.depth === 2) return innerRadius + (radius - innerRadius) * 0.47;
        return innerRadius + (radius - innerRadius) * 0.77;
      });

    // Helper to check if label fits
    const labelFits = (d) => {
      const angle = d.x1 - d.x0;
      if (d.depth === 1) return angle > 0.4;
      if (d.depth === 2) return angle > 0.25;
      return angle > 0.18;
    };

    // Helper to truncate text
    const truncateText = (text, maxLen) => {
      if (!text) return '';
      if (text.length <= maxLen) return text;
      return text.substring(0, maxLen - 2) + '..';
    };

    // Add text labels
    g.selectAll('text.arc-label')
      .data(root.descendants().filter(d => d.depth > 0 && labelFits(d)))
      .join('text')
      .attr('class', 'arc-label')
      .attr('transform', d => {
        const centroid = labelArc.centroid(d);
        const angle = (d.x0 + d.x1) / 2;
        const rotation = (angle * 180 / Math.PI) - 90;
        const flip = angle > Math.PI;
        return `translate(${centroid[0]},${centroid[1]}) rotate(${flip ? rotation + 180 : rotation})`;
      })
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('fill', d => {
        const color = d3.color(d.data.color);
        if (!color) return '#333';
        const hsl = d3.hsl(color);
        return hsl.l < 0.55 ? '#fff' : '#333';
      })
      .attr('font-size', d => {
        if (d.depth === 1) return '11px';
        if (d.depth === 2) return '10px';
        return '9px';
      })
      .attr('font-weight', d => d.depth === 1 ? '600' : '500')
      .attr('pointer-events', 'none')
      .text(d => {
        const maxLen = d.depth === 1 ? 10 : d.depth === 2 ? 8 : 7;
        return truncateText(d.data.name, maxLen);
      });

    // Add center text
    g.append('text')
      .attr('class', 'center-value')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('fill', 'var(--text-primary, #333)')
      .attr('font-size', '26px')
      .attr('font-weight', '700')
      .text(data.total);

    g.append('text')
      .attr('class', 'center-label')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('fill', 'var(--text-muted, #666)')
      .attr('font-size', '10px')
      .attr('letter-spacing', '1px')
      .attr('y', 20)
      .text('TASKS');

  }, [data, width, height, onCategoryClick, onEngineerClick]);

  if (!data || data.total === 0) {
    return (
      <div className="sunburst-empty">
        <p>No data available</p>
      </div>
    );
  }

  return (
    <div className="sunburst-chart-container" ref={containerRef}>
      <svg ref={svgRef} />
      {tooltip.visible && (
        <div 
          className="sunburst-tooltip"
          style={{ 
            left: tooltip.x, 
            top: tooltip.y
          }}
          dangerouslySetInnerHTML={{ __html: tooltip.content }}
        />
      )}
    </div>
  );
}

export default SunburstChart;
