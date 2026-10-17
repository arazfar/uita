import { Component, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Line, OrbitControls, PerspectiveCamera, useGLTF } from '@react-three/drei';
import { ArrowUpRight } from 'lucide-react';
import * as THREE from 'three';
import type { ReactNode } from 'react';
import type { Aircraft, State } from './types';

const S=2.8;
class SceneBoundary extends Component<{children:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return {failed:true}}render(){return this.state.failed?<div className="world-fallback"><strong>3D view unavailable</strong><p>Use the Traffic tab or open the traffic table to inspect aircraft.</p></div>:this.props.children}}
function SceneDiagnostics(){const {gl}=useThree();const frames=useRef({count:0,time:0});useFrame((_,dt)=>{frames.current.count++;frames.current.time+=dt;if(frames.current.time>=1){gl.domElement.dataset.renderFps=(frames.current.count/frames.current.time).toFixed(1);gl.domElement.dataset.renderDrawcalls=String(gl.info.render.calls);gl.domElement.dataset.renderTriangles=String(gl.info.render.triangles);gl.domElement.dataset.renderPixelratio=gl.getPixelRatio().toFixed(2);frames.current={count:0,time:0}}});return null}

function AirlinerAsset(){const {scene}=useGLTF('/assets/uita-airliner.glb');const model=useMemo(()=>scene.clone(true),[scene]);return <primitive object={model} rotation={[0,Math.PI,0]}/>}
function TerminalAsset(){const {scene}=useGLTF('/assets/uita-terminal.glb');const model=useMemo(()=>scene.clone(true),[scene]);return <primitive object={model} position={[-4,.1,.7]} rotation={[0,-.4,0]}/>}
const pos=(a:Aircraft):[number,number,number]=>[a.x*S,Math.max(.22,a.altitude*.0009),-a.y*S];
function Buildings(){const ref=useRef<THREE.InstancedMesh>(null);useEffect(()=>{if(!ref.current)return;const dummy=new THREE.Object3D();for(let i=0;i<160;i++){const h=.14+((i*37)%11)*.07;dummy.position.set(-15-(i%16)*2.4,h/2,32-Math.floor(i/16)*5.2);dummy.scale.set(1.25,h,2.1);dummy.updateMatrix();ref.current.setMatrixAt(i,dummy.matrix);ref.current.setColorAt(i,new THREE.Color(i%3===0?'#546365':'#3d5257'))}ref.current.instanceMatrix.needsUpdate=true;if(ref.current.instanceColor)ref.current.instanceColor.needsUpdate=true},[]);return <instancedMesh ref={ref} args={[undefined,undefined,160]}><boxGeometry args={[1,1,1]}/><meshStandardMaterial roughness={1}/></instancedMesh>}
function Land(){
 const shape=useMemo(()=>{const s=new THREE.Shape();[[-90,80],[-90,-80],[-29,-80],[-24,-42],[-18,-25],[-15,-14],[-8,-8],[-5,-4],[0,-1],[3,5],[2,11],[-5,16],[-6,25],[-12,40],[-12,80]].forEach(([x,y],i)=>i?s.lineTo(x,y):s.moveTo(x,y));s.closePath();return s},[]);

 return <><mesh rotation={[-Math.PI/2,0,0]} position={[0,-.15,0]} receiveShadow><planeGeometry args={[400,400]}/><meshStandardMaterial color="#164a57" roughness={.85} metalness={.05}/></mesh><mesh rotation={[-Math.PI/2,0,0]} position={[0,-.07,0]} receiveShadow><shapeGeometry args={[shape]}/><meshStandardMaterial color="#304749" roughness={1}/></mesh><Buildings/><mesh rotation={[-Math.PI/2,0,0]} position={[-1,-.04,0]} receiveShadow><planeGeometry args={[10,9]}/><meshStandardMaterial color="#405859" roughness={1}/></mesh><mesh position={[-33,3.0,-31]} scale={[1,.22,1]}><sphereGeometry args={[17,24,12]}/><meshStandardMaterial color="#263e42" roughness={1}/></mesh><mesh position={[-39,3.5,15]} scale={[1,.24,1]}><sphereGeometry args={[21,24,12]}/><meshStandardMaterial color="#243c41" roughness={1}/></mesh></>
}
function Strip({start,end,width=.18,color='#8caaa9',height=.04}:{start:[number,number];end:[number,number];width?:number;color?:string;height?:number}){const a=new THREE.Vector3(start[0]*S,0,-start[1]*S),b=new THREE.Vector3(end[0]*S,0,-end[1]*S);const d=b.clone().sub(a),m=a.clone().add(b).multiplyScalar(.5);return <mesh position={[m.x,height,m.z]} rotation={[0,-Math.atan2(d.z,d.x),0]} receiveShadow><boxGeometry args={[d.length(),.025,width]}/><meshStandardMaterial color={color} roughness={.85}/></mesh>}
function Airport({state,onRunway}:{state:State;onRunway:(s:string)=>void}){
 return <group>{state.runways.map(r=><group key={r.id}><Strip start={r.start} end={r.end} width={.16} color={r.closed?'#6b4b43':'#657778'}/><Strip start={r.start} end={r.end} width={.015} height={.058} color={r.closed?'#d99860':'#c7d4ce'}/>{Array.from({length:14},(_,i)=>{const t=i/13;return <mesh key={i} position={[(r.start[0]+(r.end[0]-r.start[0])*t)*S,.10,-(r.start[1]+(r.end[1]-r.start[1])*t)*S]}><sphereGeometry args={[.038,5,5]}/><meshBasicMaterial color={r.closed?'#e5985e':'#bfefed'}/></mesh>})}</group>)}<Strip start={[-1,-.5]} end={[-.1,1.6]} width={.14} color="#6e775d"/><Strip start={[-1.2,-.35]} end={[-.3,1.75]} width={.13} color="#777e64"/><TerminalAsset/></group>
}
function AircraftModel({aircraft,selected,onSelect,reduced}:{aircraft:Aircraft;selected:boolean;onSelect:()=>void;reduced:boolean}){
 const group=useRef<THREE.Group>(null);const target=useMemo(()=>new THREE.Vector3(...pos(aircraft)),[aircraft.x,aircraft.y,aircraft.altitude]);
 useFrame((_,dt)=>{if(group.current){if(reduced)group.current.position.copy(target);else group.current.position.lerp(target,1-Math.exp(-dt*7));group.current.rotation.y=-aircraft.heading*Math.PI/180;}});
 const col=aircraft.emergency?'#f2ad69':selected?'#7ce4e7':'#d5e5df';
 return <><group ref={group} position={pos(aircraft)} onClick={e=>{e.stopPropagation();onSelect()}} scale={aircraft.wake==='heavy'?.8:.63}>
 <AirlinerAsset/><mesh><sphereGeometry args={[.6,8,6]}/><meshBasicMaterial transparent opacity={0} depthWrite={false}/></mesh>
 </group>{selected&&<><Line points={[[target.x,.06,target.z],[target.x,target.y,target.z]]} color="#74d9df" dashed dashSize={.15} gapSize={.15} lineWidth={1}/><mesh position={[target.x,.065,target.z]} rotation={[-Math.PI/2,0,0]}><ringGeometry args={[.35,.4,32]}/><meshBasicMaterial color="#78dde1" transparent opacity={.7}/></mesh></>}
</>
}
function CameraClearance(){const {camera}=useThree();const physics=useRef<any>(null);useEffect(()=>{let disposed=false;import('@dimforge/rapier3d-compat').then(async R=>{await R.init();if(disposed)return;const world=new R.World({x:0,y:0,z:0});world.createCollider(R.ColliderDesc.cuboid(200,.1,200).setTranslation(0,-.22,0));world.createCollider(R.ColliderDesc.cuboid(.65,.34,1.7).setTranslation(-4,.3,.7));world.step();physics.current={R,world}});return()=>{disposed=true;physics.current?.world.free();physics.current=null}},[]);useFrame(()=>{if(!physics.current)return;const {R,world}=physics.current;const ray=new R.Ray({x:camera.position.x,y:camera.position.y+2,z:camera.position.z},{x:0,y:-1,z:0});const hit=world.castRay(ray,4,true);if(hit){const minY=camera.position.y+2-hit.timeOfImpact+.35;if(camera.position.y<minY)camera.position.y=minY}});return null}
function CameraRig({mode,selected,reduced}:{mode:string;selected?:Aircraft;reduced:boolean}){const {camera}=useThree();const controls=useRef<any>(null);useEffect(()=>{if(mode==='overview'){camera.position.set(6.8,9.0,12.2);controls.current?.target.set(0,0,0)}if(mode==='top'){camera.position.set(0,19,.1);controls.current?.target.set(0,0,0)}if(mode==='ground'){camera.position.set(-4,1.9,2.4);controls.current?.target.set(1,1,-1)}controls.current?.update()},[mode,camera]);useFrame((_,dt)=>{if(mode==='follow'&&selected){const p=new THREE.Vector3(...pos(selected));const destination=p.clone().add(new THREE.Vector3(4,2,5));if(reduced){camera.position.copy(destination);controls.current?.target.copy(p)}else{camera.position.lerp(destination,1-Math.exp(-dt*2));controls.current?.target.lerp(p,1-Math.exp(-dt*3));}controls.current?.update()}});return <OrbitControls ref={controls} makeDefault enableDamping={!reduced} dampingFactor={.1} minDistance={2} maxDistance={90} maxPolarAngle={Math.PI*.49} enableRotate={mode!=='top'} />}

type Projected={id:string;kind:'flight'|'runway';x:number;y:number;outside:boolean;text:string;detail:string;closed?:boolean};
function LabelProjector({state,onUpdate,onNorthAngle}:{state:State;onUpdate:(labels:Projected[])=>void;onNorthAngle?:(angle:number)=>void}){
 const {camera,size,gl}=useThree();const last=useRef(0);
 useFrame(({clock})=>{
  if(clock.elapsedTime-last.current<.08)return;last.current=clock.elapsedTime;
  const points:Projected[]=[];
  const project=(v:THREE.Vector3)=>{v.project(camera);return {x:(v.x+1)/2*size.width,y:(1-v.y)/2*size.height,outside:Math.abs(v.x)>.9||Math.abs(v.y)>.82||v.z>1}};
  const center=camera.position.clone().add(camera.getWorldDirection(new THREE.Vector3()).multiplyScalar(10));
  const projectedCenter=project(center.clone()),projectedNorth=project(center.add(new THREE.Vector3(0,0,-1)));
  const northX=projectedNorth.x-projectedCenter.x,northY=projectedNorth.y-projectedCenter.y;
  if(Math.hypot(northX,northY)>.001)onNorthAngle?.(Math.atan2(northX,-northY)*180/Math.PI);
  state.runways.forEach(r=>{const p=project(new THREE.Vector3(r.start[0]*S,.15,-r.start[1]*S));if(p.outside)return;points.push({id:r.id,kind:'runway',x:p.x+(r.id==='01L'?-18:r.id==='01R'?18:0),y:p.y+(r.id.endsWith('L')?21:-9),outside:false,text:r.id,detail:r.closed?'CLOSED':'',closed:r.closed})});
  state.aircraft.filter(a=>!['pending','complete','diverted'].includes(a.status)).forEach(a=>{const p=project(new THREE.Vector3(...pos(a)).add(new THREE.Vector3(0,.55,0)));points.push({id:a.id,kind:'flight',x:Math.max(60,Math.min(size.width-65,p.x)),y:Math.max(30,Math.min(size.height-120,p.y)),outside:p.outside,text:a.callsign,detail:p.outside?`${Math.hypot(a.x,a.y).toFixed(1)} NM · ${a.operation==='arrival'?'INBOUND':'OUTBOUND'}`:`${Math.round(a.altitude).toLocaleString()} FT · ${Math.round(a.speed)} KT`})});
  const canvasRect=gl.domElement.getBoundingClientRect();
  const headingRect=gl.domElement.closest('.scene-wrap')?.querySelector('.scene-heading')?.getBoundingClientRect();
  const world=gl.domElement.closest('.world-container');
  const clearance=12;
  for(const label of points){
   const element=world?.querySelector<HTMLElement>(`[data-scene-label="${label.kind}-${label.id}"]`);
   const width=element?.offsetWidth||(label.kind==='flight'?150:48),height=element?.offsetHeight||(label.kind==='flight'?46:28);
   const halfWidth=width/2,halfHeight=height/2;
   label.x=Math.max(halfWidth+clearance,Math.min(size.width-halfWidth-clearance,label.x));
   label.y=Math.max(halfHeight+clearance,Math.min(size.height-halfHeight-95,label.y));
   if(!headingRect)continue;
   const left=headingRect.left-canvasRect.left-clearance,right=headingRect.right-canvasRect.left+clearance,top=headingRect.top-canvasRect.top-clearance,bottom=headingRect.bottom-canvasRect.top+clearance;
   if(label.x+halfWidth>left&&label.x-halfWidth<right&&label.y+halfHeight>top&&label.y-halfHeight<bottom){
    const below=bottom+halfHeight,rightward=right+halfWidth;
    if(rightward<=size.width-halfWidth-clearance&&Math.abs(rightward-label.x)<Math.abs(below-label.y))label.x=rightward;
    else label.y=below;
   }
  }
  onUpdate(points);
 });return null;
}

export default function World({state,selected,onSelect,mode,routes,onRunway,onNorthAngle}:{state:State;selected:string|null;onSelect:(id:string)=>void;mode:string;routes:boolean;onRunway:(id:string)=>void;onNorthAngle?:(angle:number)=>void}){
 const [labels,setLabels]=useState<Projected[]>([]);
 const [reduced,setReduced]=useState(()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches);
 useEffect(()=>{const media=window.matchMedia('(prefers-reduced-motion: reduce)');const change=()=>setReduced(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change)},[]);
 return <div className="world-container"><SceneBoundary><Canvas fallback={<div className="world-fallback">WebGL unavailable. Use the Traffic tab or traffic table.</div>} shadows dpr={[1,1.7]} gl={{antialias:true,alpha:false}}><color attach="background" args={['#1b3945']}/><fog attach="fog" args={['#1b3945',50,140]}/><PerspectiveCamera makeDefault position={[6.8,9.0,12.2]} fov={43} near={.1} far={300}/><ambientLight intensity={1.2} color="#a4d1dc"/><hemisphereLight args={['#9cbec9','#254649',1.2]}/><directionalLight position={[-20,30,-15]} intensity={3.1} color="#ffe0af" castShadow shadow-mapSize={[1024,1024]} shadow-camera-left={-30} shadow-camera-right={30} shadow-camera-top={30} shadow-camera-bottom={-30}/><Suspense fallback={null}><Land/><Airport state={state} onRunway={onRunway}/>{state.aircraft.filter(a=>!['complete','diverted'].includes(a.status)&&(a.status!=='pending'||a.operation==='departure')).map(a=><group key={a.id}>{routes&&(a.id===selected||!selected)&&a.trajectory?.length>1&&<Line points={a.trajectory.map(p=>[p.x*S,Math.max(.10,p.altitude*.0009),-p.y*S] as [number,number,number])} color={a.id===selected?'#72d9dd':'#47898f'} transparent opacity={a.id===selected?.8:.3} lineWidth={a.id===selected?1.5:1} dashed dashSize={.20} gapSize={.12}/>}<AircraftModel aircraft={a} selected={a.id===selected} onSelect={()=>onSelect(a.id)} reduced={reduced}/></group>)}</Suspense><SceneDiagnostics/><LabelProjector state={state} onUpdate={setLabels} onNorthAngle={onNorthAngle}/><CameraClearance/><CameraRig reduced={reduced} mode={mode} selected={state.aircraft.find(a=>a.id===selected)}/></Canvas></SceneBoundary><div className="world-labels">{labels.map(l=><button key={l.kind+l.id} data-scene-label={`${l.kind}-${l.id}`} style={{left:l.x,top:l.y}} onClick={()=>l.kind==='flight'?onSelect(l.id):onRunway(l.id)} className={l.kind==='runway'?`runway-marker ${l.closed?'closed':''}`:`aircraft-label ${l.id===selected?'selected':''} ${l.outside?'offscreen':''}`}><span>{l.outside&&<ArrowUpRight size={11}/>} {l.text}</span>{(l.outside||l.id===selected||l.closed)&&<small>{l.detail}</small>}</button>)}</div></div>
}
