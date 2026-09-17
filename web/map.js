const NS="http://www.w3.org/2000/svg";
const colorFor=channel=>`hsl(${(channel*137.5)%360} 68% 45%)`;
const element=(name,attributes={})=>{const node=document.createElementNS(NS,name);Object.entries(attributes).forEach(([key,value])=>node.setAttribute(key,value));return node};

export function channelColor(channel){return colorFor(channel)}

function directionalSector(source){
  const phi=source.direction_deg*Math.PI/180,spread=Math.PI/2,r=source.reception_radius;
  const start={x:source.x+r*Math.cos(phi-spread),y:source.y+r*Math.sin(phi-spread)};
  const end={x:source.x+r*Math.cos(phi+spread),y:source.y+r*Math.sin(phi+spread)};
  return`M ${source.x} ${-source.y} L ${start.x} ${-start.y} A ${r} ${r} 0 0 0 ${end.x} ${-end.y} Z`;
}

export function renderMap(svg,state,visible,target,selectedChannel=null){
  svg.replaceChildren();
  for(let value=-1800;value<=1800;value+=300){
    svg.append(element("line",{x1:-1900,y1:-value,x2:1900,y2:-value,class:"map-grid"}));
    svg.append(element("line",{x1:value,y1:-1900,x2:value,y2:1900,class:"map-grid"}));
  }
  svg.append(element("circle",{cx:0,cy:0,r:1800,class:"target-boundary"}));
  const points=state.events.filter(event=>event.position).map(event=>`${event.position[0]},${-event.position[1]}`);
  if(points.length)svg.append(element("polyline",{points:[`0,0`,...points].join(" "),class:"route"}));
  state.channels.filter(item=>visible.has(item.channel)&&item.status!=="cleared").forEach(item=>{
    const color=colorFor(item.channel);
    if(item.status==="detected"){
      // 有信号：只显示可能的区域，不再叠加排除盘/无信号标记
      item.layer.possible_polygons.forEach(polygon=>svg.append(element("polygon",{points:polygon.map(([x,y])=>`${x},${-y}`).join(" "),class:"possible",fill:color,stroke:color})));
    }else{
      // 无信号（或尚未检测）：只显示排除区域
      item.layer.excluded_disks.forEach(disk=>svg.append(element("circle",{cx:disk.x,cy:-disk.y,r:disk.radius,class:"excluded"})));
      item.layer.negative_observations.forEach(point=>{
        svg.append(element("line",{x1:point.x-25,y1:-point.y-25,x2:point.x+25,y2:-point.y+25,class:"negative"}));
        svg.append(element("line",{x1:point.x-25,y1:-point.y+25,x2:point.x+25,y2:-point.y-25,class:"negative"}));
      });
    }
  });
  (state.truth||[]).forEach(source=>{
    const knowledge=state.channels.find(item=>item.channel===source.channel);
    if(knowledge?.status==="cleared")return;
    if(source.direction_deg===null){svg.append(element("circle",{cx:source.x,cy:-source.y,r:source.reception_radius,fill:"#16a36a18",stroke:"#16a36a","stroke-width":8}))}
    else{
      svg.append(element("path",{d:directionalSector(source),fill:"#8d49c720",stroke:"#8d49c7","stroke-width":8}));
      const phi=source.direction_deg*Math.PI/180;svg.append(element("line",{x1:source.x,y1:-source.y,x2:source.x+140*Math.cos(phi),y2:-(source.y+140*Math.sin(phi)),stroke:"#6f2ba0","stroke-width":18}));
    }
    svg.append(element("circle",{cx:source.x,cy:-source.y,r:18,class:"truth-source",fill:source.direction_deg===null?"#16a36a":"#8d49c7"}));
    if(source.channel===selectedChannel){
      svg.append(element("circle",{cx:source.x,cy:-source.y,r:58,class:"selected-source"}));
      const label=element("text",{x:source.x+70,y:-source.y-70,class:"selected-source-label"});
      label.textContent=`ch${String(source.channel).padStart(2,"0")}`;
      svg.append(label);
    }
  });
  const selected=state.channels.find(item=>item.channel===selectedChannel);
  if(selected?.status!=="cleared"&&selected?.possible_region){
    const {center,radius_m:radius}=selected.possible_region,color=colorFor(selected.channel);
    svg.append(element("circle",{cx:center[0],cy:-center[1],r:radius,class:"possible-radius",stroke:color}));
    const label=element("text",{x:center[0]+20,y:-center[1]-radius-35,class:"map-label",fill:color});
    label.textContent=`ch${String(selected.channel).padStart(2,"0")} 可行域包围半径 ≈ ${radius.toFixed(1)} m`;
    svg.append(label);
  }
  state.channels.filter(item=>item.status==="cleared"&&item.cleared_position).forEach(item=>{
    const [x,y]=item.cleared_position;
    svg.append(element("circle",{cx:x,cy:-y,r:34,class:"cleared-point"}));
    const label=element("text",{x:x+55,y:-y-45,class:"map-label cleared-label"});
    label.textContent=`ch${String(item.channel).padStart(2,"0")} · cleared`;
    svg.append(label);
  });
  state.intelligence.filter(item=>item.position).forEach(item=>svg.append(element("circle",{cx:item.position[0],cy:-item.position[1],r:32,fill:"none",stroke:"#e11d48","stroke-width":12})));
  svg.append(element("circle",{cx:state.position[0],cy:-state.position[1],r:28,class:"robot"}));
  if(target)svg.append(element("circle",{cx:target.x,cy:-target.y,r:5,class:"candidate-radius"}));
}

export function mapCoordinates(svg,event){
  const point=svg.createSVGPoint();point.x=event.clientX;point.y=event.clientY;
  const local=point.matrixTransform(svg.getScreenCTM().inverse());
  return{x:Math.round(local.x*10)/10,y:Math.round(-local.y*10)/10};
}
