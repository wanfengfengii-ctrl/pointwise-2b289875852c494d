# Spectra fixed FITS archive V1

Python 3.11 standard library only. Spectra validates a single-pass FITS byte stream, publishes an immutable SQLite revision, selects rows by a scalar physical value and reads fixed spectral windows after the original source has disappeared.

Run from this directory:

    python3.11 -B -m unittest discover -s tests -t . -v
    python3.11 -B examples.py

Tests and demo create and remove their own temporary directories. They never read external datasets. The four regression modules cover import, exact physical reads, failed input, and revision reopening/publication failures. Failures produce a nonzero exit status.

## Public API

    from spectra import Archive
    a = Archive("observations.sqlite")
    revision = a.ingest(chunks)
    metadata = a.describe(revision)
    rows = a.select_rows(revision, "temperature", 2, 6)
    window = a.cell(revision, rows[0], "flux", 0, 3)
    a.close()

Archive(database_path) creates or opens an archive; ":memory:" is supported. ingest(chunks) obtains one iterator and consumes bytes blocks, including empty blocks, through final EOF. It returns a new positive revision number only after every HDU, padding byte and staged count has passed validation. Failed imports do not change any preexisting revision or leave staged records. Numbers need not be consecutive after failure.

The file contains an empty primary HDU (SIMPLE=T, BITPIX=8, NAXIS=0) followed by at least one BINTABLE. Tables require BITPIX=8, NAXIS=2, GCOUNT=1, nonnegative row dimensions and PCOUNT=0. THEAP may be absent or exactly equal to the row area length. Only positive fixed J/rJ columns are supported; J means one signed big-endian 32-bit integer. Column widths must sum exactly to NAXIS1. Zero rows are valid. P/Q, other element types, compressed HDUs and other HDU types are rejected.

Headers use printable ASCII 80-byte cards. Values are quoted strings (doubled single quotes escape a quote), booleans or finite decimal/exponent numbers. Slashes inside strings are data; slashes outside strings introduce comments. Layout and interpretation keywords cannot repeat. COMMENT, HISTORY and blank cards may repeat. END and space header padding, zero data padding, subsequent HDUs and EOF are all checked; trailing junk or truncation rejects the import.

Each column requires a nonempty unique TTYPE and a supported TFORM. TNULL is an optional signed 32-bit integer. TSCAL and TZERO default to 1 and 0; decimal and E/D exponents are parsed directly into Fraction, with no float conversion. Null comparison uses raw integers before scaling. Non-null physical values are raw*TSCAL+TZERO, including zero and negative scaling. Interpretations belong to their column and revision.

describe(revision) returns a fresh dictionary with revision and ordered tables. Each table has hdu_index, row_count and ordered columns; each column has name, canonical tform (for example "3J"), repeat, tnull, tscal and tzero. Scale/zero values are Fraction instances. Mutable metadata containers are independent on every call.

column is either an unambiguous name string or (hdu_index, name). HDU indices follow file order from 0 (primary), so the first table is 1. Ambiguous unqualified names, missing revisions/tables/columns and rows past the table length raise KeyError. row must be a non-boolean nonnegative integer; invalid row types or negative rows raise ValueError.

cell(revision,row,column,start,stop) returns an independent tuple of Fraction or None. Scalars have length one. Both bounds must be non-boolean nonnegative integers with start<=stop. Bounds are clipped to the fixed length; windows are half-open and empty windows return (). Only the requested byte window of the target fixed cell is fetched.

select_rows(revision,column,lower,upper) requires a length-one column and integer/Fraction bounds, excluding booleans, with lower<=upper. It compares non-null physical values against a closed interval and returns a tuple of table-local row indices in source order. Invalid ranges or array columns raise ValueError.

Formatting and unsupported-subset errors raise ValueError. Exceptions from source iteration propagate as the original object. SQLite failures propagate unchanged. An import uses one transaction for candidate revision, tables, columns and raw fixed-cell BLOBs. A real SQLite trigger regression rejects the final publication update to exercise rollback. No helper commits directory or cell writes.

close() is idempotent. All four business methods raise RuntimeError after closing, before handling arguments. Reopening and subsequent imports preserve historical metadata, selection and windows. Revisions own their fixed bytes and never consult the source file again. Concurrent import, crash continuation, updates, deduplication and collection are outside V1.

## Implementation map

fits/ owns the single source iterator, cards, headers, fixed layouts, padding and HDU scanning. columns/ owns fixed J declarations, raw nulls and exact scaling. catalog/ owns the connection, invisible import session, table interpretation persistence, coordinated staging and EOF-gated revision publication. storage/ owns the schema, fixed raw cells, signed J codec and confined windows. access/ owns lifecycle, published target resolution, detached metadata, physical cell reads and scalar row selection.

The scanner calls table-start and fixed-row callbacks. The coordinator stores each fixed column's own raw bytes, verifies storage counts, then publishes only after the scanner returns from successful EOF validation. Read requests resolve one immutable revision/table/column target before fetching and interpreting its local window. V1 stages a complete fixed row and each fixed cell in memory; it makes no streaming-memory guarantee for arbitrarily wide arrays.

The finite example has temperature raw values [4,2,-999] with scale -2, zero 10, null -999, and fixed flux rows [10,-999,30], [40,50,60], [70,80,90] with scale 0.5, zero 1, null -999. Selecting temperature in [2,6] yields rows (0,1); the first flux cell is (Fraction(6),None,Fraction(16)). examples.py imports it in small chunks, deletes its source, reopens the archive and reads the selected windows.

## V2 request: variable J spectra

This section defines the requested addition; the initial production code still implements V1. All earlier V1 contracts and original tests remain applicable. For tables containing only fixed J columns, PCOUNT must still be zero and THEAP must remain absent or equal to the row-area length. A table containing at least one variable column may mix fixed J and variable J columns and may use a heap. Other FITS element types, compression, updates, deduplication, collection, concurrent import and crash continuation remain outside this request.

### Input and public results

The existing Archive.ingest(chunks), describe(revision), cell(revision,row,column,start,stop), select_rows and close remain the entry points. No alternate import API is required. Source iteration remains single-pass, arbitrary bytes chunk boundaries and empty chunks remain legal. Source exceptions and SQLite exceptions propagate unchanged; invalid FITS raises ValueError. Input and output argument/error behavior from V1 is preserved.

A variable TFORM is PJ, 1PJ, QJ or 1QJ (outer whitespace allowed). Each row contains exactly one descriptor per such column. Parenthesized maxima, repeat counts other than one and non-J elements are unsupported. P occupies eight row bytes: signed big-endian 32-bit count followed by signed 32-bit offset. Q occupies sixteen: signed big-endian 64-bit count and offset. The count is the number of signed big-endian 32-bit J elements, not a byte count. Row width is the sum of the fixed cell widths and descriptor widths.

Let R=NAXIS1*NAXIS2. PCOUNT is a nonnegative integer counting every byte after the row area and before the data padding, including any gap. THEAP is an integer measured from the start of that HDU's data area; default R. It must satisfy R<=THEAP<=R+PCOUNT. The heap is [THEAP,R+PCOUNT); descriptor offsets are relative to THEAP, never relative to the file or row area. Gap and heap bytes are unrestricted; data padding after R+PCOUNT must be zero as in V1. Counts must be nonnegative. A nonempty descriptor requires a nonnegative offset and offset+4*count<=heap length. A zero count ignores even a negative offset and yields (). Check the whole referenced range before publication, even if it is never read. Zero-row variable tables are valid.

Offsets may be unordered, repeated, overlapping or unaligned. Every cell decodes its own consecutive four-byte groups starting at its own offset. Sharing bytes never shares a column's TNULL/TSCAL/TZERO interpretation. Apply raw integer null comparison before exact Fraction scaling, including zero or negative scales. All HDUs and final EOF must validate before a revision becomes visible; a later invalid descriptor, bad padding, truncation, source failure or publication failure leaves no candidate revision or candidate-owned persistent content and preserves all older revisions.

describe retains its V1 shape. For a variable column, canonical tform is "1PJ" or "1QJ" and repeat is 1 (descriptor count, not a claimed common array length); tnull/tscal/tzero retain their V1 types and meaning. Fixed column metadata remains identical. cell returns an independent tuple, clipping its validated nonnegative half-open bounds to this particular cell's count. Existing qualified column identity, row numbering and exceptions apply. select_rows continues to support only fixed length-one J columns; reject variable columns with ValueError even if their cells happen to have length one. A mixed table's fixed scalar selection must still work. Historical metadata and cells remain independent after append, close and reopen; archives created by V1 remain readable and appendable.

### Resource and ownership boundary

A single variable cell, the heap, and the total stream may exceed working memory. Excluding the current input block and requested slice result, import/read working memory must not grow linearly with variable element count, heap byte length or row count. It may depend on headers, column declarations and the fixed-width row area needed by the existing fixed-column path; V1's unrelated arbitrarily wide fixed-array memory behavior is not an extra optimization target. Do not retain all descriptors/rows in memory or decode the entire variable cell for a small slice. Temporary disk, random access, repeated scans, and permanently retaining an archive-owned copy of the complete source are all allowed. Payload deduplication is optional.

The FITS input responsibility must hand the archive responsibility a trustworthy array length, J interpretation and actual payload ownership/location. The archive must durably consume that representation and read bounded windows after the original input iterator, caller's source file and Archive object have disappeared. A P/Q descriptor is never the array's inline J payload. Internal interfaces, on-disk representation and ownership organization are implementation choices. Reuse the existing transaction and EOF-gated publication behavior.

### Examples and delivery

heap_cases.py contains small independent byte specimens, a simple expected-value calculation over those small specimens, and a generated large source. It contains no P/Q archive implementation. In the sample, heap integers are [10,-999,30]. For flux, TNULL=-999, TSCAL=0.5 and TZERO=1: descriptor (3,0) reads (Fraction(6),None,Fraction(16)); (2,4) reads (None,Fraction(16)); (0,-123) reads (). A second column references overlapping and unaligned bytes with a different null and scale; offsets belong to their own HDU. P and Q versions carry the same spectra.

Retain every original test without editing it. Deliver the interacting input and persistent storage/read changes and a short explanation of representation, ownership and range-validation invariants. Provide independent business checks for overlap, repeated/unordered/unaligned offsets, different column interpretations, empty arrays, THEAP gaps, multiple HDUs, exact boundary and invalid ranges, late failures, old fixed behavior, source deletion, append and reopening. Include generated-source resource measurements that vary variable array length and row count separately while requesting a fixed small slice. Report Python allocation peaks and process memory; the supplied resource command reports both but does not replace interpretation of the measurements. No particular indexing strategy or throughput target is imposed.

The existing .pointwise-runtime.json remains the execution contract: version 1, kind cli, setup is a list of command argument arrays, and verify/demo are command argument arrays. Update its verify to actually check the original workflow and new persistent spectra, and its demo to display real overlapping spectra after reopening. Failures must exit nonzero; a printed success marker alone is insufficient. The supplied helper commands are:

    python3.11 -B heap_cases.py fixtures
    python3.11 -B heap_cases.py verify
    python3.11 -B heap_cases.py demo
    python3.11 -B heap_cases.py resource --elements 262144 --rows 256
    python3.11 -B heap_cases.py resource --elements 4194304 --rows 256
    python3.11 -B heap_cases.py resource --elements 4 --rows 256
    python3.11 -B heap_cases.py resource --elements 4 --rows 16384

fixtures checks only the non-answer specimens and works on the initial V1 tree. verify/demo/resource exercise the requested capability and are expected to require implementation. They are examples of executable checks, not a replacement for all public requirements above. Run resource cases in separate processes so each process memory peak has a useful scope. The original unittest command and examples.py remain the normal V1 regression and demo.
