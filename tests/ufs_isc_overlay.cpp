// SPDX-License-Identifier: GPL-3.0-or-later
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>
using IOReturn = int;
constexpr int kIOReturnSuccess=0, kIOReturnBadArgument=1, kIOReturnIOError=2, kIOReturnNoMemory=3;
constexpr unsigned kDataMax=131072;
#include "../UniXNU/drivers/NativeUfs/RootWindowRead.h"
#include "../UniXNU/drivers/NativeUfs/RootWindowOverlay.h"
struct Ops {
  std::vector<uint8_t> seed, descriptor;
  bool locked=false, failRead=false;
  uint64_t reads=0, allocated=0, released=0, shortCopy=UINT64_MAX;
  Ops():seed(5*4096),descriptor(3*4096) {
    for(unsigned i=0;i<seed.size();++i)seed[i]=uint8_t(i*13+9);
  }
  void lock(){assert(!locked);locked=true;}
  void unlock(){assert(locked);locked=false;}
  uint8_t *allocate(){assert(locked);++allocated;return static_cast<uint8_t*>(malloc(4096));}
  void release(uint8_t *p){++released;free(p);}
  int read(uint64_t lba,uint32_t count,void *out){
    assert(locked && count==1 && lba>=1 && lba<4);++reads;
    if(failRead)return kIOReturnIOError;
    memcpy(out,seed.data()+lba*4096,4096);return 0;
  }
  uint64_t load(uint64_t offset,void *out,uint64_t n){
    assert(locked);if(n>shortCopy)n=shortCopy;memcpy(out,descriptor.data()+offset,n);return n;
  }
  uint64_t copy(uint64_t offset,const void *data,uint64_t n){
    assert(locked);if(n>shortCopy)n=shortCopy;memcpy(descriptor.data()+offset,data,n);return n;
  }
};
struct Fixture {
  Ops ops;
  uint8_t *pages[3]={},bounce[4096];
  RamSparseDisk disk={pages,3*4096,0};
  ~Fixture(){for(auto *p:pages)if(p)ops.release(p);assert(ops.allocated==ops.released);}
  UfsWindowResult io(bool write,uint64_t block,uint64_t count,uint64_t limit=8192){
    auto r=ufsOverlayIO(ops,disk,4096,write,block,count,limit,bounce);assert(!ops.locked);return r;
  }
};
int main(){
  {
    Fixture f;auto before=f.ops.seed;
    assert(f.io(false,0,24).status==0);
    assert(!memcmp(f.ops.descriptor.data(),before.data()+4096,12288));
    memset(f.ops.descriptor.data(),0xa7,1536);
    auto r=f.io(true,7,3);assert(r.status==0 && r.done==1536 && f.disk.resident==8192);
    assert(f.io(false,0,24).status==0);
    for(unsigned i=0;i<12288;++i)assert(f.ops.descriptor[i]==(i>=3584&&i<5120?0xa7:before[4096+i]));
    assert(f.ops.seed==before);
    uint64_t reads=f.ops.reads;
    assert(f.io(true,24,1).status==kIOReturnBadArgument);
    assert(f.io(true,UINT64_MAX,1).status==kIOReturnBadArgument);
    assert(f.io(true,0,UINT64_MAX).status==kIOReturnBadArgument);
    assert(f.ops.reads==reads && f.ops.seed==before);
  }
  {
    Fixture f;auto before=f.ops.seed;memset(f.ops.descriptor.data(),0x55,1024);
    auto r=f.io(true,7,2,4096);assert(r.status==kIOReturnNoMemory && r.done==512 && f.disk.resident==4096);
    assert(!f.pages[1] && f.ops.seed==before);
  }
  {
    Fixture f;f.ops.failRead=true;
    auto r=f.io(true,0,1);assert(r.status==kIOReturnIOError && r.done==0 && !f.disk.resident);
    assert(!f.pages[0]);
  }
  {
    Fixture f;f.ops.shortCopy=17;
    auto r=f.io(true,1,1);assert(r.status==kIOReturnIOError && r.done==17 && f.disk.resident==4096);
    assert(!memcmp(f.pages[0],f.ops.seed.data()+4096,512));
  }
}
