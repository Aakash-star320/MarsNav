"""Optional deterministic SYNTHETIC fixture generator. Requires numpy and Pillow."""
from pathlib import Path
import numpy as np, json
from PIL import Image
out=Path(__file__).resolve().parents[1]/'data/sample'; out.mkdir(parents=True,exist_ok=True)
n=97; span=2400.; x=np.linspace(-1200,1200,n); y=np.linspace(1200,-1200,n); X,Y=np.meshgrid(x,y)
def height(X,Y):
 r=np.sqrt((X-190)**2+(Y-140)**2)
 h=52+125*np.exp(-((r-470)/125)**2)-36*np.exp(-(r/320)**2)
 h+=45*np.exp(-((X+850)**2+(Y-650)**2)/180000)+28*np.sin(X/350)*np.cos(Y/470)
 h+=5*np.sin(X/61)*np.sin(Y/85)+1*np.cos(X/27)*np.sin(Y/43)
 return h
H=height(X,Y); mask=~((X>850)&(Y>800)); data=[round(float(z),3) if ok else None for z,ok in zip(H.flat,mask.flat)]
R=3396190.; lat=18.44; lon=77.45
latd=180/np.pi/R; lond=latd/np.cos(np.deg2rad(lat))
def ll(x,y):return {'latitude_deg':lat+y*latd,'longitude_deg_east':lon+x*lond}
bounds={'west_deg_east':lon-1200*lond,'east_deg_east':lon+1200*lond,'south_deg':lat-1200*latd,'north_deg':lat+1200*latd}
dem={'version':1,'synthetic':True,'width':n,'height':n,'bounds':bounds,'projection':{'kind':'mars-local-equirectangular','radius_m':R,'latitude_origin_deg':lat,'longitude_origin_deg_east':lon},'affine':[-1200,25,0,1200,0,-25],'sample_registration':'point','vertical_datum':'synthetic zero datum','units':'m','values':data}
(out/'dem.synthetic.json').write_text(json.dumps(dem,separators=(',',':')))
# Derived preview rasters are visualization fixtures, not NASA products.
N=768; XX,YY=np.meshgrid(np.linspace(-1200,1200,N),np.linspace(1200,-1200,N)); HH=height(XX,YY); gy,gx=np.gradient(HH,2400/(N-1)); slope=np.degrees(np.arctan(np.hypot(gx,gy))); shade=np.clip(.7-.8*gx+.65*gy,.22,1.3)
noise=np.random.default_rng(42).normal(0,2,(N,N)); valid=~((XX>850)&(YY>800))
base=np.stack([136+HH*.34,76+HH*.22,48+HH*.16],axis=-1)*shade[:,:,None]+noise[:,:,None]
for kind in ['imagery','elevation','slope','roughness','hazard','science','coverage']:
 if kind=='imagery':rgb=base
 elif kind=='elevation':
  t=np.clip(HH/200,0,1); rgb=np.stack([45+195*t,80+80*np.sin(t*3),150-95*t],-1)
 elif kind=='slope':
  t=np.clip(slope/35,0,1);rgb=np.stack([70+180*t,185-125*t,160-120*t],-1)
 elif kind=='roughness':
  t=np.abs(np.sin(XX/61)*np.cos(YY/85));rgb=np.stack([95+110*t,80+40*t,160+55*t],-1)
 elif kind=='hazard':
  t=np.clip(slope/30,0,1);rgb=np.stack([140+110*t,110-80*t,60-25*t],-1)
 elif kind=='science':
  t=np.exp(-((XX+600)**2+(YY-150)**2)/120000)+np.exp(-((XX-630)**2+(YY+480)**2)/90000);t=np.clip(t,0,1);rgb=np.stack([75+80*t,55+150*t,110+115*t],-1)
 else:rgb=np.zeros((N,N,3))+[42,140,133]
 alpha=valid*255
 if kind=='coverage':rgb[~valid]=[236,100,80];alpha=np.full((N,N),200)
 Image.fromarray(np.dstack([np.clip(rgb,0,255).astype('uint8'),alpha.astype('uint8')]),'RGBA').save(out/(kind+'.synthetic.png'))
def route(points,id):
 coords=[]
 for a,b in zip(points[:-1],points[1:]):
  for t in np.linspace(0,1,12,endpoint=False):coords.append(ll(a[0]*(1-t)+b[0]*t,a[1]*(1-t)+b[1]*t))
 coords.append(ll(*points[-1])); distance=sum(np.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(points[:-1],points[1:]))
 return {'id':id,'feasible':True,'geometry':coords,'waypoints':[ll(*p) for p in points[1:]],'metrics':{'distance_m':round(distance),'estimated_duration_min':round(distance/35),'confidence':'unknown'},'target_ids':[],'warnings':['Synthetic prescribed route; no safety or science assessment.'],'constraint_conflicts':[],'segments':[],'elevation_profile':[],'alternatives':[],'conflict_details':[]}
primary=route([(-950,-850),(-800,-320),(-660,180),(-560,680),(30,950),(720,900)],'00000000-0000-0000-0000-000000000001')
alt=route([(-950,-850),(-250,-950),(450,-800),(920,-300),(960,350),(720,900)],'00000000-0000-0000-0000-000000000002')
targets=[]
for i,(p,title) in enumerate([((-660,180),'Western outcrop'),((-560,680),'Rim survey'),((630,-480),'Southern exposure')]):targets.append({'id':f'00000000-0000-0000-0000-{101+i:012d}','location':ll(*p),'title':title+' · synthetic','objective_category':'synthetic-preview','relevance_score':0,'confidence':'unknown','evidence':[]})
(out/'mission.synthetic.json').write_text(json.dumps({'bounds':bounds,'base':primary['geometry'][0],'destination':primary['geometry'][-1],'route':primary,'alternatives':[alt],'targets':targets},indent=2))
(out/'MAP_FIXTURES.md').write_text('All files here are deterministic synthetic fixtures, not NASA observations. Images and DEM have a masked northeast corner. No fixture route is a computed safe path. Run tools/generate_map_fixtures.py to regenerate. Source: local mathematical functions; seed 42. All assets generated for this demo.\n')
