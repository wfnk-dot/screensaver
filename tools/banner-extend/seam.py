import cv2, numpy as np
L,T,W,H=66,53,1092,457
ext=cv2.GaussianBlur(np.load('ext_static.npy'),(0,0),0.8); t=np.load('sky_t.npy'); med=np.load('bn_med_col.npy'); col0=np.load('bn_col.npy')[0].astype(np.float32)
# frog mask in canvas (from the frog alpha used in extend.py): recompute quickly
al=np.load('frog_alpha.npy').astype(np.float32); al1=cv2.resize(al,(3104,1299),interpolation=cv2.INTER_AREA)
X,Y=np.meshgrid(np.arange(W,dtype=np.float32),np.arange(H,dtype=np.float32)); bx,by=X-L,Y-T
c=np.array([1360,721],np.float32); s=1.3; K=2.3235; o=np.array([277.1,358.55])
px=(c[0]+((K*bx+o[0])-c[0])/s).astype(np.float32); py=(c[1]+((K*by+o[1]+128)-c[1])/s).astype(np.float32)
fm=cv2.remap(cv2.dilate(al1,np.ones((7,7),np.uint8)),px,py,cv2.INTER_LINEAR)
fm=np.clip(fm,0,1)
win=lambda a: a[T:T+340,L:L+960]
m=np.ones((340,960),bool)
for (x0,y0,x1,y1) in [(15,45,345,180),(595,140,955,275)]: m[y0:y1,x0:x1]=False
fw=win(fm)>0.9; nf=win(fm)<0.05
out=np.zeros_like(ext)
for rows,wt in [(slice(0,105),t),(slice(125,340),1-t)]:
  mm=np.zeros_like(m); mm[rows]=m[rows]&nf[rows]
  g=np.zeros_like(ext)
  for ch in range(3):
    a,b=np.polyfit(win(ext)[...,ch][mm],med[...,ch][mm],1); g[...,ch]=ext[...,ch]*a+b
  out+=g*wt[...,None]
# frog: own linear fit on frog pixels inside the banner
fg=np.zeros_like(ext)
for ch in range(3):
  sel=fw&(np.arange(340)[:,None]>150)
  a,b=np.polyfit(win(ext)[...,ch][sel],med[...,ch][sel],1); fg[...,ch]=ext[...,ch]*a+b
out=out*(1-fm[...,None])+fg*fm[...,None]
# boundary correction: offset = banner edge - ext edge, spread outward with decay
BH=338
inside=np.zeros((H,W),bool); inside[T:T+BH,L:L+960]=True
din=cv2.distanceTransform(inside.astype(np.uint8),cv2.DIST_L2,5)
ring=inside & (din>=16) & (din<26)
edge=inside & (din<2)
full=out.copy(); full[inside]=med[...,:][inside[T:T+340,L:L+960]] if False else 0
D=np.zeros_like(out)
D[T:T+BH,L:L+960]=med[:BH]-out[T:T+BH,L:L+960]
# keep only ring values, smooth along the border
D=cv2.medianBlur(np.clip(D,-60,60).astype(np.float32),5)
Dr=np.where(ring[...,None],D,0); wr=ring.astype(np.float32)
sm=lambda a,sg: cv2.GaussianBlur(a,(0,0),sg)
Ds=sm(Dr,25)/np.maximum(sm(wr,25),1e-4)[...,None]
# nearest-ring propagation
dist,lab=cv2.distanceTransformWithLabels((~ring).astype(np.uint8),cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
ry,rx=np.nonzero(ring); idx=np.zeros(lab.max()+1,np.int64); idx[lab[ry,rx]]=np.arange(len(ry))
nearest=Ds[ry,rx][idx[lab]]
decay=np.exp(-np.maximum(dist-26,0)/120.0)[...,None]
corr=cv2.GaussianBlur((nearest*decay).astype(np.float32),(0,0),14)
fixed=out+corr

np.save('ext_final.npy',fixed.astype(np.float32))
# feather: the banner's outer 8 px fade into the extension
fe=np.zeros((H,W),np.float32); fe[T:T+BH,L:L+960]=1
dd=cv2.distanceTransform((fe>0).astype(np.uint8),cv2.DIST_L2,5)
alpha=np.clip((dd-1)/16.0,0,1); alpha=alpha*alpha*(3-2*alpha)
np.save('ban_alpha.npy',alpha.astype(np.float32))
f=fixed.copy(); B=np.zeros_like(f); B[T:T+BH,L:L+960]=col0[:BH]
f=f*(1-alpha[...,None])+B*alpha[...,None]
cv2.imwrite('ext_f0_big.jpg',cv2.resize(np.clip(f,0,255).astype(np.uint8),(1720,720),interpolation=cv2.INTER_CUBIC))
