/**
 * DrillDownSunburst Component
 * 
 * Unified interactive sunburst chart:
 * - Initial view: Category (inner) → Status (outer)
 * - Click Category: drills to Status → Engineer
 * - Click Engineer segment: shows that engineer's Category → Status breakdown
 * - Always shows contextual drill-down based on what you click
 */
import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import * as d3 from 'd3';
import './DrillDownSunburst.css';

function DrillDownSunburst({ 
  data, 
  width = 450, 
  height = 450,
  onCategoryClick,
  onEngineerClick 
}) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [tooltip, setTooltip] = useState({ visible: false, x: 0, y: 0, content: '' });
  const [drillState, setDrillState] = useState({ type: 'overview' }); // overview, category, engineer
  const [breadcrumb, setBreadcrumb] = useState([{ label: 'Overview', type: 'overview' }]);

  // Pre-compute engineer data for quick lookup
  const engineerData = useMemo(() => {
    if (!data || !data.categories) return {};

    const engineers = {};
    const colorScale = d3.scaleOrdinal(d3.schemeTableau10);
    let engineerIndex = 0;
    
    data.categories.forEach(cat => {
      cat.statuses.forEach(status => {
        status.engineers.forEach(eng => {
          if (!engineers[eng.name]) {
            engineers[eng.name] = {
              name: eng.name,
              color: colorScale(engineerIndex++),
              categories: {},
              total: 0
            };
          }
          if (!engineers[eng.name].categories[cat.key]) {
            engineers[eng.name].categories[cat.key] = {
              key: cat.key,
              name: cat.name,
              color: cat.color,
              statuses: {}
            };
          }
          if (!engineers[eng.name].categories[cat.key].statuses[status.key]) {
            engineers[eng.name].categories[cat.key].statuses[status.key] = {
              key: status.key,
              name: status.name,
              color: status.color,
              count: 0
            };
          }
          engineers[eng.name].categories[cat.key].statuses[status.key].count += eng.value;
          engineers[eng.name].total += eng.value;
        });
      });
    });

    return engineers;
  }, [data]);

  const resetView = useCallback(() => {
    setDrillState({ type: 'overview' });
    setBreadcrumb([{ label: 'Overview', type: 'overview' }]);
  }, []);

  const drawChart = useCallback(() => {
    if (!data || !data.categories || data.categories.length === 0 || !svgRef.current) {
      return;
    }

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const radius = Math.min(width, height) / 2;
    const innerRadius = radius * 0.22;

    let hierarchyData;
    let ringConfig;
    let viewTitle = '';

    if (drillState.type === 'overview') {
      // Overview: Category → Status (2 levels)
      hierarchyData = {
        name: 'Total',
        children: data.categories.map(cat => ({
          name: cat.name,
          key: cat.key,
          color: cat.color,
          itemType: 'category',
          children: cat.statuses
            .filter(status => status.engineers.reduce((sum, e) => sum + e.value, 0) > 0)
            .map(status => ({
              name: status.name,
              key: status.key,
              color: status.color,
              itemType: 'status',
              categoryKey: cat.key,
              categoryName: cat.name,
              value: status.engineers.reduce((sum, e) => sum + e.value, 0)
            }))
        })).filter(cat => cat.children.length > 0)
      };
      ringConfig = { levels: 2 };
      viewTitle = 'All Categories';
    } else if (drillState.type === 'category') {
      // Category drill: Status → Engineer (2 levels)
      const category = data.categories.find(c => c.key === drillState.categoryKey);
      if (!category) return;

      hierarchyData = {
        name: category.name,
        color: category.color,
        children: category.statuses
          .filter(status => status.engineers.length > 0 && status.engineers.some(e => e.value > 0))
          .map(status => ({
            name: status.name,
            key: status.key,
            color: status.color,
            itemType: 'status',
            children: status.engineers
              .filter(eng => eng.value > 0)
              .map(eng => ({
                name: eng.name,
                value: eng.value,
                itemType: 'engineer',
                color: d3.color(status.color).brighter(0.4).toString()
              }))
          })).filter(status => status.children && status.children.length > 0)
      };
      ringConfig = { levels: 2 };
      viewTitle = category.name;
    } else if (drillState.type === 'engineer') {
      // Engineer drill: Category → Status (shows what this engineer works on)
      const engineer = engineerData[drillState.engineerName];
      if (!engineer) return;

      const categories = Object.values(engineer.categories);
      
      hierarchyData = {
        name: engineer.name,
        color: engineer.color,
        children: categories.map(cat => ({
          name: cat.name,
          key: cat.key,
          color: cat.color,
          itemType: 'category',
          children: Object.values(cat.statuses)
            .filter(s => s.count > 0)
            .map(status => ({
              name: status.name,
              key: status.key,
              color: status.color,
              itemType: 'status',
              value: status.count
            }))
        })).filter(cat => cat.children.length > 0)
      };
      ringConfig = { levels: 2 };
      viewTitle = engineer.name;
    }

    if (!hierarchyData || !hierarchyData.children || hierarchyData.children.length === 0) {
      // No data for this view
      const g = svg
        .attr('width', width)
        .attr('height', height)
        .append('g')
        .attr('transform', `translate(${width / 2},${height / 2})`);
      
      g.append('text')
        .attr('text-anchor', 'middle')
        .attr('fill', 'var(--text-muted, #666)')
        .attr('font-size', '14px')
        .text('No data available');
      return;
    }

    // Create hierarchy
    const root = d3.hierarchy(hierarchyData)
      .sum(d => d.value || 0)
      .sort((a, b) => b.value - a.value);

    const partition = d3.partition()
      .size([2 * Math.PI, radius]);

    partition(root);

    // Arc generator
    const getRadii = (depth) => {
      const ringWidth = (radius - innerRadius) / ringConfig.levels;
      return {
        inner: depth === 0 ? 0 : innerRadius + ringWidth * (depth - 1),
        outer: depth === 0 ? innerRadius : Math.min(innerRadius + ringWidth * depth - 2, radius - 2)
      };
    };

    const arc = d3.arc()
      .startAngle(d => d.x0)
      .endAngle(d => d.x1)
      .padAngle(d => Math.min((d.x1 - d.x0) / 2, 0.008))
      .padRadius(radius / 2)
      .innerRadius(d => getRadii(d.depth).inner)
      .outerRadius(d => getRadii(d.depth).outer);

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
      .attr('fill', d => d.data.color || '#ccc')
      .attr('fill-opacity', d => d.depth === ringConfig.levels ? 0.8 : 1)
      .attr('stroke', '#fff')
      .attr('stroke-width', d => d.depth === 1 ? 2 : 1)
      .style('cursor', 'pointer')
      .on('mouseenter', function(event, d) {
        d3.select(this)
          .transition()
          .duration(150)
          .attr('fill-opacity', 0.6)
          .attr('transform', () => {
            const [x, y] = arc.centroid(d);
            const angle = Math.atan2(y, x);
            return `translate(${Math.cos(angle) * 5},${Math.sin(angle) * 5})`;
          });
        
        let content = `<strong>${d.data.name}</strong><br/>${d.value} task${d.value !== 1 ? 's' : ''}`;
        
        // Add drill hint based on item type and current state
        if (d.data.itemType === 'category' && drillState.type === 'overview') {
          content += `<br/><span class="drill-hint">Click to see engineers</span>`;
        } else if (d.data.itemType === 'engineer') {
          content += `<br/><span class="drill-hint">Click to see their work</span>`;
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
        d3.select(this)
          .transition()
          .duration(150)
          .attr('fill-opacity', d.depth === ringConfig.levels ? 0.8 : 1)
          .attr('transform', 'translate(0,0)');
        setTooltip({ visible: false, x: 0, y: 0, content: '' });
      })
      .on('click', function(event, d) {
        event.stopPropagation();
        setTooltip({ visible: false, x: 0, y: 0, content: '' });

        if (d.data.itemType === 'category' && drillState.type === 'overview') {
          // Drill into category
          setDrillState({ type: 'category', categoryKey: d.data.key });
          setBreadcrumb([
            { label: 'Overview', type: 'overview' },
            { label: d.data.name, type: 'category', categoryKey: d.data.key }
          ]);
          if (onCategoryClick) onCategoryClick(d.data.key);
        } else if (d.data.itemType === 'engineer') {
          // Drill into engineer's work
          setDrillState({ type: 'engineer', engineerName: d.data.name });
          setBreadcrumb([
            { label: 'Overview', type: 'overview' },
            { label: d.data.name, type: 'engineer', engineerName: d.data.name }
          ]);
          if (onEngineerClick) onEngineerClick(d.data.name);
        } else if (d.data.itemType === 'status' && drillState.type === 'overview') {
          // Click status in overview - drill into that category
          setDrillState({ type: 'category', categoryKey: d.data.categoryKey });
          setBreadcrumb([
            { label: 'Overview', type: 'overview' },
            { label: d.data.categoryName, type: 'category', categoryKey: d.data.categoryKey }
          ]);
          if (onCategoryClick) onCategoryClick(d.data.categoryKey);
        } else if (d.data.itemType === 'category' && drillState.type === 'engineer') {
          // In engineer view, clicking category filters to it
          if (onCategoryClick) onCategoryClick(d.data.key);
        }
      });

    // Animate entrance
    g.selectAll('path')
      .attr('opacity', 0)
      .transition()
      .duration(400)
      .attr('opacity', 1);

    // Add labels for segments with enough space
    const labelArc = d3.arc()
      .startAngle(d => d.x0)
      .endAngle(d => d.x1)
      .innerRadius(d => (getRadii(d.depth).inner + getRadii(d.depth).outer) / 2)
      .outerRadius(d => (getRadii(d.depth).inner + getRadii(d.depth).outer) / 2);

    const labelFits = (d) => {
      const angle = d.x1 - d.x0;
      return angle > 0.3;
    };

    const truncateText = (text, maxLen) => {
      if (!text) return '';
      if (text.length <= maxLen) return text;
      return text.substring(0, maxLen - 1) + '…';
    };

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
      .attr('font-size', d => d.depth === 1 ? '11px' : '10px')
      .attr('font-weight', d => d.depth === 1 ? '600' : '500')
      .attr('pointer-events', 'none')
      .attr('opacity', 0)
      .text(d => truncateText(d.data.name, d.depth === 1 ? 11 : 9))
      .transition()
      .delay(200)
      .duration(300)
      .attr('opacity', 1);

    // Center content
    const centerGroup = g.append('g').attr('class', 'center-content');
    const viewTotal = root.value;
    const centerRadius = innerRadius - 4;
    
    if (drillState.type !== 'overview') {
      // Drilled view - show back button
      centerGroup.append('circle')
        .attr('r', centerRadius)
        .attr('fill', 'var(--primary-color, #6366f1)')
        .attr('cursor', 'pointer')
        .on('mouseenter', function() {
          d3.select(this)
            .transition()
            .duration(150)
            .attr('r', centerRadius + 4);
        })
        .on('mouseleave', function() {
          d3.select(this)
            .transition()
            .duration(150)
            .attr('r', centerRadius);
        })
        .on('click', resetView);

      centerGroup.append('circle')
        .attr('r', centerRadius - 6)
        .attr('fill', 'var(--bg-secondary, #fff)')
        .attr('pointer-events', 'none');

      centerGroup.append('text')
        .attr('text-anchor', 'middle')
        .attr('y', -12)
        .attr('fill', 'var(--text-primary, #333)')
        .attr('font-size', '24px')
        .attr('font-weight', '700')
        .attr('pointer-events', 'none')
        .text(viewTotal);

      centerGroup.append('text')
        .attr('text-anchor', 'middle')
        .attr('y', 8)
        .attr('fill', 'var(--text-muted, #666)')
        .attr('font-size', '10px')
        .attr('pointer-events', 'none')
        .text('tasks');

      centerGroup.append('text')
        .attr('text-anchor', 'middle')
        .attr('y', 26)
        .attr('fill', 'var(--primary-color, #6366f1)')
        .attr('font-size', '11px')
        .attr('font-weight', '700')
        .attr('pointer-events', 'none')
        .text('↩ BACK');
    } else {
      // Overview - show total
      centerGroup.append('text')
        .attr('text-anchor', 'middle')
        .attr('y', -6)
        .attr('fill', 'var(--text-primary, #333)')
        .attr('font-size', '30px')
        .attr('font-weight', '700')
        .text(data.total);

      centerGroup.append('text')
        .attr('text-anchor', 'middle')
        .attr('y', 18)
        .attr('fill', 'var(--text-muted, #666)')
        .attr('font-size', '10px')
        .attr('letter-spacing', '0.5px')
        .text('TOTAL TASKS');
    }

  }, [data, width, height, drillState, engineerData, onCategoryClick, onEngineerClick, resetView]);

  useEffect(() => {
    drawChart();
  }, [drawChart]);

  // Reset view when data changes
  useEffect(() => {
    resetView();
  }, [data?.total, resetView]);

  if (!data || data.total === 0) {
    return (
      <div className="drilldown-sunburst-empty">
        <p>No data available</p>
      </div>
    );
  }

  // Get current view description
  const getViewDescription = () => {
    if (drillState.type === 'overview') {
      return 'Category → Status • Click to explore';
    } else if (drillState.type === 'category') {
      return 'Status → Engineers in this category';
    } else if (drillState.type === 'engineer') {
      return 'Categories → Status for this engineer';
    }
    return '';
  };

  return (
    <div className="drilldown-sunburst-wrapper">
      {/* Breadcrumb navigation */}
      <div className="sunburst-breadcrumb">
        {breadcrumb.map((crumb, idx) => (
          <React.Fragment key={idx}>
            {idx > 0 && <span className="breadcrumb-separator">›</span>}
            <button
              className={`breadcrumb-item ${idx === breadcrumb.length - 1 ? 'active' : ''}`}
              onClick={() => {
                if (crumb.type === 'overview') {
                  resetView();
                } else if (crumb.type === 'category') {
                  setDrillState({ type: 'category', categoryKey: crumb.categoryKey });
                  setBreadcrumb(breadcrumb.slice(0, idx + 1));
                } else if (crumb.type === 'engineer') {
                  setDrillState({ type: 'engineer', engineerName: crumb.engineerName });
                  setBreadcrumb(breadcrumb.slice(0, idx + 1));
                }
              }}
              disabled={idx === breadcrumb.length - 1}
            >
              {crumb.label}
            </button>
          </React.Fragment>
        ))}
      </div>

      {/* View description */}
      <div className="view-description">
        {getViewDescription()}
      </div>

      {/* Chart */}
      <div className="drilldown-sunburst-container" ref={containerRef}>
        <svg ref={svgRef} />
        {tooltip.visible && (
          <div 
            className="sunburst-tooltip"
            style={{ left: tooltip.x, top: tooltip.y }}
            dangerouslySetInnerHTML={{ __html: tooltip.content }}
          />
        )}
      </div>

      {/* Reset button when drilled down */}
      {drillState.type !== 'overview' && (
        <button className="reset-view-btn" onClick={resetView}>
          <span className="reset-icon">↩</span>
          <span>Back to Overview</span>
        </button>
      )}

      {/* Legend for overview */}
      {drillState.type === 'overview' && (
        <div className="sunburst-quick-legend">
          <span className="legend-title">Status:</span>
          <div className="legend-item">
            <span className="dot" style={{ background: '#22c55e' }}></span>Done
          </div>
          <div className="legend-item">
            <span className="dot" style={{ background: '#3b82f6' }}></span>In Progress
          </div>
          <div className="legend-item">
            <span className="dot" style={{ background: '#ef4444' }}></span>Blocked
          </div>
          <div className="legend-item">
            <span className="dot" style={{ background: '#94a3b8' }}></span>To Do
          </div>
        </div>
      )}
    </div>
  );
}

export default DrillDownSunburst;
