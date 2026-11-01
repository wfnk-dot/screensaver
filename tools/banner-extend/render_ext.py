import cv2, numpy as np, subprocess, sys, math
L,T,W,H,BH=66,53,1092,457,338
OUTW,OUTH=3440,1440
col=np.load('bn_col.npy'); flows=np.load('flows.npy').astype(np.float32)
ext=np.load('ext_final.npy'); alpha=np.load('ban_alpha.npy')[...,None]
N=len(col); FPS=25; TT=N/FPS
X,Y=np.meshgrid(np.arange(W,dtype=np.float32),np.arange(H,dtype=np.float32))
cy=np.clip(Y-T,0,105).astype(np.int32); cx=np.clip(X-L,0,959).astype(np.int32)
wsky=np.clip((125-(Y-T))/20,0,1)
inside=np.zeros((H,W),bool); inside[T:T+BH,L:L+960]=True
# stars in the added sky: lift them off, twinkle them
Lm=cv2.cvtColor(np.clip(ext,0,255).astype(np.uint8),cv2.COLOR_BGR2GRAY).astype(np.float32)
th=Lm-cv2.morphologyEx(Lm,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
smask=(th>25)&(~inside)&((Y-T)<100)
n,lab,st,_=cv2.connectedComponentsWithStats(smask.astype(np.uint8))
keep=(st[:,4]<=12); keep[0]=False
lab=np.where(keep[lab],lab,0)
star=(ext-cv2.morphologyEx(ext,cv2.MORPH_OPEN,np.ones((5,5),np.uint8)))*(lab>0)[...,None]
base=ext-star
rng=np.random.default_rng(3)
sph=rng.random(n+1); scyc=rng.integers(4,13,n+1)   # whole cycles per 32 s loop
# fireflies in the added meadow, like the banner's (lavender and amber)
spots=[]
for (x0,y0,x1,y1,c) in [(0,T+150,L-8,H-5,3),(L+968,T+150,W,H-5,3),(L,T+BH+8,L+960,H-4,5)]:
  for _ in range(c): spots.append((rng.uniform(x0,x1),rng.uniform(y0,y1)))
spots=np.array(spots)
fcol=np.array([[255,150,200],[80,160,255]],np.float32)[rng.integers(0,2,len(spots))]   # BGR lavender, amber
fk=rng.integers(4,9,(len(spots),2)); fph=rng.random((len(spots),2)); fbk=rng.integers(4,9,len(spots)); fbp=rng.random(len(spots))
def dot(f,x,y,c,a,R=2.2):
  x0,y0=int(x)-8,int(y)-8
  yy,xx=np.mgrid[y0:y0+17,x0:x0+17].astype(np.float32)
  d2=(xx-x)**2+(yy-y)**2
  g=np.exp(-d2/(2*(R*0.45)**2))+0.35*np.exp(-d2/(2*R**2))
  ys,xs=slice(max(0,y0),min(H,y0+17)),slice(max(0,x0),min(W,x0+17))
  gs=g[ys.start-y0:ys.stop-y0, xs.start-x0:xs.stop-x0]
  f[ys,xs]+=gs[...,None]*c*a
def frame(i):
  t=i/FPS; u=t/TT
  Fs=flows[i]
  fx=Fs[cy,cx,0]*wsky; fy=Fs[cy,cx,1]*wsky
  g=0.25+1.6*(0.5-0.5*np.cos(2*math.pi*(scyc*u+sph)))**2; g[0]=0
  img=base+star*g[lab][...,None]
  img=cv2.remap(img,X-fx,Y-fy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
  for (sx,sy),c,k,ph,bk,bp in zip(spots,fcol,fk,fph,fbk,fbp):
    x=sx+10*math.sin(2*math.pi*(k[0]*u+ph[0])); y=sy+6*math.sin(2*math.pi*(k[1]*u+ph[1]))
    a=(0.5-0.5*math.cos(2*math.pi*(bk*u+bp)))**2
    dot(img,x,y,c,a)
  B=np.zeros_like(img); B[T:T+BH,L:L+960]=col[i][:BH]
  img=img*(1-alpha)+B*alpha
  return np.clip(img,0,255).astype(np.uint8)
if __name__=='__main__':
  if sys.argv[1]=='test':
    for i in [0,12,25,50]:
      cv2.imwrite(f'ext_t{i}.jpg',cv2.resize(frame(i),(1720,720),interpolation=cv2.INTER_CUBIC))
  else:
    out=sys.argv[2]
    p=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{OUTW}x{OUTH}','-r',str(FPS),'-i','-',
      '-c:v','libx264','-pix_fmt','yuv420p','-profile:v','high','-crf','18','-preset','slow','-g','50','-movflags','+faststart',out],stdin=subprocess.PIPE)
    for i in range(N):
      f=cv2.resize(frame(i),(OUTW,OUTH),interpolation=cv2.INTER_LANCZOS4)
      p.stdin.write(f.tobytes())
      if i%100==0: print(i,flush=True)
    p.stdin.close(); p.wait()
