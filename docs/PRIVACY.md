# Local Data and Privacy Boundary

AllSpark is offline-first, not encrypted-by-default. Runtime records are stored
as local plaintext SQLite data and local plaintext snapshots. The Stable claim
is therefore limited to process behavior and POSIX file-permission isolation;
it does not claim protection after device theft, disk imaging, administrator
access, malware running as the same user, or an unlocked user session.

## Data inventory

The database may contain survivor profile and health answers, resource levels,
threat and location observations, goals, tasks, diary entries, timeline events,
knowledge imports, reset audit records, and operating or hardware state.
`backups/` and `snapshots/` can contain the same information. Snapshot metadata
also exposes creation time, label, size, and checksum.

Web authentication tokens are process credentials. An operator-provided token
is not redisplayed. An auto-generated non-loopback token is emitted once on
stderr because the operator must receive it; systemd, containers, CI, and shell
redirection may capture stderr, so those records are sensitive. Do not include
tokens in bug reports, shell history, shared logs, screenshots, or support
archives. AllSpark does not intentionally write tokens through its application
logger, nor log diary bodies, health answers, location coordinates, or database
contents, but operators must still inspect every captured stream before sharing.

The Experimental crisis-support path keeps its bounded, ten-minute
confirmation state only in process memory and isolates it by conversation ID.
Anonymous or invalid IDs do not share pending state. It does not write the
triggering text, the user's safety answer, or an intervention event to the
diary, timeline, governance records, or network, and it has no automatic
notification channel. Locally configured
crisis contacts may themselves be sensitive and must be protected with the
same device and file controls as the rest of `config.toml`. A future save or
share workflow requires separate, explicit consent and is not implemented in
v1.0.3.

## Permission model

On POSIX systems, AllSpark migrates its managed data, backup, and snapshot
directories to `0700`. Database, WAL, SHM, rollback journal, backup, snapshot,
and snapshot metadata files are migrated to `0600`. A database path is rejected
when any ancestor is writable by group or other users because another account
could replace the database directory or its SQLite sidecars. POSIX sticky shared
directories such as `/tmp` remain valid because their directory entries cannot
be replaced by unrelated users. User-controlled symbolic links are rejected for
every sensitive storage directory component, including backup and snapshot
directories, so the validated storage root cannot be silently redirected.
Root-owned operating-system aliases such as macOS `/var` and `/tmp` are allowed;
their resolved target chain is still checked before storage is opened.

These controls protect against other ordinary local accounts while the owning
account remains secure. Windows ACL behavior has not been validated on a real
Windows environment and remains Testing; POSIX mode tests are not Windows ACL
evidence.

## Deletion and reset

L2 archive reset deletes selected operational records while retaining the
documented protected state and knowledge. L3 factory reset logically deletes
application rows while retaining the selected language and the new reset audit
record. Neither operation is a cryptographic erase guarantee: SQLite free
pages, filesystem snapshots, backups, SSD wear leveling, and external copies
may retain prior bytes.

For device transfer or disposal, remove AllSpark backups and snapshots, then
use the operating system or storage vendor's secure-erasure procedure. On an
SSD, whole-device encryption established before sensitive data is written is a
more reliable boundary than trying to overwrite individual files later.

## Encryption decision

The v1 release does not add application-level database encryption. It would
introduce key storage, offline recovery, forgotten-passphrase, backup, and
corruption-recovery failure modes that have not been proven under emergency
conditions. Use operating-system full-disk encryption and a strong device login
for data at rest. Application-level encryption remains future work until key
recovery and disaster restore can be validated without creating a data-loss
hazard.

## Backups and removable media

Local snapshots inherit the same plaintext sensitivity as the live database.
Do not place them on shared folders or unencrypted removable media. Independent
or removable-media disaster recovery remains Experimental until a real device,
interrupted-write, restore, and permission-boundary run is attached to the
release evidence.
