#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import argparse, json, os, socket, struct, subprocess, time
import xml.etree.ElementTree as ET
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
  try:
   return receive()
  except TimeoutError:
   s.sendall(b'\x03');receive()
   raw=bytes.fromhex(packet('g'))
   registers=struct.unpack('<33Q',raw[:264])
   report={f'x{i}':hex(v) for i,v in enumerate(registers[:31])}
   report.update(sp=hex(registers[31]),pc=hex(registers[32]))
   def feature(name):
    offset=0;text=''
    while True:
     chunk=packet(f'qXfer:features:read:{name}:{offset:x},1000')
     text+=chunk[1:];offset+=len(chunk)-1
     if chunk[0]=='l':
      if 'xi:include' in text and 'xmlns:xi=' not in text:
       text=text.replace('<target','<target xmlns:xi="http://www.w3.org/2001/XInclude"',1)
      return ET.fromstring(text)
   target_xml=feature('target.xml')
   for include in target_xml.findall('{http://www.w3.org/2001/XInclude}include'):
    for reg in feature(include.attrib['href']).findall('reg'):
     if reg.attrib['name'] in ('TCR_EL1','TTBR0_EL1','TTBR1_EL1','SCTLR_EL1','ESR_EL1','FAR_EL1','ELR_EL1'):
      report[reg.attrib['name']]=hex(int.from_bytes(bytes.fromhex(packet(f'p{int(reg.attrib["regnum"]):x}')),'little'))
   (p/'timeout-registers.json').write_text(json.dumps(report,indent=2)+'\n')
   print(json.dumps(report),flush=True)
   raise
 def memory(address, length):
  reply=packet(f'm{address:x},{length:x}')
  return bytes.fromhex(reply)
 assert packet(f'Z0,{symbols["after_entry"]:x},4')=='OK'
 assert packet('c').startswith(('T05','S05'))
 record=struct.unpack('<24Q',memory(symbols['sheng_early_exception_record'],192))
 assert record[0]==1 and record[12]==symbols['boot_args']
 assert record[23]==12
 for stage in range(16):
  pixel=0x44000000+568*2560+(224+24*stage)*4
  expected=0xff00ff00 if stage<=12 else 0xff303030
  assert struct.unpack('<I',memory(pixel,4))[0]==expected
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
 saved=struct.unpack('<24Q',memory(symbols['sheng_early_exception_record']+delta,192))
 assert saved[0]==2 and saved[1]==trampoline+24 and saved[2]==0xf2000123, [hex(x) for x in saved]
 assert struct.unpack('<Q',memory(symbols['sheng_early_exception_record'],8))[0]==1
 screen=p/'screen.raw'
 result=packet('qRcmd,'+f'pmemsave 0x44000000 0x190000 "{screen}"'.encode().hex())
 while result.startswith('O') and result!='OK':
  print(bytes.fromhex(result[1:]).decode(errors='replace'));result=receive()
 assert result=='OK',result
 raw=screen.read_bytes();assert len(raw)==640*640*4
 for stage in range(16):
  offset=568*2560+(224+24*stage)*4
  assert struct.unpack_from('<I',raw,offset)[0]==(0xff00ff00 if stage<=12 else 0xff303030)
 Image.frombytes('RGBX',(640,640),raw,'raw','BGRX').convert('RGB').save(p/'screen.png')
 # Exercise the shared vector hook while executing high VA with TTBR0 disabled.
 assert packet(f'z0,{halt:x},4')=='OK'
 target=symbols['qemu_mmu_test']
 branch=0x14000000|((target-halt)//4 & 0x3ffffff)
 assert packet(f'M{halt:x},4:'+struct.pack('<I',branch).hex())=='OK'
 original_halt=symbols['Lsheng_early_halt']
 assert packet(f'Z0,{original_halt:x},4')=='OK'
 # A framebuffer in the existing kernel block must not replace that mapping.
 fb_field=symbols['boot_args']+40
 assert packet(f'M{fb_field:x},8:'+struct.pack('<Q',0x41000000).hex())=='OK'
 mapped=symbols['qemu_trace_mapped']
 assert packet(f'Z0,{mapped:x},4')=='OK'
 assert packet('c').startswith(('T05','S05'))
 assert struct.unpack('<Q',memory(symbols['sheng_bootstrap_fb_trace_ready'],8))[0]==0
 assert struct.unpack('<Q',memory(symbols['test_l2']+256,8))[0]==0x40000701
 assert packet(f'z0,{mapped:x},4')=='OK'
 assert packet(f'M{fb_field:x},8:'+struct.pack('<Q',0x44000000).hex())=='OK'
 assert packet('P20='+struct.pack('<Q',target).hex())=='OK'
 assert packet(f'Z0,{mapped:x},4')=='OK'
 assert packet('c').startswith(('T05','S05'))
 assert struct.unpack('<Q',memory(symbols['sheng_bootstrap_fb_trace_ready'],8))[0]==1
 for stage in (13,14,15):
  pixel=0x44000000+568*2560+(224+24*stage)*4
  assert struct.unpack('<I',memory(pixel,4))[0]==0xff0080ff
 assert packet(f'z0,{mapped:x},4')=='OK'
 assert packet('c').startswith(('T05','S05'))
 mmu=struct.unpack('<24Q',memory(symbols['sheng_early_exception_record'],192))
 high=0xffff800000000000
 assert mmu[0]==3 and mmu[1]==high+symbols['qemu_high_fault'] and mmu[2]==0xf2000124, [hex(x) for x in mmu]
 assert mmu[5]&1 and mmu[6]&128 and mmu[7]==0
 assert mmu[23]==15
 assert struct.unpack('<Q',memory(symbols['sheng_bootstrap_fb_trace_ready'],8))[0]==1
 screen=p/'mmu-screen.raw'
 result=packet('qRcmd,'+f'pmemsave 0x44000000 0x190000 "{screen}"'.encode().hex())
 while result.startswith('O') and result!='OK':
  print(bytes.fromhex(result[1:]).decode(errors='replace'));result=receive()
 assert result=='OK',result
 raw=screen.read_bytes()
 for stage in (13,15):
  pixel=568*2560+(224+24*stage)*4
  assert struct.unpack_from('<I',raw,pixel)[0]==0xff00ff00
 Image.frombytes('RGBX',(640,640),raw,'raw','BGRX').convert('RGB').save(p/'mmu-screen.png')
 # The first translated branch must still reach physical vectors when TTBR1
 # and the exception stack cannot be used. Only redirect execution, not records.
 target=symbols['qemu_transition_test']
 assert packet('P20='+struct.pack('<Q',target).hex())=='OK'
 assert packet('c').startswith(('T05','S05'))
 transition=struct.unpack('<24Q',memory(symbols['sheng_early_exception_record'],192))
 assert transition[0]==3 and transition[1]==0xffff800040000000, [hex(x) for x in transition]
 assert transition[2]>>26==0x21 and transition[3]==transition[1]
 assert transition[5]&1 and transition[8]==0 and transition[10]==0
 (p/'transition-record.json').write_text(json.dumps(
  dict(state=transition[0],elr=hex(transition[1]),esr=hex(transition[2]),
       far=hex(transition[3]),ttbr1=hex(transition[8]),sp=hex(transition[10])),indent=2)+'\n')
 # Once console setup disables the gate, the original exception handler runs.
 assert packet(f'z0,{original_halt:x},4')=='OK'
 target=symbols['qemu_mmu_test']
 branch=0x14000000|((target-original_halt)//4 & 0x3ffffff)
 assert packet(f'M{original_halt:x},4:'+struct.pack('<I',branch).hex())=='OK'
 assert packet(f'M{symbols["sheng_bootstrap_capture_enabled"]:x},4:00000000')=='OK'
 normal=high+symbols['qemu_normal_dispatch']
 assert packet(f'Z0,{normal:x},4')=='OK'
 assert packet('c').startswith(('T05','S05'))
 unchanged=struct.unpack('<24Q',memory(high+symbols['sheng_early_exception_record'],192))
 assert unchanged[:23]==transition[:23] and unchanged[23]==15
 result={'entry_returned':True,'relocated_vector_fault_captured':True,
         'mmu_on_fault_captured':True,'disabled_gate_uses_original_dispatch':True,
         'first_translation_fault_without_stack_captured':True,
         'bootstrap_stage_strip_captured':True,
         'post_mmu_device_framebuffer_marks_captured':True,
         'framebuffer_kernel_mapping_overlap_refused':True,
         'status':mmu[0],'elr':hex(mmu[1]),'esr':hex(mmu[2]),'far':hex(mmu[3]),
         'captured_sctlr':hex(mmu[5]),'captured_tcr':hex(mmu[6]),'captured_ttbr0':hex(mmu[7]),
         'record':hex(symbols['sheng_early_exception_record']),
         'copied_page_bytes':4096,'vector_used_bytes':symbols['sheng_early_exception_record']+192-symbols['LowExceptionVectorBase'],
         'sheng_hardware_executed':False}
 (p/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
finally:
 proc.terminate()
 try:proc.wait(timeout=3)
 except subprocess.TimeoutExpired:proc.kill();proc.wait()
 log.close()
