#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import argparse, json, os, socket, struct, subprocess, time
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Execute the native early exception screen and its copied vector page in QEMU')
parser.add_argument('--clang', type=Path, required=True)
parser.add_argument('--qemu', type=Path, required=True)
parser.add_argument('--output', type=Path, default=ROOT/'out/native-early-exception')
args=parser.parse_args()
p=args.output.resolve();p.mkdir(parents=True,exist_ok=True)
llvm=args.clang.resolve().parent
linker=p/'test.ld'
linker.write_text('ENTRY(_start)\nSECTIONS { . = 0x40200000; .text : { *(.text*) } .data : { *(.data*) } }\n')
source=ROOT/'probes/native-early-exception/qemu.S'
subprocess.run([args.clang.resolve(),'--target=aarch64-none-elf','-march=armv8.3-a','-nostdlib','-fuse-ld=lld','-Wl,-T,'+str(linker),source,'-o',p/'test.elf'],check=True,timeout=60)
subprocess.run([args.clang.resolve(),'--target=arm64e-apple-macos26.5','-c',source,'-o',p/'test-mach.o'],check=True,timeout=60)
symbols={line.split()[2]:int(line.split()[0],16) for line in subprocess.check_output([llvm/'llvm-nm',p/'test.elf'],text=True).splitlines() if len(line.split())==3}
listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1];listener.close()
env=dict(os.environ,LD_LIBRARY_PATH=str(args.qemu.resolve().parent.parent/'lib/x86_64-linux-gnu'))
log=(p/'qemu.log').open('w')
proc=subprocess.Popen([str(args.qemu.resolve()),'-M','virt,virtualization=off','-cpu','max','-m','512M','-nodefaults','-display','none','-serial','none','-monitor','none','-device','loader,file='+str(p/'test.elf')+',cpu-num=0','-S','-gdb',f'tcp:127.0.0.1:{port}'],env=env,stdout=log,stderr=log)
try:
 for i in range(50):
  try:s=socket.create_connection(('127.0.0.1',port),timeout=.2);break
  except OSError:time.sleep(.02)
 else:raise RuntimeError('QEMU debugger did not start')
 s.settimeout(15);s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
 def receive():
  while True:
   ch=s.recv(1)
   if not ch:raise RuntimeError('debugger closed')
   if ch==b'$':break
  payload=b''
  while True:
   ch=s.recv(1)
   if ch==b'#':break
   payload+=ch
  checksum=s.recv(2)
  assert int(checksum,16)==sum(payload)%256
  s.sendall(b'+')
  return payload.decode()
 def packet(command):
  payload=command.encode();s.sendall(b'$'+payload+b'#'+f'{sum(payload)%256:02x}'.encode())
  return receive()
 def memory(address, length):
  reply=packet(f'm{address:x},{length:x}')
  return bytes.fromhex(reply)
 assert packet(f'Z0,{symbols["after_entry"]:x},4')=='OK'
 assert packet('c').startswith(('T05','S05'))
 record=struct.unpack('<18Q',memory(symbols['sheng_early_exception_record'],144))
 assert record[0]==1 and record[12]==symbols['boot_args']
 assert packet(f'z0,{symbols["after_entry"]:x},4')=='OK'
 # The vector page is copied during XNU CPU bootstrap; verify PC-relative code remains valid.
 copy=0x40300000;delta=copy-symbols['LowExceptionVectorBase']
 original=memory(symbols['LowExceptionVectorBase'],4096)
 for offset in range(0,4096,512):
  data=original[offset:offset+512]
  assert packet(f'M{copy+offset:x},{len(data):x}:'+data.hex())=='OK'
 # Change VBAR through a real guest MSR, without depending on debugger register numbering.
 # Replace the BRK with a three-instruction jump to a tiny MMU-off trampoline.
 trampoline=0x40400000
 # ldr x0, literal; msr vbar_el1,x0; branch over literal; brk #0x123.
 code=struct.pack('<III',0x58000080,0xd518c000,0x14000004)+struct.pack('<I',0xd5033fdf)+struct.pack('<Q',copy)+struct.pack('<II',0xd4202460,0x14000000)
 assert packet(f'M{trampoline:x},{len(code):x}:'+code.hex())=='OK'
 branch=0x14000000|((trampoline-symbols['after_entry'])//4 & 0x3ffffff)
 assert packet(f'M{symbols["after_entry"]:x},4:'+struct.pack('<I',branch).hex())=='OK'
 halt=symbols['Lsheng_early_halt']+delta
 assert packet(f'Z0,{halt:x},4')=='OK'
 assert packet('c').startswith(('T05','S05'))
 saved=struct.unpack('<18Q',memory(symbols['sheng_early_exception_record']+delta,144))
 assert saved[0]==2 and saved[1]==trampoline+24 and saved[2]==0xf2000123, [hex(x) for x in saved]
 assert struct.unpack('<Q',memory(symbols['sheng_early_exception_record'],8))[0]==1
 screen=p/'screen.raw'
 result=packet('qRcmd,'+f'pmemsave 0x41000000 0x190000 "{screen}"'.encode().hex())
 while result.startswith('O') and result!='OK':
  print(bytes.fromhex(result[1:]).decode(errors='replace'));result=receive()
 assert result=='OK',result
 raw=screen.read_bytes();assert len(raw)==640*640*4
 Image.frombytes('RGBX',(640,640),raw,'raw','BGRX').convert('RGB').save(p/'screen.png')
 result={'entry_returned':True,'relocated_vector_fault_captured':True,'status':saved[0],'elr':hex(saved[1]),'esr':hex(saved[2]),'far':hex(saved[3]),'record':hex(symbols['sheng_early_exception_record']+delta),'copied_page_bytes':4096,'vector_used_bytes':symbols['sheng_early_exception_record']+144-symbols['LowExceptionVectorBase'],'sheng_hardware_executed':False}
 (p/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
finally:
 proc.terminate()
 try:proc.wait(timeout=3)
 except subprocess.TimeoutExpired:proc.kill();proc.wait()
 log.close()
