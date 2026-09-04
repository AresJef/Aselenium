# Driver management: Step 3 filesystem, archives and probes

> Historical audit: this records the implementation at its original checkpoint.
> Subsequent [compatibility removals](legacy-removal.md) supersede its old-feature
> and dependency guidance; historical measurements are not current support promises.

> Historical Step 3 checkpoint. See [Steps 4–5](driver-management-steps-4-5.md)
> for subsequent changes, current validation and remaining work.

Completed 2026-09-04. Step 3 hardens manager-owned provisioning operations and
builds on the uncommitted Step 1 and Step 2 work. No commit, push, release,
dependency change or Python-minimum change was performed. Step 4 is not started.

## Result

The offline suite now contains **486 cases: 473 passed and 13 expected failures**
on both Python 3.11.15 and 3.13.12, macOS ARM64. Eight Step 3 regressions that were
previously expected failures now pass as normal tests. Another 183 safety cases
were added; no new expected-failure exemptions were introduced.

The main source changes are `manager/driver.py`, `manager/file.py` and the new
private `manager/_filesystem.py`. The existing manager exports, callable
parameters/defaults and successful installation return types are unchanged.

## Changes made

### 1. Shell-free, time-bounded version probes

- macOS/Linux probes pass `[browser_path, "--version"]` with `shell=False`.
  Quotes, spaces, Unicode, shell metacharacters and embedded newlines remain data.
- Windows invokes the Windows PowerShell executable under `SystemRoot` directly,
  with `-NoLogo`, `-NoProfile`, `-NonInteractive` and `-EncodedCommand`. The script
  uses `Get-Item -LiteralPath` and a correctly escaped single-quoted path. The old
  shell-detection command and shell interpolation are removed.
- Communication has a 10-second deadline. An interrupted/timed-out probe attempts
  to kill the direct child and waits at most another second to reap it. It does
  not enter a second unbounded pipe read if a descendant holds stdout open.
- Nonzero exit status is an error, even if output contains a plausible version.
  Timeout, process, decoding and version-parsing causes are retained under the
  existing `BrowserBinaryNotDetectedError` API. Pipe handles are closed.

The Windows literal-path behavior is grounded in Microsoft's
[Get-Item documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/get-item?view=powershell-7.5).
Timeout handling follows the requirement to terminate/reap a timed-out child in
the [Python subprocess documentation](https://docs.python.org/3/library/subprocess.html#subprocess.Popen.communicate),
with a bounded wait instead of a potentially indefinite second pipe drain.

### 2. Finite filesystem failures with preserved causes

- Read, metadata write, archive save, cache deletion, publication and cleanup no
  longer contain infinite retry loops.
- Permanent failures such as access denial, disk-full and read-only filesystem
  errors fail on the first attempt. Transient `EINTR`, `EAGAIN`, `EBUSY`,
  `ETXTBSY`, and Windows sharing/lock errors 32/33 get at most three attempts,
  with 50 ms and 100 ms backoffs.
- Errors name the operation and preserve the underlying exception. Missing
  metadata still returns `None`; deletion of an already-absent entry is harmless.
- Failed cleanup is logged without replacing the original installation error.
  The log identifies retained staging, temporary metadata or an unindexed new
  entry so the problem is visible rather than silently ignored.

The retry budget bounds attempts, not the duration of a single OS filesystem
call. An unresponsive filesystem is not made interruptible by this change.

### 3. Managed-root containment

- The cache directory is anchored to an absolute, resolved location. A symlink
  or Windows reparse-point cache root is refused.
- Metadata reads/writes, cache selection and deletions validate their target
  paths. Parent traversal, a foreign sibling directory, the root itself, and
  symlink/reparse-point ancestors are rejected.
- Cache hits also validate that the executable is inside the metadata entry's
  folder; a tampered location cannot select an arbitrary outside executable.
- Cleanup validates selected folders before starting a batch and rechecks each
  target on each retry. It does not use archive or metadata paths unchecked.

These checks protect against untrusted paths and static link substitution. They
are not cross-process locking or a complete defense against an adversarial local
process racing every filesystem operation. Python also documents platform
differences in [rmtree's symlink-attack resistance](https://docs.python.org/3/library/shutil.html#shutil.rmtree).

### 4. Private staged extraction and explicit archive policy

- A download is saved and extracted in a uniquely named, private sibling staging
  directory. A validated executable is selected before that directory is renamed
  into the final cache entry. A pre-existing final entry is not overwritten.
- ZIP and TAR members are copied explicitly; no `extractall()` behavior or
  version-dependent TAR extraction defaults are relied upon. This avoids the
  default-policy differences described in the
  [Python tarfile documentation](https://docs.python.org/3/library/tarfile.html#extraction-filters).
- Absolute/traversal paths, backslashes, Windows drive/stream aliases, reserved
  device names, duplicate or case/Unicode-aliased names, path collisions, special
  devices, FIFOs, encrypted ZIP entries and sparse TAR members are rejected.
- Contained relative symlinks and regular-file hard links remain supported for
  browser bundles. Links are created only after regular files; dangling,
  out-of-root, ancestor-directory and unresolved cyclic links are refused. The
  complete link graph is revalidated to catch later links changing earlier `..`
  resolution. No archive data is written through a link.
- Files receive owner read/write permissions plus the archive's ordinary execute
  bits; setuid, setgid and group/world write bits are discarded. Directory creation
  is private. Only the validated target gains owner execute permission when needed;
  license/data files are not indiscriminately made executable. No chmod subprocesses
  are launched. Windows does not provide the same POSIX permission semantics.
- Multiple distinct candidates for the target executable are rejected as ambiguous.

The initial internal limits are explicit and testable:

| Limit | Value |
| --- | --- |
| Archive members | 50,000 |
| Expanded bytes per member | 2 GiB |
| Total declared expanded bytes | 4 GiB |
| Member path depth | 128 components |
| Link target length | 4,096 UTF-8 bytes |
| File-copy chunk size | 1 MiB |

Regular file contents must match their declared expanded size. These limits bound
extraction, not all parser CPU/memory use; the download and archive indexes can
still be buffered in memory. The limits are internal policy constants, not a new
public configuration API. They have not been validated against every live vendor
archive; legitimate unusual archives may need an explicitly reviewed adjustment.

### 5. Save-before-eviction cache updates

- Metadata is written to a sibling temporary file and published using `os.replace`.
  A failed or partial write does not truncate the previous Feather metadata file.
- New metadata is calculated separately, persisted, and only then installed in
  memory. Existing cache entries are not evicted before this succeeds.
- If metadata publication fails, only the newly unpacked entry is eligible for
  rollback. Existing binaries and the previous disk/in-memory indexes remain.
- Once a new installation is committed, eviction failures are logged as deferred
  cleanup rather than reported as a failed installation after earlier deletions.
  This can temporarily leave unindexed directories on disk.
- The just-installed entry always remains indexed, including when an old entry
  has a future timestamp. Direct file-manager cache calls require a positive
  integer limit or `None`.

This is the minimum commit ordering needed for the Step 3 preservation contract.
Feather remains the storage format. Power-loss durability, crash recovery,
unindexed-directory garbage collection and process-safe index transactions remain
for the later cache redesign; `os.replace` alone is not a durability guarantee.

## Verification

| Check | Observed result |
| --- | --- |
| Full suite, Python 3.13.12, asyncio debug | 473 passed, 13 xfailed |
| Full suite, Python 3.11.15, asyncio debug | 473 passed, 13 xfailed |
| Python 3.13 with expected failures disabled | Exactly 13 known failures, 473 passed; expected exit 1 |
| Direct-wheel and sdist-rebuilt-wheel offline install tests | Passed within both full-suite runs |
| Three new safety test modules | 183 passing cases |
| Dependency consistency, both environments | Passed |
| Patch whitespace check | Passed |

No unexpected failures, local skips, TAR-filter warnings, leaked-task warnings or
unawaited-coroutine warnings occurred in the final full-suite runs.

New tests live in `test_probe_safety.py`, `test_archive_safety.py` and
`test_filesystem_safety.py`. Existing discovery and file tests have had the eight
resolved xfail markers removed. Failure injection covers permissions, disk-full,
read-only filesystems, busy files, Windows sharing violations, partial writes,
publication failure and cleanup failure. Real filesystem fixtures are disposable.

Browser/driver probes remain faked. Two explicitly scoped tests use a real Python
child—not a browser, driver or shell—to verify literal argument passing and
timeout/reaping behavior. Builds and wheel installs also use local Python
subprocesses. No browser or driver was downloaded or launched. Personal browser
profiles and caches were not touched.

Native Windows/Linux execution, remote CI, Python 3.10/3.12/3.14 local runs and live
vendor/browser smoke tests were not performed. Simulated platform branches are
not a substitute for native OS validation.

Reproduction commands, using the prepared development environment:

```sh
.venv/bin/python -m pytest -q --asyncio-debug --tb=short
.venv/bin/python -m pytest -q --runxfail --tb=no
.venv/bin/python -m pip check
.venv/bin/python scripts/benchmark_manager.py --samples 7 --lookup-iterations 100 --cache-entries 10 100 1000
git diff --check
```

## Measured performance tradeoff

The original benchmark script was rerun unchanged, with the same parameters and
Python 3.13.12 on this host. The raw result is in
[`baselines/driver-manager-step-3.json`](baselines/driver-manager-step-3.json),
including environment, samples, package-source digest and script digest. The
Step 1 baseline is preserved unchanged.

| Median metric | Step 1 | Step 3 |
| --- | ---: | ---: |
| Fresh-process package import | 247.38 ms | 251.95 ms |
| Exact cache hit, 10 entries | 498.33 µs | 574.63 µs |
| Exact cache hit, 100 entries | 500.65 µs | 575.68 µs |
| Exact cache hit, 1,000 entries | 505.96 µs | 575.20 µs |
| Exact cache miss, 1,000 entries | 482.01 µs | 477.89 µs |
| Feather reload, 1,000 entries | 0.457 ms | 0.455 ms |

Cache hits cost roughly 69–76 µs more in this snapshot (about 14–15%). Additional
path validation is a plausible contributor, but this is not an isolated causal
benchmark: it compares Steps 2+3 to Step 1 and includes ordinary run-to-run noise.
There is no claim of faster cache lookup, reduced import cost or improved live
provisioning throughput. Later optimization should retain these security checks.

## Remaining work and review checkpoint

The 13 known failures are unchanged deferred issues: seven concurrency/task-lifetime
cases, four exact-version-pin cases, and two historical Gecko-range cases.
Python 3.10-specific HTTP timeout cases also remain unverified locally.

Probes and filesystem work are still synchronous. Probe output uses an in-memory
pipe capture; the timeout is not a strict output-memory quota, and process creation
or an unresponsive OS may not be interruptible. Descendant process-tree ownership
is not added here. Archive authenticity, streamed downloads, process coordination,
cache schema migration and complete crash recovery are not claimed by this step.

**Review checkpoint:** Step 3 is complete. Next is Step 4: isolate installation
request/result state, replace the cross-event-loop global lock strategy, and own,
cancel and await sibling downloads correctly. Step 4 has not been started.
