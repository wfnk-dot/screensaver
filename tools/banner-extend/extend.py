import cv2, numpy as np
L,T,W,H=66,53,1092,457
plate=cv2.imread('plate.png').astype(np.float32)          # has the original frog
clean=cv2.imread('plate_nofrog.png').astype(np.float32)
X,Y=np.meshgrid(np.arange(W,dtype=np.float32),np.arange(H,dtype=np.float32))
bx,by=X-L,Y-T
def remap(img,mx,my): return cv2.remap(img,mx,my,cv2.INTER_AREA if False else cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
# downsample plate first to banner-ish scale to avoid aliasing
def band(img,s,ox,oy):
  small=cv2.resize(img,None,fx=1/s,fy=1/s,interpolation=cv2.INTER_AREA)
  return cv2.remap(small,(ox/s+bx).astype(np.float32),(oy/s+by).astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
top=band(clean,2.14,399,114); low=band(clean,2.3235,277.1,358.55)
t=np.clip((124-by)/18,0,1); t=t*t*(3-2*t)
bg=top*t[...,None]+low*(1-t[...,None])
# original frog (with its purple outline), scaled 1.3 like the banner
al=np.load('frog_alpha.npy').astype(np.float32); al1=cv2.resize(al,(3104,1299),interpolation=cv2.INTER_AREA)
fa=np.clip(cv2.GaussianBlur(cv2.dilate((al1>0.3).astype(np.float32),np.ones((9,9),np.uint8)),(0,0),1.5),0,1)
c=np.array([1360,721],np.float32); s=1.3
# plate point p' = c + s*(p-c) + (0,-128); banner b = (p' - o)/K  -> inverse for remap: p = c + ((K*b+o) - (0,-128) - c)/s
K=2.3235; o=np.array([277.1,358.55])
px=(c[0]+((K*bx+o[0])-c[0])/s).astype(np.float32); py=(c[1]+((K*by+o[1]+128)-c[1])/s).astype(np.float32)
# sample at plate resolution scaled appropriately: prefilter by K/s
pre=K/s
sm=cv2.GaussianBlur(plate,(0,0),0.5*pre); smA=cv2.GaussianBlur(fa,(0,0),0.5*pre)
frog=cv2.remap(sm,px,py,cv2.INTER_LINEAR); fA=cv2.remap(smA,px,py,cv2.INTER_LINEAR)[...,None]
ext=bg*(1-fA)+frog*fA
np.save('ext_static.npy',ext.astype(np.float32))
np.save('sky_t.npy',t.astype(np.float32))
cv2.imwrite('ext_static.png',np.clip(ext,0,255).astype(np.uint8))
