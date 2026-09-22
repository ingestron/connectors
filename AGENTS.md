# Ingestron connectors

Own source manifests/settings, discovery, protocol adapters, dependency locks and
reviewed snapshot publication. Providers own compute and native platform generation;
core owns shared host contracts. Do not add a source registry to core or providers.

Original code is Apache-2.0, licensed by Otrera Limited; preserve upstream terms.
The public GitHub package is local-only. Keep other sources/platform support out
of public manifests until qualified. Use exact explicit manifest references and
independent immutable source tags. Preserve old private history in its archive.

Use scoped codex/ branches, Node 22, pnpm 10.15.0 and Python 3.12. Run pnpm validate
and installed-package acceptance. Never use customer data or credentials in tests.
The test fixture redirects the unmodified tap to loopback and blocks other sockets;
it must never ship in a runtime asset map. No live-source/cloud execution without
specific authority. Preserve generated-file and committed-output ownership.
