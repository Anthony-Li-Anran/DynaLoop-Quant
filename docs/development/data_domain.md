# Data Domain Reference

## Ownership and boundary

Data owns source and dataset identity, immutable dataset-version definitions, logical partitions, snapshot manifests, transformation lineage references, and quality reports. Domain values do not access storage or load external references. The module does not own research logic, strategy backtests, calibration, or experiment execution.

IDs and opaque versions are supplied by creators. A `Dataset` is a stable logical identity; a `DatasetVersion` identifies one immutable state. Version ordering is not inferred from an ID or timestamp. Updating a live dataset does not itself mutate a published version.

## Dataset versions and time

`DataPartition` is a logical unit, not a file or storage location. Its optional event-time bounds are timezone-aware datetimes with left-closed, right-open semantics `[start, end)`. `DatasetVersion` may declare an event-time range; if it does, every partition must declare bounds contained within that range. Comparisons use UTC instants while the original datetime values remain stored.

`TemporalFieldRole` keeps event time, ingestion time, availability time, processing time, report period, publication time, and revision time distinct. Dataset-version partition validation can inspect partition metadata, not record contents; it cannot prove record-level uniqueness declared by a dataset rule. Optional Dataset metadata and versioned `DatasetSchema` fields describe data type, market, granularity, format, and schema without imposing market-data fields on every dataset.

## Snapshot source mapping

A `DatasetSnapshot` is an immutable manifest of explicit partition selections, not a data copy. Each selection is scoped by dataset ID and logical partition values and names one source DatasetVersion reference plus a partition ID. Each logical partition has at most one source in the manifest.

Different partitions in a Snapshot may come from different versions of the same Dataset. A corrected version can replace the source for a partition while another partition continues to reference an older version. The mapping—not version IDs, timestamps, or implicit precedence—determines the selected data. The Snapshot's member references must be exactly the versions used by its source mappings. An empty Snapshot represents an empty view.

Validation uses only the candidate versions supplied by the caller. It confirms that each source version and partition exists, that member partition identities and time bounds are internally consistent, and that the partition's dataset identity and logical key match the mapping. It does not resolve references through a registry or repository.

## Local persistence and publication

The domain remains independent of storage and database implementations. `DataFacade.open_local(database_path, storage_root)` composes SQLite metadata repositories with `LocalFileStorageBackend`; callers can register datasets, inspect the current Head, publish complete versions, read verified partition bytes, and persist Snapshot manifests through the facade.

The local storage adapter stages files under its configured root and atomically links validated SHA-256 content into an immutable content-addressed path. SQLite stores versioned JSON metadata envelopes for Dataset, DatasetVersion, and Snapshot values. Candidate versions are hidden from normal reads. Publication uses a SQLite `BEGIN IMMEDIATE` transaction to compare the expected Head and atomically update candidate state and Head. Since the filesystem and SQLite do not share a transaction, failed metadata publication may leave unreferenced immutable content; it never exposes an unpublished version.

## Acquisition, processing, quality, and access

The local acquisition service imports arbitrary file bytes and optionally converts header-based CSV into JSON Lines. Its incremental file mode uses an explicit byte-offset cursor and currently accepts one partition file per import. A Dataset associates source IDs; successful imports persist non-secret acquisition metadata only after the resulting DatasetVersion has been published. Failed imports do not publish partial versions.

Processing accepts a caller-selected transform, reads and writes JSON Lines, applies the declared output Schema's type normalization, and supports explicit null, duplicate, sort, and time-alignment policies. It can publish multiple outputs and records their complete input/output references, operation metadata, parameters, and execution time in a `ProcessingLineage`. Output publications and lineage persistence are not one cross-record transaction; a later output or lineage persistence failure can leave earlier output versions published.

The schema quality checker reports required-field, type, null, uniqueness, event-time ordering/range, and content-integrity findings as PASS, WARNING, or FAIL. It does not mutate data or block publication. The facade supports fixed-version, Snapshot, partition, batch, JSON Lines filter, and byte-offset incremental reads. Query and record-level processing are intentionally limited to JSON Lines; non-structured formats remain available as raw bytes.

## Processing lineage

A `ProcessingLineage` describes one completed transformation: one or more input version references, one or more output version references, operation name and opaque operation version, immutable scalar parameters, and a timezone-aware execution timestamp. All listed outputs are attributed to the named operation over the complete listed input set. The object does not assert that referenced artifacts exist and does not execute processing.

Parameter names are unique non-empty strings. Values are immutable strings, integers, finite floats, booleans, or `None`; nested mutable values are not accepted. Operation-specific interpretation belongs to the operation owner.

## Quality reports

A `QualityReport` associates a result with an explicit DatasetVersion reference and quality-rule-set ID/version. A failed report records a quality outcome; it does not by itself decide whether a version may be published.

## Deferred capabilities

External supplier connectors, PDF parsing/OCR, domain-specific processors and checkers, streaming orchestration, and complex query engines remain deferred. The domain model does not itself execute acquisition, processing, or quality rules; these capabilities live in application services and adapters.
