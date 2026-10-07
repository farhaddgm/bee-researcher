# Researcher 3.39 security release

This release implements review items 1, 2, 4–9, 11–13 and 15. Mandatory MFA,
public API visibility and the offsite backup design are outside this release.

The source starts at the exact running 3.38.2 revision, not the older monorepo
copy. `Dockerfile.release` deliberately reuses that immutable runtime base
without downloading libraries or submitting a dependency inventory. The
release manifest binds the clean source commit, all copied source hashes,
image ID, tests, SBOM, offline scanner report and rollback instructions. A
local signature proves integrity under the existing release key; it is not a
claim of third-party verification.

The HTTP process uses `bee_researcher_runtime`. Only the separate migration job
receives `bee_researcher_migrator`; the latter owns the Researcher schema and
has no cluster administration privileges. The runtime cannot create objects,
alter schema, modify migration history or modify security journal rows.
Existing public grants are checked before deployment so another schema cannot
become reachable through `PUBLIC`. Other application roles remain unchanged.

Redis runs on an internal Docker network with no host port. The default user
is disabled. Its application ACL permits only required commands and keys
under `market-intelligence:*`; config, ACL administration, database flushing
and arbitrary keys are denied. Persistence uses AOF every second and the
memory policy is `noeviction`. Cutover copies only Researcher keys and their
remaining TTLs after stopping its poller/scheduler. Rollback repeats this copy
in reverse before restarting the previous image, preserving Telegram offsets
and idempotency state. Never restart both publishers together.

Database, Redis, signing and MFA encryption secrets are independent random
values stored in a private directory (0700, files 0600), outside Git and public
release artifacts. No migration password is passed to the web container.
Provisioning independent signing keys deliberately invalidates browser
sessions and pending OAuth flows. Password hashes upgrade upon successful
login; existing passwords keep working. New or changed passwords require
15–128 characters and reject common/repetitive values using a vendored
[SecLists public blocklist](https://github.com/danielmiessler/SecLists/blob/master/Passwords/Common-Credentials/10k-most-common.txt)
with 10,001 entries, a pinned source revision/hash and its license. All password
comparisons remain local. Hashing uses scrypt
N=131072/r=8/p=1 in a bounded two-thread pool, with legacy verification and
timing padding. Administrative cookies remain HttpOnly/Secure/SameSite.

Both portals use a 30-minute server idle deadline and a fixed 12-hour maximum;
the User portal also retains its 02:00 cutoff in the configured service
timezone. Passive polling does not extend the deadline. Only same-origin
foreground activity or mutations can touch it; the absolute cap is never
extended. Both portals require a session-bound signed CSRF token on mutations.

Password/OAuth admission reserves Redis quotas atomically and fails closed
when counters cannot be checked. Username and normalized email aliases share
the same account quota across IPs and portals. IP/global quotas remain after
successful login. Forwarded addresses are trusted only from configured exact
proxy addresses; Uvicorn automatic proxy rewriting is disabled.

Untrusted HTTP sources use a DNS-validating TCP backend: each socket connects
only to the public numeric address actually validated, while TLS SNI and
certificate verification retain the original hostname. Private/mixed DNS,
unusual ports, redirects to private origins and environment proxies cannot
bypass this policy. Existing size/redirect/credential-host limits remain.

Source instructions are treated as data, normalized for common Unicode
obfuscation and redacted before model input. Detection puts a publication in
review. A project administrator must leave a review note and approve the
exact source and outbound message. Later edits invalidate the approval. The
final sender enforces the same gate as the automatic selector. Detection is
heuristic; human review and absence of model tools provide separate barriers.

Telegram identities are mapped from stable numeric IDs to active local
accounts, then checked against the report/analysis project. A recycled
username grants no permission. A preexisting authorized private identity is
verified with `getChat`, without sending a message, before the mapping is made.

Security events are inserted into a separate journal without foreign-key
cascades. Database permissions and an update/delete/truncate trigger enforce
append-only history. Logs emit the same minimal event without credentials or
request bodies. The owner's incident feed surfaces recent warning/critical
events; database logging failures emit a separate error signal. System/root
administrators can still alter the database or logs: this is not external WORM
storage. No external notification is sent by this release.
