import cv2, numpy as np, subprocess, sys, math
# full purple picture (like Brave's own new tab) + the banner's own neon boxes beside the frog
W,H=2000,1299; OUTW,OUTH=3024,1964; FPS=25
plate=cv2.imread('plate.png').astype(np.float32)
base0=plate[:,552:552+W].copy()          # the purple still, old text removed, original frog
col=np.load('bn_col.npy').astype(np.float32); flows=np.load('flows.npy').astype(np.float32)
N=len(col); TT=N/FPS
ext=np.load('ext_final.npy'); L0,T0=66,53
bgest=ext[T0:T0+340,L0:L0+960]           # banner background without boxes (estimate)
X,Y=np.meshgrid(np.arange(W,dtype=np.float32),np.arange(H,dtype=np.float32))
# cloud motion: banner sky band maps to the still by x=-153+2.14*bx, y=114+2.14*by
bxm=np.clip((X+153)/2.14,0,959).astype(np.int32); bym=np.clip((Y-114)/2.14,0,105).astype(np.int32)
wsky=np.clip((400-Y)/70,0,1)
# stars
Lm=cv2.cvtColor(np.clip(base0,0,255).astype(np.uint8),cv2.COLOR_BGR2GRAY).astype(np.float32)
th=Lm-cv2.morphologyEx(Lm,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
n,lab,st,_=cv2.connectedComponentsWithStats(((th>25)&(Y<330)).astype(np.uint8))
keep=st[:,4]<=14; keep[0]=False; lab=np.where(keep[lab],lab,0)
star=(base0-cv2.morphologyEx(base0,cv2.MORPH_OPEN,np.ones((5,5),np.uint8)))*(lab>0)[...,None]
base=base0-star
rng=np.random.default_rng(5); sph=rng.random(n+1); scyc=rng.integers(4,13,n+1)
# fireflies in the meadow and dark hills (not over the frog)
spots=np.array([(rng.uniform(x0,x1),rng.uniform(y0,y1)) for (x0,y0,x1,y1,c) in
  [(40,600,560,1280,7),(1080,950,1960,1280,6),(1400,560,1960,900,3),(620,500,1000,700,2)] for _ in range(c)])
fcol=np.array([[255,150,200],[80,160,255]],np.float32)[rng.integers(0,2,len(spots))]
fk=rng.integers(4,9,(len(spots),2)); fph=rng.random((len(spots),2)); fbk=rng.integers(4,9,len(spots)); fbp=rng.random(len(spots))
def dot(f,x,y,c,a,R=3.0):
  x0,y0=int(x)-10,int(y)-10
  yy,xx=np.mgrid[y0:y0+21,x0:x0+21].astype(np.float32); d2=(xx-x)**2+(yy-y)**2
  g=np.exp(-d2/(2*(R*0.45)**2))+0.35*np.exp(-d2/(2*R**2))
  ys,xs=slice(max(0,y0),min(H,y0+21)),slice(max(0,x0),min(W,x0+21))
  f[ys,xs]+=g[ys.start-y0:ys.stop-y0, xs.start-x0:xs.stop-x0][...,None]*c*a
# the banner's boxes: [banner rect of the outline], destination centre in the still
SC=1.75   # boxes about the size of the original text
BOX=[((30.5,70.5,327.5,153.5),(322,740)),((612.5,163.5,936,247.5),(1330,900))]
G=22  # glow margin (banner px)
layers=[]
for (x0,y0,x1,y1),(cx,cy) in BOX:
  X0,Y0,X1,Y1=int(x0)-G,int(y0)-G,int(math.ceil(x1))+G,int(math.ceil(y1))+G
  h,w=Y1-Y0,X1-X0
  m=np.zeros((h,w),np.uint8)
  cv2.rectangle(m,(int(x0-X0)-3,int(y0-Y0)-3),(int(x1-X0)+3,int(y1-Y0)+3),255,-1)
  oh,ow=int(round(h*SC)),int(round(w*SC))
  inner=cv2.GaussianBlur(cv2.resize(m.astype(np.float32)/255,(ow,oh)),(0,0),1.5)[...,None]
  ty,tx=int(round(cy-oh/2)),int(round(cx-ow/2))
  fm=np.zeros((oh,ow),np.float32); e=int(G*SC*0.9); fm[e//3:oh-e//3, e//3:ow-e//3]=1
  fade=cv2.GaussianBlur(fm,(0,0),e/3)[...,None]
  layers.append((Y0,Y1,X0,X1,inner,ty,tx,oh,ow,fade))
def frame(i):
  u=i/N
  F=flows[i]; fx=2.14*F[bym,bxm,0]*wsky; fy=2.14*F[bym,bxm,1]*wsky
  g=0.25+1.6*(0.5-0.5*np.cos(2*math.pi*(scyc*u+sph)))**2; g[0]=0
  img=base+star*g[lab][...,None]
  img=cv2.remap(img,X-fx,Y-fy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
  for (sx,sy),c,k,ph,bk,bp in zip(spots,fcol,fk,fph,fbk,fbp):
    x=sx+14*math.sin(2*math.pi*(k[0]*u+ph[0])); y=sy+9*math.sin(2*math.pi*(k[1]*u+ph[1]))
    dot(img,x,y,c,(0.5-0.5*math.cos(2*math.pi*(bk*u+bp)))**2)
  B=col[i]
  for Y0,Y1,X0,X1,inner,ty,tx,oh,ow,fade in layers:
    src=cv2.resize(B[Y0:Y1,X0:X1],(ow,oh),interpolation=cv2.INTER_CUBIC)
    glow=np.clip(src-cv2.resize(bgest[Y0:Y1,X0:X1],(ow,oh),interpolation=cv2.INTER_CUBIC),0,None)
    dst=img[ty:ty+oh,tx:tx+ow]
    img[ty:ty+oh,tx:tx+ow]=dst*(1-inner)+src*inner+glow*(1-inner)*fade
  return np.clip(img,0,255).astype(np.uint8)
if __name__=='__main__':
  if sys.argv[1]=='test':
    for i in [0,12,37]: cv2.imwrite(f'full_t{i}.jpg',cv2.resize(frame(i),(1512,982),interpolation=cv2.INTER_AREA))
  else:
    p=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{OUTW}x{OUTH}','-r',str(FPS),'-i','-',
      '-c:v','libx264','-pix_fmt','yuv420p','-profile:v','high','-crf','18','-preset','slow','-g','50','-movflags','+faststart',sys.argv[2]],stdin=subprocess.PIPE)
    for i in range(N):
      p.stdin.write(cv2.resize(frame(i),(OUTW,OUTH),interpolation=cv2.INTER_LANCZOS4).tobytes())
      if i%100==0: print(i,flush=True)
    p.stdin.close(); p.wait()
