import cv2, numpy as np, subprocess, sys, math
sys.path.insert(0,'/home/user/screensaver/tools'); import render as R
from PIL import Image, ImageDraw, ImageFont
W,H=2000,1299; OUTW,OUTH=3024,1964; FPS=25; K=OUTW/W
col=np.load('bn_col.npy').astype(np.float32); N=len(col); TT=N/FPS
ext=np.load('ext_final.npy'); bgest=ext[53:53+340,66:66+960]
base0=cv2.imread('plate.png')[:,552:552+W].astype(np.float32)   # the original picture, old text removed
# stars: lift them off so the clouds can move without dragging them
Lm=cv2.cvtColor(base0.astype(np.uint8),cv2.COLOR_BGR2GRAY).astype(np.float32)
th=Lm-cv2.morphologyEx(Lm,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
Y=np.arange(H)[:,None]
n,lab,st,_=cv2.connectedComponentsWithStats(((th>25)&(Y<330)).astype(np.uint8))
keep=st[:,4]<=14; keep[0]=False; lab=np.where(keep[lab],lab,0)
star=(base0-cv2.morphologyEx(base0,cv2.MORPH_OPEN,np.ones((5,5),np.uint8)))*(lab>0)[...,None]
cv2.imwrite('orig_nostars.png',np.clip(base0-star,0,255).astype(np.uint8))
scene={'source':'/tmp/claude-0/-home-user/9a7e3017-60f2-53b4-b44e-2dc642cdeab7/scratchpad/frog/orig_nostars.png','ref_size':[W,H],'loop_seconds':TT,'fps':FPS}
ctx=R.Ctx(scene,(W,H),7)
clouds=R.Clouds(ctx,{'fill_offset':-450,'full_until':150,'sky_bottom':255,'direction':'left','scrolls_per_loop':1,
  'hold':[{'center':[float(x),float(y)],'radius':11} for x,y in np.load('hold_pts.npy')]})
rng=np.random.default_rng(5); sph=rng.random(n+1); scyc=rng.integers(4,13,n+1)
spots=np.array([(rng.uniform(x0,x1),rng.uniform(y0,y1)) for (x0,y0,x1,y1,c) in
  [(40,600,560,1280,7),(1080,950,1960,1280,6),(1400,560,1960,760,3)] for _ in range(c)])
fcol=np.array([[255,150,200],[80,160,255]],np.float32)[rng.integers(0,2,len(spots))]
fk=rng.integers(4,9,(len(spots),2)); fph=rng.random((len(spots),2)); fbk=rng.integers(4,9,len(spots)); fbp=rng.random(len(spots))
def dot(f,x,y,c,a,Rr=3.0):
  x0,y0=int(x)-10,int(y)-10
  yy,xx=np.mgrid[y0:y0+21,x0:x0+21].astype(np.float32); d2=(xx-x)**2+(yy-y)**2
  g=np.exp(-d2/(2*(Rr*0.45)**2))+0.35*np.exp(-d2/(2*Rr**2))
  ys,xs=slice(max(0,y0),min(H,y0+21)),slice(max(0,x0),min(W,x0+21))
  f[ys,xs]+=g[ys.start-y0:ys.stop-y0, xs.start-x0:xs.stop-x0][...,None]*c*a
# boxes: the banner's own (same animation), at the size used now, at the original text spots
SC=1.75; S2=SC*K
FONT='/home/user/screensaver/fonts/Marcellus-Regular.ttf'
BOX=[((30.5,70.5,327.5,153.5),(717,600),'Fuck bitches',44.0,(58,127)),
     ((612.5,163.5,936,247.5),(1525,830),'Get Money.',50.0,(640,217))]
G=22; layers=[]
for (x0,y0,x1,y1),(cx,cy),text,fs,(tx0,ty0) in BOX:
  X0,Y0,X1,Y1=int(x0)-G,int(y0)-G,int(math.ceil(x1))+G,int(math.ceil(y1))+G
  h,w=Y1-Y0,X1-X0; oh,ow=int(round(h*S2)),int(round(w*S2))
  m=np.zeros((h,w),np.uint8); cv2.rectangle(m,(int(x0-X0)-3,int(y0-Y0)-3),(int(x1-X0)+3,int(y1-Y0)+3),255,-1)
  inner=cv2.GaussianBlur(cv2.resize(m.astype(np.float32)/255,(ow,oh)),(0,0),2)[...,None]
  fm=np.zeros((oh,ow),np.float32); e=int(G*S2*0.9); fm[e//3:oh-e//3,e//3:ow-e//3]=1
  fade=cv2.GaussianBlur(fm,(0,0),e/3)[...,None]
  ox,oy=int(round(cx*K-ow/2)),int(round(cy*K-oh/2))
  # crisp text, drawn at full size exactly over the banner's text
  im=Image.new('L',(ow*2,oh*2),0); f=ImageFont.truetype(FONT,int(round(fs*S2*2)))
  ImageDraw.Draw(im).text(((tx0-X0)*S2*2,(ty0-Y0)*S2*2),text,font=f,fill=255,anchor='ls')
  ta=cv2.resize(np.asarray(im,np.float32)/255,(ow,oh),interpolation=cv2.INTER_AREA)[...,None]
  layers.append((Y0,Y1,X0,X1,inner,fade,ox,oy,oh,ow,ta))
TEXTC=np.array([254,236,255],np.float32)
def frame(i):
  t=i/FPS; u=i/N
  f=ctx.base.copy(); clouds.apply(f,t)
  img=cv2.cvtColor(np.clip(f,0,1).astype(np.float32),cv2.COLOR_RGB2BGR)*255
  g=0.25+1.6*(0.5-0.5*np.cos(2*math.pi*(scyc*u+sph)))**2; g[0]=0
  img=img+star*g[lab][...,None]
  for (sx,sy),c,k,ph,bk,bp in zip(spots,fcol,fk,fph,fbk,fbp):
    dot(img,sx+14*math.sin(2*math.pi*(k[0]*u+ph[0])),sy+9*math.sin(2*math.pi*(k[1]*u+ph[1])),c,(0.5-0.5*math.cos(2*math.pi*(bk*u+bp)))**2)
  out=cv2.resize(np.clip(img,0,255),(OUTW,OUTH),interpolation=cv2.INTER_LANCZOS4)
  out=out+0.35*(out-cv2.GaussianBlur(out,(0,0),1.6))     # a light sharpen
  B=col[i]
  for Y0,Y1,X0,X1,inner,fade,ox,oy,oh,ow,ta in layers:
    src=cv2.resize(B[Y0:Y1,X0:X1],(ow,oh),interpolation=cv2.INTER_LANCZOS4)
    glow=np.clip(src-cv2.resize(bgest[Y0:Y1,X0:X1],(ow,oh),interpolation=cv2.INTER_CUBIC),0,None)
    d=out[oy:oy+oh,ox:ox+ow]
    d=d*(1-inner)+src*inner+glow*(1-inner)*fade
    d=d*(1-ta)+TEXTC*ta
    out[oy:oy+oh,ox:ox+ow]=d
  return np.clip(out,0,255).astype(np.uint8)
if __name__=='__main__':
  if sys.argv[1]=='test':
    for i in [0,200]: cv2.imwrite(f'orig_t{i}.png',frame(i))
  else:
    p=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{OUTW}x{OUTH}','-r',str(FPS),'-i','-',
      '-c:v','libx264','-pix_fmt','yuv420p','-profile:v','high','-crf','16','-preset','slow','-g','50','-movflags','+faststart',sys.argv[2]],stdin=subprocess.PIPE)
    for i in range(N):
      p.stdin.write(frame(i).tobytes())
      if i%100==0: print(i,flush=True)
    p.stdin.close(); p.wait()
