# Add a source without expanding the host

This repository owns independent source manifests, settings, discovery and runtime
adapters. An execution provider owns compute and platform assets. Core owns the
common package/operation schemas; source-specific catalogues do not belong there.

Add a source only with its exact upstream version, licence text, dependency lock,
settings schema and a tested runtime path. Prefer existing well-maintained libraries
when suitable; an upstream connector is optional, not a required abstraction.
Keep package versions independent and install only the selected package's runtime.

The current public interface is `ingestron.connector/v1` with a required
`ingestron.snapshot/python/v1` runtime. It is not yet a portable native-execution
contract. Do not add speculative execution modes or advertise provider support
before those combinations have implemented adapters and acceptance evidence.
Future contract changes must be versioned and preserve existing package behaviour.

Use synthetic source data to check reviewed selection, data types, credentials,
failure, retries, schema drift and actual stored output. A mocked protocol is
useful evidence but not proof of live source behaviour. Retain reviewed contracts
and output ownership; never silently change the selected execution implementation.
