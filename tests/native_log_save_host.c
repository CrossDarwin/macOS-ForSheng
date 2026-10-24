// Host EFI-service fixture. RAM and filesystem bytes are synthetic.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
#include <assert.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#undef NULL
#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/PrintLib.h>
#include <Library/UefiLib.h>
#include <Protocol/SimpleFileSystem.h>
#include <Protocol/PartitionInfo.h>
#include <Protocol/BlockIo.h>
static EFI_BOOT_SERVICES services;
EFI_BOOT_SERVICES *gBS = &services;
EFI_GUID gEfiPartitionInfoProtocolGuid = {1};
EFI_GUID gEfiSimpleFileSystemProtocolGuid = {2};
EFI_GUID gEfiBlockIoProtocolGuid = {3};
static EFI_PARTITION_INFO_PROTOCOL part;
static EFI_BLOCK_IO_MEDIA media;
static EFI_BLOCK_IO_PROTOCOL block;
static EFI_SIMPLE_FILE_SYSTEM_PROTOCOL fs;
static int short_write, corrupt_read, reserve_fail, bad_mapping, opens, corrupt_verify;
static unsigned held, connects;
static int fs_unbound;
static EFI_STATUS connect_status;
static char disk[1024];
typedef struct { UINT64 Base, End; } KERNEL;
static UINT32 U32(const void *p) { UINT32 v; memcpy(&v,p,4); return v; }
static UINT64 U64(const void *p) { UINT64 v; memcpy(&v,p,8); return v; }
UINT64 EFIAPI ReadUnaligned64(CONST VOID *p) { return U64(p); }
UINT32 EFIAPI ReadUnaligned32(CONST VOID *p) { return U32(p); }
VOID *EFIAPI CopyMem(VOID *d, CONST VOID *s, UINTN n) { return memcpy(d,s,n); }
VOID *EFIAPI ZeroMem(VOID *d, UINTN n) { return memset(d,0,n); }
INTN EFIAPI CompareMem(CONST VOID *a,CONST VOID *b,UINTN n) { return memcmp(a,b,n); }
BOOLEAN EFIAPI CompareGuid(CONST GUID *a, CONST GUID *b) { return memcmp(a,b,16)==0; }
INTN EFIAPI StrCmp(CONST CHAR16 *a, CONST CHAR16 *b) { while(*a && *a==*b) {a++;b++;} return (INTN)*a-*b; }
VOID *EFIAPI AllocatePool(UINTN n) { return calloc(1,n); }
VOID EFIAPI FreePool(VOID *p) { free(p); }
UINTN EFIAPI Print(CONST CHAR16 *f,...) { (void)f; return 0; }
UINTN EFIAPI UnicodeSPrint(CHAR16 *out,UINTN n,CONST CHAR16 *f,...) {
 (void)f; va_list v; va_start(v,f); unsigned id=va_arg(v,unsigned); va_end(v);
 char b[32]; int len=snprintf(b,sizeof(b),"CAP%05u",id); assert(n >= (UINTN)(len+1)*2);
 for(int k=0;k<=len;k++)out[k]=b[k];return len;
}
UINTN EFIAPI AsciiSPrint(CHAR8 *out,UINTN n,CONST CHAR8 *f,...) {
 va_list v;va_start(v,f);int len=vsnprintf((char*)out,n,(const char*)f,v);va_end(v);return len;
}
static EFI_STATUS EFIAPI crc(VOID *p, UINTN n, UINT32 *out) {
 UINT32 c=~0U; const unsigned char *b=p;for(UINTN i=0;i<n;i++){c^=b[i];for(unsigned k=0;k<8;k++)c=c&1?(c>>1)^0xedb88320:c>>1;}*out=~c;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI alloc(EFI_ALLOCATE_TYPE a,EFI_MEMORY_TYPE t,UINTN n,EFI_PHYSICAL_ADDRESS *p) {
 (void)t;assert(a==AllocateAddress && n && *p>=0x880000000ULL);if(reserve_fail)return EFI_NOT_FOUND;held++;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI release(EFI_PHYSICAL_ADDRESS p,UINTN n){(void)p;(void)n;assert(held);held--;return EFI_SUCCESS;}
static UINT64 EFIAPI DarwinPhysicalAddress(UINT64 p) {return bad_mapping ? p+4096 : p;}
typedef struct { EFI_FILE_PROTOCOL e; FILE *stream; char path[1100]; int directory; } HFILE;
static HFILE *wrap(const char *path,int directory,const char *mode);
static EFI_STATUS EFIAPI closefile(EFI_FILE_PROTOCOL *self) {HFILE *h=(HFILE*)self;if(h->stream)fclose(h->stream);free(h);return EFI_SUCCESS;}
static EFI_STATUS EFIAPI deletefile(EFI_FILE_PROTOCOL *self) {HFILE *h=(HFILE*)self;int r=unlink(h->path);closefile(self);return r?EFI_WARN_DELETE_FAILURE:EFI_SUCCESS;}
static EFI_STATUS EFIAPI flush(EFI_FILE_PROTOCOL *self){HFILE *h=(HFILE*)self;if(h->stream){if(fflush(h->stream)||fsync(fileno(h->stream)))return EFI_DEVICE_ERROR;}return EFI_SUCCESS;}
static EFI_STATUS EFIAPI position(EFI_FILE_PROTOCOL *self,UINT64 at){HFILE*h=(HFILE*)self;return fseek(h->stream,(long)at,SEEK_SET)?EFI_DEVICE_ERROR:EFI_SUCCESS;}
static EFI_STATUS EFIAPI readfile(EFI_FILE_PROTOCOL*self,UINTN*n,VOID*data){HFILE*h=(HFILE*)self;*n=fread(data,1,*n,h->stream);if((corrupt_read || (corrupt_verify && strstr(h->path,"CAP"))) && *n)((unsigned char*)data)[0]^=1;return ferror(h->stream)?EFI_DEVICE_ERROR:EFI_SUCCESS;}
static EFI_STATUS EFIAPI writefile(EFI_FILE_PROTOCOL*self,UINTN*n,VOID*data){HFILE*h=(HFILE*)self;if(short_write && *n)*n-=1;*n=fwrite(data,1,*n,h->stream);return ferror(h->stream)?EFI_VOLUME_FULL:EFI_SUCCESS;}
static EFI_STATUS EFIAPI openfile(EFI_FILE_PROTOCOL*self,EFI_FILE_PROTOCOL**out,CHAR16*name,UINT64 mode,UINT64 attr){
 HFILE*h=(HFILE*)self;char ascii[100];unsigned k=0;for(;name[k] && k<99;k++)ascii[k]=(char)name[k];ascii[k]=0;
 if(ascii[0]=='\\')memmove(ascii,ascii+1,strlen(ascii));char path[1100];int len=snprintf(path,sizeof(path),"%s/%s",h->path,ascii);assert(len>0 && len<(int)sizeof(path));
 struct stat st;int exists=stat(path,&st)==0;int create=(mode&EFI_FILE_MODE_CREATE)!=0;
 if(!exists && !create)return EFI_NOT_FOUND;
 if(!exists && (attr&EFI_FILE_DIRECTORY)){if(mkdir(path,0700))return EFI_DEVICE_ERROR;}
 int dir=(exists && S_ISDIR(st.st_mode)) || (attr&EFI_FILE_DIRECTORY);HFILE*f=wrap(path,dir,create&&!exists?"w+b":(mode&EFI_FILE_MODE_WRITE)?"r+b":"rb");
 if(!f)return EFI_DEVICE_ERROR;*out=&f->e;return EFI_SUCCESS;
}
static HFILE *wrap(const char *path,int directory,const char *mode){HFILE*h=calloc(1,sizeof(*h));assert(h);strcpy(h->path,path);h->directory=directory;if(!directory){h->stream=fopen(path,mode);if(!h->stream){free(h);return NULL;}}h->e.Open=openfile;h->e.Close=closefile;h->e.Delete=deletefile;h->e.Read=readfile;h->e.Write=writefile;h->e.Flush=flush;h->e.SetPosition=position;return h;}
static EFI_STATUS EFIAPI volume(EFI_SIMPLE_FILE_SYSTEM_PROTOCOL*self,EFI_FILE_PROTOCOL**out){(void)self;opens++;*out=&wrap(disk,1,"rb")->e;return EFI_SUCCESS;}
static EFI_STATUS EFIAPI locate(EFI_LOCATE_SEARCH_TYPE search,EFI_GUID*guid,VOID*key,UINTN*n,EFI_HANDLE**handles){(void)key;assert(search==ByProtocol && CompareGuid(guid,&gEfiPartitionInfoProtocolGuid));*n=1;*handles=malloc(sizeof(EFI_HANDLE));(*handles)[0]=(EFI_HANDLE)1;return EFI_SUCCESS;}
static EFI_STATUS EFIAPI protocol(EFI_HANDLE handle,EFI_GUID*guid,VOID**out){assert(handle==(EFI_HANDLE)1);if(CompareGuid(guid,&gEfiPartitionInfoProtocolGuid))*out=&part;else if(CompareGuid(guid,&gEfiBlockIoProtocolGuid))*out=&block;else if(CompareGuid(guid,&gEfiSimpleFileSystemProtocolGuid)){if(fs_unbound)return EFI_UNSUPPORTED;*out=&fs;}else return EFI_NOT_FOUND;return EFI_SUCCESS;}
static EFI_STATUS EFIAPI connect(EFI_HANDLE h,EFI_HANDLE *drivers,EFI_DEVICE_PATH_PROTOCOL *path,BOOLEAN recursive){assert(h==(EFI_HANDLE)1 && !drivers && !path && !recursive);connects++;if(!EFI_ERROR(connect_status) || connect_status==EFI_ALREADY_STARTED)fs_unbound=0;return connect_status;}
static EFI_STATUS ReadFile(EFI_FILE_PROTOCOL*root,CONST CHAR16*path,UINTN limit,VOID**out,UINTN*bytes){EFI_FILE_PROTOCOL*f;*out=NULL;EFI_STATUS s=root->Open(root,&f,(CHAR16*)path,EFI_FILE_MODE_READ,0);if(EFI_ERROR(s))return s;HFILE*h=(HFILE*)f;fseek(h->stream,0,SEEK_END);long n=ftell(h->stream);rewind(h->stream);if(n<=0||(UINTN)n>limit){f->Close(f);return EFI_BAD_BUFFER_SIZE;}*bytes=n;*out=calloc(1,n);s=f->Read(f,bytes,*out);f->Close(f);return s;}
#include "NativeLogSave.h"
static void filebytes(const char *name,const void *p,size_t bytes){char path[1200];snprintf(path,sizeof(path),"%s/%s",disk,name);FILE*f=fopen(path,"wb");assert(f);assert(fwrite(p,1,bytes,f)==bytes);fclose(f);}
static int exists(const char *name){char path[1200];snprintf(path,sizeof(path),"%s/%s",disk,name);return access(path,F_OK)==0;}
static void checkfile(const char*name,const void*p,size_t n){char path[1200];snprintf(path,sizeof(path),"%s/%s",disk,name);FILE*f=fopen(path,"rb");assert(f);void*b=malloc(n+1);assert(fread(b,1,n+1,f)==n);assert(!memcmp(b,p,n));free(b);fclose(f);}
int main(int argc,char**argv){assert(argc==2);strcpy(disk,argv[1]);
 services.LocateHandleBuffer=locate;services.HandleProtocol=protocol;services.AllocatePages=alloc;services.FreePages=release;services.CalculateCrc32=crc;services.ConnectController=connect;
 part.Revision=EFI_PARTITION_INFO_PROTOCOL_REVISION;part.Type=PARTITION_TYPE_GPT;part.Info.Gpt.UniquePartitionGUID=mNativeLogPartition;part.Info.Gpt.PartitionTypeGUID=mNativeLogType;part.Info.Gpt.StartingLBA=448512;part.Info.Gpt.EndingLBA=464895;CHAR16 name[]=L"macoslog";memcpy(part.Info.Gpt.PartitionName,name,sizeof(name));
 media.LogicalPartition=TRUE;media.MediaPresent=TRUE;media.BlockSize=4096;media.LastBlock=16383;block.Media=&media;fs.OpenVolume=volume;
 assert(NativeLogRange(0x880000000ULL,NATIVE_LOG_BYTES));assert(NativeLogRange(0x8c1004000ULL,NATIVE_LOG_BYTES));assert(NativeLogRange(0x981004000ULL,NATIVE_PANIC_BYTES));
 assert(!NativeLogRange(0x8bb300000ULL,NATIVE_LOG_BYTES));assert(!NativeLogRange(0x8bb500000ULL,NATIVE_LOG_BYTES));assert(!NativeLogRange(0x8ffff0001ULL,NATIVE_LOG_BYTES));assert(!NativeLogRange(0x9ffffc000ULL,NATIVE_LOG_BYTES));assert(!NativeLogRange(0xffffffffffffc000ULL,NATIVE_LOG_BYTES));
 EFI_FILE_PROTOCOL *v;fs_unbound=1;part.Info.Gpt.UniquePartitionGUID.Data1^=1;assert(NativeLogOpenVolume(&v)==EFI_NOT_FOUND);assert(!connects);part.Info.Gpt.UniquePartitionGUID.Data1^=1;
 connect_status=EFI_DEVICE_ERROR;assert(NativeLogOpenVolume(&v)==EFI_DEVICE_ERROR);assert(connects==1 && !v);
 connect_status=EFI_ALREADY_STARTED;assert(NativeLogOpenVolume(&v)==EFI_SUCCESS);assert(connects==2);v->Close(v);
 fs_unbound=1;connect_status=EFI_SUCCESS;assert(NativeLogOpenVolume(&v)==EFI_SUCCESS);assert(connects==3);v->Close(v);
 UINT64 pa=0x881004000ULL,panicpa=0x882a10000ULL;unsigned char*log=mmap((void*)(uintptr_t)pa,NATIVE_LOG_BYTES,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(log!=(void*)-1);unsigned char*panic=mmap((void*)(uintptr_t)panicpa,NATIVE_PANIC_BYTES,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(panic!=(void*)-1);memset(panic,0xa7,NATIVE_PANIC_BYTES);
 NATIVE_LOG_REQUEST req={0};memcpy(req.Magic,"SHNSAVE1",8);req.Version=1;req.Bytes=80;req.LogAddress=pa;req.LogBytes=NATIVE_LOG_BYTES;req.PanicAddress=panicpa;req.PanicBytes=NATIVE_PANIC_BYTES;memset(req.KernelUuid,0x62,16);req.PartitionGuid=mNativeLogPartition;crc(&req,sizeof(req),&req.Crc32);
 memcpy(log,"SHNLOG01",8);UINT32 fields[]={1,128,16384,65536};memcpy(log+8,fields,sizeof(fields));UINT64 total=30,va=0xfffffe0007004000ULL;memcpy(log+24,&total,8);memcpy(log+48,&pa,8);memcpy(log+104,&va,8);memcpy(log+112,req.KernelUuid,16);memcpy(log+128,"synthetic console bytes\n",24);
 filebytes("NEXTLOG.BIN",&req,sizeof(req));assert(NativeLogSave()==EFI_SUCCESS);assert(!held);assert(!exists("NEXTLOG.BIN"));assert(exists("CAP00001/DONE.TXT"));checkfile("CAP00001/NATIVE.BIN",log,NATIVE_LOG_BYTES);checkfile("CAP00001/PANIC.BIN",panic,NATIVE_PANIC_BYTES);
 filebytes("NEXTLOG.BIN",&req,sizeof(req));assert(NativeLogSave()==EFI_SUCCESS);assert(exists("CAP00002/DONE.TXT"));checkfile("CAP00001/NATIVE.BIN",log,NATIVE_LOG_BYTES);
 filebytes("NEXTLOG.BIN",&req,sizeof(req));log[112]^=1;assert(NativeLogSave()==EFI_COMPROMISED_DATA);assert(!exists("CAP00003"));log[112]^=1;
 part.Info.Gpt.UniquePartitionGUID.Data1^=1;int old=opens;assert(NativeLogSave()==EFI_NOT_FOUND);assert(opens==old);part.Info.Gpt.UniquePartitionGUID.Data1^=1;
 reserve_fail=1;assert(NativeLogSave()==EFI_NOT_FOUND);assert(!held);UINT8 failed[16]={0};memcpy(failed,"SHNREC01",8);UINT64 failure=EFI_NOT_FOUND;memcpy(failed+8,&failure,8);checkfile("RECOVERY.BIN",failed,sizeof(failed));reserve_fail=0;
 bad_mapping=1;assert(NativeLogSave()==EFI_NO_MAPPING);assert(!held);bad_mapping=0;
 req.LogAddress=0xffffffffffffc000ULL;assert(NativeLogValidateRequest(&req)==EFI_COMPROMISED_DATA);req.LogAddress=pa;
 req.Crc32^=1;assert(NativeLogValidateRequest(&req)==EFI_CRC_ERROR);req.Crc32^=1;
 short_write=1;assert(NativeLogSave()==EFI_VOLUME_FULL);short_write=0;assert(!exists("CAP00003/DONE.TXT"));assert(exists("NEXTLOG.BIN"));assert(!held);
 corrupt_read=1;assert(NativeLogSave()==EFI_COMPROMISED_DATA);corrupt_read=0;
 corrupt_verify=1;assert(NativeLogSave()==EFI_DEVICE_ERROR);corrupt_verify=0;assert(!exists("CAP00004/DONE.TXT"));assert(!held);
 unsigned char image[1024]={0};UINT32 mh[]={0xfeedfacf,0x100000c,2,2,2,48};memcpy(image,mh,sizeof(mh));UINT32 uuidcmd[]={0x1b,24};memcpy(image+32,uuidcmd,8);memset(image+40,0x62,16);UINT32 symcmd[]={2,24,128,1,200,100};memcpy(image+56,symcmd,24);UINT32 strindex=1;memcpy(image+128,&strindex,4);image[132]=0x0e;UINT64 symbolva=va+0x4000;memcpy(image+136,&symbolva,8);memcpy(image+201,"_sheng_log_buffer",18);
 KERNEL kernel={va,va+0x200000};EFI_FILE_PROTOCOL *r,*f;assert(NativeLogOpenVolume(&r)==EFI_SUCCESS);assert(r->Open(r,&f,L"\\NEXTLOG.BIN",EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE,0)==EFI_SUCCESS);assert(f->Delete(f)==EFI_SUCCESS);r->Close(r);
 assert(NativeLogArm(image,sizeof(image),&kernel,pa-0x4000,panicpa,TRUE)==EFI_SUCCESS);checkfile("NEXTLOG.BIN",&req,sizeof(req));assert(NativeLogArm(image,sizeof(image),&kernel,pa-0x4000,panicpa,TRUE)==EFI_ALREADY_STARTED);assert(NativeLogSave()==EFI_SUCCESS);assert(exists("CAP00005/DONE.TXT"));
 total=100000;memcpy(log+24,&total,8);UINT64 dropped=9;memcpy(log+32,&dropped,8);UINT32 busy=1;memcpy(log+40,&busy,4);memset(log+128,'A',16384);for(unsigned i=0;i<65536;i++)log[128+16384+i]=(unsigned char)('a'+i%26);
 filebytes("NEXTLOG.BIN",&req,sizeof(req));assert(NativeLogSave()==EFI_SUCCESS);assert(exists("CAP00006/DONE.TXT"));
 UINT64 highpa=0x8c1004000ULL,highpanic=0x981004000ULL;unsigned char*highlog=mmap((void*)(uintptr_t)highpa,NATIVE_LOG_BYTES,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(highlog!=(void*)-1);unsigned char*highpanicbuf=mmap((void*)(uintptr_t)highpanic,NATIVE_PANIC_BYTES,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);assert(highpanicbuf!=(void*)-1);
 memcpy(highlog,log,NATIVE_LOG_BYTES);memcpy(highlog+48,&highpa,8);memcpy(highpanicbuf,panic,NATIVE_PANIC_BYTES);req.LogAddress=highpa;req.PanicAddress=highpanic;req.Crc32=0;crc(&req,sizeof(req),&req.Crc32);
 assert(NativeLogArm(image,sizeof(image),&kernel,highpa-0x4000,highpanic,TRUE)==EFI_SUCCESS);checkfile("NEXTLOG.BIN",&req,sizeof(req));assert(NativeLogSave()==EFI_SUCCESS);assert(!held && !exists("NEXTLOG.BIN"));checkfile("CAP00007/NATIVE.BIN",highlog,NATIVE_LOG_BYTES);checkfile("CAP00007/PANIC.BIN",highpanicbuf,NATIVE_PANIC_BYTES);
 puts("PASS - high-bank 3 GiB window arming and capture; partition-bound FAT connect; ring wrap, interrupted writer and omitted bytes; automatic actual-PA arming; raw log and panic persisted and read back; captures never overwritten; UUID, GPT, address, allocation, mapping, CRC and short-write rejection");
 return 0;
}
