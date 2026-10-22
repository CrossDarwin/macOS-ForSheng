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

Apple restore images, KDKs, reconstructed private ABI headers, firmware and
device backups are not included in this repository.
