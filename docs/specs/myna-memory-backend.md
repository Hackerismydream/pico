# Myna Memory backend contract

Status: implemented against the installed public Plugin seam. The Myna
distribution remains externally release-blocked until its frozen artifact is
published from a remote-resolvable source.

## Ownership

Pico owns Turn execution, Session persistence, Context assembly, the generic
`MemoryBackend` Interface, Plugin discovery, compatibility admission, and
lifecycle calls. Myna owns repository binding, durable source capture,
normalization, memory policy, indexing, recall admission, provenance, and
operator remediation.

Pico does not vendor Myna code, import private Myna modules, configure Myna's
runtime root, or expose a second storage route.

## Plugin identity

The installed distribution must expose:

```text
distribution:       myna-memory
entry-point group:  pico.plugins
entry point:        myna = myna.integrations.pico
manifest id:        myna-memory
compatible Pico:    >=0.1,<0.2
backend:            myna
factory:            myna.integrations.pico.backend:make_backend
```

Pico reads `pico-plugin.toml` from the entry point's owning distribution. The
distribution name and version must match the manifest, and the installed Pico
version must satisfy the declared interval. Failure occurs before contribution
activation or backend construction.

## Lifecycle

`start()` binds the configured Pico Workspace to an initialized Myna Git
repository and checks recovery, index readiness, and live health. It must fail
closed for missing initialization, repository mismatch, or degraded durable
state. The operator remedy starts with `myna init` or `myna doctor --live`.

`recall()` uses the user track and returns a compiled, bounded `Memory` object.
No admitted Myna memory means `[]`. Returned metadata retains Myna's repository
cursor, rendered memory ids, and `myna://` source URIs.

`store()` accepts the normalized after-Turn Session slice. Myna journals the
slice before import and index synchronization. Journal or index failure raises;
Pico does not report the store as successful.

`stop()` is safe after a successful start and releases owned resources. Pico's
Runtime Assembly also calls it after later startup failures so partial state is
not retained.

## Configuration behavior

- `memory.backend = "myna"` selects the installed Plugin.
- `memory.backend = null` disables Memory and does not touch the Plugin registry.
- retired backend values fail with an explicit edit instruction.
- there is no alias, fallback, dual read, or automatic data migration.
- Pico-side Myna configuration overrides are rejected by the Adapter.

## Evidence boundary

Passing unit and installed-wheel checks proves manifest admission, host
lifecycle dispatch, persistence continuity, provenance, abstention, and
failure propagation for the tested artifacts. It does not prove task effect,
performance gains, production reliability, or a published Myna release.
