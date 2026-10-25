# Third-party sources

The root MIT license covers original integration tools only. Upstream checkouts
retain their own licenses and authorship; they are not vendored into this repository.

- UniXNU and UniXNU-sheng: BSD-2-Clause-Patent. The ShengPreflight patch extends
  `UniXNU/UniXNU-sheng` at the commit recorded in `sources.lock.json` and retains
  its source license. See that repository's LICENSE for the complete terms.
- Snapintosh: MIT with component-specific licenses. `scripts/gates.py` imports
  the existing host resource contract; `scripts/build_monitor.py` calls its
  existing builder. They do not replace its monitor or alter the A16 baseline.
- q1n1 / Asahi m1n1: upstream licenses and notices remain in their checkout.
- Mesa / Linux / Apple open source: fetched separately at pinned revisions;
  consult their own license files.
- UEFITool / UEFIExtract: BSD-2-Clause with bundled third-party notices;
  source is fetched separately and used to audit firmware volumes.
- Droid-VM/macOS-DroidVM: the optional GOP companion adapts DroidVMDisplay.cpp
  at revision 1dfb172304400eef4ed4c935e5dfbda4e4cf5fe9, which declares
  BSD-2-Clause-Patent. Its source attribution and SPDX header are preserved by
  patches/DroidVM/0001-native-gop-display.patch. Source and generated ABI inputs
  are fetched separately with the hashes in config/macos26-gop-reference.json;
  reconstructed private ABI headers are not vendored here.

Apple restore images, KDKs, reconstructed private ABI headers, firmware and
device backups are not included in this repository.

`config/sheng_defconfig` 原样来自固定提交的 UniXNU/UniXNU-sheng，遵循其 BSD-2-Clause-Patent 许可证；来源与文件哈希见 `config/sheng-baseline.json`。
