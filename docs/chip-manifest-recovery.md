# Chip recovery: one current-run manifest

Normal resource updates use albi0's optional `on_remote_manifest` callback. Its
detached read-only snapshot is captured before glob, size and local-delta filters,
including updates with no changed bundle files. Only the requested updater and
exact target version are accepted. This callback never fetches a second manifest.
`package-manifests/DefaultPackage.json` remains an incremental download record;
it is not used as a complete official source for recovery.

The normal entrypoint passes that validated snapshot explicitly to chip recovery.
It fails rather than silently requesting another manifest if the snapshot is
missing or targets a different version. The chip-only entrypoint can still fetch
one version-pinned official manifest when no current-run snapshot is available.
Already valid version-matched PNG caches require no recovery download.

The unique `game_ui_autocard` / `game_ui_autocard.bundle` source entry supplies
the official content-addressed URL, positive byte size and MD5. A local bundle is
reused only after both checks. Otherwise only that bundle is downloaded. Response
reading, total deadline and size/MD5 validation share at most three request-level
attempts. There is no whole-job retry, downloader retry wrapper, or fallback after
the normal downloader has failed. Permanent HTTP errors and non-network program
errors propagate immediately; 408, 429, 5xx, transport failures, deadlines and
integrity failures can retry within the same three-attempt budget.

Connection timeout is 15 seconds. Manifest I/O timeout is 30 seconds, with a
60-second total attempt limit. Bundle I/O and total attempt limits are 180 seconds.
Logs identify the phase, target version, source kind, safe request host/path,
attempt number, error type/status, bundle reuse and validated extraction outcome.
Authentication headers, URL userinfo and query parameters are not logged.

Version changes do not authorize simply changing the extraction record. Recovery
actually extracts the verified bundle in an isolated directory and validates PNG
decoding, visible pixels and IDs before publishing images and the extraction
record. Failure does not commit/push DefaultPackage or chip records. Other resource
incremental behavior and downstream publication gates remain unchanged.
